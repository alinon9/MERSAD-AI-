#!/usr/bin/env python3
"""
MERSAD LAB 1.0 — PREVIEW 0.1 | Virtual Camera Simulation & Media Quality Server
خادم مختبر محاكاة الكاميرات وفحص جودة الوسائط والربط مع مرصاد الذكي
Default Binding: 127.0.0.1:8090 (Local Loopback Only)
"""
import argparse
import cgi
import html
import http.client
import http.cookies
import ipaddress
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
import ssl
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


# AUD-002: allowlisted, DNS-pinned LAB -> AI connection. No redirects are followed.
_AI_MAX_RESPONSE_BYTES = 1024 * 1024
_AI_LOCAL_ALLOWED_PORTS = {80, 443, 8000, 8765}
_AI_REMOTE_ALLOWED_PORTS = {443, 8443, 8000, 8765}


def _normalize_ai_host(value: str) -> str:
    raw = str(value or "").strip().lower().rstrip(".")
    if raw.startswith("[") and raw.endswith("]"):
        raw = raw[1:-1]
    if not raw or "%" in raw or any(ord(ch) < 33 or ord(ch) == 127 for ch in raw):
        raise ValueError("invalid host")
    try:
        return str(ipaddress.ip_address(raw))
    except ValueError:
        try:
            return raw.encode("idna").decode("ascii").lower()
        except UnicodeError as exc:
            raise ValueError("invalid host") from exc


def _allowed_ai_hosts() -> set:
    values = os.environ.get("MERSAD_LAB_ALLOWED_AI_HOSTS", "")
    return {_normalize_ai_host(item) for item in values.split(",") if item.strip()}


def _allowed_ai_ports(env_name: str, defaults: set) -> set:
    raw = os.environ.get(env_name, "").strip()
    if not raw:
        return set(defaults)
    ports = set()
    for item in raw.split(","):
        try:
            port = int(item.strip())
        except (TypeError, ValueError) as exc:
            raise ValueError("invalid port policy") from exc
        if not 1 <= port <= 65535:
            raise ValueError("invalid port policy")
        ports.add(port)
    if not ports:
        raise ValueError("empty port policy")
    return ports


def _ip_for_policy(value: str):
    if "%" in str(value):
        raise ValueError("scoped IP addresses are not allowed")
    ip_obj = ipaddress.ip_address(value)
    return getattr(ip_obj, "ipv4_mapped", None) or ip_obj


def _is_disallowed_remote_ip(ip_obj) -> bool:
    return bool(
        ip_obj.is_loopback
        or ip_obj.is_link_local
        or ip_obj.is_multicast
        or ip_obj.is_unspecified
        or ip_obj.is_reserved
    )


def _validate_ai_connect_url(ai_url: str) -> dict:
    """Validate an AI base URL, resolve its host once, and pin the TCP destination IP."""
    try:
        parsed = urllib.parse.urlsplit(str(ai_url or "").strip())
        if parsed.scheme.lower() not in ("http", "https"):
            raise ValueError("unsupported scheme")
        if parsed.username is not None or parsed.password is not None:
            raise ValueError("URL credentials are not allowed")
        if parsed.query or parsed.fragment or parsed.path not in ("", "/"):
            raise ValueError("only an origin/base URL is allowed")
        if not parsed.hostname:
            raise ValueError("missing host")
        host = _normalize_ai_host(parsed.hostname)
        port = parsed.port or (443 if parsed.scheme.lower() == "https" else 80)
        if not 1 <= port <= 65535:
            raise ValueError("invalid port")

        try:
            host_ip = ipaddress.ip_address(host)
            is_loopback_host = bool((getattr(host_ip, "ipv4_mapped", None) or host_ip).is_loopback)
        except ValueError:
            is_loopback_host = host == "localhost"

        if is_loopback_host:
            allowed_ports = _allowed_ai_ports("MERSAD_LAB_ALLOWED_LOCAL_AI_PORTS", _AI_LOCAL_ALLOWED_PORTS)
            if parsed.scheme.lower() not in ("http", "https") or port not in allowed_ports:
                raise ValueError("loopback destination/port is not allowed")
        else:
            if parsed.scheme.lower() != "https":
                raise ValueError("remote AI hosts require HTTPS")
            if host not in _allowed_ai_hosts():
                raise ValueError("remote AI host is not allowlisted")
            allowed_ports = _allowed_ai_ports("MERSAD_LAB_ALLOWED_AI_PORTS", _AI_REMOTE_ALLOWED_PORTS)
            if port not in allowed_ports:
                raise ValueError("remote AI port is not allowlisted")

        try:
            literal_ip = ipaddress.ip_address(host)
        except ValueError:
            literal_ip = None

        if literal_ip is not None:
            resolved = [str(literal_ip)]
        else:
            # Exactly one hostname resolution. The resulting IP is used for the TCP
            # socket directly; the hostname is retained separately for Host/SNI.
            infos = socket.getaddrinfo(host, port, type=socket.SOCK_STREAM)
            resolved = []
            for info in infos:
                address = info[4][0]
                if address not in resolved:
                    resolved.append(address)

        if not resolved:
            raise ValueError("host did not resolve")
        normalized_ips = []
        for address in resolved:
            ip_obj = _ip_for_policy(address)
            if is_loopback_host:
                if not ip_obj.is_loopback:
                    raise ValueError("localhost resolved to a non-loopback address")
            elif _is_disallowed_remote_ip(ip_obj):
                raise ValueError("allowlisted host resolved to a prohibited address")
            normalized_ips.append(str(ipaddress.ip_address(address.split("%", 1)[0])))

        return {
            "scheme": parsed.scheme.lower(),
            "host": host,
            "port": port,
            "pinned_ip": normalized_ips[0],
            "path": "/api/cameras/add",
        }
    except (ValueError, OSError, UnicodeError) as exc:
        raise ValueError("AI destination is invalid or not allowlisted") from exc


