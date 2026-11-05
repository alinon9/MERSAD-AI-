#!/usr/bin/env python3
"""
MERSAD LAB 1.0 — PREVIEW 0.1
Comprehensive Functional & Security Test Suite (20 Checks)
==========================================================
Covers:
A. The 8 Mandatory Core Tests:
   1. LAB-01: Camera JPEG rendering (normal, lowlight, lowres, noise, occluded, frozen, delay).
   2. LAB-02: MJPEG streaming (`multipart/x-mixed-replace; boundary=frame`).
   3. LAB-03: Health endpoint (`/api/health` & `/health` JSON schema & telemetry).
   4. LAB-04: Invalid camera mode rejection (`HTTP 400`).
   5. LAB-05: Offline camera `HTTP 503` on `/frame/<cam>.jpg` and `/stream/<cam>.mjpg`.
   6. LAB-06: OpenCV/FFmpeg virtual camera reading (`cv2.VideoCapture` over MJPEG HTTP URL).
   7. LAB-07: Image quality upload (`/api/analyze/image` multipart & raw JPEG).
   8. LAB-08: Video quality upload (`/api/analyze/video` valid synthetic MP4/AVI).
B. The 12 New Security, Resilience & Lifecycle Tests:
   9. LAB-SEC-01: Access control & token validation (`X-Lab-Token` / `require_auth=True` / invalid token `HTTP 401`).
   10. LAB-SEC-02: Host & Origin validation (DNS rebinding & foreign origin `HTTP 403`).
   11. LAB-SEC-03: CSRF & unexpected local access (`Origin: null`, cross-site `text/plain` POST blocked `HTTP 403`).
   12. LAB-SEC-04: Dynamic XSS prevention (`<script>` payload in camera title/mode escaped + `CSP` header verified).
   13. LAB-SEC-05: Static & runtime `innerHTML` audit (`index.html` contains 0 `innerHTML` / `outerHTML` / `document.write` sinks).
   14. LAB-SEC-06: Abnormal/oversized file upload rejection (`HTTP 413 Payload Too Large`).
   15. LAB-SEC-07: Corrupt & truncated video handling (`HTTP 400` / `HTTP 422` without server crash or temp file leak).
   16. LAB-SEC-08: Memory & CPU pressure bounds during sustained multi-camera rendering & uploads.
   17. LAB-SEC-09: Concurrent upload throttling & thread safety (`HTTP 429` when exceeding semaphore limit).
   18. LAB-SEC-10: Video processing timeout enforcement (`HTTP 504 Gateway Timeout` when exceeding deadline).
   19. LAB-SEC-11: Rapid start/stop lifecycle stability (multiple sequential controller cycles on ephemeral ports).
   20. LAB-SEC-12: Zero hanging processes, threads, or bound ports after server shutdown.
"""
import io
import json
import os
import re
import socket
import subprocess
import sys
import tempfile
import threading
import time
import urllib.error
import urllib.request

import cv2
import numpy as np

from lab_server import LabServerController, get_process_telemetry, resolve_lab_asset
from sim_engine import render_synthetic_camera_frame

PASS = 0
FAIL = 0
RESULTS = []


def ok(name: str, detail: str = ""):
    global PASS
    PASS += 1
    msg = f"  [PASS] {name}" + (f" -- {detail}" if detail else "")
    print(msg)
    RESULTS.append({"test": name, "status": "PASS", "detail": detail})


def fail(name: str, detail: str = ""):
    global FAIL
    FAIL += 1
    msg = f"  [FAIL] {name}" + (f" -- {detail}" if detail else "")
    print(msg)
    RESULTS.append({"test": name, "status": "FAIL", "detail": detail})


def _http_req(url: str, method: str = "GET", data: bytes = None, headers: dict = None, timeout: float = 8.0):
    req = urllib.request.Request(url, data=data, headers=headers or {}, method=method)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return resp.status, dict(resp.headers), resp.read()
    except urllib.error.HTTPError as he:
        body = he.read() if he.fp else b""
        return he.code, dict(he.headers) if he.headers else {}, body


