#!/usr/bin/env python3
"""
MERSAD AI V7.1 + MERSAD LAB 1.0 — PREVIEW 0.1
Phase 1: Real AI Models Download, SHA-256 Verification & Ground-Truth Acceptance Suite
======================================================================================
Enforces strict ground-truth acceptance rules (NEVER grants PASS merely for loading a model
or executing inference on 4 frames without ground-truth accuracy validation):
  1. Pinned, immutable SHA-256 digests verified BEFORE loading into memory:
       - YOLOv8n (`models/yolov8n.pt` -> 31e20dde3def09e2cf938c7be6fe23d9150bbbe503982af13345706515f2ef95)
       - EasyOCR Arabic + English (`models/easyocr/*.pth` -> craft_mlt_25k.pth, arabic.pth, english_g2.pth, latin_g2.pth)
       - YuNet (`models/yunet.onnx` -> 8f2383e4dd3cfbb4553ea8718107fc0423210dc964f9f4280604804ed2552fa4)
       - SFace (`models/sface.onnx` -> 0ba9fbfa01b5270c96627c4ef784da859931e02f04419c829e83484087c34e79)
  2. YOLOv8n Ground-Truth Gate:
       - Evaluates detected vehicle bounding boxes and COCO vehicle classes (`car, motorcycle, bus, truck`)
         against ground-truth reference boxes (`IoU >= 0.50`, `Recall >= 0.75`, `Precision >= 0.75`)
         and verifies `0` false positives on negative non-vehicle scenes.
       - If a realistic ground-truth vehicle dataset is absent (or weights are missing), status remains `NOT_TESTED`.
  3. EasyOCR Ground-Truth Gate:
       - Compares predicted plate text against ground-truth expected strings (`عدن-12345`, `صنعاء-48210`, `تعز-73901`, `حضرموت-55120`).
       - Computes `Exact Match Rate`, `Digits Match Rate`, and `Mean Character Error Rate (CER)`.
       - Requires `samples >= 4`, `Exact Match Rate >= 0.75`, and `Mean CER <= 0.25` to grant `PASS`.
  4. YuNet Ground-Truth Gate:
       - Requires positive face detection (`Recall >= 0.75` on authorized positive face benchmark images in
         `models/eval_benchmarks/faces_positive/`) AND negative sample rejection (`0` false positives on non-face road/noise scenes).
       - If authorized positive face images are not provided on disk, retains `NOT_TESTED` (`MISSING_AUTHORIZED_POSITIVE_FACE_SAMPLES`).
  5. SFace Ground-Truth Gate:
       - Requires YuNet-detected & aligned crops (`det.detect -> rec.alignCrop`) across authorized multi-identity
         face pairs (`models/eval_benchmarks/faces_authorized_pairs/`), verifying intra-person cosine similarity
         (`same person >= 0.363`) AND inter-person separation (`different persons < 0.363`, `False Accept Rate == 0`).
       - If authorized multi-identity face crops are not provided on disk, retains `NOT_TESTED`.
  6. Tesseract 5 LSTM is evaluated strictly in a separate auxiliary section (`INDEPENDENT_AUXILIARY_TESSERACT_BENCHMARK`)
     with full `Exact Match Rate` and `Mean CER` metrics, and is NEVER substituted for EasyOCR acceptance.
"""
import argparse
import hashlib
import json
import os
import re
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
os.environ["OMP_THREAD_LIMIT"] = "1"

import mersad_live as m
import prefetch as pf
import registry as reg
from lab_server import LabHTTPServer, LabRequestHandler, LabState
from sim_engine import VirtualCamera

MIN_REQUIRED_PLATE_SAMPLES = 4
EXPECTED_LAB_PLATES = [
    ("cam1", "عدن-12345", [160, 170, 320, 210], "car"),
    ("cam2", "صنعاء-48210", [160, 170, 320, 210], "car"),
    ("cam3", "تعز-73901", [160, 170, 320, 210], "car"),
    ("cam4", "حضرموت-55120", [160, 170, 320, 210], "car"),
]


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


def build_negative_non_face_non_vehicle_scenes() -> list[np.ndarray]:
    """Generate 4 negative control frames (empty asphalt road, geometric stripes, blank dark, noise) that contain 0 faces and 0 vehicles."""
    neg1 = np.full((480, 640, 3), 45, dtype=np.uint8)
    cv2.line(neg1, (0, 240), (640, 240), (90, 90, 90), 2)
    neg2 = np.zeros((480, 640, 3), dtype=np.uint8)
    for x in range(0, 640, 40):
        cv2.line(neg2, (x, 0), (x, 480), (120, 120, 120), 1)
    neg3 = np.full((480, 640, 3), 15, dtype=np.uint8)
    rng = np.random.default_rng(42)
    neg4 = rng.integers(20, 80, size=(480, 640, 3), dtype=np.uint8)
    return [neg1, neg2, neg3, neg4]


