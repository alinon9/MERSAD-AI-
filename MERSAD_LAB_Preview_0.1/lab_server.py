#!/usr/bin/env python3
"""
MERSAD LAB 1.0 — PREVIEW 0.1 | Virtual Camera Simulation & Media Quality Server
خادم مختبر محاكاة الكاميرات وفحص جودة الوسائط والربط مع مرصاد الذكي
Default Binding: 127.0.0.1:8090 (Local Loopback Only)
"""
import argparse
import cgi
import html
import http.cookies
import io
import json
import logging
import os
import re
try:
    import resource
except ImportError:  # The resource module is Unix-only; Windows uses Win32 process counters.
    resource = None
import secrets
import signal
import socket
import sys
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from sim_engine import (
    VALID_CAMERA_MODES,
    VirtualCamera,
    analyze_image_bytes,
    analyze_video_bytes,
)

VERSION = "MERSAD LAB 1.0 — PREVIEW 0.1"
DEFAULT_HOST = "127.0.0.1"
DEFAULT_PORT = 8090
MAX_IMAGE_UPLOAD_BYTES = int(os.environ.get("MERSAD_LAB_MAX_IMAGE_BYTES", str(10 * 1024 * 1024)))
MAX_VIDEO_UPLOAD_BYTES = int(os.environ.get("MERSAD_LAB_MAX_VIDEO_BYTES", str(50 * 1024 * 1024)))
MAX_JSON_BODY_BYTES = 256 * 1024
MAX_CONCURRENT_UPLOADS = int(os.environ.get("MERSAD_LAB_MAX_CONCURRENT_UPLOADS", "3"))
DEFAULT_VIDEO_TIMEOUT_SEC = float(os.environ.get("MERSAD_LAB_VIDEO_TIMEOUT_SEC", "8.0"))
MAX_MJPEG_STREAMS = 16

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
log = logging.getLogger("mersad.lab")


def resolve_lab_asset(filename: str) -> str:
    meipass = getattr(sys, "_MEIPASS", None)
    if meipass:
        cand = os.path.join(meipass, filename)
        if os.path.isfile(cand):
            return cand
    if getattr(sys, "frozen", False):
        cand = os.path.join(os.path.dirname(os.path.abspath(sys.executable)), filename)
        if os.path.isfile(cand):
            return cand
    return os.path.join(os.path.dirname(os.path.abspath(__file__)), filename)


def get_process_telemetry(start_time: float) -> dict:
    """Return portable process telemetry without requiring Unix-only modules on Windows."""
    rss_mb = 0.0
    try:
        if sys.platform.startswith("linux") and os.path.isfile("/proc/self/statm"):
            with open("/proc/self/statm", encoding="ascii") as statm:
                parts = statm.read().split()
            rss_mb = round((int(parts[1]) * os.sysconf("SC_PAGE_SIZE")) / (1024.0 * 1024.0), 2)
        elif sys.platform == "win32":
            # GetProcessMemoryInfo reports the current working set in bytes.
            # This keeps the LAB memory-pressure telemetry meaningful on Windows.
            import ctypes
            from ctypes import wintypes

            class PROCESS_MEMORY_COUNTERS(ctypes.Structure):
                _fields_ = [
                    ("cb", wintypes.DWORD),
                    ("PageFaultCount", wintypes.DWORD),
                    ("PeakWorkingSetSize", ctypes.c_size_t),
                    ("WorkingSetSize", ctypes.c_size_t),
                    ("QuotaPeakPagedPoolUsage", ctypes.c_size_t),
                    ("QuotaPagedPoolUsage", ctypes.c_size_t),
                    ("QuotaPeakNonPagedPoolUsage", ctypes.c_size_t),
                    ("QuotaNonPagedPoolUsage", ctypes.c_size_t),
                    ("PagefileUsage", ctypes.c_size_t),
                    ("PeakPagefileUsage", ctypes.c_size_t),
                ]

            counters = PROCESS_MEMORY_COUNTERS()
            counters.cb = ctypes.sizeof(counters)
            kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
            get_current_process = kernel32.GetCurrentProcess
            get_current_process.restype = wintypes.HANDLE
            psapi = ctypes.WinDLL("Psapi.dll", use_last_error=True)
            get_memory_info = psapi.GetProcessMemoryInfo
            get_memory_info.argtypes = [
                wintypes.HANDLE,
                ctypes.POINTER(PROCESS_MEMORY_COUNTERS),
                wintypes.DWORD,
            ]
            get_memory_info.restype = wintypes.BOOL
            if not get_memory_info(get_current_process(), ctypes.byref(counters), counters.cb):
                raise OSError(ctypes.get_last_error(), "GetProcessMemoryInfo failed")
            rss_mb = round(counters.WorkingSetSize / (1024.0 * 1024.0), 2)
        elif resource is not None:
            ru = resource.getrusage(resource.RUSAGE_SELF)
            # ru_maxrss is bytes on macOS and KiB on other common Unix platforms.
            rss_bytes = ru.ru_maxrss if sys.platform == "darwin" else ru.ru_maxrss * 1024.0
            rss_mb = round(rss_bytes / (1024.0 * 1024.0), 2)
    except Exception:
        # Telemetry must never bring down the LAB health endpoint.
        rss_mb = 0.0
    cpu_sec = round(float(time.process_time()), 3)
    uptime_sec = round(max(0.001, time.time() - start_time), 2)
    return {
        "rss_mb": rss_mb,
        "cpu_time_sec": cpu_sec,
        "uptime_sec": uptime_sec,
        "active_threads": threading.active_count(),
    }


