"""Comprehensive installation, dependency, environment readiness (.ready), and AI model verifier for MERSAD AI.
Distinguishes clearly between:
- REQUIRED_LIB: Core runtime library missing
- OPTIONAL_LIB: Optional library missing (e.g. scikit-learn, which falls back to StatForest)
- VERSION_CONFLICT: Version mismatch against requirements.txt/constraints-win-x64.txt or opencv-python-headless conflict
- MODEL_MISSING: Model weight file not downloaded yet (expected in fresh offline dev environment; required before live run/build)
- MODEL_CORRUPT: Model file exists on disk but fails SHA-256 or structural integrity check
- BUILD_REQ: PyInstaller build requirement status
- ENV_STAMP: Cryptographic venv/.ready readiness stamp tied to Python version, 64-bit arch, dependency file hashes, and models

Usage:
  python check_install.py                # Standard diagnostic report
  python check_install.py --strict       # Fail if any runtime library or model is missing/corrupt (used by BUILD_EXE.bat)
  python check_install.py --verify-ready # Verify venv/.ready stamp matches current environment & models
  python check_install.py --write-ready  # Write venv/.ready stamp ONLY if all libraries and models pass verification
  python check_install.py --json         # Output structured JSON diagnostic report
"""
import argparse, hashlib, importlib.metadata, json, os, re, socket, struct, subprocess, sys, tempfile, threading, time

ROOT_DIR = os.path.dirname(os.path.abspath(__file__))
if ROOT_DIR not in sys.path:
    sys.path.insert(0, ROOT_DIR)

TARGET_PYTHON_MAJOR_MINOR = (3, 11)
SUPPORTED_PYTHON_MINORS = ((3, 10), (3, 11), (3, 12))

PINNED_RUNTIME_SPECS = {
    "numpy": "1.26.4",
    "opencv-python": "4.11.0.86",
    "Pillow": "10.4.0",
    "easyocr": "1.7.2",
    "ultralytics": "8.3.0",
    "openpyxl": "3.1.5",
}
PINNED_TORCH_SPECS = {
    "torch": "2.5.1",
    "torchvision": "0.20.1",
}
OPTIONAL_SPECS = {
    "scikit-learn": "1.5.2",
}
BUILD_SPECS = {
    "pyinstaller": "6.11.1",
}


def _opencv_gui_build_available():
    """Return True only when the active cv2 module exposes a GUI backend."""
    try:
        import cv2
        info = cv2.getBuildInformation()
        match = re.search(r"(?m)^\s*GUI:\s*(.*?)\s*$", info)
        gui = match.group(1).strip().upper() if match else ""
        if os.name == "nt":
            return "WIN32UI" in gui
        return bool(gui) and gui not in ("NONE", "NO")
    except Exception:
        return False


def _file_sha256(path):
    if not path or not os.path.isfile(path):
        return ""
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


def _pkg_version(dist_name):
    try:
        return importlib.metadata.version(dist_name)
    except importlib.metadata.PackageNotFoundError:
        return None


def compute_env_manifest(root_dir=ROOT_DIR):
    """Compute a deterministic manifest of Python version, architecture, dependency file hashes, and installed packages."""
    req_path = os.path.join(root_dir, "requirements.txt")
    con_path = os.path.join(root_dir, "constraints-win-x64.txt")
    pre_path = os.path.join(root_dir, "prefetch.py")
    installed = {}
    for pkg in list(PINNED_RUNTIME_SPECS) + list(PINNED_TORCH_SPECS) + list(OPTIONAL_SPECS) + ["opencv-python-headless"]:
        v = _pkg_version(pkg)
        if v is not None:
            installed[pkg] = v
    manifest = {
        "python_version": f"{sys.version_info.major}.{sys.version_info.minor}.{sys.version_info.micro}",
        "python_major_minor": f"{sys.version_info.major}.{sys.version_info.minor}",
        "arch_bits": struct.calcsize("P") * 8,
        "requirements_sha256": _file_sha256(req_path),
        "constraints_sha256": _file_sha256(con_path),
        "prefetch_sha256": _file_sha256(pre_path),
        "installed": installed,
    }
    raw_bytes = json.dumps(manifest, sort_keys=True).encode("utf-8")
    manifest["fingerprint"] = hashlib.sha256(raw_bytes).hexdigest()
    return manifest


