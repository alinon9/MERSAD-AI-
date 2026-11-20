"""Tiny dependency-free web server: live MJPEG video (per-camera support) + Server-Sent Events + registry & path-tracking API.
Supports HttpOnly session cookie (with 302 redirect on first ?k=TOKEN visit to strip token from URL)
while retaining full backward compatibility with ?k=TOKEN query parameters."""
import http.cookies, ipaddress, json, logging, os, queue, re, secrets, socket, ssl, sys, threading, time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, unquote, urlparse, urlsplit

BASE = getattr(sys, "_MEIPASS", os.path.dirname(os.path.abspath(__file__)))
MAX_UPLOAD = 5_000_000
log = logging.getLogger("mersad.server")


def resolve_dashboard_path(filename="dashboard.html"):
    """Resolve static UI asset path reliably across source tree, PyInstaller _MEIPASS, and frozen .exe directory (GAP-12)."""
    candidates = []
    meipass = getattr(sys, "_MEIPASS", None)
    if meipass:
        candidates.append(os.path.join(meipass, filename))
    if getattr(sys, "frozen", False):
        candidates.append(os.path.join(os.path.dirname(os.path.abspath(sys.executable)), filename))
    candidates.append(os.path.join(BASE, filename))
    candidates.append(os.path.join(os.path.dirname(os.path.abspath(__file__)), filename))
    data_dir = os.environ.get("MERSAD_DATA_DIR")
    if data_dir:
        candidates.append(os.path.join(data_dir, filename))
    candidates.append(os.path.abspath(filename))
    for c in candidates:
        if c and os.path.isfile(c):
            return c
    return os.path.join(BASE, filename)


class Bus:
    def __init__(self):
        self._lock = threading.RLock()
        self.frame, self.fid, self.subs, self.alerts, self.failed_dispatches = None, 0, [], [], []
        self.cam_frames = {}                             # cam_id -> {"jpg": bytes, "fid": int, "status": str, "ts": float}
        self.cam_status = {}                             # cam_id -> str ("online" | "reconnecting" | "offline")
        self.token = os.environ.get("MERSAD_TOKEN", "").strip() or secrets.token_urlsafe(24)
        self.post = {}                                   # path -> fn(data: dict, ip) -> dict
        self.verify = lambda: "Audit chain OK (0 records)"
        self.on_list = self.on_template = self.on_import = self.on_insights = self.on_stats = self.on_path = None
        self.on_camera_links = self.on_camera_links_export = self.on_camera_links_import = None
        self.on_field_calibrations = self.on_field_calibrations_export = self.on_field_calibrations_import = None
        self.on_plate_eval_status = self.on_plate_eval_history = self.on_plate_eval_export = self.on_plate_eval_template = None
        self.on_camera_links_suggestions = self.on_readiness = None
        self.on_cameras_list = None
        self.active_mjpeg_clients = 0
        self.max_mjpeg_clients = 16
        self.on_analytics = self.on_analytics_export = None
        self.on_camera_health = self.on_camera_health_export = None
        self.auth_failures = {}                          # ip -> [count, window_start_ts, blocked_until_ts]
        self.auth_max_failures = 15
        self.auth_window_sec = 60.0
        self.auth_block_sec = 60.0
        self.evidence_dir = "evidence"
        self.archive_dir = "evidence_archive"
        self.stop_event = threading.Event()

    def set_frame(self, jpg, cam=None, status="online"):
        now_ts = time.time()
        with self._lock:
            self.frame, self.fid = jpg, self.fid + 1
            if cam:
                prev = self.cam_frames.get(cam, {})
                self.cam_frames[cam] = {
                    "jpg": jpg,
                    "fid": prev.get("fid", 0) + 1,
                    "status": status,
                    "ts": now_ts
                }
                self.cam_status[cam] = status

    def get_stream_frame(self, cam=""):
        with self._lock:
            if cam and cam in self.cam_frames:
                cf = self.cam_frames[cam]
                return cf.get("fid", 0), cf.get("jpg")
            return self.fid, self.frame

    def get_init_payload(self):
        with self._lock:
            alerts_copy = list(self.alerts)
            fdisp_copy = list(self.failed_dispatches)
        return json.dumps({"type": "init", "alerts": alerts_copy, "failed_dispatches": fdisp_copy}, ensure_ascii=False)

    max_subs = 32

    def add_sub(self, q):
        with self._lock:
            if q not in self.subs:
                if len(self.subs) >= self.max_subs:
                    self.subs.pop(0)
                self.subs.append(q)

    def remove_sub(self, q):
        with self._lock:
            while q in self.subs:
                self.subs.remove(q)

    def publish(self, ev):
        if isinstance(ev, dict) and ev.get("type") == "camera_status" and ev.get("cam"):
            with self._lock:
                self.cam_status[ev["cam"]] = ev.get("status", "unknown")
        s = json.dumps(ev, ensure_ascii=False)
        with self._lock:
            subs_snapshot = list(self.subs)
        for q in subs_snapshot:
            try:
                q.put_nowait(s)
            except Exception:
                pass


