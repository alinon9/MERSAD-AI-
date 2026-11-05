"""Run ONCE with internet: safely downloads every AI model from pinned sources with socket timeouts,
bounded retries, atomic .part files, SHA-256 verification (for OpenCV Zoo ONNX models),
and structural PyTorch ZIP/checkpoint & EasyOCR weight verification so the program and built .exe work fully OFFLINE.
Never overwrites or deletes an existing valid model file if a download fails partway."""
import hashlib, os, shutil, socket, sys, time, urllib.error, urllib.request, uuid, zipfile

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
if BASE_DIR not in sys.path:
    sys.path.insert(0, BASE_DIR)

from mersad_live import (
    MODELS,
    MODEL_SHA256,
    EASYOCR_SHA256,
    MODEL_MIN_BYTES,
    YOLO_MODEL_URL,
    YOLO_RELEASE_VERSION,
    register_trusted_model,
    resolve_compute_device,
    safe_download_model,
    verify_onnx_file,
    verify_yolo_pt_file,
    verify_easyocr_dir,
)

EXPECTED_MIN_BYTES = dict(MODEL_MIN_BYTES)


def download_verified(filename, url, min_bytes=50_000, expected_sha256=None, retries=3, timeout=30.0, target_dir="models", validator_fn=None):
    """Download a model file safely to a temporary .part file, verify size, SHA-256, and structure, then atomically replace target."""
    if validator_fn is None:
        if filename.endswith(".onnx"):
            validator_fn = lambda p: verify_onnx_file(p, expected_sha256=expected_sha256, min_bytes=min_bytes)
        elif filename.endswith(".pt"):
            validator_fn = lambda p: verify_yolo_pt_file(p, expected_sha256=expected_sha256, min_bytes=min_bytes)
    return safe_download_model(
        filename=filename,
        url=url,
        target_dir=target_dir,
        min_bytes=min_bytes,
        expected_sha256=expected_sha256,
        timeout=timeout,
        retries=retries,
        validator_fn=validator_fn,
    )


def prefetch_all_models(models_dir="models", timeout=30.0, retries=3):
    """Download and verify all required AI models (YuNet, SFace, EasyOCR ar+en, YOLOv8n)."""
    os.makedirs(os.path.join(models_dir, "easyocr"), exist_ok=True)

    print("1/3 Face detection + recognition models (OpenCV Zoo ONNX, pinned commit + SHA-256)...")
    for fname, url in MODELS.items():
        download_verified(
            fname,
            url,
            min_bytes=EXPECTED_MIN_BYTES.get(fname, 50_000),
            expected_sha256=MODEL_SHA256.get(fname),
            retries=retries,
            timeout=timeout,
            target_dir=models_dir,
        )

    print("2/3 Plate reading models (EasyOCR Arabic + English)...")
    easy_dir = os.path.join(models_dir, "easyocr")
    ok_easy, reason_easy = verify_easyocr_dir(easy_dir)
    if ok_easy:
        print(f"  [OK] EasyOCR Arabic/English weights already verified in {easy_dir} ({reason_easy})")
    else:
        import easyocr
        dev_info = resolve_compute_device(os.environ.get("MERSAD_DEVICE", "auto"))
        try:
            easyocr.Reader(["ar", "en"], gpu=dev_info["use_gpu"], model_storage_directory=easy_dir, download_enabled=True)
        except TypeError:
            easyocr.Reader(["ar", "en"], gpu=dev_info["use_gpu"], model_storage_directory=easy_dir)
        ok_after, reason_after = verify_easyocr_dir(easy_dir)
        if not ok_after:
            raise RuntimeError(f"EasyOCR model verification failed in {easy_dir}: {reason_after}")
        print(f"  [SAVED & VERIFIED] EasyOCR models ready ({reason_after})")

    print(f"3/3 Vehicle / truck detection model (YOLOv8n from pinned Ultralytics {YOLO_RELEASE_VERSION}, verified SHA-256)...")
    yolo_target = os.path.join(models_dir, "yolov8n.pt")
    yolo_expected_sha = os.environ.get("MERSAD_YOLO_SHA256", "").strip() or MODEL_SHA256["yolov8n.pt"]
    download_verified(
        "yolov8n.pt",
        YOLO_MODEL_URL,
        min_bytes=EXPECTED_MIN_BYTES.get("yolov8n.pt", 6_000_000),
        expected_sha256=yolo_expected_sha,
        retries=retries,
        timeout=timeout,
        target_dir=models_dir,
    )
    if os.path.isfile(yolo_target):
        ok_y_chk, r_y_chk = verify_yolo_pt_file(yolo_target, expected_sha256=yolo_expected_sha, min_bytes=EXPECTED_MIN_BYTES.get("yolov8n.pt", 6_000_000))
        if not ok_y_chk:
            raise RuntimeError(f"yolov8n.pt failed pinned SHA-256 verification before loading: {r_y_chk}")
        try:
            register_trusted_model(yolo_target, who="prefetch")
        except Exception:
            pass

    # Verify YOLO model actually loads via Ultralytics if installed
    try:
        from ultralytics import YOLO
        _ = YOLO(yolo_target)
        print("  [OK] yolov8n.pt loaded and verified by Ultralytics YOLO.")
    except ImportError:
        pass

    print("\nAll models are verified and ready in the 'models' folder for offline operation.")
    return True


def main():
    os.chdir(BASE_DIR)
    prefetch_all_models(models_dir="models")


if __name__ == "__main__":
    main()