def check_models_detailed(root_dir=ROOT_DIR):
    """Check each AI model file and distinguish MODEL_MISSING from MODEL_CORRUPT and MODEL_OK."""
    from mersad_live import (
        MODEL_SHA256,
        MODEL_MIN_BYTES,
        verify_onnx_file,
        verify_yolo_pt_file,
        verify_easyocr_dir,
        resolve_resource_path,
    )
    results = []
    for fname in ("yunet.onnx", "sface.onnx"):
        rel = os.path.join("models", fname)
        p = os.path.join(root_dir, rel)
        if not os.path.exists(p):
            alt = resolve_resource_path(rel)
            if os.path.exists(alt):
                p = alt
        if not os.path.exists(p):
            results.append({
                "item": rel,
                "category": "MODEL_MISSING",
                "status": "MISSING",
                "reason": f"Model file '{rel}' has not been downloaded yet",
                "remediation": "Run `python prefetch.py` with internet access or copy verified models/ folder",
            })
        else:
            ok, reason = verify_onnx_file(p, expected_sha256=MODEL_SHA256.get(fname), min_bytes=MODEL_MIN_BYTES.get(fname, 50_000))
            results.append({
                "item": rel,
                "category": "MODEL_OK" if ok else "MODEL_CORRUPT",
                "status": "PASS" if ok else "FAIL",
                "reason": reason,
                "remediation": "" if ok else f"Delete corrupt '{rel}' and re-run `python prefetch.py`",
            })

    yolo_rel = os.path.join("models", "yolov8n.pt")
    yolo_p = os.path.join(root_dir, yolo_rel)
    if not os.path.exists(yolo_p):
        alt_y = resolve_resource_path(yolo_rel)
        if os.path.exists(alt_y):
            yolo_p = alt_y
    if not os.path.exists(yolo_p):
        results.append({
            "item": yolo_rel,
            "category": "MODEL_MISSING",
            "status": "MISSING",
            "reason": "YOLOv8n weight file 'models/yolov8n.pt' is not present",
            "remediation": "Run `python prefetch.py` to download and verify yolov8n.pt",
        })
    else:
        ok_y, reason_y = verify_yolo_pt_file(yolo_p, min_bytes=MODEL_MIN_BYTES.get("yolov8n.pt", 6_000_000))
        results.append({
            "item": yolo_rel,
            "category": "MODEL_OK" if ok_y else "MODEL_CORRUPT",
            "status": "PASS" if ok_y else "FAIL",
            "reason": reason_y,
            "remediation": "" if ok_y else "Delete corrupt 'models/yolov8n.pt' and re-run `python prefetch.py`",
        })

    easy_rel = os.path.join("models", "easyocr")
    easy_p = os.path.join(root_dir, easy_rel)
    if not os.path.exists(easy_p):
        alt_e = resolve_resource_path(easy_rel)
        if os.path.exists(alt_e):
            easy_p = alt_e
    ok_e, reason_e = verify_easyocr_dir(easy_p)
    if not ok_e and ("missing" in reason_e or "no_pth_files" in reason_e):
        results.append({
            "item": easy_rel,
            "category": "MODEL_MISSING",
            "status": "MISSING",
            "reason": f"EasyOCR weights not downloaded yet ({reason_e})",
            "remediation": "Run `python prefetch.py` to download Arabic & English EasyOCR weights",
        })
    else:
        results.append({
            "item": easy_rel,
            "category": "MODEL_OK" if ok_e else "MODEL_CORRUPT",
            "status": "PASS" if ok_e else "FAIL",
            "reason": reason_e,
            "remediation": "" if ok_e else "Remove incomplete/corrupt files in 'models/easyocr' and re-run `python prefetch.py`",
        })
    return results


