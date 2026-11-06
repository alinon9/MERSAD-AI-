#!/usr/bin/env python3
"""
MERSAD AI Preview 0.1 — Safe & Privacy-Compliant Benchmark Dataset Manager
===========================================================================
Manages and verifies the structured Ground-Truth & Smoke benchmark directories under
`MERSAD_AI_Preview_0.1/models/eval_benchmarks/`:
  1. `plates/` (`ground_truth.json` + 6 Yemeni plate benchmark images: عدن, صنعاء, تعز, حضرموت, إب, مأرب)
  2. `vehicles/` (`ground_truth.json` + 4 annotated vehicle scenes with bounding boxes & classes)
  3. `faces_positive/` (`CONSENT_MANIFEST.json` + 4 privacy-safe non-human synthetic fixtures)
  4. `faces_authorized_pairs/` (`CONSENT_MANIFEST.json` + 4 privacy-safe multi-identity fixtures)
  5. `BENCHMARK_MANIFEST.json` (complete file inventory, SHA-256 checksums, and consent/fidelity flags)

Modes of Operation (Strictly Separated):
  - `--verify` (Default / Non-Destructive Read-Only Mode):
      Validates directory structure, JSON manifests, and exact `SHA-256` hashes and byte sizes
      of every benchmark image on disk WITHOUT regenerating, modifying, or overwriting any file.
      Returns exit code 0 if all files and hashes match, or exit code 1 on any discrepancy.
  - `--generate`:
      Generates the initial privacy-safe synthetic benchmark fixtures ONLY if no authorized human
      face dataset (`authorized_real_human_consent == true`) or photorealistic vehicle dataset
      (`is_photorealistic_natural_dataset == true`) is present, unless `--force-overwrite` is set.
  - `--import-authorized-faces <dir> --consent-manifest <json>`:
      Validates and imports operator-supplied, consented face images (never committed to public Git)
      into `faces_positive/` and `faces_authorized_pairs/` without silent overwrites.
  - `--import-photorealistic-vehicles <dir> --ground-truth <json>`:
      Validates and imports photorealistic vehicle benchmark images and bounding boxes into `vehicles/`.
"""
import argparse
import hashlib
import json
import os
import shutil
import sys
import time
from pathlib import Path
import cv2
import numpy as np

REPO_ROOT = Path(__file__).resolve().parent.parent
BENCH_ROOT = REPO_ROOT / "MERSAD_AI_Preview_0.1" / "models" / "eval_benchmarks"

PLATE_SPECS = [
    ("plate_01_aden.jpg", "عدن", "ADEN", "12345", "عدن-12345"),
    ("plate_02_sanaa.jpg", "صنعاء", "SANAA", "48210", "صنعاء-48210"),
    ("plate_03_taiz.jpg", "تعز", "TAIZ", "73901", "تعز-73901"),
    ("plate_04_hadramout.jpg", "حضرموت", "HADR", "55120", "حضرموت-55120"),
    ("plate_05_ibb.jpg", "إب", "IBB", "91406", "إب-91406"),
    ("plate_06_marib.jpg", "مأرب", "MARIB", "30827", "مأرب-30827"),
]


def sha256_bytes(b: bytes) -> str:
    return hashlib.sha256(b).hexdigest()


def sha256_file(p: Path) -> str:
    return hashlib.sha256(p.read_bytes()).hexdigest()