class LabState:
    def __init__(self, token: str = None, require_auth: bool = False):
        self.start_time = time.time()
        self.token = token or os.environ.get("MERSAD_LAB_TOKEN") or secrets.token_urlsafe(16)
        self.require_auth = bool(require_auth)
        self.stop_event = threading.Event()
        self.upload_semaphore = threading.BoundedSemaphore(MAX_CONCURRENT_UPLOADS)
        self.active_uploads = 0
        self.active_streams = 0
        self.max_image_bytes = MAX_IMAGE_UPLOAD_BYTES
        self.max_video_bytes = MAX_VIDEO_UPLOAD_BYTES
        self.video_timeout_sec = DEFAULT_VIDEO_TIMEOUT_SEC
        self._lock = threading.RLock()
        self.cameras = {
            "cam1": VirtualCamera("cam1", "الكاميرا الافتراضية 1 — المدخل الشمالي (عدن)", plate_idx=0),
            "cam2": VirtualCamera("cam2", "الكاميرا الافتراضية 2 — البوابة الشرقية (صنعاء)", plate_idx=1),
            "cam3": VirtualCamera("cam3", "الكاميرا الافتراضية 3 — التقاطع الرئيسي (تعز)", plate_idx=2),
            "cam4": VirtualCamera("cam4", "الكاميرا الافتراضية 4 — الخط الساحلي (حضرموت)", plate_idx=3),
        }

    def get_camera(self, cam_id: str) -> VirtualCamera:
        cid = re.sub(r"[^a-zA-Z0-9_-]", "", str(cam_id or "").strip().lower())
        with self._lock:
            return self.cameras.get(cid)

    def add_or_update_camera(self, cam_id: str, title_ar: str = "", plate_idx: int = 0) -> VirtualCamera:
        cid = re.sub(r"[^a-zA-Z0-9_-]", "", str(cam_id or "").strip().lower())[:24]
        if not cid:
            raise ValueError("معرف الكاميرا غير صالح")
        safe_title = html.escape(str(title_ar or f"كاميرا افتراضية ({cid})").strip()[:80])
        with self._lock:
            if cid not in self.cameras and len(self.cameras) >= 8:
                raise ValueError("الحد الأقصى للكاميرات الافتراضية هو 8 كاميرات")
            cam = self.cameras.get(cid)
            if cam is None:
                cam = VirtualCamera(cid, safe_title, plate_idx=plate_idx)
                self.cameras[cid] = cam
            elif title_ar:
                cam.title_ar = safe_title
            return cam


class LabHTTPServer(ThreadingHTTPServer):
    daemon_threads = True
    allow_reuse_address = True

    def __init__(self, server_address, RequestHandlerClass, lab_state: LabState):
        super().__init__(server_address, RequestHandlerClass)
        self.lab_state = lab_state


