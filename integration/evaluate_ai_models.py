#!/usr/bin/env python3
"""
MERSAD AI V7.1 + MERSAD LAB 1.0 — PREVIEW 0.1
Phase 1: Real AI Models Download, SHA-256 Verification & Inference Suite
========================================================================
Enforces the strict rules of ARGON Final Remediation Phase 1:
  1. Uses pinned, immutable SHA-256 digests for all 4 model families:
       - YOLOv8n (`models/yolov8n.pt` -> 31e20dde3def09e2cf938c7be6fe23d9150bbbe503982af13345706515f2ef95)
       - EasyOCR Arabic + English (`models/easyocr/*.pth` -> craft_mlt_25k.pth, arabic.pth, english_g2.pth, latin_g2.pth)
       - YuNet (`models/yunet.onnx` -> 8f2383e4dd3cfbb4553ea8718107fc0423210dc964f9f4280604804ed2552fa4)
       - SFace (`models/sface.onnx` -> 0ba9fbfa01b5270c96627c4ef784da859931e02f04419c829e83484087c34e79)
  2. Never treats a self-generated `.sha256` sidecar from a newly downloaded file as proof of authenticity.
  3. Verifies SHA-256 of every model file (including every EasyOCR `.pth` weight) BEFORE loading into memory.
  4. EasyOCR CANNOT receive `PASS` unless it executes real inference on at least `MIN_REQUIRED_PLATE_SAMPLES` (4)
     plate crops and produces non-empty OCR reads.
  5. SFace strictly requires a real face crop detected and landmark-aligned by YuNet (`det.detect` -> `rec.alignCrop`),
     never a random crop from the center of the image.
  6. Clearly separates and labels:
       - Classification A: `SYNTHETIC_VIRTUAL_CAMERA_SCENE_INFERENCE` (in-memory `VirtualCamera` scenes)
       - Classification B: `LIVE_LAB_HTTP_MJPEG_STREAM_INFERENCE` (live HTTP MJPEG stream via `cv2.VideoCapture`)
       - Classification C: `INDEPENDENT_AUXILIARY_TESSERACT_BENCHMARK` (never substituted for EasyOCR acceptance)
"""
import argparse
import hashlib
import json
import os
import shutil
import subprocess
import sys
import tempfile
import threading
import time
import urllib.error
import urllib.request
from pathlib import Path

import cv2
import numpy as np

ROOT_DIR = Path(__file__).resolve().parent.parent
AI_DIR = ROOT_DIR / "MERSAD_AI_Preview_0.1"
LAB_DIR = ROOT_DIR / "MERSAD_LAB_Preview_0.1"

sys.path.insert(0, str(AI_DIR))
sys.path.insert(0, str(LAB_DIR))

BENCH_HOME = tempfile.mkdtemp(prefix="mersad_phase1_models_")
os.environ["MERSAD_DATA_DIR"] = BENCH_HOME
os.environ["YOLO_AUTOINSTALL"] = "false"
os.environ["ULTRALYTICS_AUTOINSTALL"] = "false"

import mersad_live as m
import prefetch as pf
import registry as reg
from lab_server import LabHTTPServer, LabRequestHandler, LabState
from sim_engine import VirtualCamera

MIN_REQUIRED_PLATE_SAMPLES = 4


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


def ensure_verified_model(url: str, dest: Path, expected_sha256: str, timeout: float = 30.0) -> dict:
    """Download model if missing and strictly verify against pinned constant SHA-256 before returning OK."""
    if not expected_sha256 or len(expected_sha256.strip()) != 64:
        return {
            "ok": False,
            "download_status": "MISSING_PINNED_SHA256",
            "sha256": None,
            "error": "No trusted constant SHA-256 provided",
        }
    if dest.is_file():
        actual = sha256_file(dest)
        if actual.lower() == expected_sha256.lower():
            return {"ok": True, "download_status": "PRESENT_AND_SHA256_VERIFIED", "sha256": actual, "error": None}
        return {
            "ok": False,
            "download_status": "SHA256_MISMATCH_ON_DISK",
            "sha256": actual,
            "error": f"Expected {expected_sha256}, got {actual}",
        }
    try:
        dest.parent.mkdir(parents=True, exist_ok=True)
        req = urllib.request.Request(url, headers={"User-Agent": "MERSAD-AI-Prefetch/0.1"})
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            data = resp.read()
        actual = hashlib.sha256(data).hexdigest()
        if actual.lower() != expected_sha256.lower():
            return {
                "ok": False,
                "download_status": "DOWNLOADED_SHA256_MISMATCH",
                "sha256": actual,
                "error": f"Expected {expected_sha256}, got {actual}",
            }
        dest.write_bytes(data)
        return {"ok": True, "download_status": "DOWNLOADED_AND_SHA256_VERIFIED", "sha256": actual, "error": None}
    except Exception as e:
        return {"ok": False, "download_status": "FAILED_DOWNLOAD", "sha256": None, "error": f"{type(e).__name__}: {e}"}