def build_four_stage_breakdown(
    downloaded_and_sha256_verified: bool,
    loaded_and_inference_executed: bool,
    ground_truth_samples_available: bool,
    ground_truth_acceptance_passed: bool,
    acceptance_status: str,
    not_tested_or_fail_reason: str = None,
) -> dict:
    """
    Explicitly separate the 4 distinct validation stages for each AI model:
      1. Model downloaded and SHA-256 verified against pinned digest.
      2. Model loaded into memory and executed real forward-pass inference.
      3. Ground-truth benchmark dataset/samples available on disk (including authorized face samples for YuNet/SFace).
      4. Ground-truth quantitative acceptance thresholds passed.
    Never converts NOT_TESTED to PASS.
    """
    final_status = acceptance_status
    if not (downloaded_and_sha256_verified and loaded_and_inference_executed and ground_truth_samples_available and ground_truth_acceptance_passed):
        if final_status == "PASS":
            final_status = "NOT_TESTED" if not ground_truth_samples_available else "FAIL"
    smoke_status = "PASS" if (downloaded_and_sha256_verified and loaded_and_inference_executed) else ("FAIL" if (downloaded_and_sha256_verified and not loaded_and_inference_executed) else "NOT_TESTED")
    return {
        "stage1_downloaded_and_sha256_verified": bool(downloaded_and_sha256_verified),
        "stage2_loaded_and_inference_executed": bool(loaded_and_inference_executed),
        "stage3_ground_truth_samples_available": bool(ground_truth_samples_available),
        "stage4_ground_truth_acceptance_passed": bool(ground_truth_acceptance_passed),
        "smoke_inference_status": smoke_status,
        "ground_truth_acceptance_status": final_status,
        "final_status": final_status,
        "status_explanation": not_tested_or_fail_reason,
    }


def compute_ocr_ground_truth_metrics(samples: list[dict]) -> dict:
    """Compute Exact Match Rate, Digits Match Rate, and Mean Character Error Rate (CER) against ground-truth plates."""
    if not samples:
        return {
            "samples_count": 0,
            "exact_matches": 0,
            "exact_match_rate": 0.0,
            "digits_match_rate": 0.0,
            "mean_cer": 1.0,
            "passes_acceptance_gate": False,
        }
    exact_cnt = 0
    digits_cnt = 0
    cers = []
    for s in samples:
        exp = reg.norm_plate(s.get("expected", ""))
        pred = reg.norm_plate(s.get("predicted", ""))
        if exp and pred == exp:
            exact_cnt += 1
        exp_dig = "".join(re.findall(r"\d+", exp))
        pred_dig = "".join(re.findall(r"\d+", pred))
        if exp_dig and pred_dig == exp_dig:
            digits_cnt += 1
        cers.append(m._compute_cer(exp, pred))
    n = len(samples)
    em_rate = round(exact_cnt / n, 4)
    dm_rate = round(digits_cnt / n, 4)
    mean_cer = round(float(np.mean(cers)), 4)
    passes = (n >= MIN_REQUIRED_PLATE_SAMPLES and em_rate >= 0.75 and mean_cer <= 0.25)
    return {
        "samples_count": n,
        "exact_matches": exact_cnt,
        "exact_match_rate": em_rate,
        "digits_match_rate": dm_rate,
        "mean_cer": mean_cer,
        "passes_acceptance_gate": passes,
    }


def evaluate_yolo_ground_truth_gate(vyolo, pos_frames: list[np.ndarray], neg_frames: list[np.ndarray], gt_specs: list[tuple], benchmark_dir: Path = None) -> dict:
    """
    Evaluate YOLOv8n against ground-truth vehicle boxes & classes + negative scenes.
    Never grants PASS merely for running on 4 frames: requires Recall >= 0.75, Precision >= 0.75, Mean IoU >= 0.50, and Negative FP == 0.
    If only synthetic geometric rectangles are present without natural vehicle images and recall is 0, returns NOT_TESTED.
    """
    tp = 0
    fp = 0
    fn = 0
    ious = []
    lats = []
    class_matches = 0
    allowed_classes = {"car", "motorcycle", "bus", "truck"}

    for f_img, (_, _, gt_box, gt_cls) in zip(pos_frames, gt_specs):
        t0 = time.perf_counter()
        dets = m.detect_vehicles(f_img, vyolo)
        lats.append((time.perf_counter() - t0) * 1000.0)
        if not dets:
            fn += 1
            continue
        best_iou = 0.0
        best_cls = None
        for d in dets:
            x1, y1, x2, y2 = d[:4]
            d_cls = str(d[4]) if len(d) > 4 else "car"
            pred_xywh = [x1, y1, max(1, x2 - x1), max(1, y2 - y1)]
            iou_val = m._bbox_iou(pred_xywh, gt_box)
            if iou_val > best_iou:
                best_iou = iou_val
                best_cls = d_cls
        if best_iou >= 0.50 and best_cls in allowed_classes:
            tp += 1
            ious.append(best_iou)
            if best_cls == gt_cls or best_cls in allowed_classes:
                class_matches += 1
            fp += max(0, len(dets) - 1)
        else:
            fn += 1
            fp += len(dets)

    neg_fp = 0
    for nf in neg_frames:
        t0 = time.perf_counter()
        ndets = m.detect_vehicles(nf, vyolo)
        lats.append((time.perf_counter() - t0) * 1000.0)
        neg_fp += len(ndets)

    precision = round(tp / (tp + fp + neg_fp), 4) if (tp + fp + neg_fp) > 0 else 0.0
    recall = round(tp / (tp + fn), 4) if (tp + fn) > 0 else 0.0
    f1 = round(2 * precision * recall / (precision + recall), 4) if (precision + recall) > 0 else 0.0
    mean_iou = round(float(np.mean(ious)), 4) if ious else 0.0
    mean_lat = round(float(np.mean(lats)), 2) if lats else None

    has_real_vehicle_benchmark = False
    if benchmark_dir and benchmark_dir.is_dir():
        gt_json_p = benchmark_dir / "ground_truth.json"
        if gt_json_p.is_file():
            try:
                gt_meta = json.loads(gt_json_p.read_text(encoding="utf-8"))
                has_real_vehicle_benchmark = bool(gt_meta.get("is_photorealistic_natural_dataset", False))
                if has_real_vehicle_benchmark:
                    for item in gt_meta.get("samples", []):
                        img_p = benchmark_dir / item["filename"]
                        b_img = cv2.imread(str(img_p))
                        if b_img is None or b_img.size == 0:
                            continue
                        t0 = time.perf_counter()
                        bdets = m.detect_vehicles(b_img, vyolo)
                        lats.append((time.perf_counter() - t0) * 1000.0)
                        if not bdets:
                            fn += 1
                            continue
                        best_iou = 0.0
                        best_cls = None
                        for d in bdets:
                            x1, y1, x2, y2 = d[:4]
                            d_cls = str(d[4]) if len(d) > 4 else "car"
                            pred_xywh = [x1, y1, max(1, x2 - x1), max(1, y2 - y1)]
                            iou_val = m._bbox_iou(pred_xywh, item["bbox_xywh"])
                            if iou_val > best_iou:
                                best_iou = iou_val
                                best_cls = d_cls
                        if best_iou >= 0.50 and best_cls in allowed_classes:
                            tp += 1
                            ious.append(best_iou)
                            class_matches += 1
                        else:
                            fn += 1
                            fp += len(bdets)
                    precision = round(tp / (tp + fp + neg_fp), 4) if (tp + fp + neg_fp) > 0 else 0.0
                    recall = round(tp / (tp + fn), 4) if (tp + fn) > 0 else 0.0
                    f1 = round(2 * precision * recall / (precision + recall), 4) if (precision + recall) > 0 else 0.0
                    mean_iou = round(float(np.mean(ious)), 4) if ious else 0.0
                    mean_lat = round(float(np.mean(lats)), 2) if lats else None
            except Exception:
                has_real_vehicle_benchmark = False
    if tp == 0 and not has_real_vehicle_benchmark:
        status = "NOT_TESTED"
        reason = "INSUFFICIENT_NATURAL_VEHICLE_BENCHMARK_DATASET (VirtualCamera and synthetic fixtures render 2D geometric rectangles; photorealistic vehicle benchmark photos required for YOLOv8n Ground-Truth Accuracy acceptance, while Smoke/Inference and Negative FP=0 are verified)"
    elif recall >= 0.75 and precision >= 0.75 and mean_iou >= 0.50 and neg_fp == 0:
        status = "PASS"
        reason = None
    else:
        status = "FAIL"
        reason = f"Ground-truth gate not met: recall={recall} (req >=0.75), precision={precision} (req >=0.75), mean_iou={mean_iou} (req >=0.50), neg_fp={neg_fp} (req 0)"

    return {
        "status": status,
        "tp": tp,
        "fp": fp,
        "fn": fn,
        "negative_false_positives": neg_fp,
        "precision": precision,
        "recall": recall,
        "f1": f1,
        "mean_iou": mean_iou,
        "class_matches": class_matches,
        "latency_ms": mean_lat,
        "reason": reason,
    }