class LabRequestHandler(BaseHTTPRequestHandler):
    timeout = 15

    def log_message(self, fmt, *args):
        pass

    @property
    def state(self) -> LabState:
        return self.server.lab_state

    def _send_security_headers(self):
        self.send_header(
            "Content-Security-Policy",
            "default-src 'self'; img-src 'self' data: blob:; media-src 'self' blob:; "
            "style-src 'self' 'unsafe-inline'; script-src 'self' 'unsafe-inline'; frame-ancestors 'none'",
        )
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("X-Frame-Options", "DENY")
        self.send_header("Referrer-Policy", "no-referrer")
        self.send_header("Cache-Control", "no-store")

    def _json(self, payload: dict, code: int = 200):
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        try:
            self.send_response(int(code))
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self._send_security_headers()
            self.end_headers()
            self.wfile.write(body)
        except (BrokenPipeError, ConnectionResetError, ConnectionAbortedError, OSError):
            pass

    def _validate_host_and_origin(self, is_post: bool = False) -> bool:
        """Protect local loopback service against DNS Rebinding, Origin: null, and Cross-Origin/Cross-Port CSRF."""
        host_hdr = (self.headers.get("Host") or "").strip().lower()
        if host_hdr:
            host_only = host_hdr.split(":")[0].strip("[]")
            allowed_hosts = {"127.0.0.1", "localhost", "::1", "0.0.0.0"}
            srv_host = str(self.server.server_address[0]).lower()
            if srv_host not in ("0.0.0.0", ""):
                allowed_hosts.add(srv_host)
            if host_only not in allowed_hosts:
                self._json({"ok": False, "error": "رفض الطلب: ترويسة Host غير موثوقة (DNS Rebinding Protection)"}, code=403)
                return False

        origin_hdr = (self.headers.get("Origin") or "").strip()
        if origin_hdr:
            if origin_hdr.lower() == "null":
                self._json({"ok": False, "error": "رفض الطلب: المصدر Origin: null غير مسموح (CSRF Protection)"}, code=403)
                return False
            parsed_orig = urllib.parse.urlparse(origin_hdr)
            orig_netloc = (parsed_orig.netloc or "").strip().lower()
            if not orig_netloc or (host_hdr and orig_netloc != host_hdr):
                self._json({"ok": False, "error": "رفض الطلب: تعارض Origin مع Host (Cross-Origin/Cross-Port CSRF Blocked)"}, code=403)
                return False

        sec_site = (self.headers.get("Sec-Fetch-Site") or "").strip().lower()
        if sec_site == "cross-site":
            self._json({"ok": False, "error": "رفض الطلب: Sec-Fetch-Site: cross-site غير مسموح (CSRF Protection)"}, code=403)
            return False

        if is_post:
            ctype = (self.headers.get("Content-Type") or "").strip().lower()
            # Block browser simple-request CSRF (text/plain or application/x-www-form-urlencoded without explicit token header)
            has_token_hdr = bool(self.headers.get("X-Lab-Token") or self.headers.get("Authorization"))
            if ctype.startswith(("text/plain", "application/x-www-form-urlencoded")) and not has_token_hdr:
                self._json(
                    {"ok": False, "error": "رفض الطلب لحماية الجلسة (يتطلب Content-Type: application/json أو multipart/form-data أو X-Lab-Token)"},
                    code=403,
                )
                return False
        return True

    def _check_auth(self, require_for_mutation: bool = False) -> bool:
        """Check token authentication when require_auth is enabled or when invalid token is explicitly supplied."""
        parsed = urllib.parse.urlparse(self.path)
        qs = urllib.parse.parse_qs(parsed.query)
        q_tok = (qs.get("token") or qs.get("k") or [""])[0].strip()
        h_tok = (self.headers.get("X-Lab-Token") or "").strip()
        auth_hdr = (self.headers.get("Authorization") or "").strip()
        if auth_hdr.lower().startswith("bearer "):
            h_tok = auth_hdr[7:].strip()
        c_tok = ""
        if "Cookie" in self.headers:
            c = http.cookies.SimpleCookie(self.headers["Cookie"])
            if "mersad_lab_k" in c:
                c_tok = c["mersad_lab_k"].value

        provided = h_tok or q_tok or c_tok
        expected = self.state.token

        if provided and not secrets.compare_digest(provided, expected):
            self._json({"ok": False, "error": "رمز الوصول إلى المختبر غير صالح (Unauthorized)"}, code=401)
            return False

        if (self.state.require_auth or require_for_mutation) and not provided:
            self._json({"ok": False, "error": "يتطلب هذا المسار رمز مصادقة المختبر (X-Lab-Token)"}, code=401)
            return False
        return True

    def do_GET(self):
        if not self._validate_host_and_origin(is_post=False):
            return
        parsed = urllib.parse.urlparse(self.path)
        path = parsed.path

        if path in ("/api/health", "/health"):
            tel = get_process_telemetry(self.state.start_time)
            cams = {cid: cam.info() for cid, cam in self.state.cameras.items()}
            return self._json({
                "ok": True,
                "status": "healthy",
                "service": "mersad_lab",
                "version": VERSION,
                "host": self.server.server_address[0],
                "port": self.server.server_address[1],
                "telemetry": tel,
                "cameras_count": len(cams),
                "cameras": cams,
            })

        if not self._check_auth(require_for_mutation=False):
            return

        if path in ("/", "/index.html"):
            idx_path = resolve_lab_asset("index.html")
            if not os.path.isfile(idx_path):
                return self._json({"ok": False, "error": "index.html missing"}, code=404)
            raw_html = open(idx_path, "rb").read()
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(raw_html)))
            self.send_header("Set-Cookie", f"mersad_lab_k={self.state.token}; HttpOnly; SameSite=Strict; Path=/")
            self._send_security_headers()
            self.end_headers()
            self.wfile.write(raw_html)
            return

        if path == "/api/cameras":
            cams = [cam.info() for cam in self.state.cameras.values()]
            return self._json({"ok": True, "cameras": cams, "valid_modes": sorted(VALID_CAMERA_MODES)})

        # Single JPEG frame: /frame/<cam_id>.jpg or /camera/<cam_id>/frame.jpg
        m_frame = re.match(r"^/(?:frame/([a-zA-Z0-9_-]+)\.jpg|camera/([a-zA-Z0-9_-]+)/frame\.jpg)$", path)
        if m_frame:
            cid = m_frame.group(1) or m_frame.group(2)
            cam = self.state.get_camera(cid)
            if cam is None:
                return self._json({"ok": False, "error": "الكاميرا غير موجودة"}, code=404)
            code, jpg = cam.render_jpeg()
            if code == 503 or jpg is None:
                return self._json({"ok": False, "error": "الكاميرا في وضع عدم الاتصال (Offline — HTTP 503)", "cam_id": cid, "mode": cam.mode}, code=503)
            self.send_response(200)
            self.send_header("Content-Type", "image/jpeg")
            self.send_header("Content-Length", str(len(jpg)))
            self._send_security_headers()
            self.end_headers()
            self.wfile.write(jpg)
            return

        # MJPEG stream: /stream/<cam_id>.mjpg or /camera/<cam_id>/stream.mjpg
        m_stream = re.match(r"^/(?:stream/([a-zA-Z0-9_-]+)\.mjpg|camera/([a-zA-Z0-9_-]+)/stream\.mjpg)$", path)
        if m_stream:
            cid = m_stream.group(1) or m_stream.group(2)
            cam = self.state.get_camera(cid)
            if cam is None:
                return self._json({"ok": False, "error": "الكاميرا غير موجودة"}, code=404)
            code, first_jpg = cam.render_jpeg()
            if code == 503 or first_jpg is None:
                return self._json({"ok": False, "error": "الكاميرا في وضع عدم الاتصال (Offline — HTTP 503)", "cam_id": cid, "mode": cam.mode}, code=503)

            with self.state._lock:
                if self.state.active_streams >= MAX_MJPEG_STREAMS:
                    return self._json({"ok": False, "error": "تم تجاوز الحد الأقصى لتدفقات MJPEG المتزامنة"}, code=429)
                self.state.active_streams += 1

            qs = urllib.parse.parse_qs(parsed.query)
            max_frames = int((qs.get("frames") or ["0"])[0]) if (qs.get("frames") or ["0"])[0].isdigit() else 0
            sent_frames = 0
            try:
                self.send_response(200)
                self.send_header("Content-Type", "multipart/x-mixed-replace; boundary=frame")
                self._send_security_headers()
                self.end_headers()

                cur_jpg = first_jpg
                while not self.state.stop_event.is_set():
                    part = (
                        b"--frame\r\n"
                        b"Content-Type: image/jpeg\r\n"
                        b"Content-Length: " + str(len(cur_jpg)).encode("ascii") + b"\r\n\r\n"
                        + cur_jpg + b"\r\n"
                    )
                    self.wfile.write(part)
                    self.wfile.flush()
                    sent_frames += 1
                    if max_frames > 0 and sent_frames >= max_frames:
                        break
                    interval = 1.0 / max(1.0, cam.target_fps)
                    if self.state.stop_event.wait(timeout=min(0.25, interval)):
                        break
                    code, cur_jpg = cam.render_jpeg()
                    if code != 200 or cur_jpg is None:
                        break
            except (BrokenPipeError, ConnectionResetError, ConnectionAbortedError, OSError):
                pass
            finally:
                with self.state._lock:
                    self.state.active_streams = max(0, self.state.active_streams - 1)
            return

        return self._json({"ok": False, "error": "المسار غير موجود"}, code=404)

    def _read_bounded_body(self, max_bytes: int):
        try:
            clen = int(self.headers.get("Content-Length", "0"))
        except ValueError:
            self._json({"ok": False, "error": "ترويسة Content-Length غير صالحة"}, code=400)
            return None
        if clen < 0:
            self._json({"ok": False, "error": "حجم الطلب غير صالح"}, code=400)
            return None
        if clen > max_bytes:
            self._json(
                {"ok": False, "error": f"حجم الملف يتجاوز الحد الأقصى المسموح ({max_bytes} بايت)", "max_bytes": max_bytes},
                code=413,
            )
            return None
        return self.rfile.read(clen) if clen > 0 else b""

    def _extract_upload_bytes(self, raw_body: bytes) -> bytes:
        ctype = (self.headers.get("Content-Type") or "").strip()
        if "multipart/form-data" in ctype.lower():
            env = {
                "REQUEST_METHOD": "POST",
                "CONTENT_TYPE": ctype,
                "CONTENT_LENGTH": str(len(raw_body)),
            }
            fs = cgi.FieldStorage(fp=io.BytesIO(raw_body), headers=self.headers, environ=env, keep_blank_values=True)
            for key in ("file", "image", "video", "media"):
                if key in fs:
                    item = fs[key]
                    if isinstance(item, list):
                        item = item[0]
                    if getattr(item, "file", None) is not None:
                        return item.file.read()
            if getattr(fs, "list", None):
                for item in fs.list:
                    if getattr(item, "file", None) is not None and getattr(item, "filename", None):
                        return item.file.read()
            return b""
        return raw_body

    def do_POST(self):
        if not self._validate_host_and_origin(is_post=True):
            return
        if not self._check_auth(require_for_mutation=False):
            return

        parsed = urllib.parse.urlparse(self.path)
        path = parsed.path

        # 1. Change camera mode: /api/cameras/<cam_id>/mode or /api/camera/mode
        m_mode = re.match(r"^/api/cameras/([a-zA-Z0-9_-]+)/mode$", path)
        if m_mode or path in ("/api/camera/mode", "/api/cameras/mode"):
            raw = self._read_bounded_body(MAX_JSON_BODY_BYTES)
            if raw is None:
                return
            try:
                data = json.loads(raw.decode("utf-8") if raw else "{}")
            except Exception:
                return self._json({"ok": False, "error": "صيغة JSON غير صالحة"}, code=400)
            if not isinstance(data, dict):
                return self._json({"ok": False, "error": "بيانات الطلب غير صالحة"}, code=400)

            cid = m_mode.group(1) if m_mode else str(data.get("cam_id") or data.get("camera") or "cam1")
            mode = str(data.get("mode") or "").strip().lower()
            delay_s = data.get("delay_sec")
            if mode not in VALID_CAMERA_MODES:
                return self._json(
                    {
                        "ok": False,
                        "error": f"وضع الكاميرا غير صالح: {html.escape(mode[:32])}",
                        "valid_modes": sorted(VALID_CAMERA_MODES),
                    },
                    code=400,
                )
            cam = self.state.get_camera(cid)
            if cam is None:
                return self._json({"ok": False, "error": "الكاميرا غير موجودة"}, code=404)
            cam.set_mode(mode, delay_sec=delay_s)
            return self._json({"ok": True, "camera": cam.info()})

        # 2. Add/Update virtual camera: /api/cameras/add
        if path == "/api/cameras/add":
            raw = self._read_bounded_body(MAX_JSON_BODY_BYTES)
            if raw is None:
                return
            try:
                data = json.loads(raw.decode("utf-8") if raw else "{}")
                cam = self.state.add_or_update_camera(
                    data.get("cam_id") or data.get("name"),
                    title_ar=data.get("title_ar") or data.get("title") or "",
                    plate_idx=int(data.get("plate_idx") or 0),
                )
                return self._json({"ok": True, "camera": cam.info()})
            except ValueError as ve:
                return self._json({"ok": False, "error": str(ve)}, code=400)
            except Exception:
                return self._json({"ok": False, "error": "تعذّر إضافة الكاميرا الافتراضية"}, code=400)

        # 3. Image quality upload: /api/analyze/image or /api/upload/image or /upload/image
        if path in ("/api/analyze/image", "/api/upload/image", "/upload/image"):
            if not self.state.upload_semaphore.acquire(blocking=False):
                return self._json({"ok": False, "error": "تم تجاوز الحد الأقصى لعمليات الرفع المتزامنة (Too Many Concurrent Uploads)"}, code=429)
            try:
                with self.state._lock:
                    self.state.active_uploads += 1
                raw = self._read_bounded_body(self.state.max_image_bytes)
                if raw is None:
                    return
                img_bytes = self._extract_upload_bytes(raw)
                res = analyze_image_bytes(img_bytes)
                code = res.pop("status_code", 200 if res.get("ok") else 400)
                return self._json(res, code=code)
            finally:
                with self.state._lock:
                    self.state.active_uploads = max(0, self.state.active_uploads - 1)
                self.state.upload_semaphore.release()

        # 4. Video quality upload: /api/analyze/video or /api/upload/video or /upload/video
        if path in ("/api/analyze/video", "/api/upload/video", "/upload/video"):
            if not self.state.upload_semaphore.acquire(blocking=False):
                return self._json({"ok": False, "error": "تم تجاوز الحد الأقصى لعمليات الرفع المتزامنة (Too Many Concurrent Uploads)"}, code=429)
            try:
                with self.state._lock:
                    self.state.active_uploads += 1
                raw = self._read_bounded_body(self.state.max_video_bytes)
                if raw is None:
                    return
                vid_bytes = self._extract_upload_bytes(raw)
                qs = urllib.parse.parse_qs(parsed.query)
                sim_delay = float((qs.get("simulate_delay") or ["0"])[0]) if (qs.get("simulate_delay") or ["0"])[0].replace(".", "", 1).isdigit() else 0.0
                timeout_override = self.state.video_timeout_sec
                if "timeout" in qs:
                    try:
                        timeout_override = max(0.05, min(30.0, float(qs["timeout"][0])))
                    except ValueError:
                        pass
                res = analyze_video_bytes(vid_bytes, timeout_sec=timeout_override, artificial_delay_per_frame=sim_delay)
                code = res.pop("status_code", 200 if res.get("ok") else 400)
                return self._json(res, code=code)
            finally:
                with self.state._lock:
                    self.state.active_uploads = max(0, self.state.active_uploads - 1)
                self.state.upload_semaphore.release()

        # 5. Integration helper: Connect virtual camera to MERSAD AI (/api/integration/connect_ai)
        if path == "/api/integration/connect_ai":
            raw = self._read_bounded_body(MAX_JSON_BODY_BYTES)
            if raw is None:
                return
            try:
                data = json.loads(raw.decode("utf-8") if raw else "{}")
            except Exception:
                return self._json({"ok": False, "error": "صيغة JSON غير صالحة"}, code=400)
            ai_url = str(data.get("ai_url") or "http://127.0.0.1:8765").rstrip("/")
            ai_token = str(data.get("ai_token") or "").strip()
            cam_id = str(data.get("cam_id") or "cam1").strip()
            cam_name = str(data.get("cam_name") or f"LAB_{cam_id.upper()}").strip()
            cam = self.state.get_camera(cam_id)
            if cam is None:
                return self._json({"ok": False, "error": "الكاميرا المطلوبة غير موجودة في المختبر"}, code=404)
            lab_host, lab_port = self.server.server_address
            eff_host = "127.0.0.1" if lab_host in ("0.0.0.0", "") else lab_host
            stream_url = f"http://{eff_host}:{lab_port}/stream/{cam.cam_id}.mjpg"
            req_body = json.dumps({"name": cam_name, "source": stream_url}).encode("utf-8")
            req = urllib.request.Request(
                f"{ai_url}/api/cameras/add",
                data=req_body,
                headers={
                    "Content-Type": "application/json",
                    "X-Mersad-Token": ai_token,
                },
                method="POST",
            )
            try:
                with urllib.request.urlopen(req, timeout=5.0) as resp:
                    ai_resp = json.loads(resp.read().decode("utf-8"))
                return self._json({"ok": True, "stream_url": stream_url, "ai_response": ai_resp})
            except urllib.error.HTTPError as he:
                return self._json({"ok": False, "error": f"رفض خادم مرصاد الطلب (HTTP {he.code})", "stream_url": stream_url}, code=502)
            except Exception as e:
                return self._json({"ok": False, "error": f"تعذّر الاتصال بخادم مرصاد: {e}", "stream_url": stream_url}, code=502)

        return self._json({"ok": False, "error": "المسار غير موجود"}, code=404)