def _open_pinned_socket(pinned_ip: str, port: int, timeout: float):
    """Open a socket to a numeric IP without performing hostname DNS resolution."""
    ip_obj = ipaddress.ip_address(pinned_ip)
    family = socket.AF_INET6 if ip_obj.version == 6 else socket.AF_INET
    sock = socket.socket(family, socket.SOCK_STREAM)
    try:
        sock.settimeout(timeout)
        sockaddr = (str(ip_obj), int(port), 0, 0) if ip_obj.version == 6 else (str(ip_obj), int(port))
        sock.connect(sockaddr)
        return sock
    except Exception:
        sock.close()
        raise


class _PinnedIPHTTPConnection(http.client.HTTPConnection):
    def __init__(self, host: str, port: int, pinned_ip: str, timeout: float = 5.0):
        super().__init__(host=host, port=port, timeout=timeout)
        self._pinned_ip = str(pinned_ip)

    def connect(self):
        if self._tunnel_host:
            raise OSError("HTTP tunneling is disabled for pinned AI connections")
        self.sock = _open_pinned_socket(self._pinned_ip, self.port, self.timeout)


class _PinnedIPHTTPSConnection(http.client.HTTPSConnection):
    def __init__(self, host: str, port: int, pinned_ip: str, timeout: float = 5.0, context=None):
        context = context or ssl.create_default_context()
        if not context.check_hostname or context.verify_mode != ssl.CERT_REQUIRED:
            raise ValueError("TLS certificate and hostname verification are mandatory")
        super().__init__(host=host, port=port, timeout=timeout, context=context)
        self._pinned_ip = str(pinned_ip)

    def connect(self):
        if self._tunnel_host:
            raise OSError("HTTPS tunneling is disabled for pinned AI connections")
        raw_sock = _open_pinned_socket(self._pinned_ip, self.port, self.timeout)
        try:
            self.sock = self._context.wrap_socket(raw_sock, server_hostname=self.host)
        except Exception:
            raw_sock.close()
            raise


def _send_pinned_ai_request(target: dict, request_body: bytes, ai_token: str) -> dict:
    """Send one POST to a prevalidated/pinned destination; redirects are never followed."""
    host = target["host"]
    port = target["port"]
    conn_type = _PinnedIPHTTPSConnection if target["scheme"] == "https" else _PinnedIPHTTPConnection
    kwargs = {"host": host, "port": port, "pinned_ip": target["pinned_ip"], "timeout": 5.0}
    if target["scheme"] == "https":
        kwargs["context"] = ssl.create_default_context()
    conn = conn_type(**kwargs)
    try:
        conn.request(
            "POST",
            target["path"],
            body=request_body,
            headers={
                "Content-Type": "application/json",
                "Accept": "application/json",
                "X-Mersad-Token": ai_token,
                "Connection": "close",
            },
        )
        response = conn.getresponse()
        if 300 <= response.status < 400:
            raise OSError("AI endpoint redirects are not permitted")
        raw = response.read(_AI_MAX_RESPONSE_BYTES + 1)
        if len(raw) > _AI_MAX_RESPONSE_BYTES:
            raise OSError("AI response exceeds size limit")
        if response.status < 200 or response.status >= 300:
            raise OSError("AI endpoint returned a non-success status")
        result = json.loads(raw.decode("utf-8"))
        if not isinstance(result, dict):
            raise ValueError("AI response must be a JSON object")
        return result
    finally:
        conn.close()


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
    def __init__(self, token: str = None, require_auth: bool = False, allow_lan: bool = False):
        self.start_time = time.time()
        self.token = token or os.environ.get("MERSAD_LAB_TOKEN") or secrets.token_urlsafe(16)
        self.require_auth = bool(require_auth)
        self.allow_lan = bool(allow_lan)
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