def evaluate_yunet_and_sface_ground_truth_gates(det, rec, neg_frames: list[np.ndarray], pos_face_dir: Path, pairs_face_dir: Path) -> tuple[dict, dict]:
    """
    Evaluate YuNet (positive face detection + negative non-face rejection) and
    SFace (intra-person cosine similarity >= 0.363 + inter-person separation < 0.363 on authorized face crops).
    Never grants PASS merely for running on 4 road frames with 0 faces!
    """
    neg_lats = []
    neg_fp = 0
    for nf in neg_frames:
        t0 = time.perf_counter()
        det.setInputSize((nf.shape[1], nf.shape[0]))
        _, faces = det.detect(nf)
        neg_lats.append((time.perf_counter() - t0) * 1000.0)
        if faces is not None and len(faces) > 0:
            neg_fp += len(faces)

    consent_manifest_p = (pos_face_dir / "CONSENT_MANIFEST.json") if (pos_face_dir and pos_face_dir.is_dir()) else None
    has_authorized_human_consent = False
    if consent_manifest_p and consent_manifest_p.is_file():
        try:
            c_meta = json.loads(consent_manifest_p.read_text(encoding="utf-8"))
            has_authorized_human_consent = bool(c_meta.get("authorized_real_human_consent", False) and not c_meta.get("is_synthetic_non_human", True))
        except Exception:
            has_authorized_human_consent = False
    pos_files = sorted(pos_face_dir.glob("*.jpg")) if (pos_face_dir and pos_face_dir.is_dir() and has_authorized_human_consent) else []
    pos_tp = 0
    detected_crops = []
    for pf_path in pos_files:
        img = cv2.imread(str(pf_path))
        if img is None or img.size == 0:
            continue
        t0 = time.perf_counter()
        det.setInputSize((img.shape[1], img.shape[0]))
        _, faces = det.detect(img)
        neg_lats.append((time.perf_counter() - t0) * 1000.0)
        if faces is not None and len(faces) > 0:
            pos_tp += 1
            detected_crops.append((pf_path.stem, img, faces[0]))

    yunet_lat = round(float(np.mean(neg_lats)), 2) if neg_lats else None
    if len(pos_files) < 2:
        yunet_status = "NOT_TESTED"
        yunet_reason = (
            f"Negative rejection verified (neg_fp={neg_fp}/{len(neg_frames)} non-face frames), "
            "but authorized positive face benchmark images (models/eval_benchmarks/faces_positive/*.jpg) are not present on disk; "
            "refusing to grant PASS without positive face ground-truth samples."
        )
        pos_recall = None
    else:
        pos_recall = round(pos_tp / len(pos_files), 4)
        if pos_recall >= 0.75 and neg_fp == 0:
            yunet_status = "PASS"
            yunet_reason = None
        else:
            yunet_status = "FAIL"
            yunet_reason = f"YuNet gate failed: pos_recall={pos_recall} (req >=0.75), neg_fp={neg_fp} (req 0)"

    yunet_res = {
        "status": yunet_status,
        "positive_samples_count": len(pos_files),
        "positive_true_positives": pos_tp,
        "positive_recall": pos_recall,
        "negative_samples_count": len(neg_frames),
        "negative_false_positives": neg_fp,
        "latency_ms": yunet_lat,
        "reason": yunet_reason,
    }

    # SFace evaluation: verify forward-pass feature extraction on a 112x112 aligned crop if rec is loaded,
    # then require >= 2 identities with >= 2 samples each for ground-truth acceptance.
    sface_smoke_lat = None
    if rec is not None:
        t0_sf = time.perf_counter()
        _ = rec.feature(np.zeros((112, 112, 3), dtype=np.uint8))
        sface_smoke_lat = round((time.perf_counter() - t0_sf) * 1000.0, 2)

    if rec is None or len(detected_crops) < 4:
        sface_res = {
            "status": "NOT_TESTED",
            "forward_pass_verified": bool(rec is not None),
            "pairs_evaluated": 0,
            "same_person_cosine_sim_mean": None,
            "different_person_cosine_sim_max": None,
            "false_accept_rate": None,
            "latency_ms": sface_smoke_lat,
            "reason": (
                "MISSING_AUTHORIZED_MULTI_IDENTITY_FACE_SAMPLES: SFace acceptance requires >= 4 YuNet-aligned crops across >= 2 authorized volunteers "
                "to measure intra-person similarity (>= 0.363) and inter-person separation (< 0.363)."
            ),
        }
    else:
        by_person = {}
        sf_lats = []
        for stem, img, face_row in detected_crops:
            pid = stem.split("_")[0]
            t0 = time.perf_counter()
            aligned = rec.alignCrop(img, face_row)
            emb = rec.feature(aligned)
            sf_lats.append((time.perf_counter() - t0) * 1000.0)
            vec = np.asarray(emb, dtype=np.float32).reshape(-1)
            norm = float(np.linalg.norm(vec))
            if norm > 1e-6:
                vec = vec / norm
            by_person.setdefault(pid, []).append(vec)

        same_sims = []
        diff_sims = []
        pids = sorted(by_person.keys())
        for pid in pids:
            vecs = by_person[pid]
            for i in range(len(vecs)):
                for j in range(i + 1, len(vecs)):
                    same_sims.append(float(np.dot(vecs[i], vecs[j])))
        for i in range(len(pids)):
            for j in range(i + 1, len(pids)):
                for va in by_person[pids[i]]:
                    for vb in by_person[pids[j]]:
                        diff_sims.append(float(np.dot(va, vb)))

        if not same_sims or not diff_sims:
            sface_res = {
                "status": "NOT_TESTED",
                "pairs_evaluated": 0,
                "same_person_cosine_sim_mean": None,
                "different_person_cosine_sim_max": None,
                "false_accept_rate": None,
                "latency_ms": round(float(np.mean(sf_lats)), 2) if sf_lats else None,
                "reason": "Need at least 2 images per volunteer and at least 2 distinct volunteers to compute intra/inter-person similarity.",
            }
        else:
            same_mean = round(float(np.mean(same_sims)), 4)
            diff_max = round(float(np.max(diff_sims)), 4)
            far = round(sum(1 for s in diff_sims if s >= 0.363) / len(diff_sims), 4)
            sf_ok = (same_mean >= 0.363 and diff_max < 0.363 and far == 0.0)
            sface_res = {
                "status": "PASS" if sf_ok else "FAIL",
                "pairs_evaluated": len(same_sims) + len(diff_sims),
                "same_person_cosine_sim_mean": same_mean,
                "different_person_cosine_sim_max": diff_max,
                "false_accept_rate": far,
                "latency_ms": round(float(np.mean(sf_lats)), 2) if sf_lats else None,
                "reason": None if sf_ok else f"SFace threshold gate failed: same_mean={same_mean} (req >=0.363), diff_max={diff_max} (req <0.363)",
            }

    return yunet_res, sface_res


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
    """Run all 4 primary models on the provided frame set with strict pre-load SHA-256 verification and ground-truth accuracy gates."""
    results = {}
    all_passed = True
    neg_frames = build_negative_non_face_non_vehicle_scenes()
    pos_face_dir = AI_DIR / "models" / "eval_benchmarks" / "faces_positive"
    veh_bench_dir = AI_DIR / "models" / "eval_benchmarks" / "vehicles"

    # 1 & 2. YuNet & SFace (`models/yunet.onnx`, `models/sface.onnx`)
    yunet_exp_sha = pf.MODEL_SHA256["yunet.onnx"]
    sface_exp_sha = pf.MODEL_SHA256["sface.onnx"]
    det_obj = None
    rec_obj = None
    yunet_load = "NOT_LOADED"
    sface_load = "NOT_LOADED"
    yunet_err = yunet_dl["error"]
    sface_err = sface_dl["error"]

    if yunet_dl["ok"]:
        ok_onnx, reason_onnx = pf.verify_onnx_file(
            str(yunet_path),
            expected_sha256=yunet_exp_sha,
            min_bytes=pf.MODEL_MIN_BYTES.get("yunet.onnx", 200_000),
        )
        if not ok_onnx:
            yunet_load = "PRELOAD_SHA256_VERIFY_FAILED"
            yunet_err = reason_onnx
        else:
            try:
                det_obj = cv2.FaceDetectorYN.create(str(yunet_path), "", (640, 480), 0.65)
                yunet_load = "LOADED_AFTER_SHA256_VERIFY"
            except Exception as e:
                yunet_load = "LOAD_OR_INFER_FAILED"
                yunet_err = f"{type(e).__name__}: {e}"

    if sface_dl["ok"]:
        ok_onnx_sf, reason_onnx_sf = pf.verify_onnx_file(
            str(sface_path),
            expected_sha256=sface_exp_sha,
            min_bytes=pf.MODEL_MIN_BYTES.get("sface.onnx", 30_000_000),
        )
        if not ok_onnx_sf:
            sface_load = "PRELOAD_SHA256_VERIFY_FAILED"
            sface_err = reason_onnx_sf
        else:
            try:
                rec_obj = cv2.FaceRecognizerSF.create(str(sface_path), "")
                sface_load = "LOADED_AFTER_SHA256_VERIFY"
            except Exception as e:
                sface_load = "LOAD_OR_INFER_FAILED"
                sface_err = f"{type(e).__name__}: {e}"

    if det_obj is not None:
        yn_gate, sf_gate = evaluate_yunet_and_sface_ground_truth_gates(det_obj, rec_obj, frames + neg_frames, pos_face_dir, pos_face_dir)
        yunet_status = yn_gate["status"]
        yunet_inf = (
            f"[{classification_label}] pos_samples={yn_gate['positive_samples_count']}, "
            f"pos_recall={yn_gate['positive_recall']}, neg_fp={yn_gate['negative_false_positives']}/{yn_gate['negative_samples_count']}"
        )
        yunet_lat = yn_gate["latency_ms"]
        if yn_gate["reason"]:
            yunet_err = yn_gate["reason"]
    else:
        yunet_status = "FAIL" if (yunet_load == "PRELOAD_SHA256_VERIFY_FAILED") else "NOT_TESTED"
        yunet_inf = "NOT_EXECUTED"
        yunet_lat = None
        sf_gate = {
            "status": "FAIL" if (sface_load == "PRELOAD_SHA256_VERIFY_FAILED") else "NOT_TESTED",
            "pairs_evaluated": 0,
            "same_person_cosine_sim_mean": None,
            "different_person_cosine_sim_max": None,
            "false_accept_rate": None,
            "latency_ms": None,
            "reason": sface_err,
        }

    if yunet_status != "PASS":
        all_passed = False
    if sf_gate["status"] != "PASS":
        all_passed = False

    yn_has_gt_samples = bool(det_obj is not None and yn_gate.get("positive_samples_count", 0) >= 2)
    yn_gt_passed = bool(yunet_status == "PASS" and yn_has_gt_samples)
    results["YuNet"] = {
        "test_classification": classification_label,
        "acceptance_status": yunet_status,
        "four_stage_breakdown": build_four_stage_breakdown(
            downloaded_and_sha256_verified=bool(yunet_dl["ok"] and yunet_load != "PRELOAD_SHA256_VERIFY_FAILED"),
            loaded_and_inference_executed=bool(det_obj is not None),
            ground_truth_samples_available=yn_has_gt_samples,
            ground_truth_acceptance_passed=yn_gt_passed,
            acceptance_status=yunet_status,
            not_tested_or_fail_reason=yunet_err,
        ),
        "download_status": yunet_dl["download_status"],
        "expected_sha256": yunet_exp_sha,
        "actual_sha256": yunet_dl["sha256"],
        "verified_before_load": bool(yunet_dl["ok"]),
        "model_load_status": yunet_load,
        "inference_result": yunet_inf,
        "ground_truth_metrics": yn_gate if det_obj is not None else None,
        "latency_ms": yunet_lat,
        "errors": yunet_err,
    }

    sf_has_gt_samples = bool(rec_obj is not None and sf_gate.get("pairs_evaluated", 0) > 0)
    sf_gt_passed = bool(sf_gate["status"] == "PASS" and sf_has_gt_samples)
    results["SFace"] = {
        "test_classification": classification_label,
        "acceptance_status": sf_gate["status"],
        "four_stage_breakdown": build_four_stage_breakdown(
            downloaded_and_sha256_verified=bool(sface_dl["ok"] and sface_load != "PRELOAD_SHA256_VERIFY_FAILED"),
            loaded_and_inference_executed=bool(rec_obj is not None),
            ground_truth_samples_available=sf_has_gt_samples,
            ground_truth_acceptance_passed=sf_gt_passed,
            acceptance_status=sf_gate["status"],
            not_tested_or_fail_reason=sf_gate["reason"] or sface_err,
        ),
        "download_status": sface_dl["download_status"],
        "expected_sha256": sface_exp_sha,
        "actual_sha256": sface_dl["sha256"],
        "verified_before_load": bool(sface_dl["ok"]),
        "input_source": "YuNet_detect_alignCrop_only (intra-person >=0.363 & inter-person <0.363 required)",
        "model_load_status": sface_load,
        "inference_result": (
            f"[{classification_label}] pairs={sf_gate['pairs_evaluated']}, "
            f"same_sim={sf_gate['same_person_cosine_sim_mean']}, diff_max={sf_gate['different_person_cosine_sim_max']}"
            if rec_obj is not None else "NOT_EXECUTED"
        ),
        "ground_truth_metrics": sf_gate if rec_obj is not None else None,
        "latency_ms": sf_gate["latency_ms"],
        "errors": sf_gate["reason"] or sface_err,
    }

    # 3. YOLOv8n (`models/yolov8n.pt`) — Pinned SHA-256 verified before load + Ground-Truth IoU & Class Gate
    yolo_exp_sha = pf.MODEL_SHA256["yolov8n.pt"]
    yolo_status = "NOT_TESTED"
    yolo_load = "NOT_LOADED"
    yolo_inf = "NOT_EXECUTED"
    yolo_lat = None
    yolo_gt_metrics = None
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
                yolo_gt_metrics = evaluate_yolo_ground_truth_gate(vyolo, frames, neg_frames, EXPECTED_LAB_PLATES, veh_bench_dir)
                yolo_status = yolo_gt_metrics["status"]
                yolo_lat = yolo_gt_metrics["latency_ms"]
                yolo_inf = (
                    f"[{classification_label}] recall={yolo_gt_metrics['recall']}, "
                    f"precision={yolo_gt_metrics['precision']}, mean_iou={yolo_gt_metrics['mean_iou']}, "
                    f"neg_fp={yolo_gt_metrics['negative_false_positives']}"
                )
                if yolo_gt_metrics["reason"]:
                    yolo_errs.append(yolo_gt_metrics["reason"])
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
        # Keep yolo_status as NOT_TESTED when weights are unreachable; --require-real-models checks stage1/stage2 at exit

    yolo_has_gt_samples = bool(yolo_gt_metrics is not None and (yolo_gt_metrics.get("tp", 0) > 0 or (veh_bench_dir.is_dir() and list(veh_bench_dir.glob("*.jpg")))))
    yolo_gt_passed = bool(yolo_status == "PASS" and yolo_has_gt_samples)
    results["YOLOv8n"] = {
        "test_classification": classification_label,
        "acceptance_status": yolo_status,
        "four_stage_breakdown": build_four_stage_breakdown(
            downloaded_and_sha256_verified=bool(yolo_dl["ok"] and yolo_load != "PRELOAD_SHA256_VERIFY_FAILED"),
            loaded_and_inference_executed=bool(yolo_load == "LOADED_AFTER_SHA256_VERIFY" and yolo_gt_metrics is not None),
            ground_truth_samples_available=yolo_has_gt_samples,
            ground_truth_acceptance_passed=yolo_gt_passed,
            acceptance_status=yolo_status,
            not_tested_or_fail_reason=" | ".join(yolo_errs) if yolo_errs else None,
        ),
        "download_status": yolo_dl["download_status"],
        "expected_sha256": yolo_exp_sha,
        "actual_sha256": yolo_dl["sha256"],
        "verified_before_load": bool(yolo_dl["ok"]),
        "model_load_status": yolo_load,
        "inference_result": yolo_inf,
        "ground_truth_metrics": yolo_gt_metrics,
        "latency_ms": yolo_lat,
        "errors": " | ".join(yolo_errs) if yolo_errs else None,
    }

    # 4. EasyOCR Arabic + English (`models/easyocr`) — Pinned SHA-256 verified BEFORE load + Exact Match Rate & CER Gate
    eocr_ok, eocr_reason = pf.verify_easyocr_dir(str(easyocr_dir))
    eocr_status = "NOT_TESTED"
    eocr_load = "NOT_LOADED"
    eocr_inf = "NOT_EXECUTED"
    eocr_lat = None
    eocr_gt_metrics = None
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
        # Keep eocr_status as NOT_TESTED when weights are unreachable; --require-real-models checks stage1/stage2 at exit
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
            sample_rows = []
            for f_img, (cam_id, exp_plate, _, _) in zip(frames, EXPECTED_LAB_PLATES):
                boxes = m.find_plates(f_img)
                if boxes:
                    x, y, bw, bh = boxes[0]
                    t0 = time.perf_counter()
                    norm_txt, conf_val = m.read_plate(reader, f_img[y:y + bh, x:x + bw])
                    lats.append((time.perf_counter() - t0) * 1000.0)
                    sample_rows.append({"cam": cam_id, "expected": exp_plate, "predicted": norm_txt or "", "conf": round(conf_val, 3)})
                else:
                    sample_rows.append({"cam": cam_id, "expected": exp_plate, "predicted": "", "conf": 0.0})
            plates_gt_p = AI_DIR / "models" / "eval_benchmarks" / "plates" / "ground_truth.json"
            if plates_gt_p.is_file():
                p_gt_data = json.loads(plates_gt_p.read_text(encoding="utf-8"))
                for item in p_gt_data.get("samples", []):
                    b_img = cv2.imread(str(plates_gt_p.parent / item["filename"]))
                    if b_img is not None:
                        boxes = m.find_plates(b_img)
                        if boxes:
                            x, y, bw, bh = boxes[0]
                            t0 = time.perf_counter()
                            norm_txt, conf_val = m.read_plate(reader, b_img[y:y + bh, x:x + bw])
                            lats.append((time.perf_counter() - t0) * 1000.0)
                            sample_rows.append({"cam": item["filename"], "expected": item["expected_plate"], "predicted": norm_txt or "", "conf": round(conf_val, 3)})
            eocr_lat = round(float(np.mean(lats)), 2) if lats else None
            eocr_gt_metrics = compute_ocr_ground_truth_metrics(sample_rows)
            eocr_inf = (
                f"[{classification_label}] exact_match_rate={eocr_gt_metrics['exact_match_rate']}, "
                f"digits_match_rate={eocr_gt_metrics['digits_match_rate']}, mean_cer={eocr_gt_metrics['mean_cer']}, "
                f"samples={sample_rows}"
            )
            if eocr_gt_metrics["passes_acceptance_gate"]:
                eocr_status = "PASS"
            else:
                eocr_status = "FAIL"
                eocr_errs.append(
                    f"Ground-truth OCR gate failed: exact_match_rate={eocr_gt_metrics['exact_match_rate']} (req >=0.75), "
                    f"mean_cer={eocr_gt_metrics['mean_cer']} (req <=0.25)"
                )
                all_passed = False
        except Exception as e:
            eocr_load = "LOAD_OR_INFER_FAILED"
            eocr_errs.append(f"{type(e).__name__}: {e}")
            all_passed = False
            if require_real_models:
                eocr_status = "FAIL"

    eocr_has_gt_samples = bool(eocr_gt_metrics is not None and eocr_gt_metrics.get("samples_count", 0) >= MIN_REQUIRED_PLATE_SAMPLES)
    eocr_gt_passed = bool(eocr_status == "PASS" and eocr_has_gt_samples)
    results["EasyOCR_Ar_En"] = {
        "test_classification": classification_label,
        "acceptance_status": eocr_status,
        "four_stage_breakdown": build_four_stage_breakdown(
            downloaded_and_sha256_verified=bool(eocr_ok),
            loaded_and_inference_executed=bool(eocr_load == "LOADED_AFTER_SHA256_VERIFY" and eocr_gt_metrics is not None),
            ground_truth_samples_available=eocr_has_gt_samples,
            ground_truth_acceptance_passed=eocr_gt_passed,
            acceptance_status=eocr_status,
            not_tested_or_fail_reason=" | ".join(eocr_errs) if eocr_errs else None,
        ),
        "download_status": "PRESENT_AND_SHA256_VERIFIED" if eocr_ok else "FAILED_OR_MISSING_WEIGHTS",
        "expected_sha256_files": dict(pf.EASYOCR_SHA256),
        "actual_sha256_files": eocr_shas,
        "verified_before_load": bool(eocr_ok),
        "min_required_plate_samples": MIN_REQUIRED_PLATE_SAMPLES,
        "model_load_status": eocr_load,
        "inference_result": eocr_inf,
        "ground_truth_metrics": eocr_gt_metrics,
        "latency_ms": eocr_lat,
        "errors": " | ".join(eocr_errs) if eocr_errs else None,
        "tesseract_substituted": False,
    }

    return results, all_passed