class LabServerController:
    """Clean start/stop wrapper around LabHTTPServer with zero hanging threads."""

    def __init__(self, host: str = DEFAULT_HOST, port: int = DEFAULT_PORT, token: str = None, require_auth: bool = False):
        self.state = LabState(token=token, require_auth=require_auth)
        self.httpd = LabHTTPServer((host, int(port)), LabRequestHandler, self.state)
        self.host, self.port = self.httpd.server_address
        self._thread = None

    def start(self):
        self._thread = threading.Thread(target=self.httpd.serve_forever, kwargs={"poll_interval": 0.1}, daemon=True, name="mersad-lab-http")
        self._thread.start()
        return self

    def stop(self, timeout: float = 5.0):
        self.state.stop_event.set()
        try:
            self.httpd.shutdown()
        except Exception:
            pass
        try:
            self.httpd.server_close()
        except Exception:
            pass
        if self._thread is not None and self._thread.is_alive():
            self._thread.join(timeout=timeout)


def main():
    ap = argparse.ArgumentParser(description="MERSAD LAB 1.0 — PREVIEW 0.1 Virtual Camera & Quality Server")
    ap.add_argument("--host", default=DEFAULT_HOST, help="Bind address (default: 127.0.0.1 local only)")
    ap.add_argument("--port", type=int, default=DEFAULT_PORT, help="TCP port (default: 8090)")
    ap.add_argument("--token", default=None, help="Optional lab API access token")
    ap.add_argument("--require-auth", action="store_true", help="Require X-Lab-Token on all requests")
    ap.add_argument("--allow-lan", action="store_true", help="Allow non-loopback binding (requires explicit flag)")
    ap.add_argument("--self-check", action="store_true", help="Run startup self-check and exit 0")
    args = ap.parse_args()

    if args.host not in ("127.0.0.1", "localhost", "::1") and not args.allow_lan:
        print("[SECURITY ERROR] MERSAD LAB binds to 127.0.0.1 by default. Pass --allow-lan explicitly if LAN binding is required.", file=sys.stderr)
        sys.exit(2)

    ctrl = LabServerController(host=args.host, port=args.port, token=args.token, require_auth=args.require_auth)
    if args.self_check:
        ctrl.start()
        try:
            url = f"http://127.0.0.1:{ctrl.port}/api/health"
            with urllib.request.urlopen(url, timeout=3.0) as r:
                data = json.loads(r.read().decode("utf-8"))
            print(json.dumps({"ok": data.get("ok"), "version": data.get("version"), "port": ctrl.port}, ensure_ascii=False))
            sys.exit(0 if data.get("ok") else 1)
        finally:
            ctrl.stop()

    stop_sig = threading.Event()
    def _on_signal(signum, frame):
        stop_sig.set()

    signal.signal(signal.SIGINT, _on_signal)
    signal.signal(signal.SIGTERM, _on_signal)

    ctrl.start()
    print("======================================================================")
    print(f"  {VERSION}")
    print(f"  Local URL   : http://{ctrl.host}:{ctrl.port}/")
    print(f"  Stream CAM1 : http://{ctrl.host}:{ctrl.port}/stream/cam1.mjpg")
    print("  Security    : Localhost-only (127.0.0.1) + Host/Origin/CSRF Guard")
    print("======================================================================")
    try:
        while not stop_sig.is_set():
            stop_sig.wait(timeout=0.5)
    except KeyboardInterrupt:
        pass
    finally:
        print("\nShutting down MERSAD LAB cleanly...")
        ctrl.stop()


if __name__ == "__main__":
    main()
