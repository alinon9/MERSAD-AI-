#!/usr/bin/env python3
"""
MERSAD LAB 1.0 — PREVIEW 0.1 | Synthetic Camera Simulation & Media Quality Engine
محرك محاكاة الكاميرات الافتراضية وتحليل جودة الصور والفيديو (بيانات اصطناعية 100%)
"""
import concurrent.futures
import os
import tempfile
import threading
import time
import cv2
import numpy as np

VALID_CAMERA_MODES = frozenset({
    "normal",
    "lowlight",
    "lowres",
    "noise",
    "occluded",
    "frozen",
    "delay",
    "offline",
})

# Synthetic Yemeni plate samples (100% synthetic for testing & preview)
SYNTHETIC_PLATES = (
    ("عدن", "12345", "ADEN 12345"),
    ("صنعاء", "48210", "SANAA 48210"),
    ("تعز", "73901", "TAIZ 73901"),
    ("حضرموت", "55120", "HADR 55120"),
)


class VirtualCamera:
    """Thread-safe virtual camera supporting 8 simulation modes and synthetic vehicle/plate rendering."""

    def __init__(self, cam_id: str, title_ar: str, plate_idx: int = 0, width: int = 640, height: int = 480, fps: float = 15.0):
        self.cam_id = cam_id
        self.title_ar = title_ar
        self.plate_gov, self.plate_digits, self.plate_ascii = SYNTHETIC_PLATES[plate_idx % len(SYNTHETIC_PLATES)]
        self.width = int(width)
        self.height = int(height)
        self.target_fps = float(fps)
        self.mode = "normal"
        self.delay_sec = 0.35
        self.frame_seq = 0
        self.last_frame_ts = time.time()
        self._frozen_jpeg = None
        self._frozen_bgr = None
        self._lock = threading.RLock()

    def set_mode(self, mode: str, delay_sec: float = None) -> bool:
        m = str(mode or "").strip().lower()
        if m not in VALID_CAMERA_MODES:
            return False
        with self._lock:
            self.mode = m
            if delay_sec is not None:
                self.delay_sec = max(0.05, min(5.0, float(delay_sec)))
            if m != "frozen":
                self._frozen_jpeg = None
                self._frozen_bgr = None
        return True

    def _draw_base_scene(self, seq: int) -> np.ndarray:
        h, w = self.height, self.width
        img = np.full((h, w, 3), (48, 52, 56), dtype=np.uint8)
        # Road surface
        cv2.rectangle(img, (0, int(h * 0.25)), (w, h), (62, 66, 70), -1)
        # Lane markings
        cv2.line(img, (int(w * 0.1), h), (int(w * 0.35), int(h * 0.28)), (200, 200, 200), 2)
        cv2.line(img, (int(w * 0.9), h), (int(w * 0.65), int(h * 0.28)), (200, 200, 200), 2)

        # Synthetic vehicle body (slight horizontal oscillation so frames are live unless frozen)
        dx = int((seq % 12) - 6) * 2
        vx1, vy1 = max(40, int(w * 0.22) + dx), int(h * 0.32)
        vx2, vy2 = min(w - 40, int(w * 0.78) + dx), int(h * 0.86)
        cv2.rectangle(img, (vx1, vy1), (vx2, vy2), (140, 95, 55), -1)
        cv2.rectangle(img, (vx1, vy1), (vx2, vy2), (210, 180, 140), 2)
        # Windshield & headlights
        cv2.rectangle(img, (vx1 + 35, vy1 + 18), (vx2 - 35, vy1 + 85), (85, 110, 130), -1)
        cv2.circle(img, (vx1 + 40, vy2 - 55), 16, (215, 245, 255), -1)
        cv2.circle(img, (vx2 - 40, vy2 - 55), 16, (215, 245, 255), -1)

        # High-contrast rectangular license plate in lower vehicle region (compatible with find_plates Canny + real Tesseract/EasyOCR)
        px1 = int((vx1 + vx2) * 0.5) - 105
        py1 = vy2 - 72
        px2 = px1 + 210
        py2 = py1 + 52
        cv2.rectangle(img, (px1, py1), (px2, py2), (252, 252, 252), -1)
        cv2.rectangle(img, (px1, py1), (px2, py2), (10, 10, 10), 3)
        plate_txt = f"{self.plate_ascii.split()[0][:4]} {self.plate_digits}"
        cv2.putText(img, plate_txt, (px1 + 14, py2 - 15), cv2.FONT_HERSHEY_SIMPLEX, 0.85, (10, 10, 10), 2, cv2.LINE_AA)

        # Telemetry banner at top
        cv2.rectangle(img, (0, 0), (w, 30), (22, 26, 32), -1)
        ts_str = time.strftime("%H:%M:%S", time.localtime())
        cv2.putText(
            img,
            f"MERSAD LAB 1.0 | {self.cam_id.upper()} | MODE={self.mode.upper()} | SEQ={seq} | {ts_str}",
            (10, 20),
            cv2.FONT_HERSHEY_SIMPLEX,
            0.46,
            (0, 230, 180),
            1,
            cv2.LINE_AA,
        )
        return img

    def render_bgr(self):
        """Render next BGR frame according to current camera mode. Returns (status_code, bgr_frame_or_None)."""
        with self._lock:
            mode = self.mode
            delay_s = self.delay_sec
            if mode == "offline":
                return 503, None
            if mode == "frozen" and self._frozen_bgr is not None:
                self.frame_seq += 1
                self.last_frame_ts = time.time()
                return 200, self._frozen_bgr.copy()
            self.frame_seq += 1
            seq = self.frame_seq
            self.last_frame_ts = time.time()

        if mode == "delay":
            time.sleep(delay_s)

        frame = self._draw_base_scene(seq)

        if mode == "lowlight":
            frame = (frame.astype(np.float32) * 0.22).clip(0, 255).astype(np.uint8)
        elif mode == "lowres":
            small = cv2.resize(frame, (160, 120), interpolation=cv2.INTER_AREA)
            frame = small
        elif mode == "noise":
            rng = np.random.default_rng(seq)
            noise = rng.normal(0, 38, frame.shape).astype(np.int16)
            frame = np.clip(frame.astype(np.int16) + noise, 0, 255).astype(np.uint8)
        elif mode == "occluded":
            frame[:] = (4, 4, 4)
            cv2.putText(frame, "OCCLUDED", (20, 40), cv2.FONT_HERSHEY_SIMPLEX, 0.7, (18, 18, 18), 1)
        elif mode == "frozen":
            with self._lock:
                self._frozen_bgr = frame.copy()

        return 200, frame

    def render_jpeg(self, quality: int = 85):
        """Render next frame encoded as JPEG bytes. Returns (status_code, jpeg_bytes_or_None)."""
        with self._lock:
            if self.mode == "offline":
                return 503, None
            if self.mode == "frozen" and self._frozen_jpeg is not None:
                self.frame_seq += 1
                self.last_frame_ts = time.time()
                return 200, self._frozen_jpeg

        code, bgr = self.render_bgr()
        if code != 200 or bgr is None:
            return code, None
        ok, enc = cv2.imencode(".jpg", bgr, [int(cv2.IMWRITE_JPEG_QUALITY), int(quality)])
        if not ok:
            return 500, None
        jpg_bytes = enc.tobytes()
        with self._lock:
            if self.mode == "frozen" and self._frozen_jpeg is None:
                self._frozen_jpeg = jpg_bytes
        return 200, jpg_bytes

    def info(self) -> dict:
        with self._lock:
            return {
                "cam_id": self.cam_id,
                "title_ar": self.title_ar,
                "mode": self.mode,
                "synthetic_plate": f"{self.plate_gov}-{self.plate_digits}",
                "width": 160 if self.mode == "lowres" else self.width,
                "height": 120 if self.mode == "lowres" else self.height,
                "fps": 0.0 if self.mode == "offline" else (round(1.0 / max(0.1, self.delay_sec), 1) if self.mode == "delay" else self.target_fps),
                "frame_seq": self.frame_seq,
                "last_frame_ts": self.last_frame_ts,
                "frame_url": f"/frame/{self.cam_id}.jpg",
                "stream_url": f"/stream/{self.cam_id}.mjpg",
            }