def check_libraries_detailed():
    """Inspect required, optional, and build libraries and detect version mismatches or headless conflicts."""
    items = []
    arch_bits = struct.calcsize("P") * 8
    py_mm = (sys.version_info.major, sys.version_info.minor)
    py_ok = arch_bits == 64 and py_mm in SUPPORTED_PYTHON_MINORS
    items.append({
        "item": "python_runtime",
        "category": "PYTHON_ENV",
        "status": "PASS" if py_ok else "FAIL",
        "reason": f"Python {sys.version.split()[0]} ({arch_bits}-bit); target is Python 3.11 64-bit",
        "remediation": "" if py_ok else "Install 64-bit Python 3.11 from python.org",
    })

    headless_ver = _pkg_version("opencv-python-headless")
    if headless_ver is not None and not _opencv_gui_build_available():
        items.append({
            "item": "opencv-python-headless",
            "category": "VERSION_CONFLICT",
            "status": "WARN",
            "reason": f"Conflicting opencv-python-headless ({headless_ver}) is installed and may disable cv2.imshow GUI",
            "remediation": "Run `pip uninstall -y opencv-python-headless && pip install --force-reinstall --no-deps opencv-python==4.11.0.86`",
        })

    for pkg, exp_ver in {**PINNED_RUNTIME_SPECS, **PINNED_TORCH_SPECS}.items():
        cur_ver = _pkg_version(pkg)
        if cur_ver is None:
            items.append({
                "item": pkg,
                "category": "REQUIRED_LIB",
                "status": "MISSING",
                "reason": f"Required runtime library '{pkg}' is not installed (expected =={exp_ver})",
                "remediation": "Run `setup.bat` or `pip install -r requirements.txt -c constraints-win-x64.txt`",
            })
        else:
            base_cur = cur_ver.split("+")[0]
            ver_match = (base_cur == exp_ver)
            items.append({
                "item": pkg,
                "category": "REQUIRED_LIB" if ver_match else "VERSION_MISMATCH",
                "status": "PASS" if ver_match else "WARN",
                "reason": f"installed={cur_ver} (pinned={exp_ver})",
                "remediation": "" if ver_match else f"Run `pip install {pkg}=={exp_ver} -c constraints-win-x64.txt` for exact reproducibility",
            })

    for pkg, exp_ver in OPTIONAL_SPECS.items():
        cur_ver = _pkg_version(pkg)
        if cur_ver is None:
            items.append({
                "item": pkg,
                "category": "OPTIONAL_LIB",
                "status": "SKIP",
                "reason": f"Optional library '{pkg}' not installed (system automatically uses built-in StatForest fallback)",
                "remediation": f"Optional: `pip install {pkg}=={exp_ver}`",
            })
        else:
            items.append({
                "item": pkg,
                "category": "OPTIONAL_LIB",
                "status": "PASS",
                "reason": f"installed={cur_ver} (pinned={exp_ver})",
                "remediation": "",
            })

    for pkg, exp_ver in BUILD_SPECS.items():
        cur_ver = _pkg_version(pkg)
        items.append({
            "item": pkg,
            "category": "BUILD_REQ",
            "status": "PASS" if cur_ver == exp_ver else ("WARN" if cur_ver else "SKIP"),
            "reason": f"installed={cur_ver or 'not_installed'} (pinned for EXE build={exp_ver})",
            "remediation": "" if cur_ver == exp_ver else f"Before building EXE, run `pip install {pkg}=={exp_ver}`",
        })
    return items


def verify_ready_stamp(ready_path=None, root_dir=ROOT_DIR, require_models=True, require_all_libs=True):
    """Verify that venv/.ready exists, is valid JSON, matches current dependency file hashes & Python version,
    and that required libraries and models are actually present and intact (Stage 3)."""
    if ready_path is None:
        ready_path = os.path.join(root_dir, "venv", ".ready")
    if not os.path.isfile(ready_path):
        return False, "ready_stamp_missing"
    try:
        with open(ready_path, "r", encoding="utf-8") as f:
            stamp = json.load(f)
    except Exception:
        return False, "ready_stamp_corrupt_or_legacy_format"

    if not isinstance(stamp, dict) or "fingerprint" not in stamp:
        return False, "ready_stamp_missing_fingerprint"

    cur = compute_env_manifest(root_dir)
    if stamp.get("python_version") != cur["python_version"]:
        return False, f"python_version_changed:{stamp.get('python_version')}->{cur['python_version']}"
    if stamp.get("arch_bits") != 64 or cur["arch_bits"] != 64:
        return False, "python_not_64bit"
    if stamp.get("requirements_sha256") != cur["requirements_sha256"]:
        return False, "requirements_txt_modified"
    if stamp.get("constraints_sha256") != cur["constraints_sha256"]:
        return False, "constraints_txt_modified"
    if stamp.get("prefetch_sha256") != cur["prefetch_sha256"]:
        return False, "prefetch_py_modified"
    if stamp.get("fingerprint") != cur["fingerprint"]:
        return False, "installed_packages_changed"

    if require_all_libs:
        if "opencv-python-headless" in cur["installed"] and not _opencv_gui_build_available():
            return False, "conflicting_opencv_python_headless_present"
        for pkg in list(PINNED_RUNTIME_SPECS) + list(PINNED_TORCH_SPECS):
            if pkg not in cur["installed"]:
                return False, f"missing_required_package:{pkg}"

    if require_models:
        m_checks = check_models_detailed(root_dir)
        for mc in m_checks:
            if mc["status"] != "PASS":
                return False, f"model_invalid:{mc['item']}:{mc['category']}:{mc['reason']}"

    return True, "ok"