def _normalize_allowed_host(value: str) -> str:
    raw = str(value or "").strip().lower()
    if not raw or any(ch in raw for ch in ("/", "\\", "@", "%")):
        raise ValueError("invalid allowed host")
    try:
        return str(ipaddress.ip_address(raw))
    except ValueError:
        if raw.endswith("."):
            raw = raw[:-1]
        if not raw or any(not part for part in raw.split(".")):
            raise ValueError("invalid allowed host")
        return raw.encode("idna").decode("ascii").lower()


def _configured_lab_allowed_hosts() -> set:
    raw = os.environ.get("MERSAD_LAB_ALLOWED_HOSTS", "")
    hosts = set()
    for item in raw.split(","):
        if item.strip():
            hosts.add(_normalize_allowed_host(item))
    return hosts


def _is_loopback_bind(host: str) -> bool:
    value = str(host or "").strip().lower()
    if value == "localhost":
        return True
    try:
        return ipaddress.ip_address(value).is_loopback
    except ValueError:
        return False


def _validate_lab_bind_policy(host: str, allow_lan: bool, token: str = None) -> None:
    """Fail closed before socket creation when a non-loopback LAB bind is requested."""
    if _is_loopback_bind(host):
        return
    if not allow_lan:
        raise ValueError("Non-loopback LAB binding requires --allow-lan")
    allowed_hosts = _configured_lab_allowed_hosts()
    if not allowed_hosts:
        raise ValueError("LAN binding requires MERSAD_LAB_ALLOWED_HOSTS with explicit client-facing host names/IPs")
    bind_value = str(host).strip()
    if bind_value not in ("0.0.0.0", "::"):
        normalized_bind = _normalize_allowed_host(bind_value)
        if normalized_bind not in allowed_hosts:
            raise ValueError("MERSAD_LAB_ALLOWED_HOSTS must include the configured bind address")
    if not str(token or os.environ.get("MERSAD_LAB_TOKEN", "")).strip():
        raise ValueError("LAN binding requires an explicitly configured LAB token (--token or MERSAD_LAB_TOKEN)")


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
        """Validate authority/port safely, including bracketed IPv6, before processing a request."""
        host_hdr = (self.headers.get("Host") or "").strip()
        if not host_hdr:
            self._json({"ok": False, "error": "رفض الطلب: ترويسة Host مطلوبة"}, code=400)
            return False
        try:
            parsed_host = urllib.parse.urlsplit("//" + host_hdr)
            host_only = _normalize_allowed_host(parsed_host.hostname or "")
            host_port = parsed_host.port
            if parsed_host.username is not None or parsed_host.password is not None or parsed_host.path or parsed_host.query or parsed_host.fragment:
                raise ValueError("invalid Host authority")
            if host_port is not None and host_port != int(self.server.server_address[1]):
                raise ValueError("unexpected Host port")
        except (ValueError, UnicodeError):
            self._json({"ok": False, "error": "رفض الطلب: ترويسة Host غير صالحة"}, code=400)
            return False

        allowed_hosts = {"127.0.0.1", "localhost", "::1"}
        srv_host = str(self.server.server_address[0]).lower()
        if srv_host not in ("0.0.0.0", "::", ""):
            allowed_hosts.add(_normalize_allowed_host(srv_host))
        try:
            allowed_hosts.update(_configured_lab_allowed_hosts())
        except (ValueError, UnicodeError):
            self._json({"ok": False, "error": "سياسة أسماء المضيفين المسموحة غير صالحة"}, code=503)
            return False
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
        q_tok = "" if require_for_mutation else (qs.get("token") or qs.get("k") or [""])[0].strip()
        h_tok = (self.headers.get("X-Lab-Token") or "").strip()
        auth_hdr = (self.headers.get("Authorization") or "").strip()
        if auth_hdr.lower().startswith("bearer "):
            h_tok = auth_hdr[7:].strip()
        c_tok = ""
        raw_cookie = self.headers.get("Cookie", "")
        if raw_cookie:
            # SimpleCookie may silently discard malformed fragments instead of
            # raising CookieError, so validate each name=value pair first.
            for part in raw_cookie.split(";"):
                pair = part.strip()
                name, sep, value = pair.partition("=")
                if (
                    not sep
                    or not re.fullmatch(r"[!#$%&'*+.^_|~0-9A-Za-z-]+", name.strip())
                    or any(ord(ch) < 0x21 or ord(ch) == 0x7f for ch in value.strip())
                ):
                    self._json({"ok": False, "error": "ترويسة Cookie غير صالحة"}, code=400)
                    return False
            try:
                c = http.cookies.SimpleCookie()
                c.load(raw_cookie)
                if not c:
                    self._json({"ok": False, "error": "ترويسة Cookie غير صالحة"}, code=400)
                    return False
                if "mersad_lab_k" in c:
                    c_tok = c["mersad_lab_k"].value
            except http.cookies.CookieError:
                self._json({"ok": False, "error": "ترويسة Cookie غير صالحة"}, code=400)
                return False

        # State-changing requests must authenticate with an explicit header.
        # Browser cookies and query-string tokens are never accepted for mutations.
        provided = h_tok or q_tok or ("" if require_for_mutation else c_tok)
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
            # Health remains unauthenticated for loopback diagnostics only. LAN mode
            # requires the same explicit header as other sensitive API routes.
            if self.state.allow_lan and not self._check_auth(require_for_mutation=True):
                return
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
        if not self._check_auth(require_for_mutation=True):
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
            if not isinstance(data, dict):
                return self._json({"ok": False, "error": "بيانات الربط غير صالحة"}, code=400)
            ai_url = str(data.get("ai_url") or "http://127.0.0.1:8765").strip()
            ai_token = str(data.get("ai_token") or "").strip()
            if len(ai_token) > 4096 or "\r" in ai_token or "\n" in ai_token:
                return self._json({"ok": False, "error": "رمز المصادقة غير صالح"}, code=400)
            try:
                target = _validate_ai_connect_url(ai_url)
            except ValueError:
                return self._json({"ok": False, "error": "عنوان خادم مرصاد غير مسموح أو غير صالح"}, code=400)
            cam_id = str(data.get("cam_id") or "cam1").strip()
            cam_name = str(data.get("cam_name") or f"LAB_{cam_id.upper()}").strip()
            cam = self.state.get_camera(cam_id)
            if cam is None:
                return self._json({"ok": False, "error": "الكاميرا المطلوبة غير موجودة في المختبر"}, code=404)
            lab_host, lab_port = self.server.server_address
            eff_host = "127.0.0.1" if lab_host in ("0.0.0.0", "") else lab_host
            if ":" in eff_host and not eff_host.startswith("["):
                eff_host = f"[{eff_host}]"
            stream_url = f"http://{eff_host}:{lab_port}/stream/{cam.cam_id}.mjpg"
            req_body = json.dumps({"name": cam_name, "source": stream_url}).encode("utf-8")
            try:
                ai_resp = _send_pinned_ai_request(target, req_body, ai_token)
                return self._json({"ok": True, "stream_url": stream_url, "ai_response": ai_resp})
            except Exception as exc:
                log.warning("MERSAD AI connection failed (%s)", type(exc).__name__)
                return self._json({"ok": False, "error": "تعذّر الاتصال بخادم مرصاد"}, code=502)

        return self._json({"ok": False, "error": "المسار غير موجود"}, code=404)


class LabServerController:
    """Clean start/stop wrapper around LabHTTPServer with zero hanging threads."""

    def __init__(self, host: str = DEFAULT_HOST, port: int = DEFAULT_PORT, token: str = None, require_auth: bool = False, allow_lan: bool = False):
        _validate_lab_bind_policy(host, allow_lan, token=token)
        self.state = LabState(token=token, require_auth=require_auth, allow_lan=allow_lan)
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

    generated_token = not args.token and not os.environ.get("MERSAD_LAB_TOKEN")
    try:
        ctrl = LabServerController(
            host=args.host, port=args.port, token=args.token,
            require_auth=args.require_auth, allow_lan=args.allow_lan,
        )
    except (OSError, ValueError) as exc:
        print(f"[SECURITY ERROR] LAB bind policy rejected startup: {type(exc).__name__}: {exc}", file=sys.stderr)
        sys.exit(2)
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
    if generated_token:
        # Show the auto-generated credential only to the local operator console.
        # It is never returned by HTTP and is not stored in browser cookies.
        print(f"  LAB API Token: {ctrl.state.token}", flush=True)
        print("  Enter this token in the LAB page; keep it private.")
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
