"""Tiny dependency-free web server: live MJPEG video (per-camera support) + Server-Sent Events + registry & path-tracking API.
Supports HttpOnly session cookie (with 302 redirect on first ?k=TOKEN visit to strip token from URL)
while retaining full backward compatibility with ?k=TOKEN query parameters."""
import http.cookies, ipaddress, json, logging, os, queue, re, secrets, socket, ssl, sys, threading, time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, unquote, urlparse

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
        self.token = secrets.token_urlsafe(12)
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


_LOG_URL_CREDENTIALS = re.compile(r"(?i)\\b(rtsp|rtsps|http|https)://([^/@\\s:]+):([^/@\\s]+)@")
_LOG_BOT_TOKEN = re.compile(r"(?i)(/bot)[0-9]{5,}:[A-Za-z0-9_-]+")
_LOG_SECRET_PARAM = re.compile(r"(?i)(token|authorization|password|passwd)=([^&\\s]+)")


def _redact_log_text(value):
    text = str(value or "")
    text = _LOG_URL_CREDENTIALS.sub(r"\\1://[REDACTED]@", text)
    text = _LOG_BOT_TOKEN.sub(r"\\1[REDACTED]", text)
    text = _LOG_SECRET_PARAM.sub(r"\\1=[REDACTED]", text)
    return text[:1600]


bus = Bus()