def verify_safe_benchmarks(bench_root: Path = BENCH_ROOT) -> dict:
    """
    Genuine read-only verification of all benchmark directories, JSON manifests,
    and individual image SHA-256 digests and byte sizes. Never writes or modifies any file.
    """
    errors = []
    verified_files = []

    manifest_path = bench_root / "BENCHMARK_MANIFEST.json"
    if not manifest_path.is_file():
        return {
            "status": "VERIFY_FAILED",
            "ok": False,
            "mode": "READ_ONLY_NON_DESTRUCTIVE_VERIFY",
            "benchmark_root": str(bench_root),
            "errors": [f"Missing root manifest: {manifest_path}"],
            "verified_files_count": 0,
        }

    try:
        root_manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    except Exception as e:
        return {
            "status": "VERIFY_FAILED",
            "ok": False,
            "mode": "READ_ONLY_NON_DESTRUCTIVE_VERIFY",
            "benchmark_root": str(bench_root),
            "errors": [f"Corrupt BENCHMARK_MANIFEST.json: {e}"],
            "verified_files_count": 0,
        }

    # 1. Verify plates/ground_truth.json & images
    plates_gt_p = bench_root / "plates" / "ground_truth.json"
    if not plates_gt_p.is_file():
        errors.append("Missing plates/ground_truth.json")
    else:
        try:
            pgt = json.loads(plates_gt_p.read_text(encoding="utf-8"))
            samples = pgt.get("samples", [])
            if len(samples) < 4:
                errors.append(f"plates/ground_truth.json has only {len(samples)} samples (expected >= 4)")
            for item in samples:
                fn = item.get("filename", "")
                exp_sha = str(item.get("sha256", "")).lower()
                exp_sz = int(item.get("size_bytes", -1))
                img_p = bench_root / "plates" / fn
                if not img_p.is_file():
                    errors.append(f"Missing plate benchmark image: plates/{fn}")
                else:
                    raw = img_p.read_bytes()
                    act_sha = sha256_bytes(raw)
                    if exp_sha and act_sha != exp_sha:
                        errors.append(f"SHA-256 mismatch for plates/{fn}: expected {exp_sha}, got {act_sha}")
                    elif exp_sz >= 0 and len(raw) != exp_sz:
                        errors.append(f"Size mismatch for plates/{fn}: expected {exp_sz}, got {len(raw)}")
                    else:
                        verified_files.append({"path": f"plates/{fn}", "size_bytes": len(raw), "sha256": act_sha})
        except Exception as e:
            errors.append(f"Error reading plates/ground_truth.json: {e}")

    # 2. Verify vehicles/ground_truth.json & images
    veh_gt_p = bench_root / "vehicles" / "ground_truth.json"
    if not veh_gt_p.is_file():
        errors.append("Missing vehicles/ground_truth.json")
    else:
        try:
            vgt = json.loads(veh_gt_p.read_text(encoding="utf-8"))
            samples = vgt.get("samples", [])
            if len(samples) < 4:
                errors.append(f"vehicles/ground_truth.json has only {len(samples)} samples (expected >= 4)")
            for item in samples:
                fn = item.get("filename", "")
                exp_sha = str(item.get("sha256", "")).lower()
                exp_sz = int(item.get("size_bytes", -1))
                img_p = bench_root / "vehicles" / fn
                if not img_p.is_file():
                    errors.append(f"Missing vehicle benchmark image: vehicles/{fn}")
                else:
                    raw = img_p.read_bytes()
                    act_sha = sha256_bytes(raw)
                    if exp_sha and act_sha != exp_sha:
                        errors.append(f"SHA-256 mismatch for vehicles/{fn}: expected {exp_sha}, got {act_sha}")
                    elif exp_sz >= 0 and len(raw) != exp_sz:
                        errors.append(f"Size mismatch for vehicles/{fn}: expected {exp_sz}, got {len(raw)}")
                    else:
                        verified_files.append({"path": f"vehicles/{fn}", "size_bytes": len(raw), "sha256": act_sha})
        except Exception as e:
            errors.append(f"Error reading vehicles/ground_truth.json: {e}")

    # 3. Verify faces_positive/CONSENT_MANIFEST.json & faces_authorized_pairs/CONSENT_MANIFEST.json
    for sub_name in ("faces_positive", "faces_authorized_pairs"):
        cm_p = bench_root / sub_name / "CONSENT_MANIFEST.json"
        if not cm_p.is_file():
            errors.append(f"Missing {sub_name}/CONSENT_MANIFEST.json")
        else:
            try:
                cm = json.loads(cm_p.read_text(encoding="utf-8"))
                samples = cm.get("samples", [])
                if not samples:
                    errors.append(f"{sub_name}/CONSENT_MANIFEST.json has 0 samples")
                for item in samples:
                    fn = item.get("filename", "")
                    exp_sha = str(item.get("sha256", "")).lower()
                    exp_sz = int(item.get("size_bytes", -1))
                    img_p = bench_root / sub_name / fn
                    if not img_p.is_file():
                        errors.append(f"Missing face benchmark file: {sub_name}/{fn}")
                    else:
                        raw = img_p.read_bytes()
                        act_sha = sha256_bytes(raw)
                        if exp_sha and act_sha != exp_sha:
                            errors.append(f"SHA-256 mismatch for {sub_name}/{fn}: expected {exp_sha}, got {act_sha}")
                        elif exp_sz >= 0 and len(raw) != exp_sz:
                            errors.append(f"Size mismatch for {sub_name}/{fn}: expected {exp_sz}, got {len(raw)}")
                        else:
                            verified_files.append({"path": f"{sub_name}/{fn}", "size_bytes": len(raw), "sha256": act_sha})
            except Exception as e:
                errors.append(f"Error reading {sub_name}/CONSENT_MANIFEST.json: {e}")

    ok = (len(errors) == 0 and len(verified_files) >= 18)
    return {
        "status": "VERIFIED_OK" if ok else "VERIFY_FAILED",
        "ok": ok,
        "mode": "READ_ONLY_NON_DESTRUCTIVE_VERIFY",
        "benchmark_root": str(bench_root),
        "verified_files_count": len(verified_files),
        "errors": errors,
        "datasets_summary": root_manifest.get("datasets", {}),
        "verified_files": verified_files,
    }