def write_ready_stamp(ready_path=None, root_dir=ROOT_DIR, require_models=True, require_all_libs=True):
    """Write venv/.ready atomically ONLY after verifying all required packages and AI models."""
    if ready_path is None:
        ready_path = os.path.join(root_dir, "venv", ".ready")
    # Remove any previous stamp first so a failure below never leaves a stale stamp
    if os.path.lexists(ready_path):
        try: os.remove(ready_path)
        except OSError: pass

    cur = compute_env_manifest(root_dir)
    if cur["arch_bits"] != 64:
        return False, "python_not_64bit"

    if require_all_libs:
        if "opencv-python-headless" in cur["installed"] and not _opencv_gui_build_available():
            return False, "conflicting_opencv_python_headless_present"
        for pkg in list(PINNED_RUNTIME_SPECS) + list(PINNED_TORCH_SPECS):
            if pkg not in cur["installed"]:
                return False, f"missing_required_package:{pkg}"

    if require_models:
        m_checks = check_models_detailed(root_dir)
        for mc in m_checks:
            if mc["status"] != "PASS":
                return False, f"model_invalid:{mc['item']}:{mc['category']}:{mc['reason']}"

    os.makedirs(os.path.dirname(os.path.abspath(ready_path)), exist_ok=True)
    stamp_data = {
        **cur,
        "verified_ts": time.time(),
        "models_verified": bool(require_models),
    }
    tmp_p = f"{ready_path}.tmp.{os.getpid()}"
    try:
        with open(tmp_p, "w", encoding="utf-8") as f:
            json.dump(stamp_data, f, indent=2, sort_keys=True)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp_p, ready_path)
        return True, "written"
    except OSError as e:
        if os.path.exists(tmp_p):
            try: os.remove(tmp_p)
            except OSError: pass
        return False, f"write_error:{e}"


def c_db_modules():
    import sqlite3, registry, insights, analytics, camera_history
    tmp_d = tempfile.mkdtemp(prefix="mersad_chk_")
    old_env = os.environ.get("MERSAD_DATA_DIR")
    try:
        os.environ["MERSAD_DATA_DIR"] = tmp_d
        registry._HMAC_KEY_CACHE.clear()
        db = sqlite3.connect(":memory:", check_same_thread=False); lock = threading.RLock()
        registry.init(db, lock, lambda *a: None, lambda: None); insights.init(db, lock)
        camera_history.init(db, lock, db_path=":memory:")
        analytics_report = analytics.build_report(db, {}, now=1700000000.0)
        camera_report = camera_history.build_report(db, {}, period="24h", now=1700000000.0)
        assert analytics_report["ok"] and len(analytics_report["trend"]) == 24 and camera_report["ok"]
        assert registry.save_vehicle({"plate": "12345", "status": "wanted"}, "t")["ok"]
        r = registry.import_file("vehicles", "t.csv", "plate,status\n23456,stolen\n".encode(), "t"); assert r["added"] == 1, r
        assert registry.template("persons")[1].startswith("mersad_persons_template")
        r = insights.seed_demo()
        s = insights.summary()
        pt = insights.plate_path("99991")
        assert r["ok"] and s["forecast"] and s["corridors"] and pt["found"] and pt["conflicts"], r
        return f"learning ({s['model']['type']}) + path tracking + operations analytics + camera-history schema verified on {r['n']} synthetic records"
    finally:
        if old_env is not None:
            os.environ["MERSAD_DATA_DIR"] = old_env
        else:
            os.environ.pop("MERSAD_DATA_DIR", None)
        registry._HMAC_KEY_CACHE.clear()
        shutil.rmtree(tmp_d, ignore_errors=True)


def c_port():
    s = socket.socket()
    s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    try:
        s.bind(("127.0.0.1", 0))
        return "local socket binding OK"
    finally:
        s.close()