def analyze_image_bytes(raw_bytes: bytes) -> dict:
    """Decode and compute quality metrics for an uploaded image buffer."""
    if not raw_bytes:
        return {"ok": False, "status_code": 400, "error": "ملف الصورة فارغ"}
    arr = np.frombuffer(raw_bytes, dtype=np.uint8)
    img = cv2.imdecode(arr, cv2.IMREAD_COLOR)
    if img is None or getattr(img, "size", 0) == 0:
        return {"ok": False, "status_code": 400, "error": "ملف الصورة تالف أو بصيغة غير مدعومة"}
    h, w = img.shape[:2]
    if h < 8 or w < 8 or h > 8192 or w > 8192:
        return {"ok": False, "status_code": 400, "error": f"أبعاد الصورة غير صالحة ({w}x{h})"}
    gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
    brightness = round(float(np.mean(gray)), 2)
    contrast = round(float(np.std(gray)), 2)
    sharpness = round(float(cv2.Laplacian(gray, cv2.CV_64F).var()), 2)
    # Estimate high-frequency sensor noise via median blur residual
    blurred = cv2.medianBlur(gray, 3)
    noise_est = round(float(np.mean(np.abs(gray.astype(np.float32) - blurred.astype(np.float32)))), 2)

    issues = []
    if brightness < 30.0:
        issues.append("إضاءة منخفضة جداً (Low Light)")
    elif brightness > 235.0:
        issues.append("تعريض ضوئي زائد (Overexposed)")
    if contrast < 18.0:
        issues.append("تباين ضعيف (Low Contrast)")
    if sharpness < 35.0:
        issues.append("ضبابية أو دقة منخفضة (Blurry / Low Sharpness)")
    if w < 320 or h < 240:
        issues.append("دقة أبعاد منخفضة (Low Resolution)")

    grade = "ممتازة (Excellent)" if not issues else ("متوسطة (Fair)" if len(issues) == 1 else "ضعيفة (Poor)")
    return {
        "ok": True,
        "status_code": 200,
        "width": int(w),
        "height": int(h),
        "resolution": f"{w}x{h}",
        "brightness": brightness,
        "contrast": contrast,
        "sharpness": sharpness,
        "noise_estimate": noise_est,
        "quality_grade": grade,
        "issues": issues,
    }