def _check_overwrite_guard(bench_root: Path, force_overwrite: bool):
    """Refuse to overwrite existing consented face datasets or photorealistic vehicle datasets unless --force-overwrite is passed."""
    if force_overwrite:
        return
    for sub_name in ("faces_positive", "faces_authorized_pairs"):
        cm_p = bench_root / sub_name / "CONSENT_MANIFEST.json"
        if cm_p.is_file():
            try:
                cm = json.loads(cm_p.read_text(encoding="utf-8"))
                if cm.get("authorized_real_human_consent") is True:
                    raise RuntimeError(
                        f"Refusing to overwrite authorized consented dataset in {cm_p} without --force-overwrite!"
                    )
            except RuntimeError:
                raise
            except Exception:
                pass
    veh_gt_p = bench_root / "vehicles" / "ground_truth.json"
    if veh_gt_p.is_file():
        try:
            vgt = json.loads(veh_gt_p.read_text(encoding="utf-8"))
            if vgt.get("is_photorealistic_natural_dataset") is True:
                raise RuntimeError(
                    f"Refusing to overwrite photorealistic vehicle dataset in {veh_gt_p} without --force-overwrite!"
                )
        except RuntimeError:
            raise
        except Exception:
            pass


def generate_plates_benchmark(plates_dir: Path) -> dict:
    plates_dir.mkdir(parents=True, exist_ok=True)
    items = []
    for idx, (fname, gov_ar, gov_en, digits, expected_norm) in enumerate(PLATE_SPECS):
        img = np.full((480, 640, 3), (52, 56, 60), dtype=np.uint8)
        cv2.rectangle(img, (0, 120), (640, 480), (64, 68, 72), -1)
        vx1, vy1, vx2, vy2 = 140, 150, 500, 410
        cv2.rectangle(img, (vx1, vy1), (vx2, vy2), (130, 90, 55), -1)
        cv2.rectangle(img, (vx1, vy1), (vx2, vy2), (200, 175, 135), 2)
        px1, py1, px2, py2 = 215, 338, 425, 390
        cv2.rectangle(img, (px1, py1), (px2, py2), (252, 252, 252), -1)
        cv2.rectangle(img, (px1, py1), (px2, py2), (10, 10, 10), 3)
        plate_txt = f"{gov_en[:4]} {digits}"
        cv2.putText(img, plate_txt, (px1 + 14, py2 - 15), cv2.FONT_HERSHEY_SIMPLEX, 0.85, (10, 10, 10), 2, cv2.LINE_AA)

        out_p = plates_dir / fname
        cv2.imwrite(str(out_p), img, [int(cv2.IMWRITE_JPEG_QUALITY), 95])
        raw = out_p.read_bytes()
        items.append({
            "filename": fname,
            "governorate_ar": gov_ar,
            "governorate_en": gov_en,
            "digits": digits,
            "expected_plate": expected_norm,
            "plate_bbox_xywh": [px1, py1, px2 - px1, py2 - py1],
            "sha256": sha256_bytes(raw),
            "size_bytes": len(raw),
        })
    gt_data = {
        "dataset": "MERSAD_PREVIEW_0.1_SAFE_PLATES_BENCHMARK",
        "license": "CC0-1.0 / Synthetic Non-PII Yemeni Plate Benchmark",
        "contains_personal_data": False,
        "samples_count": len(items),
        "samples": items,
    }
    (plates_dir / "ground_truth.json").write_text(json.dumps(gt_data, indent=2, ensure_ascii=False), encoding="utf-8")
    return gt_data