def run_diagnostic_report(strict=False, check_cam=False, as_json=False):
    lib_items = check_libraries_detailed()
    model_items = check_models_detailed(ROOT_DIR)
    ready_ok, ready_reason = verify_ready_stamp(root_dir=ROOT_DIR)

    core_checks = []
    for label, fn in (("Core DB, Registry, Excel/CSV & Path/Anomaly Engine", c_db_modules), ("Local TCP Socket Binding", c_port)):
        try:
            msg = fn()
            core_checks.append({"item": label, "category": "CORE_LOGIC", "status": "PASS", "reason": msg, "remediation": ""})
        except Exception as e:
            core_checks.append({"item": label, "category": "CORE_LOGIC", "status": "FAIL", "reason": f"{type(e).__name__}: {e}",
                                "remediation": "Inspect traceback and database permissions"})

    missing_req_libs = [x for x in lib_items if x["category"] == "REQUIRED_LIB" and x["status"] != "PASS"]
    corrupt_models = [x for x in model_items if x["category"] == "MODEL_CORRUPT"]
    missing_models = [x for x in model_items if x["category"] == "MODEL_MISSING"]
    core_failures = [x for x in core_checks if x["status"] == "FAIL"]

    if not missing_req_libs and not corrupt_models and not missing_models:
        env_classification = "PRODUCTION_READY (جميع المكتبات الأساسية والنماذج متوفرة وسليمة)"
    elif not core_failures and (missing_req_libs or missing_models) and not corrupt_models:
        env_classification = "DEV_WITHOUT_HEAVY_WEIGHTS (بيئة تطوير/فحص منطقي بدون أوزان الذكاء الاصطناعي الثقيلة أو مكتبات الاستدلال)"
    else:
        env_classification = "INCOMPLETE_OR_CORRUPT (توجد ملفات تالفة أو أعطال أساسية تتطلب المعالجة)"

    report = {
        "classification": env_classification,
        "ready_stamp": {"valid": ready_ok, "reason": ready_reason},
        "core_checks": core_checks,
        "libraries": lib_items,
        "models": model_items,
    }

    if as_json:
        print(json.dumps(report, indent=2, ensure_ascii=False))
    else:
        print("======================================================================")
        print("  MERSAD AI — Environment, Dependency & Model Diagnostic Report")
        print(f"  Classification: {env_classification}")
        print(f"  venv/.ready Stamp: {'VALID' if ready_ok else 'NOT READY (' + ready_reason + ')'}")
        print("======================================================================")
        for section_title, group in (
            ("[1] Core Subsystems", core_checks),
            ("[2] Python & Libraries", lib_items),
            ("[3] AI Models & Weights", model_items),
        ):
            print(f"\n{section_title}:")
            for it in group:
                st = it["status"]
                cat = it["category"]
                print(f"  {st:7s} [{cat:16s}] {it['item']}: {it['reason']}")
                if it.get("remediation") and st != "PASS":
                    print(f"          -> Fix: {it['remediation']}")

    if strict:
        has_err = bool(core_failures or missing_req_libs or corrupt_models or missing_models)
        return 1 if has_err else 0
    # In non-strict mode, corrupt models or core logic failures return 1
    return 1 if (core_failures or corrupt_models) else 0


if __name__ == "__main__":
    import shutil
    os.chdir(ROOT_DIR)
    ap = argparse.ArgumentParser()
    ap.add_argument("--strict", action="store_true", help="Require all runtime libraries and AI models to be present and verified")
    ap.add_argument("--verify-ready", action="store_true", help="Exit 0 only if venv/.ready exists and matches current dependencies & models")
    ap.add_argument("--write-ready", action="store_true", help="Verify environment & models and write venv/.ready atomically")
    ap.add_argument("--camera", action="store_true", help="Also test opening camera source from mersad_config.json")
    ap.add_argument("--json", action="store_true", help="Print JSON diagnostic report")
    args = ap.parse_args()

    if args.verify_ready:
        ok, reason = verify_ready_stamp(root_dir=ROOT_DIR, require_models=True, require_all_libs=True)
        if not ok:
            print(f"ENV_NOT_READY: {reason}")
            sys.exit(1)
        print("ENV_READY: ok")
        sys.exit(0)

    if args.write_ready:
        ok, reason = write_ready_stamp(root_dir=ROOT_DIR, require_models=True, require_all_libs=True)
        if not ok:
            print(f"WRITE_READY_FAILED: {reason}")
            sys.exit(1)
        print("WRITE_READY_OK: venv/.ready written and verified")
        sys.exit(0)

    rc = run_diagnostic_report(strict=args.strict, check_cam=args.camera, as_json=args.json)
    sys.exit(rc)