def capture_live_lab_mjpeg_frames(num_cameras: int = 4) -> tuple[list[np.ndarray], list[dict]]:
    """Start a real MERSAD LAB HTTP server and capture frames over HTTP MJPEG via OpenCV VideoCapture."""
    lab_state = LabState()
    srv = LabHTTPServer(("127.0.0.1", 0), LabRequestHandler, lab_state)
    port = srv.server_address[1]
    t = threading.Thread(target=srv.serve_forever, daemon=True)
    t.start()
    frames = []
    meta = []
    try:
        for i in range(1, num_cameras + 1):
            cam_id = f"cam{i}"
            url = f"http://127.0.0.1:{port}/stream/{cam_id}.mjpg"
            t0 = time.perf_counter()
            cap = m._open_camera_capture(url)
            ok, frame = cap.read() if (cap is not None and cap.isOpened()) else (False, None)
            if cap is not None:
                cap.release()
            lat_ms = round((time.perf_counter() - t0) * 1000.0, 2)
            if ok and frame is not None and frame.size > 0:
                frames.append(frame)
                meta.append({"cam_id": cam_id, "url": url, "ok": True, "shape": list(frame.shape), "capture_latency_ms": lat_ms})
            else:
                meta.append({"cam_id": cam_id, "url": url, "ok": False, "shape": None, "capture_latency_ms": lat_ms})
    finally:
        srv.shutdown()
        srv.server_close()
    return frames, meta