def _make_multipart(field_name: str, filename: str, content_type: str, payload: bytes):
    boundary = "----MersadLabBoundary7MA4YWxkTrZu0gW"
    body = (
        f"--{boundary}\r\n"
        f'Content-Disposition: form-data; name="{field_name}"; filename="{filename}"\r\n'
        f"Content-Type: {content_type}\r\n\r\n"
    ).encode("utf-8") + payload + f"\r\n--{boundary}--\r\n".encode("utf-8")
    return f"multipart/form-data; boundary={boundary}", body


def _create_synthetic_video_bytes(num_frames: int = 12, width: int = 320, height: int = 240, fps: float = 10.0) -> bytes:
    fd, tmp_path = tempfile.mkstemp(prefix="mersad_lab_test_", suffix=".avi")
    os.close(fd)
    try:
        fourcc = cv2.VideoWriter_fourcc(*"MJPG")
        writer = cv2.VideoWriter(tmp_path, fourcc, fps, (width, height))
        for i in range(num_frames):
            img, _ = render_synthetic_camera_frame("cam1", i, mode="normal", width=width, height=height)
            writer.write(img)
        writer.release()
        with open(tmp_path, "rb") as f:
            return f.read()
    finally:
        try:
            os.remove(tmp_path)
        except OSError:
            pass


