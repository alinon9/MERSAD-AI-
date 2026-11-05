"""Tiny dependency-free web server: live MJPEG video (per-camera support) + Server-Sent Events + registry & path-tracking API.
Supports HttpOnly session cookie (with 302 redirect on first ?k=TOKEN visit to strip token from URL)
while retaining full backward compatibility with ?k=TOKEN query parameters."""
import http.cookies, json, logging, os, queue, secrets, socket, sys, threading, time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, unquote, urlparse

BASE = getattr(sys, "_MEIPASS", os.path.dirname(os.path.abspath(__file__)))
MAX_UPLOAD = 5_000_000
log = logging.getLogger("mersad.server")


class Bus:
    def __init__(self):
        self.frame, self.fid, self.subs, self.alerts, self.failed_dispatches = None, 0, [], [], []
        self.cam_frames = {}                             # cam_id -> {"jpg": bytes, "fid": int, "status": str, "ts": float}
        self.token = secrets.token_urlsafe(12)
        self.post = {}                                   # path -> fn(data: dict, ip) -> dict
        self.verify = lambda: "Audit chain OK (0 records)"
        self.on_list = self.on_template = self.on_import = self.on_insights = self.on_stats = self.on_path = None
        self.on_analytics = self.on_analytics_export = None
        self.on_camera_health = self.on_camera_health_export = None
        self.evidence_dir = "evidence"
        self.archive_dir = "evidence_archive"

    def set_frame(self, jpg, cam=None, status="online"):
        self.frame, self.fid = jpg, self.fid + 1
        if cam:
            prev = self.cam_frames.get(cam, {})
            self.cam_frames[cam] = {
                "jpg": jpg,
                "fid": prev.get("fid", 0) + 1,
                "status": status,
                "ts": time.time()
            }

    def publish(self, ev):
        s = json.dumps(ev, ensure_ascii=False)
        for q in list(self.subs):
            try: q.put_nowait(s)
            except Exception: pass


bus = Bus()