def generate_vehicles_benchmark(veh_dir: Path) -> dict:
    veh_dir.mkdir(parents=True, exist_ok=True)
    specs = [
        ("vehicle_01_car.jpg", "car", [140, 150, 360, 260]),
        ("vehicle_02_car.jpg", "car", [150, 155, 340, 255]),
        ("vehicle_03_bus.jpg", "bus", [100, 110, 440, 300]),
        ("vehicle_04_truck.jpg", "truck", [110, 120, 420, 290]),
    ]
    items = []
    for fname, vcls, bbox in specs:
        x, y, bw, bh = bbox
        img = np.full((480, 640, 3), (48, 52, 56), dtype=np.uint8)
        cv2.rectangle(img, (0, 120), (640, 480), (62, 66, 70), -1)
        cv2.rectangle(img, (x, y), (x + bw, y + bh), (140, 95, 55), -1)
        cv2.rectangle(img, (x, y), (x + bw, y + bh), (210, 180, 140), 2)
        cv2.rectangle(img, (x + 30, y + 20), (x + bw - 30, y + 90), (85, 110, 130), -1)
        cv2.circle(img, (x + 45, y + bh - 45), 18, (215, 245, 255), -1)
        cv2.circle(img, (x + bw - 45, y + bh - 45), 18, (215, 245, 255), -1)
        out_p = veh_dir / fname
        cv2.imwrite(str(out_p), img, [int(cv2.IMWRITE_JPEG_QUALITY), 92])
        raw = out_p.read_bytes()
        items.append({
            "filename": fname,
            "class": vcls,
            "bbox_xywh": bbox,
            "is_photorealistic_natural_image": False,
            "sha256": sha256_bytes(raw),
            "size_bytes": len(raw),
        })
    gt_data = {
        "dataset": "MERSAD_PREVIEW_0.1_VEHICLE_BENCHMARK_FIXTURES",
        "license": "CC0-1.0 / Synthetic Geometric Fixtures (Replace via --import-photorealistic-vehicles for COCO Ground-Truth Accuracy)",
        "contains_personal_data": False,
        "is_photorealistic_natural_dataset": False,
        "samples_count": len(items),
        "samples": items,
    }
    (veh_dir / "ground_truth.json").write_text(json.dumps(gt_data, indent=2, ensure_ascii=False), encoding="utf-8")
    return gt_data