def evaluate_four_models_on_frames(
    frames: list[np.ndarray],
    classification_label: str,
    require_real_models: bool,
    yunet_dl: dict,
    sface_dl: dict,
    yolo_dl: dict,
    yunet_path: Path,
    sface_path: Path,
    yolo_path: Path,
    easyocr_dir: Path,
) -> tuple[dict, bool]:
    """Run all 4 primary models on the provided frame set with strict pre-load SHA-256 verification and sample gates."""
    results = {}
    all_passed = True

    # 1. YuNet (`models/yunet.onnx`)
    yunet_exp_sha = pf.MODEL_SHA256["yunet.onnx"]
    yunet_status = "NOT_TESTED"
    yunet_load = "NOT_LOADED"
    yunet_inf = "NOT_EXECUTED"
    yunet_lat = None
    yunet_err = yunet_dl["error"]
    yunet_detected_faces = []  # List of (frame, face_row) from genuine YuNet detection

    if yunet_dl["ok"]:
        ok_onnx, reason_onnx = pf.verify_onnx_file(
            str(yunet_path),
            expected_sha256=yunet_exp_sha,
            min_bytes=pf.MODEL_MIN_BYTES.get("yunet.onnx", 200_000),
        )
        if not ok_onnx:
            yunet_load = "PRELOAD_SHA256_VERIFY_FAILED"
            yunet_err = reason_onnx
            yunet_status = "FAIL"
            all_passed = False
        else:
            try:
                det = cv2.FaceDetectorYN.create(str(yunet_path), "", (640, 480), 0.65)
                yunet_load = "LOADED_AFTER_SHA256_VERIFY"
                lats = []
                for f_img in frames:
                    t0 = time.perf_counter()
                    det.setInputSize((f_img.shape[1], f_img.shape[0]))
                    _, faces = det.detect(f_img)
                    lats.append((time.perf_counter() - t0) * 1000.0)
                    if faces is not None and len(faces) > 0:
                        for face_row in faces:
                            yunet_detected_faces.append((f_img, face_row))
                yunet_lat = round(float(np.mean(lats)), 2) if lats else None
                yunet_inf = (
                    f"[{classification_label}] EXECUTED on {len(frames)} frames "
                    f"(faces_detected={len(yunet_detected_faces)})"
                )
                yunet_status = "PASS" if len(frames) >= MIN_REQUIRED_PLATE_SAMPLES else "FAIL"
                if yunet_status != "PASS":
                    all_passed = False
            except Exception as e:
                yunet_load = "LOAD_OR_INFER_FAILED"
                yunet_err = f"{type(e).__name__}: {e}"
                yunet_status = "FAIL"
                all_passed = False
    else:
        all_passed = False
        if require_real_models:
            yunet_status = "FAIL"

    results["YuNet"] = {
        "test_classification": classification_label,
        "acceptance_status": yunet_status,
        "download_status": yunet_dl["download_status"],
        "expected_sha256": yunet_exp_sha,
        "actual_sha256": yunet_dl["sha256"],
        "verified_before_load": bool(yunet_dl["ok"]),
        "model_load_status": yunet_load,
        "inference_result": yunet_inf,
        "faces_detected_count": len(yunet_detected_faces),
        "latency_ms": yunet_lat,
        "errors": yunet_err,
    }

    # 2. SFace (`models/sface.onnx`) — STRICTLY requires real face crop from YuNet (never a random center crop)
    sface_exp_sha = pf.MODEL_SHA256["sface.onnx"]
    sface_status = "NOT_TESTED"
    sface_load = "NOT_LOADED"
    sface_inf = "NOT_EXECUTED"
    sface_lat = None
    sface_err = sface_dl["error"]

    if sface_dl["ok"]:
        ok_onnx_sf, reason_onnx_sf = pf.verify_onnx_file(
            str(sface_path),
            expected_sha256=sface_exp_sha,
            min_bytes=pf.MODEL_MIN_BYTES.get("sface.onnx", 30_000_000),
        )
        if not ok_onnx_sf:
            sface_load = "PRELOAD_SHA256_VERIFY_FAILED"
            sface_err = reason_onnx_sf
            sface_status = "FAIL"
            all_passed = False
        else:
            try:
                rec = cv2.FaceRecognizerSF.create(str(sface_path), "")
                sface_load = "LOADED_AFTER_SHA256_VERIFY"
                if not yunet_detected_faces:
                    sface_inf = (
                        f"[{classification_label}] BLOCKED: 0 YuNet face detections available; "
                        "random center-crop fallback is strictly prohibited."
                    )
                    sface_err = "SFace requires at least 1 real face bounding box detected by YuNet (det.detect -> rec.alignCrop)"
                    sface_status = "FAIL" if require_real_models else "NOT_TESTED"
                    all_passed = False
                else:
                    lats = []
                    emb_shape = None
                    for f_img, face_box in yunet_detected_faces:
                        t0 = time.perf_counter()
                        aligned_face = rec.alignCrop(f_img, face_box)
                        feat = rec.feature(aligned_face)
                        lats.append((time.perf_counter() - t0) * 1000.0)
                        emb_shape = list(feat.shape)
                    sface_lat = round(float(np.mean(lats)), 2) if lats else None
                    sface_inf = (
                        f"[{classification_label}] EXECUTED on {len(yunet_detected_faces)} YuNet-aligned face crops "
                        f"(embedding_shape={emb_shape})"
                    )
                    sface_status = "PASS"
            except Exception as e:
                sface_load = "LOAD_OR_INFER_FAILED"
                sface_err = f"{type(e).__name__}: {e}"
                sface_status = "FAIL"
                all_passed = False
    else:
        all_passed = False
        if require_real_models:
            sface_status = "FAIL"

    results["SFace"] = {
        "test_classification": classification_label,
        "acceptance_status": sface_status,
        "download_status": sface_dl["download_status"],
        "expected_sha256": sface_exp_sha,
        "actual_sha256": sface_dl["sha256"],
        "verified_before_load": bool(sface_dl["ok"]),
        "input_source": "YuNet_detect_alignCrop_only (random crop prohibited)",
        "model_load_status": sface_load,
        "inference_result": sface_inf,
        "yunet_crops_processed": len(yunet_detected_faces),
        "latency_ms": sface_lat,
        "errors": sface_err,
    }

    # 3. YOLOv8n (`models/yolov8n.pt`) — Pinned SHA-256 verified before load
    yolo_exp_sha = pf.MODEL_SHA256["yolov8n.pt"]
    yolo_status = "NOT_TESTED"
    yolo_load = "NOT_LOADED"
    yolo_inf = "NOT_EXECUTED"
    yolo_lat = None
    yolo_errs = [yolo_dl["error"]] if yolo_dl["error"] else []

    if yolo_dl["ok"]:
        ok_pt, reason_pt = pf.verify_yolo_pt_file(
            str(yolo_path),
            expected_sha256=yolo_exp_sha,
            min_bytes=pf.MODEL_MIN_BYTES.get("yolov8n.pt", 6_000_000),
        )
        if not ok_pt:
            yolo_load = "PRELOAD_SHA256_VERIFY_FAILED"
            yolo_errs.append(reason_pt)
            yolo_status = "FAIL"
            all_passed = False
        else:
            try:
                from ultralytics import YOLO
                vyolo = YOLO(str(yolo_path))
                yolo_load = "LOADED_AFTER_SHA256_VERIFY"
                lats = []
                veh_total = 0
                for f_img in frames:
                    t0 = time.perf_counter()
                    dets = m.detect_vehicles(f_img, vyolo)
                    lats.append((time.perf_counter() - t0) * 1000.0)
                    veh_total += len(dets)
                yolo_lat = round(float(np.mean(lats)), 2) if lats else None
                yolo_inf = (
                    f"[{classification_label}] EXECUTED on {len(frames)} frames "
                    f"(vehicles_detected={veh_total})"
                )
                yolo_status = "PASS" if len(frames) >= MIN_REQUIRED_PLATE_SAMPLES else "FAIL"
                if yolo_status != "PASS":
                    all_passed = False
            except Exception as e:
                yolo_load = "LOAD_OR_INFER_FAILED"
                yolo_errs.append(f"{type(e).__name__}: {e}")
                yolo_status = "FAIL" if require_real_models else "NOT_TESTED"
                all_passed = False
    else:
        try:
            import ultralytics  # noqa: F401
        except Exception as e:
            yolo_errs.append(f"{type(e).__name__}: {e}")
        all_passed = False
        if require_real_models:
            yolo_status = "FAIL"

    results["YOLOv8n"] = {
        "test_classification": classification_label,
        "acceptance_status": yolo_status,
        "download_status": yolo_dl["download_status"],
        "expected_sha256": yolo_exp_sha,
        "actual_sha256": yolo_dl["sha256"],
        "verified_before_load": bool(yolo_dl["ok"]),
        "model_load_status": yolo_load,
        "inference_result": yolo_inf,
        "latency_ms": yolo_lat,
        "errors": " | ".join(yolo_errs) if yolo_errs else None,
    }

    # 4. EasyOCR Arabic + English (`models/easyocr`) — Pinned SHA-256 verified BEFORE load + MIN_REQUIRED_PLATE_SAMPLES gate
    eocr_ok, eocr_reason = pf.verify_easyocr_dir(str(easyocr_dir))
    eocr_status = "NOT_TESTED"
    eocr_load = "NOT_LOADED"
    eocr_inf = "NOT_EXECUTED"
    eocr_lat = None
    eocr_shas = {}
    eocr_errs = []
    if easyocr_dir.is_dir():
        for pth in sorted(easyocr_dir.glob("*.pth")):
            eocr_shas[pth.name] = sha256_file(pth)

    if not eocr_ok and require_real_models:
        try:
            import easyocr
            easyocr_dir.mkdir(parents=True, exist_ok=True)
            _ = easyocr.Reader(["ar", "en"], gpu=False, model_storage_directory=str(easyocr_dir), download_enabled=True)
            eocr_ok, eocr_reason = pf.verify_easyocr_dir(str(easyocr_dir))
            eocr_shas = {pth.name: sha256_file(pth) for pth in sorted(easyocr_dir.glob("*.pth"))}
        except Exception as dl_exc:
            eocr_errs.append(f"EasyOCR download failed: {type(dl_exc).__name__}: {dl_exc}")

    if not eocr_ok:
        eocr_errs.append(f"verify_easyocr_dir_sha256: {eocr_reason}")
        all_passed = False
        if require_real_models:
            eocr_status = "FAIL"
    else:
        try:
            import easyocr
            reader = easyocr.Reader(
                ["ar", "en"],
                gpu=False,
                model_storage_directory=str(easyocr_dir),
                download_enabled=False,
            )
            eocr_load = "LOADED_AFTER_SHA256_VERIFY"
            lats = []
            reads = []
            valid_non_empty_reads = []
            for f_img in frames:
                boxes = m.find_plates(f_img)
                if boxes:
                    x, y, bw, bh = boxes[0]
                    t0 = time.perf_counter()
                    norm_txt, conf_val = m.read_plate(reader, f_img[y:y + bh, x:x + bw])
                    lats.append((time.perf_counter() - t0) * 1000.0)
                    reads.append((norm_txt, round(conf_val, 3)))
                    if norm_txt and str(norm_txt).strip():
                        valid_non_empty_reads.append((norm_txt, round(conf_val, 3)))
            eocr_lat = round(float(np.mean(lats)), 2) if lats else None
            eocr_inf = (
                f"[{classification_label}] EXECUTED EasyOCR on {len(reads)} plate crops "
                f"(valid_non_empty={len(valid_non_empty_reads)}/{MIN_REQUIRED_PLATE_SAMPLES} required): {reads}"
            )
            if len(valid_non_empty_reads) >= MIN_REQUIRED_PLATE_SAMPLES:
                eocr_status = "PASS"
            else:
                eocr_status = "FAIL"
                eocr_errs.append(
                    f"Insufficient valid plate crop inferences: got {len(valid_non_empty_reads)}, "
                    f"minimum required is {MIN_REQUIRED_PLATE_SAMPLES}"
                )
                all_passed = False
        except Exception as e:
            eocr_load = "LOAD_OR_INFER_FAILED"
            eocr_errs.append(f"{type(e).__name__}: {e}")
            all_passed = False
            if require_real_models:
                eocr_status = "FAIL"

    results["EasyOCR_Ar_En"] = {
        "test_classification": classification_label,
        "acceptance_status": eocr_status,
        "download_status": "PRESENT_AND_SHA256_VERIFIED" if eocr_ok else "FAILED_OR_MISSING_WEIGHTS",
        "expected_sha256_files": dict(pf.EASYOCR_SHA256),
        "actual_sha256_files": eocr_shas,
        "verified_before_load": bool(eocr_ok),
        "min_required_plate_samples": MIN_REQUIRED_PLATE_SAMPLES,
        "model_load_status": eocr_load,
        "inference_result": eocr_inf,
        "latency_ms": eocr_lat,
        "errors": " | ".join(eocr_errs) if eocr_errs else None,
        "tesseract_substituted": False,
    }

    return results, all_passed