def _decode_video_worker(tmp_path: str, max_sampled_frames: int, deadline_monotonic: float, artificial_delay_per_frame: float = 0.0) -> dict:
    cap = cv2.VideoCapture(tmp_path)
    if not cap or not cap.isOpened():
        if cap:
            cap.release()
        return {"ok": False, "status_code": 400, "error": "ملف الفيديو تالف أو لا يمكن فتحه"}
    try:
        fps = float(cap.get(cv2.CAP_PROP_FPS) or 0.0)
        total_prop = int(cap.get(cv2.CAP_PROP_FRAME_COUNT) or 0)
        w = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH) or 0)
        h = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT) or 0)

        b_vals, c_vals, s_vals = [], [], []
        frames_read = 0
        while frames_read < max_sampled_frames:
            if artificial_delay_per_frame > 0:
                time.sleep(min(0.25, float(artificial_delay_per_frame)))
            if time.monotonic() > deadline_monotonic:
                return {"ok": False, "status_code": 504, "timed_out": True, "sampled_frames": frames_read, "error": "انتهت مهلة معالجة الفيديو (Video Processing Timeout)"}
            ok, frame = cap.read()
            if not ok or frame is None or getattr(frame, "size", 0) == 0:
                break
            frames_read += 1
            if w <= 0 or h <= 0:
                h, w = frame.shape[:2]
            gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY) if frame.ndim == 3 else frame
            b_vals.append(float(np.mean(gray)))
            c_vals.append(float(np.std(gray)))
            s_vals.append(float(cv2.Laplacian(gray, cv2.CV_64F).var()))

        if frames_read == 0:
            return {"ok": False, "status_code": 422, "error": "ملف الفيديو لا يحتوي على أي إطارات صالحة للقراءة"}

        eff_fps = round(fps if 0.5 <= fps <= 240.0 else 15.0, 2)
        eff_total = max(frames_read, total_prop if total_prop > 0 else frames_read)
        duration_sec = round(eff_total / max(1.0, eff_fps), 2)
        brightness = round(float(np.mean(b_vals)), 2)
        contrast = round(float(np.mean(c_vals)), 2)
        sharpness = round(float(np.mean(s_vals)), 2)

        grade = "ممتازة (Excellent)" if (brightness >= 30.0 and sharpness >= 25.0) else "متوسطة (Fair)"
        return {
            "ok": True,
            "status_code": 200,
            "width": int(w),
            "height": int(h),
            "resolution": f"{w}x{h}",
            "fps": eff_fps,
            "frames_sampled": frames_read,
            "sampled_frames": frames_read,
            "frame_count": eff_total,
            "duration_sec": duration_sec,
            "brightness": brightness,
            "contrast": contrast,
            "sharpness": sharpness,
            "quality_grade": grade,
        }
    finally:
        cap.release()