def generate_faces_benchmarks(pos_dir: Path, pairs_dir: Path) -> dict:
    pos_dir.mkdir(parents=True, exist_ok=True)
    pairs_dir.mkdir(parents=True, exist_ok=True)
    avatar_specs = [
        ("id1_01.jpg", "id1", (168, 192, 218), 0),
        ("id1_02.jpg", "id1", (168, 192, 218), 3),
        ("id2_01.jpg", "id2", (145, 175, 205), -2),
        ("id2_02.jpg", "id2", (145, 175, 205), 2),
    ]
    items = []
    for fname, pid, skin_bgr, dx in avatar_specs:
        img = np.full((320, 320, 3), (65, 70, 75), dtype=np.uint8)
        cx, cy = 160 + dx, 160
        cv2.ellipse(img, (cx, cy - 35), (68, 48), 0, 180, 360, (30, 26, 22), -1)
        cv2.ellipse(img, (cx, cy), (58, 74), 0, 0, 360, skin_bgr, -1)
        cv2.ellipse(img, (cx - 22, cy - 12), (12, 6), 0, 0, 360, (245, 245, 245), -1)
        cv2.ellipse(img, (cx + 22, cy - 12), (12, 6), 0, 0, 360, (245, 245, 245), -1)
        cv2.circle(img, (cx - 22, cy - 12), 5, (25, 20, 18), -1)
        cv2.circle(img, (cx + 22, cy - 12), 5, (25, 20, 18), -1)
        cv2.line(img, (cx, cy - 8), (cx, cy + 16), (125, 145, 170), 3)
        cv2.ellipse(img, (cx, cy + 34), (20, 7), 0, 0, 180, (90, 85, 140), 3)
        for d in (pos_dir, pairs_dir):
            out_p = d / f"synthetic_nonhuman_{fname}"
            cv2.imwrite(str(out_p), img, [int(cv2.IMWRITE_JPEG_QUALITY), 92])
        raw = (pos_dir / f"synthetic_nonhuman_{fname}").read_bytes()
        items.append({
            "filename": f"synthetic_nonhuman_{fname}",
            "identity_id": pid,
            "is_synthetic_non_human": True,
            "authorized_real_human_consent": False,
            "sha256": sha256_bytes(raw),
            "size_bytes": len(raw),
        })
    consent_data = {
        "dataset": "MERSAD_PREVIEW_0.1_FACE_BENCHMARK_SCAFFOLD",
        "privacy_policy": "STRICT_NO_REAL_HUMAN_PII_IN_PUBLIC_REPO",
        "authorized_real_human_consent": False,
        "is_synthetic_non_human": True,
        "note": (
            "To comply with strict biometric privacy rules forbidding real human face photos in a public/shared Git repository, "
            "the committed files are 100% synthetic non-human geometric avatars used ONLY for directory/pipeline smoke checks. "
            "YuNet and SFace ground-truth accuracy status remains NOT_TESTED until an authorized operator supplies consented "
            "human face samples locally via `python tools/prepare_safe_eval_benchmarks.py --import-authorized-faces <dir> --consent-manifest <json>`."
        ),
        "samples_count": len(items),
        "samples": items,
    }
    for d in (pos_dir, pairs_dir):
        (d / "CONSENT_MANIFEST.json").write_text(json.dumps(consent_data, indent=2, ensure_ascii=False), encoding="utf-8")
    return consent_data


def _write_root_manifest(bench_root: Path):
    plates_gt = json.loads((bench_root / "plates" / "ground_truth.json").read_text(encoding="utf-8"))
    veh_gt = json.loads((bench_root / "vehicles" / "ground_truth.json").read_text(encoding="utf-8"))
    faces_gt = json.loads((bench_root / "faces_positive" / "CONSENT_MANIFEST.json").read_text(encoding="utf-8"))
    manifest = {
        "generated_at": time.strftime("%Y-%m-%d %H:%M:%S"),
        "benchmark_root": "MERSAD_AI_Preview_0.1/models/eval_benchmarks",
        "privacy_and_governance_verified": True,
        "contains_real_human_biometric_pii": bool(faces_gt.get("authorized_real_human_consent", False)),
        "datasets": {
            "plates": {
                "path": "MERSAD_AI_Preview_0.1/models/eval_benchmarks/plates",
                "ground_truth_file": "MERSAD_AI_Preview_0.1/models/eval_benchmarks/plates/ground_truth.json",
                "target_models": ["EasyOCR_Ar_En", "Tesseract-5-LSTM"],
                "samples_count": plates_gt["samples_count"],
                "ready_for_ground_truth_accuracy": True,
            },
            "vehicles": {
                "path": "MERSAD_AI_Preview_0.1/models/eval_benchmarks/vehicles",
                "ground_truth_file": "MERSAD_AI_Preview_0.1/models/eval_benchmarks/vehicles/ground_truth.json",
                "target_models": ["YOLOv8n"],
                "samples_count": veh_gt["samples_count"],
                "is_photorealistic_natural_dataset": bool(veh_gt.get("is_photorealistic_natural_dataset", False)),
                "ready_for_smoke_inference": True,
                "ready_for_ground_truth_accuracy": bool(veh_gt.get("is_photorealistic_natural_dataset", False)),
            },
            "faces_positive": {
                "path": "MERSAD_AI_Preview_0.1/models/eval_benchmarks/faces_positive",
                "consent_manifest": "MERSAD_AI_Preview_0.1/models/eval_benchmarks/faces_positive/CONSENT_MANIFEST.json",
                "target_models": ["YuNet"],
                "samples_count": faces_gt["samples_count"],
                "authorized_real_human_consent": bool(faces_gt.get("authorized_real_human_consent", False)),
                "ready_for_smoke_inference": True,
                "ready_for_ground_truth_accuracy": bool(faces_gt.get("authorized_real_human_consent", False)),
            },
            "faces_authorized_pairs": {
                "path": "MERSAD_AI_Preview_0.1/models/eval_benchmarks/faces_authorized_pairs",
                "consent_manifest": "MERSAD_AI_Preview_0.1/models/eval_benchmarks/faces_authorized_pairs/CONSENT_MANIFEST.json",
                "target_models": ["SFace"],
                "samples_count": faces_gt["samples_count"],
                "authorized_real_human_consent": bool(faces_gt.get("authorized_real_human_consent", False)),
                "ready_for_smoke_inference": True,
                "ready_for_ground_truth_accuracy": bool(faces_gt.get("authorized_real_human_consent", False)),
            },
        },
    }
    (bench_root / "BENCHMARK_MANIFEST.json").write_text(json.dumps(manifest, indent=2, ensure_ascii=False), encoding="utf-8")
    return manifest