class H(BaseHTTPRequestHandler):
    def log_message(self, *a): pass

    def arg(self, k): return parse_qs(urlparse(self.path).query).get(k, [""])[0]

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
        provided = self.arg("k") or self._cookie_token() or self.headers.get("X-Mersad-Token", "")
        if not provided or not bus.token or not secrets.compare_digest(str(provided), str(bus.token)):
            self.send_error(403, "Forbidden"); return None
        return urlparse(self.path).path

    def _send(self, body, ctype="text/html; charset=utf-8", headers=None, code=200):
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("X-Frame-Options", "DENY")
        self.send_header("Cache-Control", "no-store")
        for k, v in (headers or {}).items():
            self.send_header(k, v)
        self.end_headers()
        self.wfile.write(body)

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
        p = self._auth()
        if p is None: return
        try:
            if p == "/":
                if self.arg("k") and self.arg("noredir") != "1":
                    cookie_val = f"mersad_k={bus.token}; HttpOnly; SameSite=Strict; Path=/"
                    self.send_response(302)
                    self.send_header("Set-Cookie", cookie_val)
                    self.send_header("Location", "/")
                    self.send_header("Cache-Control", "no-store")
                    self.send_header("Content-Length", "0")
                    self.end_headers()
                    return
                with open(os.path.join(BASE, "dashboard.html"), "rb") as f:
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
            elif p == "/api/insights": self._json(bus.on_insights())
            elif p == "/api/path" and bus.on_path: self._json(bus.on_path(self.arg("plate")))
            elif p == "/api/list" and self.arg("kind") in ("vehicles", "persons"):
                self._json(bus.on_list(self.arg("kind"), self.arg("q")[:80]))
            elif p == "/api/template" and self.arg("kind") in ("vehicles", "persons"):
                body, name, mime = bus.on_template(self.arg("kind"))
                self._send(body, mime, {"Content-Disposition": f'attachment; filename="{name}"'})
            elif p.startswith("/evidence/"):
                self._serve_evidence(p)
            else:
                self.send_error(404)
        except FileNotFoundError:
            self.send_error(404)
        except (BrokenPipeError, ConnectionResetError, ConnectionAbortedError):
            pass
        except Exception as e:
            log.error("GET %s failed: %s", p, e)
            self._json({"ok": False, "error": "حدث خطأ داخلي في الخادم"}, code=500)

    def do_POST(self):
        p = self._auth()
        if p is None: return
        try:
            n = int(self.headers.get("Content-Length", 0))
        except ValueError:
            return self.send_error(400)
        if n < 0 or n > MAX_UPLOAD:
            return self.send_error(413)
        raw, ip = self.rfile.read(n), self.client_address[0]
        try:
            if p == "/api/import" and self.arg("kind") in ("vehicles", "persons"):
                res = bus.on_import(self.arg("kind"), unquote(self.headers.get("X-Filename", "")), raw, ip)
            elif p in bus.post:
                payload = json.loads(raw.decode("utf-8") if raw else "{}")
                if not isinstance(payload, dict):
                    res = {"ok": False, "error": "بيانات الطلب غير صالحة"}
                else:
                    res = bus.post[p](payload, ip)
            else:
                return self.send_error(404)
        except json.JSONDecodeError:
            res = {"ok": False, "error": "صيغة JSON غير صالحة"}
        except Exception as e:
            log.error("POST %s failed: %s", p, e)
            res = {"ok": False, "error": "تعذّر معالجة الطلب"}
        self._json(res)

    def stream(self, cam=""):
        self.send_response(200)
        self.send_header("Content-Type", "multipart/x-mixed-replace; boundary=f")
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        last = -1
        while True:
            if cam and cam in bus.cam_frames:
                cf = bus.cam_frames[cam]
                cur_fid, b = cf["fid"], cf["jpg"]
            else:
                cur_fid, b = bus.fid, bus.frame
            if b is not None and cur_fid != last:
                last = cur_fid
                self.wfile.write(b"--f\r\nContent-Type: image/jpeg\r\nContent-Length: %d\r\n\r\n" % len(b) + b + b"\r\n")
            time.sleep(0.04)

    def events(self):
        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream; charset=utf-8")
        self.send_header("Cache-Control", "no-cache")
        self.end_headers()
        q = queue.Queue(maxsize=200)
        bus.subs.append(q)
        try:
            init = json.dumps({"type": "init", "alerts": bus.alerts, "failed_dispatches": bus.failed_dispatches}, ensure_ascii=False)
            self.wfile.write(f"data: {init}\n\n".encode("utf-8"))
            while True:
                try:
                    self.wfile.write(f"data: {q.get(timeout=15)}\n\n".encode("utf-8"))
                except queue.Empty:
                    self.wfile.write(b": ping\n\n")
        finally:
            if q in bus.subs:
                bus.subs.remove(q)


def get_lan_ip():
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("10.255.255.255", 1))
        ip = s.getsockname()[0]
        s.close()
        return ip
    except Exception:
        try:
            return socket.gethostbyname(socket.gethostname())
        except Exception:
            return "127.0.0.1"


def start_server(port=8000, host="127.0.0.1"):
    """Start HTTP server. Binds to 127.0.0.1 by default for security unless host='0.0.0.0' is explicitly passed."""
    ThreadingHTTPServer.daemon_threads = True
    ThreadingHTTPServer.allow_reuse_address = True
    srv = ThreadingHTTPServer((host, port), H)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    local_url = f"http://127.0.0.1:{port}/?k={bus.token}"
    if host == "0.0.0.0":
        lan_ip = get_lan_ip()
        lan_url = f"http://{lan_ip}:{port}/?k={bus.token}"
        print(f"\nDashboard URLs:\n  Local (هذا الجهاز):      {local_url}\n  LAN / Phone (الجوالات): {lan_url}")
        print("  ⚠️ تنبيه أمني: الرمز السري يمر نصاً عبر HTTP على الشبكة المحلية. استخدم شبكة واي فاي موثوقة فقط.\n")
    else:
        print(f"\nDashboard URL (Local only — 127.0.0.1):\n  {local_url}\n  (لتفعيل الوصول من الجوالات على نفس الشبكة استخدم RUN_LAN.bat أو --host 0.0.0.0)\n")
    return srv