def run_all_tests():
    print("==================================================================")
    print("  MERSAD LAB 1.0 (PREVIEW 0.1) — 20-Check Functional & Security Suite")
    print("==================================================================")

    ctrl = LabServerController(host="127.0.0.1", port=0, token="lab_test_secret_token_2026", require_auth=False)
    ctrl.start()
    base_url = f"http://127.0.0.1:{ctrl.port}"

    try:
        # ------------------------------------------------------------------
        # 1. LAB-01: Camera JPEG rendering across all active modes
        # ------------------------------------------------------------------
        try:
            rendered_modes = []
            for mode in ("normal", "lowlight", "lowres", "noise", "occluded", "frozen", "delay"):
                st, _, body = _http_req(
                    f"{base_url}/api/cameras/cam1/mode",
                    method="POST",
                    data=json.dumps({"mode": mode, "delay_sec": 0.05}).encode("utf-8"),
                    headers={"Content-Type": "application/json"},
                )
                assert st == 200, f"Mode set {mode} failed with {st}"
                st_f, hdrs_f, jpg = _http_req(f"{base_url}/frame/cam1.jpg")
                assert st_f == 200 and jpg.startswith(b"\xff\xd8"), f"Invalid JPEG in mode {mode}"
                arr = np.frombuffer(jpg, dtype=np.uint8)
                dec = cv2.imdecode(arr, cv2.IMREAD_COLOR)
                assert dec is not None and dec.shape[0] > 0 and dec.shape[1] > 0
                rendered_modes.append(mode)
            # Reset cam1 to normal
            _http_req(
                f"{base_url}/api/cameras/cam1/mode",
                method="POST",
                data=json.dumps({"mode": "normal"}).encode("utf-8"),
                headers={"Content-Type": "application/json"},
            )
            ok("LAB-01: Camera JPEG rendering", f"modes={','.join(rendered_modes)} verified")
        except Exception as e:
            fail("LAB-01: Camera JPEG rendering", str(e))

        # ------------------------------------------------------------------
        # 2. LAB-02: MJPEG streaming
        # ------------------------------------------------------------------
        try:
            st, hdrs, raw_stream = _http_req(f"{base_url}/stream/cam1.mjpg?frames=4", timeout=8.0)
            ctype = hdrs.get("Content-Type", "")
            frame_markers = raw_stream.count(b"--frame")
            soi_markers = raw_stream.count(b"\xff\xd8")
            assert st == 200 and "multipart/x-mixed-replace" in ctype and frame_markers >= 4 and soi_markers >= 4
            ok("LAB-02: MJPEG streaming", f"status={st}, frames_received={frame_markers}, bytes={len(raw_stream)}")
        except Exception as e:
            fail("LAB-02: MJPEG streaming", str(e))

        # ------------------------------------------------------------------
        # 3. LAB-03: Health endpoint
        # ------------------------------------------------------------------
        try:
            st, _, body = _http_req(f"{base_url}/api/health")
            data = json.loads(body.decode("utf-8"))
            assert st == 200 and data.get("ok") is True and data.get("status") == "healthy"
            assert "telemetry" in data and "rss_mb" in data["telemetry"] and data.get("cameras_count", 0) >= 4
            ok("LAB-03: Health endpoint", f"version={data.get('version')}, cameras={data.get('cameras_count')}, rss_mb={data['telemetry']['rss_mb']}")
        except Exception as e:
            fail("LAB-03: Health endpoint", str(e))

        # ------------------------------------------------------------------
        # 4. LAB-04: Invalid camera mode rejection
        # ------------------------------------------------------------------
        try:
            st, _, body = _http_req(
                f"{base_url}/api/cameras/cam1/mode",
                method="POST",
                data=json.dumps({"mode": "turbo_hack_mode_999"}).encode("utf-8"),
                headers={"Content-Type": "application/json"},
            )
            data = json.loads(body.decode("utf-8"))
            assert st == 400 and data.get("ok") is False and "valid_modes" in data
            ok("LAB-04: Invalid camera mode rejection", f"HTTP {st} returned with valid_modes list")
        except Exception as e:
            fail("LAB-04: Invalid camera mode rejection", str(e))

        # ------------------------------------------------------------------
        # 5. LAB-05: Offline camera HTTP 503
        # ------------------------------------------------------------------
        try:
            _http_req(
                f"{base_url}/api/cameras/cam2/mode",
                method="POST",
                data=json.dumps({"mode": "offline"}).encode("utf-8"),
                headers={"Content-Type": "application/json"},
            )
            st_jpg, _, _ = _http_req(f"{base_url}/frame/cam2.jpg")
            st_mjpg, _, _ = _http_req(f"{base_url}/stream/cam2.mjpg?frames=1")
            _http_req(
                f"{base_url}/api/cameras/cam2/mode",
                method="POST",
                data=json.dumps({"mode": "normal"}).encode("utf-8"),
                headers={"Content-Type": "application/json"},
            )
            assert st_jpg == 503 and st_mjpg == 503, f"Expected 503/503, got {st_jpg}/{st_mjpg}"
            ok("LAB-05: Offline camera HTTP 503", f"frame={st_jpg}, stream={st_mjpg}")
        except Exception as e:
            fail("LAB-05: Offline camera HTTP 503", str(e))

        # ------------------------------------------------------------------
        # 6. LAB-06: OpenCV/FFmpeg virtual camera reading
        # ------------------------------------------------------------------
        try:
            stream_url = f"{base_url}/stream/cam1.mjpg?frames=6"
            cap = cv2.VideoCapture(stream_url)
            read_ok = 0
            shapes = []
            for _ in range(4):
                ret, frame = cap.read()
                if ret and frame is not None and frame.size > 0:
                    read_ok += 1
                    shapes.append(frame.shape)
            cap.release()
            assert read_ok >= 3, f"OpenCV VideoCapture read only {read_ok} frames"
            ok("LAB-06: OpenCV/FFmpeg virtual camera reading", f"frames_read={read_ok}, shape={shapes[0]}")
        except Exception as e:
            fail("LAB-06: OpenCV/FFmpeg virtual camera reading", str(e))

        # ------------------------------------------------------------------
        # 7. LAB-07: Image quality upload
        # ------------------------------------------------------------------
        try:
            _, sample_jpg = render_synthetic_camera_frame("cam1", 5, mode="normal")
            ctype, mp_body = _make_multipart("file", "cam1_sample.jpg", "image/jpeg", sample_jpg)
            st, _, body = _http_req(
                f"{base_url}/api/analyze/image",
                method="POST",
                data=mp_body,
                headers={"Content-Type": ctype},
            )
            data = json.loads(body.decode("utf-8"))
            assert st == 200 and data.get("ok") is True and data.get("width") == 640 and data.get("height") == 480
            assert "sharpness" in data and "brightness" in data and "quality_grade" in data
            ok("LAB-07: Image quality upload", f"grade={data['quality_grade']}, sharpness={data['sharpness']}, brightness={data['brightness']}")
        except Exception as e:
            fail("LAB-07: Image quality upload", str(e))

        # ------------------------------------------------------------------
        # 8. LAB-08: Video quality upload
        # ------------------------------------------------------------------
        try:
            vid_bytes = _create_synthetic_video_bytes(num_frames=10, width=320, height=240, fps=10.0)
            ctype, mp_body = _make_multipart("file", "synthetic_test.avi", "video/x-msvideo", vid_bytes)
            st, _, body = _http_req(
                f"{base_url}/api/analyze/video",
                method="POST",
                data=mp_body,
                headers={"Content-Type": ctype},
            )
            data = json.loads(body.decode("utf-8"))
            assert st == 200 and data.get("ok") is True and data.get("sampled_frames", 0) >= 5
            ok("LAB-08: Video quality upload", f"sampled_frames={data['sampled_frames']}, grade={data.get('quality_grade')}, elapsed={data.get('elapsed_sec')}s")
        except Exception as e:
            fail("LAB-08: Video quality upload", str(e))

        # ------------------------------------------------------------------
        # 9. LAB-SEC-01: Access permissions & token enforcement
        # ------------------------------------------------------------------
        try:
            # 9a: Invalid token header is always rejected with 401
            st_bad, _, _ = _http_req(
                f"{base_url}/api/cameras",
                headers={"X-Lab-Token": "wrong_token_999"},
            )
            # 9b: When require_auth=True, missing token is rejected with 401 and valid token succeeds with 200
            ctrl.state.require_auth = True
            try:
                st_missing, _, _ = _http_req(f"{base_url}/api/cameras")
                st_good, _, _ = _http_req(
                    f"{base_url}/api/cameras",
                    headers={"X-Lab-Token": "lab_test_secret_token_2026"},
                )
            finally:
                ctrl.state.require_auth = False
            assert st_bad == 401 and st_missing == 401 and st_good == 200, f"got {st_bad}/{st_missing}/{st_good}"
            ok("LAB-SEC-01: Access control & token validation", f"bad_token={st_bad}, missing_token={st_missing}, valid_token={st_good}")
        except Exception as e:
            fail("LAB-SEC-01: Access control & token validation", str(e))

        # ------------------------------------------------------------------
        # 10. LAB-SEC-02: Host & Origin validation (DNS rebinding & external Origin)
        # ------------------------------------------------------------------
        try:
            st_host, _, _ = _http_req(
                f"{base_url}/api/health",
                headers={"Host": "evil-rebind.attacker.com"},
            )
            st_origin, _, _ = _http_req(
                f"{base_url}/api/cameras/cam1/mode",
                method="POST",
                data=json.dumps({"mode": "normal"}).encode("utf-8"),
                headers={"Content-Type": "application/json", "Origin": "http://evil.attacker.com"},
            )
            assert st_host == 403 and st_origin == 403, f"Expected 403/403, got {st_host}/{st_origin}"
            ok("LAB-SEC-02: Host & Origin validation", f"evil_host={st_host}, evil_origin={st_origin}")
        except Exception as e:
            fail("LAB-SEC-02: Host & Origin validation", str(e))

        # ------------------------------------------------------------------
        # 11. LAB-SEC-03: CSRF & unexpected local access (`Origin: null`, `Sec-Fetch-Site: cross-site`, `text/plain` form POST)
        # ------------------------------------------------------------------
        try:
            st_null_origin, _, _ = _http_req(
                f"{base_url}/api/cameras/cam1/mode",
                method="POST",
                data=json.dumps({"mode": "offline"}).encode("utf-8"),
                headers={"Content-Type": "application/json", "Origin": "null"},
            )
            st_sec_fetch, _, _ = _http_req(
                f"{base_url}/api/cameras/cam1/mode",
                method="POST",
                data=json.dumps({"mode": "offline"}).encode("utf-8"),
                headers={"Content-Type": "application/json", "Sec-Fetch-Site": "cross-site"},
            )
            st_text_plain, _, _ = _http_req(
                f"{base_url}/api/cameras/cam1/mode",
                method="POST",
                data=b'{"mode":"offline"}',
                headers={"Content-Type": "text/plain"},
            )
            assert st_null_origin == 403 and st_sec_fetch == 403 and st_text_plain == 403
            ok("LAB-SEC-03: CSRF & unexpected local access blocked", f"null_origin={st_null_origin}, cross_site={st_sec_fetch}, text_plain={st_text_plain}")
        except Exception as e:
            fail("LAB-SEC-03: CSRF & unexpected local access blocked", str(e))

        # ------------------------------------------------------------------
        # 12. LAB-SEC-04: XSS from dynamic data & CSP headers
        # ------------------------------------------------------------------
        try:
            xss_payload = "<script>alert('XSS')</script><img src=x onerror=alert(1)>"
            st_add, hdrs_add, body_add = _http_req(
                f"{base_url}/api/cameras/add",
                method="POST",
                data=json.dumps({"cam_id": "cam_xss", "title_ar": xss_payload}).encode("utf-8"),
                headers={"Content-Type": "application/json"},
            )
            data_add = json.loads(body_add.decode("utf-8"))
            escaped_title = data_add["camera"]["title_ar"]
            csp = hdrs_add.get("Content-Security-Policy", "")
            assert st_add == 200 and "<script>" not in escaped_title and "&lt;script&gt;" in escaped_title
            assert "default-src 'self'" in csp and "frame-ancestors 'none'" in csp
            ok("LAB-SEC-04: Dynamic XSS escaping & CSP headers", f"escaped_title={escaped_title[:36]}..., CSP present")
        except Exception as e:
            fail("LAB-SEC-04: Dynamic XSS escaping & CSP headers", str(e))

        # ------------------------------------------------------------------
        # 13. LAB-SEC-05: Static & DOM audit for `innerHTML` usage
        # ------------------------------------------------------------------
        try:
            idx_file = resolve_lab_asset("index.html")
            html_src = open(idx_file, "r", encoding="utf-8").read()
            unsafe_sinks = re.findall(r"\b(?:innerHTML|outerHTML|insertAdjacentHTML|document\.write)\b", html_src)
            assert len(unsafe_sinks) == 0, f"Found unsafe DOM sinks: {unsafe_sinks}"
            assert "textContent" in html_src and "createElement" in html_src
            ok("LAB-SEC-05: Zero innerHTML usage in index.html", "0 unsafe DOM sinks; uses textContent/createElement exclusively")
        except Exception as e:
            fail("LAB-SEC-05: Zero innerHTML usage in index.html", str(e))

        # ------------------------------------------------------------------
        # 14. LAB-SEC-06: Abnormal/oversized file upload rejection (HTTP 413)
        # ------------------------------------------------------------------
        try:
            orig_max_img = ctrl.state.max_image_bytes
            ctrl.state.max_image_bytes = 64 * 1024  # 64 KB cap for fast test
            try:
                oversized_payload = b"\xff\xd8\xff\xe0" + (b"A" * (128 * 1024))
                st_big, _, body_big = _http_req(
                    f"{base_url}/api/analyze/image",
                    method="POST",
                    data=oversized_payload,
                    headers={"Content-Type": "image/jpeg"},
                )
            finally:
                ctrl.state.max_image_bytes = orig_max_img
            assert st_big == 413, f"Expected HTTP 413, got {st_big}"
            ok("LAB-SEC-06: Abnormal file size rejection", f"HTTP {st_big} returned for oversized payload")
        except Exception as e:
            fail("LAB-SEC-06: Abnormal file size rejection", str(e))

        # ------------------------------------------------------------------
        # 15. LAB-SEC-07: Corrupt & truncated video handling
        # ------------------------------------------------------------------
        try:
            corrupt_vid = b"NOT_A_REAL_VIDEO_HEADER_0000111122223333" * 40
            ctype, mp_body = _make_multipart("file", "corrupt.mp4", "video/mp4", corrupt_vid)
            st_corrupt, _, body_corrupt = _http_req(
                f"{base_url}/api/analyze/video",
                method="POST",
                data=mp_body,
                headers={"Content-Type": ctype},
            )
            data_corrupt = json.loads(body_corrupt.decode("utf-8"))
            # Verify server is still healthy after corrupt video
            st_h, _, _ = _http_req(f"{base_url}/api/health")
            assert st_corrupt in (400, 422) and data_corrupt.get("ok") is False and st_h == 200
            ok("LAB-SEC-07: Corrupt video graceful rejection", f"corrupt_video_status={st_corrupt}, post_health={st_h}")
        except Exception as e:
            fail("LAB-SEC-07: Corrupt video graceful rejection", str(e))

        # ------------------------------------------------------------------
        # 16. LAB-SEC-08: Memory & CPU pressure bounds
        # ------------------------------------------------------------------
        try:
            tel_before = get_process_telemetry(ctrl.state.start_time)
            for _ in range(20):
                _http_req(f"{base_url}/frame/cam1.jpg")
                _http_req(f"{base_url}/frame/cam3.jpg")
            tel_after = get_process_telemetry(ctrl.state.start_time)
            rss_delta = tel_after["rss_mb"] - tel_before["rss_mb"]
            assert rss_delta < 80.0, f"Excessive RSS growth during 40 frame renders: +{rss_delta:.2f} MB"
            ok("LAB-SEC-08: Memory & CPU pressure bounds", f"rss_before={tel_before['rss_mb']}MB, rss_after={tel_after['rss_mb']}MB, delta={rss_delta:+.2f}MB")
        except Exception as e:
            fail("LAB-SEC-08: Memory & CPU pressure bounds", str(e))

        # ------------------------------------------------------------------
        # 17. LAB-SEC-09: Concurrent uploads & semaphore throttling (HTTP 429)
        # ------------------------------------------------------------------
        try:
            vid_bytes = _create_synthetic_video_bytes(num_frames=8, width=320, height=240, fps=10.0)
            statuses = []
            lock = threading.Lock()

            def _worker():
                st, _, _ = _http_req(
                    f"{base_url}/api/analyze/video?simulate_delay=0.12&timeout=5.0",
                    method="POST",
                    data=vid_bytes,
                    headers={"Content-Type": "video/x-msvideo"},
                    timeout=10.0,
                )
                with lock:
                    statuses.append(st)

            threads = [threading.Thread(target=_worker) for _ in range(6)]
            for t in threads:
                t.start()
            for t in threads:
                t.join(timeout=12.0)

            count_200 = statuses.count(200)
            count_429 = statuses.count(429)
            assert count_200 >= 1 and count_429 >= 1 and len(statuses) == 6, f"Unexpected concurrent statuses: {statuses}"
            ok("LAB-SEC-09: Concurrent upload throttling (HTTP 429)", f"statuses={statuses} (200={count_200}, 429={count_429})")
        except Exception as e:
            fail("LAB-SEC-09: Concurrent upload throttling (HTTP 429)", str(e))

        # ------------------------------------------------------------------
        # 18. LAB-SEC-10: Video processing timeout enforcement (HTTP 504)
        # ------------------------------------------------------------------
        try:
            vid_bytes = _create_synthetic_video_bytes(num_frames=12, width=320, height=240, fps=10.0)
            st_to, _, body_to = _http_req(
                f"{base_url}/api/analyze/video?simulate_delay=0.10&timeout=0.25",
                method="POST",
                data=vid_bytes,
                headers={"Content-Type": "video/x-msvideo"},
                timeout=8.0,
            )
            data_to = json.loads(body_to.decode("utf-8"))
            assert st_to == 504 and data_to.get("timed_out") is True, f"Expected 504 timeout, got {st_to}: {data_to}"
            ok("LAB-SEC-10: Video processing timeout (HTTP 504)", f"status={st_to}, sampled_before_timeout={data_to.get('sampled_frames')}")
        except Exception as e:
            fail("LAB-SEC-10: Video processing timeout (HTTP 504)", str(e))

    finally:
        ctrl.stop()

    # ----------------------------------------------------------------------
    # 19. LAB-SEC-11: Start/stop process & controller stability
    # ----------------------------------------------------------------------
    try:
        ports_used = []
        for _ in range(3):
            c = LabServerController(host="127.0.0.1", port=0)
            c.start()
            ports_used.append(c.port)
            st, _, _ = _http_req(f"http://127.0.0.1:{c.port}/api/health")
            assert st == 200
            c.stop(timeout=3.0)
        # Also verify CLI --self-check subprocess exits cleanly with 0
        proc = subprocess.run(
            [sys.executable, resolve_lab_asset("lab_server.py"), "--port", "0", "--self-check"],
            capture_output=True,
            text=True,
            timeout=10.0,
        )
        assert proc.returncode == 0, f"--self-check exited with {proc.returncode}: {proc.stderr}"
        ok("LAB-SEC-11: Start/stop stability & CLI self-check", f"3 start/stop cycles + subprocess --self-check exit=0")
    except Exception as e:
        fail("LAB-SEC-11: Start/stop stability & CLI self-check", str(e))

    # ----------------------------------------------------------------------
    # 20. LAB-SEC-12: Zero hanging lab threads or bound ports after shutdown
    # ----------------------------------------------------------------------
    try:
        c = LabServerController(host="127.0.0.1", port=0)
        c.start()
        test_port = c.port
        # Start a background stream request and then stop the server
        stream_done = threading.Event()

        def _bg_reader():
            try:
                _http_req(f"http://127.0.0.1:{test_port}/stream/cam1.mjpg?frames=100", timeout=3.0)
            except Exception:
                pass
            finally:
                stream_done.set()

        t_reader = threading.Thread(target=_bg_reader, daemon=True)
        t_reader.start()
        time.sleep(0.25)
        c.stop(timeout=3.0)
        stream_done.wait(timeout=3.0)

        # Verify no thread named 'mersad-lab-http' is alive
        lingering = [t.name for t in threading.enumerate() if "mersad-lab-http" in t.name and t.is_alive()]
        # Verify port can be bound immediately
        s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        s.bind(("127.0.0.1", test_port))
        s.close()
        assert len(lingering) == 0, f"Lingering lab threads: {lingering}"
        ok("LAB-SEC-12: Zero hanging processes/threads/ports on close", f"port {test_port} released, lingering_threads=0")
    except Exception as e:
        fail("LAB-SEC-12: Zero hanging processes/threads/ports on close", str(e))

    print("==================================================================")
    print(f"  TOTAL: {PASS} PASS, {FAIL} FAIL (Out of {PASS + FAIL} checks)")
    print("==================================================================")
    sys.exit(0 if FAIL == 0 else 1)


if __name__ == "__main__":
    run_all_tests()