class H(BaseHTTPRequestHandler):
    timeout = 15

    def log_message(self, *a): pass

    def arg(self, k): return parse_qs(urlparse(self.path).query).get(k, [""])[0]

    @staticmethod
    def _parse_authority(authority):
        raw = str(authority or "").strip()
        if not raw or "%" in raw or any(ord(ch) < 33 or ord(ch) == 127 for ch in raw):
            return None
        try:
            parsed = urlparse("//" + raw)
            if parsed.username is not None or parsed.password is not None or parsed.path or parsed.params or parsed.query or parsed.fragment:
                return None
            hostname = parsed.hostname
            port = parsed.port
            if not hostname:
                return None
            try:
                hostname = ipaddress.ip_address(hostname).compressed
            except ValueError:
                hostname = hostname.rstrip(".").lower()
                if not hostname or any(not part or len(part) > 63 for part in hostname.split(".")):
                    return None
            return hostname, port
        except (ValueError, UnicodeError):
            return None

    def _allowed_hosts(self):
        """Exact local Host allowlist for the current bind; wildcard binds admit local interface IPs only."""
        allowed = {"localhost", "127.0.0.1", "::1"}
        bound = str(self.server.server_address[0] or "").lower().split("%", 1)[0]
        if bound not in ("0.0.0.0", "::", ""):
            try:
                allowed.add(ipaddress.ip_address(bound).compressed)
            except ValueError:
                allowed.add(bound.rstrip("."))
        else:
            try:
                for info in socket.getaddrinfo(socket.gethostname(), None, type=socket.SOCK_STREAM):
                    ip_text = str(info[4][0]).split("%", 1)[0]
                    try:
                        allowed.add(ipaddress.ip_address(ip_text).compressed)
                    except ValueError:
                        pass
            except OSError:
                pass
            try:
                allowed.add(ipaddress.ip_address(get_lan_ip()).compressed)
            except (OSError, ValueError):
                pass
        for item in os.environ.get("MERSAD_ALLOWED_HOSTS", "").split(","):
            item = item.strip()
            if not item:
                continue
            parsed = self._parse_authority(item)
            if parsed and parsed[1] is None:
                allowed.add(parsed[0])
        return allowed

    def _validate_host(self):
        host_hdr = self.headers.get("Host", "")
        parts = self._parse_authority(host_hdr)
        if not parts:
            self._json({"ok": False, "error": "Invalid or missing Host header"}, code=403)
            return False
        hostname, port = parts
        server_port = int(self.server.server_address[1])
        if hostname not in self._allowed_hosts() or (port is not None and port != server_port):
            self._json({"ok": False, "error": "Untrusted Host header (DNS rebinding protection)"}, code=403)
            return False
        return True

    def _validate_origin(self, is_post=False):
        origin = (self.headers.get("Origin") or "").strip()
        host_parts = self._parse_authority(self.headers.get("Host", ""))
        if not host_parts:
            self._json({"ok": False, "error": "Invalid Host header"}, code=403)
            return False
        host_name, host_port = host_parts
        if host_port is None:
            host_port = int(self.server.server_address[1])
        if origin:
            if origin.lower() == "null":
                self._json({"ok": False, "error": "Origin: null is not allowed"}, code=403)
                return False
            try:
                parsed = urlparse(origin)
                if parsed.scheme.lower() not in ("http", "https") or parsed.path or parsed.params or parsed.query or parsed.fragment:
                    raise ValueError("invalid origin")
                origin_parts = self._parse_authority(parsed.netloc)
                if not origin_parts:
                    raise ValueError("invalid origin authority")
                origin_name, origin_port = origin_parts
                if origin_port is None:
                    origin_port = 443 if parsed.scheme.lower() == "https" else 80
            except (ValueError, UnicodeError):
                self._json({"ok": False, "error": "Invalid Origin header"}, code=403)
                return False
            if origin_name != host_name or origin_port != host_port:
                self._json({"ok": False, "error": "Origin does not match Host (cross-origin/cross-port request blocked)"}, code=403)
                return False
            if bool(getattr(self.server, "is_tls", False)) != (parsed.scheme.lower() == "https"):
                self._json({"ok": False, "error": "Origin scheme does not match server transport"}, code=403)
                return False
        elif is_post:
            has_header_token = bool(self.headers.get("X-Mersad-Token") or
                                    (self.headers.get("Authorization") or "").lower().startswith("bearer "))
            if self.headers.get("Cookie") and not has_header_token:
                self._json({"ok": False, "error": "Origin is required for cookie-authenticated POST requests"}, code=403)
                return False

        if (self.headers.get("Sec-Fetch-Site") or "").strip().lower() == "cross-site":
            self._json({"ok": False, "error": "Cross-site request blocked"}, code=403)
            return False

        if is_post:
            ctype = (self.headers.get("Content-Type") or "").strip().lower()
            has_header_token = bool(self.headers.get("X-Mersad-Token") or
                                    (self.headers.get("Authorization") or "").lower().startswith("bearer "))
            if ctype.startswith(("text/plain", "application/x-www-form-urlencoded")) and not has_header_token:
                self._json({"ok": False, "error": "Simple-request CSRF blocked"}, code=403)
                return False
        return True

    def _cookie_token(self):
        raw_c = self.headers.get("Cookie", "")
        if not raw_c:
            return ""
        c = http.cookies.SimpleCookie()
        try:
            c.load(raw_c)
            if "mersad_k" in c:
                return c["mersad_k"].value
        except http.cookies.CookieError:
            log.warning("Rejected malformed session cookie from %s", self.client_address[0])
        return ""

    def _header_token(self):
        token = (self.headers.get("X-Mersad-Token") or "").strip()
        auth_hdr = (self.headers.get("Authorization") or "").strip()
        if auth_hdr.lower().startswith("bearer "):
            token = auth_hdr[7:].strip()
        return token

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
        # Query-string tokens are disabled in production. A loopback-only opt-in
        # exists solely for the legacy self-test harness while its older scenarios migrate.
        query_test_opt_in = os.environ.get("MERSAD_TEST_ALLOW_QUERY_TOKEN") == "1"
        query_token = self.arg("k") if query_test_opt_in and self.client_address[0] in ("127.0.0.1", "::1") else ""
        provided = self._header_token() or self._cookie_token() or query_token
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
            is_html = ctype.lower().startswith("text/html")
            nonce = secrets.token_urlsafe(18) if is_html else ""
            if is_html:
                body = re.sub(
                    rb"<script(?=[\s>])",
                    lambda _m: b'<script nonce="' + nonce.encode("ascii") + b'"',
                    body,
                    flags=re.IGNORECASE,
                )
            self.send_response(code)
            self.send_header("Content-Type", ctype)
            self.send_header("Content-Length", str(len(body)))
            self.send_header("X-Content-Type-Options", "nosniff")
            self.send_header("X-Frame-Options", "DENY")
            self.send_header("Referrer-Policy", "no-referrer")
            script_policy = f"script-src 'self' 'nonce-{nonce}'" if is_html else "script-src 'self'"
            self.send_header(
                "Content-Security-Policy",
                "default-src 'self'; img-src 'self' data: blob:; style-src 'self' 'unsafe-inline'; "
                + script_policy
                + "; connect-src 'self'; frame-ancestors 'none'; object-src 'none'; base-uri 'self'",
            )
            self.send_header("Cache-Control", "no-store")
            for k, v in (headers or {}).items():
                self.send_header(k, v)
            self.end_headers()
            self.wfile.write(body)
        except (BrokenPipeError, ConnectionResetError, ConnectionAbortedError):
            pass

    def _json(self, o, code=200, headers=None):
        self._send(json.dumps(o, ensure_ascii=False).encode("utf-8"), "application/json; charset=utf-8", headers=headers, code=code)

    def _create_session(self):
        if self._auth() is None:
            return
        secure_flag = "; Secure" if bool(getattr(self.server, "is_tls", False)) else ""
        cookie = f"mersad_k={bus.token}; HttpOnly; SameSite=Strict; Path=/; Max-Age=28800{secure_flag}"
        self._json({"ok": True, "authenticated": True}, headers={"Set-Cookie": cookie})
        
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
        if not self._validate_host():
            return
        request_path = urlparse(self.path).path
        # The dashboard shell is public but contains no private data.
        # Every API, event stream, image, and export route remains authenticated.
        if request_path in ("/", "/index.html"):
            try:
                with open(resolve_dashboard_path("dashboard.html"), "rb") as f:
                    self._send(f.read())
            except FileNotFoundError:
                self._json({"ok": False, "error": "Dashboard file not found"}, code=404)
            return
        p = self._auth()
        if p is None:
            return
        try:
            if p == "/stream.mjpg": self.stream(self.arg("cam"))
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
        if not self._validate_host():
            return
        if not self._validate_origin(is_post=True):
            return
        request_path = urlparse(self.path).path
        if request_path == "/api/session":
            return self._create_session()
        p = self._auth()
        if p is None:
            return
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
            has_import_guard = bool(
                self.headers.get("X-Mersad-Token")
                or self.headers.get("Authorization")
                or self.headers.get("X-Filename")
            )
            ctype_low = (self.headers.get("Content-Type") or "").strip().lower()
            if p in ("/api/import", "/api/camera_links/import", "/api/field_calibrations/import") and (
                not has_import_guard or ctype_low.startswith("text/plain")
            ):
                return self._json(
                    {"ok": False, "error": "رفض طلب الاستيراد لحماية الجلسة (يتطلب ترويسة X-Filename أو رمز X-Mersad-Token)"},
                    code=403,
                )
            if p == "/api/import" and self.arg("kind") in ("vehicles", "persons"):
                res = bus.on_import(self.arg("kind"), unquote(self.headers.get("X-Filename", "")), raw, ip)
            elif p == "/api/camera_links/import" and bus.on_camera_links_import:
                res = bus.on_camera_links_import(unquote(self.headers.get("X-Filename", "")), raw, ip)
            elif p == "/api/field_calibrations/import" and bus.on_field_calibrations_import:
                res = bus.on_field_calibrations_import(unquote(self.headers.get("X-Filename", "")), raw, ip)
            elif post_fn is not None:
                ctype_hdr = (self.headers.get("Content-Type") or "").strip().lower()
                has_explicit_tok = bool(self.headers.get("X-Mersad-Token") or self.headers.get("Authorization"))
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
            return self._json({"ok": False, "error": "صيغة JSON غير صالحة"}, code=400)
        except (BrokenPipeError, ConnectionResetError, ConnectionAbortedError):
            return
        except Exception as e:
            log.error("POST %s failed: %s", p, _redact_log_text(e))
            return self._json({"ok": False, "error": "تعذّر معالجة الطلب"}, code=500)
        if isinstance(res, dict) and res.get("ok") is False:
            return self._json(res, code=400)
        return self._json(res, code=200)

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
            stop_event = getattr(self.server, "stop_event", None)
            while not (stop_event and stop_event.is_set()):
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
            stop_event = getattr(self.server, "stop_event", None)
            last_ping = time.monotonic()
            while not (stop_event and stop_event.is_set()):
                try:
                    event_data = q.get(timeout=0.5)
                    self.wfile.write(f"data: {event_data}\n\n".encode("utf-8"))
                except queue.Empty:
                    if time.monotonic() - last_ping >= 15.0:
                        self.wfile.write(b": ping\n\n")
                        last_ping = time.monotonic()
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