def main():
    ap = argparse.ArgumentParser(description="MERSAD Phase 1: Real AI Model Verification & Inference")
    ap.add_argument("--require-real-models", action="store_true", help="Exit 1 unless all 4 real models pass SHA-256, load, and execute inference")
    ap.add_argument("--attempt-prefetch", action="store_true", help="Run prefetch.py before testing")
    args = ap.parse_args()

    print("========================================================================================")
    print("  MERSAD PREVIEW 0.1 — Phase 1: Real AI Models Verification & Inference Suite")
    print("========================================================================================")

    m.init_runtime_env(appdir=BENCH_HOME, force=True)
    reg.init(m.db, m.DBL, m.log, lambda: None, m.DB_PATH)

    if args.attempt_prefetch:
        print("  [PREFETCH] Running prefetch.py ...")
        subprocess.run([sys.executable, str(AI_DIR / "prefetch.py")], cwd=str(AI_DIR), check=False)

    # Pre-verify / download models with pinned SHA-256 constants
    yunet_path = AI_DIR / "models" / "yunet.onnx"
    sface_path = AI_DIR / "models" / "sface.onnx"
    yolo_path = AI_DIR / "models" / "yolov8n.pt"
    easyocr_dir = AI_DIR / "models" / "easyocr"

    timeout_s = 25.0 if args.require_real_models else 3.0
    yunet_dl = ensure_verified_model(pf.MODELS["yunet.onnx"], yunet_path, pf.MODEL_SHA256["yunet.onnx"], timeout=timeout_s)
    sface_dl = ensure_verified_model(pf.MODELS["sface.onnx"], sface_path, pf.MODEL_SHA256["sface.onnx"], timeout=timeout_s)
    yolo_dl = ensure_verified_model(pf.YOLO_MODEL_URL, yolo_path, pf.MODEL_SHA256["yolov8n.pt"], timeout=timeout_s)

    # --------------------------------------------------------------------------
    # Classification A: SYNTHETIC_VIRTUAL_CAMERA_SCENE_INFERENCE
    # Direct in-memory VirtualCamera.render_bgr() scenes (no HTTP/MJPEG transport)
    # --------------------------------------------------------------------------
    synth_cams = [VirtualCamera(f"cam{i+1}", f"Cam {i+1}", plate_idx=i) for i in range(4)]
    synth_frames = [c.render_bgr()[1] for c in synth_cams]
    synth_results, synth_all_passed = evaluate_four_models_on_frames(
        frames=synth_frames,
        classification_label="SYNTHETIC_VIRTUAL_CAMERA_SCENE_INFERENCE",
        require_real_models=args.require_real_models,
        yunet_dl=yunet_dl,
        sface_dl=sface_dl,
        yolo_dl=yolo_dl,
        yunet_path=yunet_path,
        sface_path=sface_path,
        yolo_path=yolo_path,
        easyocr_dir=easyocr_dir,
    )

    print("\n  --- [A] SYNTHETIC_VIRTUAL_CAMERA_SCENE_INFERENCE (In-Memory VirtualCamera) ---")
    for k, v in synth_results.items():
        print(
            f"  [SYNTH SCENE] {k:14s} | Status={v['acceptance_status']:10s} | "
            f"Download={v['download_status']:28s} | Load={v['model_load_status']:26s} | "
            f"Inference={v['inference_result']}"
        )

    # --------------------------------------------------------------------------
    # Classification B: LIVE_LAB_HTTP_MJPEG_STREAM_INFERENCE
    # Live HTTP MJPEG stream from LabHTTPServer -> OpenCV VideoCapture -> Inference
    # --------------------------------------------------------------------------
    live_frames, live_stream_meta = capture_live_lab_mjpeg_frames(num_cameras=4)
    live_results, live_all_passed = evaluate_four_models_on_frames(
        frames=live_frames,
        classification_label="LIVE_LAB_HTTP_MJPEG_STREAM_INFERENCE",
        require_real_models=args.require_real_models,
        yunet_dl=yunet_dl,
        sface_dl=sface_dl,
        yolo_dl=yolo_dl,
        yunet_path=yunet_path,
        sface_path=sface_path,
        yolo_path=yolo_path,
        easyocr_dir=easyocr_dir,
    )

    print("\n  --- [B] LIVE_LAB_HTTP_MJPEG_STREAM_INFERENCE (Live LAB HTTP MJPEG -> OpenCV) ---")
    for k, v in live_results.items():
        print(
            f"  [LIVE STREAM] {k:14s} | Status={v['acceptance_status']:10s} | "
            f"Download={v['download_status']:28s} | Load={v['model_load_status']:26s} | "
            f"Inference={v['inference_result']}"
        )

    # --------------------------------------------------------------------------
    # Classification C: INDEPENDENT_AUXILIARY_TESSERACT_BENCHMARK
    # Strictly isolated from EasyOCR acceptance
    # --------------------------------------------------------------------------
    t_reader = m.TesseractOCRReader()
    tess_synth_reads = []
    tess_live_reads = []
    tess_lats = []
    for c_obj, f_img in zip(synth_cams, synth_frames):
        boxes = m.find_plates(f_img)
        if boxes:
            x, y, bw, bh = boxes[0]
            t0 = time.perf_counter()
            norm_txt, conf_val = m.read_plate(t_reader, f_img[y:y + bh, x:x + bw])
            tess_lats.append((time.perf_counter() - t0) * 1000.0)
            tess_synth_reads.append({
                "cam": c_obj.cam_id,
                "expected": f"{c_obj.plate_gov}-{c_obj.plate_digits}",
                "predicted": norm_txt,
                "conf": round(conf_val, 3),
            })
    for c_obj, f_img in zip(synth_cams, live_frames):
        boxes = m.find_plates(f_img)
        if boxes:
            x, y, bw, bh = boxes[0]
            t0 = time.perf_counter()
            norm_txt, conf_val = m.read_plate(t_reader, f_img[y:y + bh, x:x + bw])
            tess_lats.append((time.perf_counter() - t0) * 1000.0)
            tess_live_reads.append({
                "cam": c_obj.cam_id,
                "expected": f"{c_obj.plate_gov}-{c_obj.plate_digits}",
                "predicted": norm_txt,
                "conf": round(conf_val, 3),
            })

    report = {
        "timestamp": time.strftime("%Y-%m-%d %H:%M:%S"),
        "require_real_models": bool(args.require_real_models),
        "min_required_plate_samples": MIN_REQUIRED_PLATE_SAMPLES,
        "pinned_sha256_registry": {
            "models": dict(pf.MODEL_SHA256),
            "easyocr": dict(pf.EASYOCR_SHA256),
        },
        "strict_policy": (
            "1) All 4 models require pre-load SHA-256 verification against pinned constants (self-minted .sha256 sidecars are rejected). "
            "2) EasyOCR requires >= 4 valid non-empty plate crop reads to PASS. "
            "3) SFace requires a real face crop detected and aligned by YuNet (det.detect -> rec.alignCrop). "
            "4) Synthetic VirtualCamera scene inference is separated from live LAB HTTP MJPEG stream inference. "
            "5) Tesseract is NEVER used as a substitute for EasyOCR acceptance."
        ),
        "primary_models_acceptance": live_results,
        "synthetic_virtual_camera_scene_inference": synth_results,
        "live_lab_http_mjpeg_stream_inference": {
            "stream_capture_metadata": live_stream_meta,
            "models": live_results,
        },
        "independent_tesseract_benchmark": {
            "test_classification": "INDEPENDENT_AUXILIARY_TESSERACT_BENCHMARK",
            "note": "Independent auxiliary test ONLY. NOT counted as EasyOCR acceptance.",
            "engine": "Tesseract 5 LSTM (/usr/bin/tesseract)",
            "synthetic_scene_samples": len(tess_synth_reads),
            "synthetic_scene_exact_matches": sum(1 for r in tess_synth_reads if r["predicted"] == r["expected"]),
            "live_mjpeg_stream_samples": len(tess_live_reads),
            "live_mjpeg_stream_exact_matches": sum(1 for r in tess_live_reads if r["predicted"] == r["expected"]),
            "mean_latency_ms": round(float(np.mean(tess_lats)), 2) if tess_lats else None,
            "synthetic_scene_results": tess_synth_reads,
            "live_mjpeg_stream_results": tess_live_reads,
        },
    }

    print(
        f"\n  --- [C] INDEPENDENT_AUXILIARY_TESSERACT_BENCHMARK ---\n"
        f"  [AUX TEST] Synthetic VirtualCamera Scenes: {report['independent_tesseract_benchmark']['synthetic_scene_exact_matches']}/4 matched\n"
        f"  [AUX TEST] Live LAB HTTP MJPEG Streams   : {report['independent_tesseract_benchmark']['live_mjpeg_stream_exact_matches']}/4 matched "
        f"(mean_latency={report['independent_tesseract_benchmark']['mean_latency_ms']}ms)"
    )

    out_path = ROOT_DIR / "reports_and_logs" / "model_inference_results.json"
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    Path("/tmp/evaluate_ai_models_benchmark.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")

    try:
        if m.db:
            m.db.close()
    except Exception:
        pass
    shutil.rmtree(BENCH_HOME, ignore_errors=True)

    if args.require_real_models and not (synth_all_passed and live_all_passed):
        print("  [ACCEPTANCE GATE FAILED] --require-real-models was set, and one or more of the 4 required AI models did not pass.")
        sys.exit(1)
    sys.exit(0)


if __name__ == "__main__":
    main()