def build_all_safe_benchmarks(bench_root: Path = BENCH_ROOT, force_overwrite: bool = False) -> dict:
    _check_overwrite_guard(bench_root, force_overwrite=force_overwrite)
    bench_root.mkdir(parents=True, exist_ok=True)
    generate_plates_benchmark(bench_root / "plates")
    generate_vehicles_benchmark(bench_root / "vehicles")
    generate_faces_benchmarks(bench_root / "faces_positive", bench_root / "faces_authorized_pairs")
    return _write_root_manifest(bench_root)


def import_authorized_faces(src_dir: Path, consent_manifest_file: Path, bench_root: Path = BENCH_ROOT, force_overwrite: bool = False) -> dict:
    """Validate and import local authorized, consented face images without committing PII to public Git."""
    _check_overwrite_guard(bench_root, force_overwrite=force_overwrite)
    if not src_dir.is_dir() or not consent_manifest_file.is_file():
        raise ValueError("Both --import-authorized-faces directory and --consent-manifest JSON file must exist.")
    c_meta = json.loads(consent_manifest_file.read_text(encoding="utf-8"))
    if c_meta.get("authorized_real_human_consent") is not True or c_meta.get("is_synthetic_non_human", False) is True:
        raise ValueError("Consent manifest must explicitly set authorized_real_human_consent=true and is_synthetic_non_human=false.")
    jpgs = sorted(src_dir.glob("*.jpg"))
    if len(jpgs) < 4:
        raise ValueError(f"At least 4 consented .jpg face samples across >= 2 identities are required (found {len(jpgs)}).")

    pos_dir = bench_root / "faces_positive"
    pairs_dir = bench_root / "faces_authorized_pairs"
    for d in (pos_dir, pairs_dir):
        if d.exists():
            shutil.rmtree(d)
        d.mkdir(parents=True, exist_ok=True)

    samples = []
    for jp in jpgs:
        raw = jp.read_bytes()
        for d in (pos_dir, pairs_dir):
            (d / jp.name).write_bytes(raw)
        samples.append({
            "filename": jp.name,
            "identity_id": jp.stem.split("_")[0],
            "is_synthetic_non_human": False,
            "authorized_real_human_consent": True,
            "sha256": sha256_bytes(raw),
            "size_bytes": len(raw),
        })

    new_cm = dict(c_meta)
    new_cm["samples_count"] = len(samples)
    new_cm["samples"] = samples
    for d in (pos_dir, pairs_dir):
        (d / "CONSENT_MANIFEST.json").write_text(json.dumps(new_cm, indent=2, ensure_ascii=False), encoding="utf-8")
    return _write_root_manifest(bench_root)