def _is_loopback_bind(host):
    value = str(host or "").strip().lower()
    try:
        return ipaddress.ip_address(value).is_loopback
    except ValueError:
        return value == "localhost"


def _build_server_tls_context(host, tls_cert=None, tls_key=None):
    has_cert, has_key = bool(tls_cert), bool(tls_key)
    if has_cert != has_key:
        raise ValueError("TLS requires both --tls-cert and --tls-key.")
    if not _is_loopback_bind(host) and not (has_cert and has_key):
        raise ValueError("LAN binding over plaintext HTTP is disabled. Supply --tls-cert and --tls-key.")
    if not has_cert:
        return None
    context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    context.minimum_version = ssl.TLSVersion.TLSv1_2
    context.load_cert_chain(certfile=tls_cert, keyfile=tls_key)
    return context


class _IPv6ThreadingHTTPServer(ThreadingHTTPServer):
    address_family = socket.AF_INET6


def start_server(port=8000, host="127.0.0.1", tls_cert=None, tls_key=None):
    """Start MERSAD's web server; non-loopback binds are TLS-only."""
    tls_context = _build_server_tls_context(host, tls_cert, tls_key)
    ThreadingHTTPServer.daemon_threads = True
    ThreadingHTTPServer.allow_reuse_address = True
    server_cls = _IPv6ThreadingHTTPServer if ":" in str(host) else ThreadingHTTPServer
    srv = server_cls((host, int(port)), H)
    srv.stop_event = threading.Event()
    srv.is_tls = bool(tls_context)
    srv.scheme = "https" if tls_context else "http"
    if tls_context:
        srv.socket = tls_context.wrap_socket(srv.socket, server_side=True)
    threading.Thread(target=srv.serve_forever, daemon=True, name="mersad-http-server").start()
    actual_port = int(srv.server_address[1])
    lan_ip = get_lan_ip()
    srv.local_url = f"{srv.scheme}://127.0.0.1:{actual_port}/"
    srv.lan_url = f"{srv.scheme}://{lan_ip}:{actual_port}/"
    if _is_loopback_bind(host):
        print(f"\nDashboard URL (local only): {srv.local_url}")
    else:
        print(f"\nDashboard URLs (TLS enabled):\n  Local: {srv.local_url}\n  LAN:   {srv.lan_url}")
    return srv