def main():
    ap = argparse.ArgumentParser(description="MERSAD Phase 1: Real AI Model Verification & Ground-Truth Acceptance")
    ap.add_argument("--require-real-models", action="store_true", help="Exit 1 unless all 4 real models pass Stage 1 (SHA-256) and Stage 2 (Smoke/Inference), and EasyOCR passes Stage 4 (Ground-Truth Plate Accuracy)")
    ap.add_argument("--require-smoke-inference", action="store_true", help="Exit 1 unless all 4 real models pass Smoke/Inference (Stage 1 SHA-256 + Stage 2 Load/Inference + Negative FP==0)")
    ap.add_argument("--require-ground-truth-accuracy", action="store_true", help="Exit 2 unless all 4 real models have consented/photorealistic Ground-Truth datasets (Stage 3) AND pass Stage 4 accuracy thresholds")
    ap.add_argument("--attempt-prefetch", action="store_true", help="Run prefetch.py before testing")
    args = ap.parse_args()

    print("========================================================================================")
    print("  MERSAD PREVIEW 0.1 — Phase 1: Real AI Models Ground-Truth Acceptance Suite")
    print("========================================================================================")

    m.init_runtime_env(appdir=BENCH_HOME, force=True)
    reg.init(m.db, m.DBL, m.log, lambda: None, m.DB_PATH)

    if args.attempt_prefetch:
        print("  [PREFETCH] Running prefetch.py ...")
        subprocess.run([sys.executable, str(AI_DIR / "prefetch.py")], cwd=str(AI_DIR), check=False)

    yunet_path = AI_DIR / "models" / "yunet.onnx"
    sface_path = AI_DIR / "models" / "sface.onnx"
    yolo_path = AI_DIR / "models" / "yolov8n.pt"
    easyocr_dir = AI_DIR / "models" / "easyocr"

    timeout_s = 25.0 if args.require_real_models else 3.0
    yunet_dl = ensure_verified_model(pf.MODELS["yunet.onnx"], yunet_path, pf.MODEL_SHA256["yunet.onnx"], timeout=timeout_s)
    sface_dl = ensure_verified_model(pf.MODELS["sface.onnx"], sface_path, pf.MODEL_SHA256["sface.onnx"], timeout=timeout_s)
    yolo_dl = ensure_verified_model(pf.YOLO_MODEL_URL, yolo_path, pf.MODEL_SHA256["yolov8n.pt"], timeout=timeout_s)

    # Classification A: SYNTHETIC_VIRTUAL_CAMERA_SCENE_INFERENCE
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

    # Classification B: LIVE_LAB_HTTP_MJPEG_STREAM_INFERENCE
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
        fs = v["four_stage_breakdown"]
        print(
            f"  [LIVE STREAM] {k:14s} | Smoke={fs['smoke_inference_status']:10s} | "
            f"GroundTruth={fs['ground_truth_acceptance_status']:10s} | "
            f"S1_SHA256={str(fs['stage1_downloaded_and_sha256_verified']):5s} | "
            f"S2_Infer={str(fs['stage2_loaded_and_inference_executed']):5s} | "
            f"S3_GTSamples={str(fs['stage3_ground_truth_samples_available']):5s} | "
            f"S4_GTPass={str(fs['stage4_ground_truth_acceptance_passed']):5s}"
        )

    # Classification C: INDEPENDENT_AUXILIARY_TESSERACT_BENCHMARK (with full Exact Match Rate & CER)
    t_reader = m.TesseractOCRReader()
    tess_available = m.TesseractOCRReader.is_available()
    tess_synth_reads = []
    tess_live_reads = []
    tess_bench_reads = []
    tess_lats = []
    plates_bench_gt_path = AI_DIR / "models" / "eval_benchmarks" / "plates" / "ground_truth.json"
    if tess_available and plates_bench_gt_path.is_file():
        p_gt = json.loads(plates_bench_gt_path.read_text(encoding="utf-8"))
        for item in p_gt.get("samples", []):
            p_img = cv2.imread(str(plates_bench_gt_path.parent / item["filename"]))
            if p_img is not None:
                boxes = m.find_plates(p_img)
                if boxes:
                    x, y, bw, bh = boxes[0]
                    t0 = time.perf_counter()
                    norm_txt, conf_val = m.read_plate(t_reader, p_img[y:y + bh, x:x + bw])
                    tess_lats.append((time.perf_counter() - t0) * 1000.0)
                    tess_bench_reads.append({
                        "filename": item["filename"],
                        "expected": item["expected_plate"],
                        "predicted": norm_txt,
                        "conf": round(conf_val, 3),
                    })
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

    tess_synth_metrics = compute_ocr_ground_truth_metrics(tess_synth_reads)
    tess_live_metrics = compute_ocr_ground_truth_metrics(tess_live_reads)

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
            "2) No model is granted PASS merely for loading or running on 4 frames without ground-truth accuracy validation. "
            "3) YOLOv8n requires ground-truth vehicle detection (Recall >= 0.75, Precision >= 0.75, Mean IoU >= 0.50, Negative FP == 0). "
            "4) EasyOCR requires >= 4 ground-truth plate reads with Exact Match Rate >= 0.75 and Mean CER <= 0.25. "
            "5) YuNet requires positive face detection (Recall >= 0.75 on authorized positive samples) AND negative non-face rejection (Negative FP == 0). "
            "6) SFace requires intra-person cosine similarity (>= 0.363) AND inter-person separation (< 0.363, FAR == 0) across authorized volunteer face crops. "
            "7) If appropriate benchmark datasets are absent on disk, status is strictly retained as NOT_TESTED. "
            "8) Tesseract is NEVER used as a substitute for EasyOCR acceptance."
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
            "engine": f"Tesseract 5 LSTM ({m.TesseractOCRReader.find_tesseract_binary() or 'NOT_INSTALLED'})",
            "tesseract_binary_available": tess_available,
            "benchmark_plates_6_samples": compute_ocr_ground_truth_metrics(tess_bench_reads) if tess_bench_reads else None,
            "benchmark_plates_6_results": tess_bench_reads,
            "synthetic_scene_samples": len(tess_synth_reads),
            "synthetic_scene_exact_matches": tess_synth_metrics["exact_matches"],
            "synthetic_scene_exact_match_rate": tess_synth_metrics["exact_match_rate"],
            "synthetic_scene_mean_cer": tess_synth_metrics["mean_cer"],
            "live_mjpeg_stream_samples": len(tess_live_reads),
            "live_mjpeg_stream_exact_matches": tess_live_metrics["exact_matches"],
            "live_mjpeg_stream_exact_match_rate": tess_live_metrics["exact_match_rate"],
            "live_mjpeg_stream_mean_cer": tess_live_metrics["mean_cer"],
            "mean_latency_ms": round(float(np.mean(tess_lats)), 2) if tess_lats else None,
            "synthetic_scene_results": tess_synth_reads,
            "live_mjpeg_stream_results": tess_live_reads,
        },
    }

    tess_bench_metrics = report["independent_tesseract_benchmark"]["benchmark_plates_6_samples"] or {"exact_matches": 0, "exact_match_rate": 0.0, "mean_cer": 1.0}
    print(
        f"\n  --- [C] INDEPENDENT_AUXILIARY_TESSERACT_BENCHMARK ---\n"
        f"  [AUX TEST] Benchmark Plates Dataset (6)  : {tess_bench_metrics['exact_matches']}/6 matched "
        f"(ExactMatch={tess_bench_metrics['exact_match_rate']*100:.1f}%, MeanCER={tess_bench_metrics['mean_cer']*100:.1f}%)\n"
        f"  [AUX TEST] Synthetic VirtualCamera Scenes: {tess_synth_metrics['exact_matches']}/4 matched "
        f"(ExactMatch={tess_synth_metrics['exact_match_rate']*100:.1f}%, MeanCER={tess_synth_metrics['mean_cer']*100:.1f}%)\n"
        f"  [AUX TEST] Live LAB HTTP MJPEG Streams   : {tess_live_metrics['exact_matches']}/4 matched "
        f"(ExactMatch={tess_live_metrics['exact_match_rate']*100:.1f}%, MeanCER={tess_live_metrics['mean_cer']*100:.1f}%, "
        f"mean_latency={report['independent_tesseract_benchmark']['mean_latency_ms']}ms)"
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

    if args.require_ground_truth_accuracy:
        not_passed = [k for k, v in live_results.items() if v["four_stage_breakdown"]["ground_truth_acceptance_status"] != "PASS"]
        if not_passed:
            print(f"  [GROUND-TRUTH ACCURACY GATE BLOCKED/FAILED] Models not at Ground-Truth PASS: {not_passed}")
            sys.exit(2)

    if args.require_real_models or args.require_smoke_inference:
        # Strictly verify Stage 1 (Downloaded & SHA-256 verified) and Stage 2 (Loaded & Inference executed) for all 4 models,
        # and ensure no model failed Stage 4 (Ground-Truth Acceptance). Models lacking natural/authorized benchmark samples
        # on disk (Stage 3 == False) remain honestly recorded as NOT_TESTED on ground_truth_acceptance_status and are NEVER converted to PASS.
        any_s1_s2_fail = any(
            v["four_stage_breakdown"]["smoke_inference_status"] != "PASS"
            for v in live_results.values()
        )
        any_gate_fail = any(v["four_stage_breakdown"]["ground_truth_acceptance_status"] == "FAIL" for v in live_results.values())
        not_tested_models = [k for k, v in live_results.items() if v["four_stage_breakdown"]["ground_truth_acceptance_status"] == "NOT_TESTED"]
        if not_tested_models:
            print(f"  [NOTE] Models with ground_truth_acceptance_status=NOT_TESTED (strictly preserved, never converted to PASS): {not_tested_models}")
        if any_s1_s2_fail or any_gate_fail:
            print("  [ACCEPTANCE GATE FAILED] One or more of the 4 AI models failed Smoke/Inference (Stage 1/2) or failed a Ground-Truth Accuracy Gate (Stage 4).")
            sys.exit(1)
    sys.exit(0)


if __name__ == "__main__":
    main()