bus = Bus()


def _normalize_host_name(value):
    raw = str(value or "").strip().lower().rstrip(".")
    if not raw or any(ch in raw for ch in ("/", "\\\\", "@", "%")):
        raise ValueError("invalid host")
    try:
        return str(ipaddress.ip_address(raw))
    except ValueError:
        return raw.encode("idna").decode("ascii").lower()


def _configured_allowed_hosts():
    raw = os.environ.get("MERSAD_ALLOWED_HOSTS", "")
    return {_normalize_host_name(item) for item in raw.split(",") if item.strip()}


def _is_loopback_bind(host):
    value = str(host or "").strip().lower()
    if value == "localhost":
        return True
    try:
        return ipaddress.ip_address(value).is_loopback
    except ValueError:
        return False


def _redact_log_text(value):
    text = str(value or "")
    text = re.sub(r"(?i)((?:rtsp|rtsps|https?)://[^:/\s]+:)[^@/\s]+(@)", r"\1***\2", text)
    text = re.sub(r"(?i)([?&](?:k|token)=)[^&\s]+", r"\1<REDACTED>", text)
    token = str(getattr(bus, "token", "") or "")
    if token:
        text = text.replace(token, "<REDACTED_TOKEN>")
    return text


class H(BaseHTTPRequestHandler):
    timeout = 15

    def log_message(self, *a): pass

    def arg(self, k): return parse_qs(urlparse(self.path).query).get(k, [""])[0]

    def _validate_host_header(self):
        raw = (self.headers.get("Host") or "").strip()
        if not raw:
            self._json({"ok": False, "error": "ترويسة Host مطلوبة"}, code=400)
            return False
        try:
            parsed = urlsplit("//" + raw)
            hostname = _normalize_host_name(parsed.hostname or "")
            port = parsed.port
            if parsed.username is not None or parsed.password is not None or parsed.path or parsed.query or parsed.fragment:
                raise ValueError("invalid Host authority")
            server_port = int(self.server.server_address[1])
            if port is not None and port != server_port:
                raise ValueError("unexpected Host port")
            allowed = {"127.0.0.1", "localhost", "::1"}
            bound_host = str(self.server.server_address[0]).lower()
            if bound_host not in ("0.0.0.0", "::", ""):
                allowed.add(_normalize_host_name(bound_host))
            allowed.update(_configured_allowed_hosts())
        except (ValueError, UnicodeError):
            self._json({"ok": False, "error": "ترويسة Host غير صالحة"}, code=400)
            return False
        if hostname not in allowed:
            self._json({"ok": False, "error": "ترويسة Host غير موثوقة (DNS Rebinding Blocked)"}, code=403)
            return False
        return True

    def _cookie_token(self):
        raw_c = self.headers.get("Cookie", "")
        if not raw_c:
            return ""
        try:
            c = http.cookies.SimpleCookie()
            c.load(raw_c)
            if "mersad_k" in c:
                return c["mersad_k"].value
        except Exception:
            pass
        return ""

    def _auth(self):
        client_ip = str(self.client_address[0] if getattr(self, "client_address", None) else "unknown")
        now_ts = time.time()
        with bus._lock:
            rec = bus.auth_failures.get(client_ip)
            if rec and now_ts < rec[2]:
                retry_sec = max(1, int(round(rec[2] - now_ts)))
                self._send(
                    json.dumps(
                        {
                            "ok": False,
                            "error": "تم حظر المحاولات مؤقتاً بسبب تجاوز عدد محاولات الدخول الخاطئة؛ حاول بعد دقيقة",
                            "retry_after_sec": retry_sec,
                        },
                        ensure_ascii=False,
                    ).encode("utf-8"),
                    "application/json; charset=utf-8",
                    headers={"Retry-After": str(retry_sec)},
                    code=429,
                )
                return None
        # Cookie/header auth is used by the dashboard. Legacy ?k= links remain
        # accepted for compatibility, but the current dashboard never emits them.
        provided = self.arg("k") or self._cookie_token() or self.headers.get("X-Mersad-Token", "")
        if not provided or not bus.token or not secrets.compare_digest(str(provided), str(bus.token)):
            with bus._lock:
                if len(bus.auth_failures) >= 1024 and client_ip not in bus.auth_failures:
                    expired_ips = [
                        ip for ip, r in bus.auth_failures.items()
                        if now_ts >= r[2] and (now_ts - r[1]) > bus.auth_window_sec
                    ]
                    for ip in expired_ips[:256]:
                        bus.auth_failures.pop(ip, None)
                    if len(bus.auth_failures) >= 1024:
                        oldest_ip = min(bus.auth_failures.keys(), key=lambda ip: bus.auth_failures[ip][1])
                        bus.auth_failures.pop(oldest_ip, None)
                rec = bus.auth_failures.get(client_ip)
                if not rec or (now_ts - rec[1]) > bus.auth_window_sec:
                    rec = [1, now_ts, 0.0]
                else:
                    rec[0] += 1
                if rec[0] >= bus.auth_max_failures:
                    rec[2] = now_ts + bus.auth_block_sec
                bus.auth_failures[client_ip] = rec
            try:
                self.send_error(403, "Forbidden")
            except (BrokenPipeError, ConnectionResetError, ConnectionAbortedError):
                pass
            return None
        with bus._lock:
            bus.auth_failures.pop(client_ip, None)
        return urlparse(self.path).path

    def _send(self, body, ctype="text/html; charset=utf-8", headers=None, code=200):
        try:
            self.send_response(code)
            self.send_header("Content-Type", ctype)
            self.send_header("Content-Length", str(len(body)))
            self.send_header("X-Content-Type-Options", "nosniff")
            self.send_header("X-Frame-Options", "DENY")
            self.send_header("Referrer-Policy", "no-referrer")
            self.send_header(
                "Content-Security-Policy",
                "default-src 'self'; img-src 'self' data: blob:; style-src 'self' 'unsafe-inline'; script-src 'self' 'unsafe-inline'; connect-src 'self'; frame-ancestors 'none'",
            )
            self.send_header("Cache-Control", "no-store")
            for k, v in (headers or {}).items():
                self.send_header(k, v)
            self.end_headers()
            self.wfile.write(body)
        except (BrokenPipeError, ConnectionResetError, ConnectionAbortedError):
            pass

    def _json(self, o, code=200):
        self._send(json.dumps(o, ensure_ascii=False).encode("utf-8"), "application/json; charset=utf-8", code=code)

    def _serve_evidence(self, req_path):
        """Strictly prevent path traversal and symlinks; serve .jpg from evidence/ or evidence_archive/."""
        raw_rel = unquote(req_path[len("/evidence/"):])
        if not raw_rel or "/" in raw_rel or "\\" in raw_rel or ".." in raw_rel or not raw_rel.lower().endswith(".jpg"):
            self.send_error(403, "Invalid evidence path"); return
        for folder in (bus.evidence_dir, bus.archive_dir):
            root = os.path.realpath(folder)
            candidate = os.path.join(folder, raw_rel)
            if os.path.islink(candidate):
                self.send_error(403, "Symlinks not allowed"); return
            target = os.path.realpath(candidate)
            if os.path.commonpath([root, target]) == root and os.path.isfile(target):
                with open(target, "rb") as f:
                    self._send(f.read(), "image/jpeg")
                return
        self.send_error(404, "Evidence not found")

    def do_GET(self):
        if not self._validate_host_header():
            return
        p = self._auth()
        if p is None: return
        try:
            if p == "/":
                if self.arg("k") and self.arg("noredir") != "1":
                    secure_attr = "; Secure" if isinstance(self.connection, ssl.SSLSocket) else ""
                    cookie_val = f"mersad_k={bus.token}; HttpOnly; SameSite=Strict; Path=/{secure_attr}"
                    self.send_response(302)
                    self.send_header("Set-Cookie", cookie_val)
                    self.send_header("Location", "/")
                    self.send_header("Referrer-Policy", "no-referrer")
                    self.send_header("Cache-Control", "no-store")
                    self.send_header("Content-Length", "0")
                    self.end_headers()
                    return
                with open(resolve_dashboard_path("dashboard.html"), "rb") as f:
                    self._send(f.read())
            elif p == "/stream.mjpg": self.stream(self.arg("cam"))
            elif p == "/events": self.events()
            elif p == "/api/ping": self._json({"ok": True, "ts": time.time()})
            elif p == "/api/verify": self._json({"result": bus.verify() if bus.verify else "OK"})
            elif p == "/api/stats": self._json(bus.on_stats() if bus.on_stats else {"ok": True})
            elif p == "/api/analytics": self._json(bus.on_analytics() if bus.on_analytics else {"ok": False, "error": "التحليلات غير متاحة"})
            elif p == "/api/analytics/export.csv":
                body = bus.on_analytics_export() if bus.on_analytics_export else b"\xef\xbb\xbf"
                self._send(body, "text/csv; charset=utf-8", {"Content-Disposition": 'attachment; filename="mersad_analytics.csv"'})
            elif p == "/api/camera-health": self._json(bus.on_camera_health(self.arg("period") or "24h") if bus.on_camera_health else {"ok": False, "error": "سجل صحة الكاميرات غير متاح"})
            elif p == "/api/camera-health/export.csv":
                body = bus.on_camera_health_export(self.arg("period") or "24h") if bus.on_camera_health_export else b"\xef\xbb\xbf"
                self._send(body, "text/csv; charset=utf-8", {"Content-Disposition": 'attachment; filename="mersad_camera_health.csv"'})
            elif p == "/api/insights":
                inc_demo = self.arg("demo").strip().lower() in ("1", "true", "yes")
                try:
                    self._json(bus.on_insights(include_demo=inc_demo))
                except TypeError:
                    self._json(bus.on_insights())
            elif p == "/api/path" and bus.on_path:
                inc_demo = self.arg("demo").strip().lower() in ("1", "true", "yes")
                try:
                    self._json(bus.on_path(self.arg("plate"), include_demo=inc_demo))
                except TypeError:
                    self._json(bus.on_path(self.arg("plate")))
            elif p == "/api/camera_links":
                if bus.on_camera_links:
                    try:
                        self._json(bus.on_camera_links(q=self.arg("q")[:80], status=self.arg("status")[:40]))
                    except TypeError:
                        self._json(bus.on_camera_links())
                else:
                    self._json({"ok": True, "links": [], "inferred_links": [], "calibrated_cameras": []})
            elif p == "/api/readiness":
                self._json(bus.on_readiness() if bus.on_readiness else {"ok": True})
            elif p == "/api/cameras":
                self._json(bus.on_cameras_list() if bus.on_cameras_list else {"ok": True, "cameras": {}})
            elif p == "/api/camera_links/suggestions":
                inc_demo = self.arg("demo").strip().lower() in ("1", "true", "yes")
                min_obs = int(self.arg("min_obs")) if self.arg("min_obs").strip().isdigit() else 3
                self._json(bus.on_camera_links_suggestions(include_demo=inc_demo, min_observations=min_obs) if bus.on_camera_links_suggestions else {"ok": True, "suggestions": []})
            elif p == "/api/camera_links/export" and bus.on_camera_links_export:
                body, name, mime = bus.on_camera_links_export(self.arg("fmt") or "json")
                self._send(body, mime, {"Content-Disposition": f'attachment; filename="{name}"'})
            elif p == "/api/field_calibrations":
                self._json(bus.on_field_calibrations() if bus.on_field_calibrations else {"ok": True, "items": []})
            elif p == "/api/field_calibrations/export" and bus.on_field_calibrations_export:
                body, name, mime = bus.on_field_calibrations_export(self.arg("fmt") or "json")
                self._send(body, mime, {"Content-Disposition": f'attachment; filename="{name}"'})
            elif p == "/api/plate_eval/status":
                self._json(bus.on_plate_eval_status() if bus.on_plate_eval_status else {"ok": True, "running": False, "status": "idle"})
            elif p == "/api/plate_eval/history":
                self._json(bus.on_plate_eval_history() if bus.on_plate_eval_history else {"ok": True, "runs": []})
            elif p == "/api/plate_eval/export" and bus.on_plate_eval_export:
                body, name, mime = bus.on_plate_eval_export(self.arg("fmt") or "json")
                self._send(body, mime, {"Content-Disposition": f'attachment; filename="{name}"'})
            elif p == "/api/plate_eval/template" and bus.on_plate_eval_template:
                body, name, mime = bus.on_plate_eval_template(self.arg("fmt") or "csv")
                self._send(body, mime, {"Content-Disposition": f'attachment; filename="{name}"'})
            elif p == "/api/list" and self.arg("kind") in ("vehicles", "persons"):
                self._json(bus.on_list(self.arg("kind"), self.arg("q")[:80]))
            elif p == "/api/template" and self.arg("kind") in ("vehicles", "persons"):
                body, name, mime = bus.on_template(self.arg("kind"))
                self._send(body, mime, {"Content-Disposition": f'attachment; filename="{name}"'})
            elif p.startswith("/evidence/"):
                self._serve_evidence(p)
            elif p.startswith("/api/"):
                self._json({"ok": False, "error": "المسار غير موجود"}, code=404)
            else:
                self.send_error(404)
        except FileNotFoundError:
            try: self.send_error(404)
            except (BrokenPipeError, ConnectionResetError, ConnectionAbortedError): pass
        except (BrokenPipeError, ConnectionResetError, ConnectionAbortedError):
            pass
        except Exception as e:
            log.error("GET %s failed: %s", p, _redact_log_text(e))
            self._json({"ok": False, "error": "حدث خطأ داخلي في الخادم"}, code=500)

    def do_POST(self):
        if not self._validate_host_header():
            return
        p = self._auth()
        if p is None: return
        try:
            origin_hdr = self.headers.get("Origin", "").strip()
            host_hdr = self.headers.get("Host", "").strip()
            has_explicit_auth = bool((self.headers.get("X-Mersad-Token") or "").strip())
            if not origin_hdr and not has_explicit_auth:
                return self._json(
                    {"ok": False, "error": "طلبات POST دون Origin تتطلب ترويسة X-Mersad-Token صريحة"},
                    code=403,
                )
            if origin_hdr:
                if origin_hdr.lower() == "null":
                    return self._json({"ok": False, "error": "رفض الطلب بسبب مصدر غير موثوق (Origin: null CSRF Blocked)"}, code=403)
                if host_hdr:
                    orig_netloc = urlparse(origin_hdr).netloc.strip().lower()
                    if not orig_netloc or orig_netloc != host_hdr.lower():
                        return self._json({"ok": False, "error": "رفض الطلب بسبب تعارض المصدر (CSRF Origin Mismatch)"}, code=403)
            try:
                n = int(self.headers.get("Content-Length", 0))
            except ValueError:
                return self._json({"ok": False, "error": "ترويسة Content-Length غير صالحة"}, code=400)
            if n < 0:
                return self._json({"ok": False, "error": "ترويسة Content-Length غير صالحة"}, code=400)
            if n > MAX_UPLOAD:
                return self._json({"ok": False, "error": "حجم الملف يتجاوز الحد الأقصى المسموح (5 ميجابايت)"}, code=413)
            raw, ip = self.rfile.read(n), self.client_address[0]
            try:
                with bus._lock:
                    post_fn = bus.post.get(p)
                has_import_guard = bool(self.headers.get("X-Mersad-Token") or self.headers.get("X-Filename"))
                ctype_low = (self.headers.get("Content-Type") or "").strip().lower()
                if p in ("/api/import", "/api/camera_links/import", "/api/field_calibrations/import") and (not has_import_guard or ctype_low.startswith("text/plain")):
                    return self._json({"ok": False, "error": "رفض طلب الاستيراد لحماية الجلسة (يتطلب ترويسة X-Filename أو رمز X-Mersad-Token)"}, code=403)
                if p == "/api/import" and self.arg("kind") in ("vehicles", "persons"):
                    res = bus.on_import(self.arg("kind"), unquote(self.headers.get("X-Filename", "")), raw, ip)
                elif p == "/api/camera_links/import" and bus.on_camera_links_import:
                    res = bus.on_camera_links_import(unquote(self.headers.get("X-Filename", "")), raw, ip)
                elif p == "/api/field_calibrations/import" and bus.on_field_calibrations_import:
                    res = bus.on_field_calibrations_import(unquote(self.headers.get("X-Filename", "")), raw, ip)
                elif post_fn is not None:
                    ctype_hdr = (self.headers.get("Content-Type") or "").strip().lower()
                    has_explicit_tok = bool(self.headers.get("X-Mersad-Token"))
                    if not has_explicit_tok and not ctype_hdr.startswith("application/json"):
                        return self._json(
                            {"ok": False, "error": "رفض الطلب لحماية الجلسة (يتطلب Content-Type: application/json أو رمز X-Mersad-Token)"},
                            code=403,
                        )
                    payload = json.loads(raw.decode("utf-8") if raw else "{}")
                    if not isinstance(payload, dict):
                        res = {"ok": False, "error": "بيانات الطلب غير صالحة"}
                    else:
                        res = post_fn(payload, ip)
                elif p.startswith("/api/"):
                    return self._json({"ok": False, "error": "المسار غير موجود"}, code=404)
                else:
                    return self.send_error(404)
            except json.JSONDecodeError:
                res = {"ok": False, "error": "صيغة JSON غير صالحة"}
                response_code = 400
            except Exception as e:
                log.error("POST %s failed: %s", p, _redact_log_text(e))
                res = {"ok": False, "error": "تعذّر معالجة الطلب"}
                response_code = 500
            else:
                response_code = 400 if isinstance(res, dict) and res.get("ok") is False else 200
            self._json(res, code=response_code)
        except (BrokenPipeError, ConnectionResetError, ConnectionAbortedError):
            pass

    def stream(self, cam=""):
        with bus._lock:
            if bus.active_mjpeg_clients >= bus.max_mjpeg_clients:
                return self._json({"ok": False, "error": "تم تجاوز الحد الأقصى لاتصالات البث المتزامنة"}, code=429)
            bus.active_mjpeg_clients += 1
        try:
            self.send_response(200)
            self.send_header("Content-Type", "multipart/x-mixed-replace; boundary=f")
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            last = -1
            idle_ticks = 0
            while not bus.stop_event.is_set():
                cur_fid, b = bus.get_stream_frame(cam)
                if b is not None and cur_fid != last:
                    last = cur_fid
                    idle_ticks = 0
                    self.wfile.write(b"--f\r\nContent-Type: image/jpeg\r\nContent-Length: %d\r\n\r\n" % len(b) + b + b"\r\n")
                else:
                    idle_ticks += 1
                    if idle_ticks >= 125 and b is not None:
                        idle_ticks = 0
                        self.wfile.write(b"--f\r\nContent-Type: image/jpeg\r\nContent-Length: %d\r\n\r\n" % len(b) + b + b"\r\n")
                time.sleep(0.04)
        except (BrokenPipeError, ConnectionResetError, ConnectionAbortedError, OSError):
            return
        finally:
            with bus._lock:
                bus.active_mjpeg_clients = max(0, bus.active_mjpeg_clients - 1)

    def events(self):
        q = queue.Queue(maxsize=200)
        bus.add_sub(q)
        try:
            self.send_response(200)
            self.send_header("Content-Type", "text/event-stream; charset=utf-8")
            self.send_header("Cache-Control", "no-cache")
            self.end_headers()
            init = bus.get_init_payload()
            self.wfile.write(f"data: {init}\n\n".encode("utf-8"))
            while not bus.stop_event.is_set():
                try:
                    self.wfile.write(f"data: {q.get(timeout=5)}\n\n".encode("utf-8"))
                except queue.Empty:
                    if not bus.stop_event.is_set():
                        self.wfile.write(b": ping\n\n")
        except (BrokenPipeError, ConnectionResetError, ConnectionAbortedError):
            return
        finally:
            bus.remove_sub(q)