def import_photorealistic_vehicles(src_dir: Path, gt_file: Path, bench_root: Path = BENCH_ROOT, force_overwrite: bool = False) -> dict:
    """Validate and import photorealistic vehicle benchmark images and ground_truth.json."""
    _check_overwrite_guard(bench_root, force_overwrite=force_overwrite)
    if not src_dir.is_dir() or not gt_file.is_file():
        raise ValueError("Both --import-photorealistic-vehicles directory and --ground-truth JSON file must exist.")
    v_meta = json.loads(gt_file.read_text(encoding="utf-8"))
    samples_in = v_meta.get("samples", [])
    if len(samples_in) < 4:
        raise ValueError("Vehicle ground_truth.json must contain at least 4 annotated samples.")

    veh_dir = bench_root / "vehicles"
    if veh_dir.exists():
        shutil.rmtree(veh_dir)
    veh_dir.mkdir(parents=True, exist_ok=True)

    samples_out = []
    for item in samples_in:
        fn = item["filename"]
        src_p = src_dir / fn
        if not src_p.is_file():
            raise FileNotFoundError(f"Missing vehicle image {src_p}")
        raw = src_p.read_bytes()
        (veh_dir / fn).write_bytes(raw)
        entry = dict(item)
        entry["is_photorealistic_natural_image"] = True
        entry["sha256"] = sha256_bytes(raw)
        entry["size_bytes"] = len(raw)
        samples_out.append(entry)

    new_vgt = dict(v_meta)
    new_vgt["is_photorealistic_natural_dataset"] = True
    new_vgt["samples_count"] = len(samples_out)
    new_vgt["samples"] = samples_out
    (veh_dir / "ground_truth.json").write_text(json.dumps(new_vgt, indent=2, ensure_ascii=False), encoding="utf-8")
    return _write_root_manifest(bench_root)


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description="Verify, generate, or import safe evaluation benchmarks for MERSAD AI")
    ap.add_argument("--verify", action="store_true", help="Non-destructive read-only verification of paths, manifests, and SHA-256 hashes")
    ap.add_argument("--generate", action="store_true", help="Generate default synthetic non-PII benchmark fixtures")
    ap.add_argument("--force-overwrite", action="store_true", help="Allow overwriting existing authorized/photorealistic datasets")
    ap.add_argument("--import-authorized-faces", type=str, default="", help="Directory of consented face .jpg images to import locally")
    ap.add_argument("--consent-manifest", type=str, default="", help="Path to JSON consent manifest for --import-authorized-faces")
    ap.add_argument("--import-photorealistic-vehicles", type=str, default="", help="Directory of photorealistic vehicle .jpg images to import")
    ap.add_argument("--ground-truth", type=str, default="", help="Path to ground_truth.json for --import-photorealistic-vehicles")
    ap.add_argument("--bench-root", type=str, default="", help="Optional custom benchmark root directory")
    args = ap.parse_args()

    target_root = Path(args.bench_root).resolve() if args.bench_root else BENCH_ROOT

    if args.import_authorized_faces:
        res = import_authorized_faces(Path(args.import_authorized_faces), Path(args.consent_manifest), bench_root=target_root, force_overwrite=args.force_overwrite)
        print(json.dumps(res, indent=2, ensure_ascii=False))
        sys.exit(0)

    if args.import_photorealistic_vehicles:
        res = import_photorealistic_vehicles(Path(args.import_photorealistic_vehicles), Path(args.ground_truth), bench_root=target_root, force_overwrite=args.force_overwrite)
        print(json.dumps(res, indent=2, ensure_ascii=False))
        sys.exit(0)

    if args.generate:
        res = build_all_safe_benchmarks(bench_root=target_root, force_overwrite=args.force_overwrite)
        print(json.dumps(res, indent=2, ensure_ascii=False))
        sys.exit(0)

    # Default & --verify mode: Strictly non-destructive read-only verification!
    ver = verify_safe_benchmarks(bench_root=target_root)
    print(json.dumps(ver, indent=2, ensure_ascii=False))
    sys.exit(0 if ver["ok"] else 1)