def analyze_video_bytes(raw_bytes: bytes, timeout_sec: float = 8.0, max_sampled_frames: int = 60, artificial_delay_per_frame: float = 0.0) -> dict:
    """Safely write video bytes to an isolated temp file, analyze frames with a strict timeout, and guarantee temp cleanup."""
    if not raw_bytes or len(raw_bytes) < 32:
        return {"ok": False, "status_code": 400, "error": "ملف الفيديو فارغ أو صغير جداً"}
    fd, tmp_path = tempfile.mkstemp(prefix="mersad_lab_vid_", suffix=".avi")
    try:
        with os.fdopen(fd, "wb") as f:
            f.write(raw_bytes)
        deadline = time.monotonic() + float(timeout_sec)
        if artificial_delay_per_frame > 0:
            # Used for deterministic timeout testing
            start_t = time.monotonic()
            while time.monotonic() - start_t < artificial_delay_per_frame:
                if time.monotonic() > deadline:
                    return {"ok": False, "status_code": 504, "timed_out": True, "sampled_frames": 0, "error": "انتهت مهلة معالجة الفيديو (Video Processing Timeout)"}
                time.sleep(0.02)
        t0 = time.monotonic()
        with concurrent.futures.ThreadPoolExecutor(max_workers=1) as ex:
            fut = ex.submit(_decode_video_worker, tmp_path, max_sampled_frames, deadline, artificial_delay_per_frame)
            try:
                res = fut.result(timeout=max(0.1, float(timeout_sec) + 0.5))
                if isinstance(res, dict):
                    res.setdefault("elapsed_sec", round(time.monotonic() - t0, 3))
                return res
            except concurrent.futures.TimeoutError:
                return {"ok": False, "status_code": 504, "timed_out": True, "sampled_frames": 0, "error": "انتهت مهلة معالجة الفيديو (Video Processing Timeout)"}
    finally:
        if os.path.exists(tmp_path):
            try:
                os.remove(tmp_path)
            except OSError:
                pass


def render_synthetic_camera_frame(cam_id: str = "cam1", seq: int = 1, mode: str = "normal", width: int = 640, height: int = 480):
    cam = VirtualCamera(cam_id, f"Camera {cam_id}", plate_idx=0, width=width, height=height)
    cam.frame_seq = max(0, int(seq) - 1)
    cam.set_mode(mode, delay_sec=0.05)
    code, bgr = cam.render_bgr()
    if code != 200 or bgr is None:
        return None, None
    ok, enc = cv2.imencode(".jpg", bgr, [int(cv2.IMWRITE_JPEG_QUALITY), 85])
    return bgr, (enc.tobytes() if ok else b"")