def get_lan_ip():
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
            s.connect(("10.255.255.255", 1))
            return s.getsockname()[0]
    except Exception:
        try:
            return socket.gethostbyname(socket.gethostname())
        except Exception:
            return "127.0.0.1"


def _write_operator_token_file():
    """Persist the operator credential outside the repository; never print the secret."""
    root = os.path.join(os.path.expanduser("~"), ".mersad")
    os.makedirs(root, exist_ok=True)
    path = os.environ.get("MERSAD_TOKEN_FILE") or os.path.join(root, "session.token")
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            handle.write(str(bus.token) + "\n")
    except Exception:
        try:
            os.close(fd)
        except OSError:
            pass
        raise
    try:
        os.chmod(path, 0o600)
    except OSError:
        pass
    return path


def start_server(port=8000, host="127.0.0.1"):
    """Start locally by default; non-loopback interfaces are TLS-only and host-allowlisted."""
    is_loopback = _is_loopback_bind(host)
    tls_context = None
    if not is_loopback:
        cert_file = os.environ.get("MERSAD_TLS_CERT", "").strip()
        key_file = os.environ.get("MERSAD_TLS_KEY", "").strip()
        if not cert_file or not key_file or not os.path.isfile(cert_file) or not os.path.isfile(key_file):
            raise RuntimeError("LAN mode is disabled without valid MERSAD_TLS_CERT and MERSAD_TLS_KEY files")
        allowed_hosts = _configured_allowed_hosts()
        lan_ip = get_lan_ip() if str(host).strip() in ("0.0.0.0", "::") else _normalize_host_name(host)
        if not allowed_hosts or lan_ip not in allowed_hosts:
            raise RuntimeError("LAN mode requires MERSAD_ALLOWED_HOSTS to explicitly include the served LAN address")
        tls_context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
        tls_context.minimum_version = ssl.TLSVersion.TLSv1_2
        tls_context.load_cert_chain(certfile=cert_file, keyfile=key_file)

    ThreadingHTTPServer.daemon_threads = True
    ThreadingHTTPServer.allow_reuse_address = True
    bus.stop_event.clear()
    srv = ThreadingHTTPServer((host, port), H)
    if tls_context is not None:
        srv.socket = tls_context.wrap_socket(srv.socket, server_side=True)
    thread = threading.Thread(target=srv.serve_forever, daemon=True, name="mersad-http")
    srv._mersad_thread = thread
    thread.start()

    token_file = _write_operator_token_file()
    scheme = "https" if tls_context is not None else "http"
    print(f"\nDashboard URL: {scheme}://127.0.0.1:{srv.server_address[1]}/")
    if not is_loopback:
        lan_ip = get_lan_ip() if str(host).strip() in ("0.0.0.0", "::") else str(host)
        print(f"LAN Dashboard URL: https://{lan_ip}:{srv.server_address[1]}/")
    print(f"Access credential file: {token_file}")
    print("For first sign-in, append ?k=<contents of session.token> once; the server immediately redirects and clears the URL.")
    return srv


def stop_server(server, timeout=5.0):
    """Stop request loops, close the listener, and join the serving thread."""
    if server is None:
        return
    bus.stop_event.set()
    try:
        server.shutdown()
    finally:
        server.server_close()
    thread = getattr(server, "_mersad_thread", None)
    if thread is not None and thread.is_alive():
        thread.join(timeout=max(0.0, float(timeout)))
