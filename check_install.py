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
    """Check each AI model file and distinguish MODEL_MISSING from MODEL_CORRUPT and MODEL_OK.
    GAP-03: Imports model verification helpers from mersad_live with MERSAD_SKIP_RUNTIME_INIT=1 so no DB/log/cwd side effects occur."""
    prev_skip = os.environ.get("MERSAD_SKIP_RUNTIME_INIT")
    os.environ["MERSAD_SKIP_RUNTIME_INIT"] = "1"
    try:
        from mersad_live import (
            MODEL_SHA256,
            MODEL_MIN_BYTES,
            verify_onnx_file,
            verify_yolo_pt_file,
            verify_easyocr_dir,
            resolve_resource_path,
        )
    finally:
        if prev_skip is None:
            os.environ.pop("MERSAD_SKIP_RUNTIME_INIT", None)
        else:
            os.environ["MERSAD_SKIP_RUNTIME_INIT"] = prev_skip
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
    if headless_ver is not None:
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
        if "opencv-python-headless" in cur["installed"]:
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
        if "opencv-python-headless" in cur["installed"]:
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
        registry.init(db, lock, lambda *a: None, lambda: None, db_path=":memory:")
        insights.init(db, lock, db_path=":memory:")
        camera_history.init(db, lock, db_path=":memory:")
        analytics_report = analytics.build_report(db, {}, now=1700000000.0)
        camera_report = camera_history.build_report(db, {}, period="24h", now=1700000000.0)
        assert analytics_report["ok"] and len(analytics_report["trend"]) == 24 and camera_report["ok"]
        assert registry.save_vehicle({"plate": "12345", "status": "wanted"}, "t")["ok"]
        r = registry.import_file("vehicles", "t.csv", "plate,status\n23456,stolen\n".encode(), "t"); assert r["added"] == 1, r
        assert registry.template("persons")[1].startswith("mersad_persons_template")
        r = insights.seed_demo()
        s_live = insights.summary(include_demo=False)
        s = insights.summary(include_demo=True)
        pt_live = insights.plate_path("99991", include_demo=False)
        pt = insights.plate_path("99991", include_demo=True)
        assert r["ok"] and not s_live["model"]["ready"] and not pt_live["found"] and pt_live.get("has_demo_only"), (s_live, pt_live)
        assert s["forecast"] and s["corridors"] and pt["found"] and pt["conflicts"] and s["data_source"] == "demo", r
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


def _redact_cam_source(src):
    s = str(src or "")
    try:
        from notify import _redact
        s = _redact(s)
    except Exception:
        pass
    return re.sub(r"((?:rtsp|rtsps|http|https)://[^:/@\s]+:)[^@\s]+(@)", r"\1***\2", s, flags=re.I)


def check_camera_source(root_dir=None, source_override=None, capture_factory=None):
    """Verify camera source configured in mersad_config.json (or source_override) (GAP-07):
    - Redacts RTSP/HTTP passwords before logging or returning diagnostics.
    - Tests cap.isOpened() and reads a single frame.
    - Guarantees cap.release() inside a finally: block even if reading fails or raises."""
    raw_src = source_override
    if raw_src is None:
        raw_src = os.environ.get("MERSAD_CAMERA_SOURCE")
    if raw_src is None:
        search_dirs = []
        if root_dir:
            search_dirs.append(os.path.abspath(root_dir))
        if os.environ.get("MERSAD_DATA_DIR"):
            search_dirs.append(os.path.abspath(os.environ["MERSAD_DATA_DIR"]))
        search_dirs.append(os.path.abspath(os.getcwd()))
        search_dirs.append(ROOT_DIR)
        raw_src = "0"
        for d in search_dirs:
            cfg_p = os.path.join(d, "mersad_config.json")
            sec_p = os.path.join(d, ".mersad_secrets.json")
            if os.path.isfile(cfg_p):
                try:
                    with open(cfg_p, "r", encoding="utf-8") as cf:
                        cfg_data = json.load(cf)
                    if cfg_data.get("source") is not None and str(cfg_data.get("source")).strip() != "":
                        raw_src = str(cfg_data.get("source")).strip()
                except Exception:
                    pass
                if os.path.isfile(sec_p):
                    try:
                        with open(sec_p, "r", encoding="utf-8") as sf:
                            sec_data = json.load(sf)
                        sec_src = sec_data.get("source_with_credentials") or sec_data.get("rtsp_sources")
                        if sec_src and (not raw_src or raw_src == "0" or "***" in str(raw_src)):
                            raw_src = str(sec_src).strip()
                    except Exception:
                        pass
                break

    first_src = str(raw_src if raw_src is not None else "0").split(",")[0].strip() or "0"
    safe_src = _redact_cam_source(first_src)
    open_arg = int(first_src) if first_src.isdigit() else first_src

    cap = None
    released = False
    res = {
        "item": f"camera_source ({safe_src})",
        "category": "CAMERA_SOURCE",
        "status": "FAIL",
        "source": safe_src,
        "opened": False,
        "frame_read": False,
        "released": False,
        "reason": "",
        "remediation": "Check camera source in mersad_config.json and verify device/stream availability",
    }
    try:
        if capture_factory is None:
            import cv2
            cap_fn = cv2.VideoCapture
        else:
            cap_fn = capture_factory
        cap = cap_fn(open_arg)
        if cap is None or not cap.isOpened():
            res["reason"] = f"Camera source '{safe_src}' could not be opened (isOpened()=False)"
            return res
        res["opened"] = True
        ok_frm, frm = cap.read()
        has_valid_frame = bool(ok_frm and frm is not None and getattr(frm, "size", 0) > 0)
        if not has_valid_frame:
            res["reason"] = f"Camera source '{safe_src}' opened but failed to read a valid frame"
            return res
        res["frame_read"] = True
        res["status"] = "PASS"
        shape = getattr(frm, "shape", None)
        res["resolution"] = f"{shape[1]}x{shape[0]}" if (isinstance(shape, tuple) and len(shape) >= 2) else "ok"
        res["reason"] = f"Camera source '{safe_src}' opened and read 1 frame ({res['resolution']}) cleanly"
        res["remediation"] = ""
        return res
    except Exception as e:
        res["reason"] = f"Camera source '{safe_src}' error: {type(e).__name__}: {_redact_cam_source(e)}"
        return res
    finally:
        if cap is not None:
            try:
                cap.release()
                released = True
            except Exception:
                pass
        res["released"] = released


def run_diagnostic_report(strict=False, check_cam=False, as_json=False, root_dir=None, camera_capture_factory=None):
    eff_root = os.path.abspath(root_dir) if root_dir else ROOT_DIR
    lib_items = check_libraries_detailed()
    model_items = check_models_detailed(eff_root)
    ready_ok, ready_reason = verify_ready_stamp(root_dir=eff_root)

    core_checks = []
    for label, fn in (("Core DB, Registry, Excel/CSV & Path/Anomaly Engine", c_db_modules), ("Local TCP Socket Binding", c_port)):
        try:
            msg = fn()
            core_checks.append({"item": label, "category": "CORE_LOGIC", "status": "PASS", "reason": msg, "remediation": ""})
        except Exception as e:
            core_checks.append({"item": label, "category": "CORE_LOGIC", "status": "FAIL", "reason": f"{type(e).__name__}: {e}",
                                "remediation": "Inspect traceback and database permissions"})

    cam_check = None
    if check_cam:
        cam_check = check_camera_source(root_dir=root_dir, capture_factory=camera_capture_factory)

    missing_req_libs = [x for x in lib_items if x["category"] == "REQUIRED_LIB" and x["status"] != "PASS"]
    corrupt_models = [x for x in model_items if x["category"] == "MODEL_CORRUPT"]
    missing_models = [x for x in model_items if x["category"] == "MODEL_MISSING"]
    core_failures = [x for x in core_checks if x["status"] == "FAIL"]
    cam_failed = bool(check_cam and cam_check and cam_check.get("status") != "PASS")

    if not missing_req_libs and not corrupt_models and not missing_models and not cam_failed:
        env_classification = "PRODUCTION_READY (جميع المكتبات الأساسية والنماذج متوفرة وسليمة)"
    elif not core_failures and (missing_req_libs or missing_models) and not corrupt_models and not cam_failed:
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
    if check_cam and cam_check is not None:
        report["camera"] = cam_check

    if as_json:
        print(json.dumps(report, indent=2, ensure_ascii=False))
    else:
        print("======================================================================")
        print("  MERSAD AI — Environment, Dependency & Model Diagnostic Report")
        print(f"  Classification: {env_classification}")
        print(f"  venv/.ready Stamp: {'VALID' if ready_ok else 'NOT READY (' + ready_reason + ')'}")
        print("======================================================================")
        sections = [
            ("[1] Core Subsystems", core_checks),
            ("[2] Python & Libraries", lib_items),
            ("[3] AI Models & Weights", model_items),
        ]
        if check_cam and cam_check is not None:
            sections.append(("[4] Camera Source Check", [cam_check]))
        for section_title, group in sections:
            print(f"\n{section_title}:")
            for it in group:
                st = it["status"]
                cat = it["category"]
                print(f"  {st:7s} [{cat:16s}] {it['item']}: {it['reason']}")
                if it.get("remediation") and st != "PASS":
                    print(f"          -> Fix: {it['remediation']}")

    if strict:
        has_err = bool(core_failures or missing_req_libs or corrupt_models or missing_models or cam_failed)
        return 1 if has_err else 0
    return 1 if (core_failures or corrupt_models or cam_failed) else 0


_EASYOCR_HEADLESS_RE = re.compile(
    r"^easyocr\s+\S+\s+(?:requires|has requirement)\s+opencv-python-headless(?:\s*[<>=!~,\d\.\*]+)?,\s+which is not installed\.?$",
    re.IGNORECASE,
)



REQUIRED_LOCAL_HIDDENIMPORTS = (
    "registry",
    "insights",
    "analytics",
    "camera_history",
    "notify",
    "server",
    "check_install",
    "prefetch",
    "openpyxl",
)


def verify_build_config_consistency(root_dir=ROOT_DIR):
    """Verify that mersad_ai.spec, BUILD_EXE.bat, and .github/workflows/windows-build.yml are aligned (GAP-18)."""
    spec_p = os.path.join(root_dir, "mersad_ai.spec")
    bat_p = os.path.join(root_dir, "BUILD_EXE.bat")
    yml_p = os.path.join(root_dir, ".github", "workflows", "windows-build.yml")

    def _read_txt(p):
        if not os.path.isfile(p):
            return ""
        with open(p, encoding="utf-8") as f:
            return f.read()

    spec_s = _read_txt(spec_p)
    bat_s = _read_txt(bat_p)
    yml_s = _read_txt(yml_p)

    spec_hi = set(re.findall(r'"([A-Za-z0-9_]+)"', spec_s.partition("hiddenimports = [")[2].partition("]")[0]))
    bat_hi = set(re.findall(r"--hidden-import\s+([A-Za-z0-9_]+)", bat_s))

    req_set = set(REQUIRED_LOCAL_HIDDENIMPORTS)
    hi_match = (spec_hi == bat_hi) and req_set.issubset(spec_hi)

    no_hardcoded_user = ("runneradmin" not in yml_s.lower()) and ("c:\\users\\" not in yml_s.lower())
    uses_pwsh_env = ("$env:MERSAD_BLOCK_SKLEARN" in yml_s) and ("Remove-Item Env:\\MERSAD_BLOCK_SKLEARN" in yml_s)
    uses_runner_temp_isolation = (
        "$env:RUNNER_TEMP" in yml_s
        and "$env:MERSAD_DATA_DIR" in yml_s
        and "--verify-models" in yml_s
        and "--verify" in yml_s
    )
    ok = bool(hi_match and no_hardcoded_user and uses_pwsh_env and uses_runner_temp_isolation)
    return ok, {
        "ok": ok,
        "spec_hiddenimports": sorted(spec_hi),
        "bat_hiddenimports": sorted(bat_hi),
        "hiddenimports_aligned": hi_match,
        "no_hardcoded_user": no_hardcoded_user,
        "uses_pwsh_env": uses_pwsh_env,
        "uses_runner_temp_isolation": uses_runner_temp_isolation,
    }


def verify_pip_deps(pip_check_output=None, pip_returncode=None, opencv_version=None, headless_version=None, cv2_module=None):
    """Run `python -m pip check` and programmatically validate dependency integrity (GAP-01).
    - Tolerates ONLY the metadata-only `easyocr -> opencv-python-headless not installed` notice,
      strictly conditioned on verifying that `opencv-python==4.11.0.86` is installed,
      `opencv-python-headless` is absent, and `cv2` is importable with a callable `cv2.imshow`.
    - Fails immediately on any other missing dependency or version conflict."""
    if pip_check_output is None:
        proc = subprocess.run([sys.executable, "-m", "pip", "check"], capture_output=True, text=True, timeout=60)
        raw_out = ((proc.stdout or "") + "\n" + (proc.stderr or "")).strip()
        rc = proc.returncode if pip_returncode is None else pip_returncode
    else:
        raw_out = str(pip_check_output).strip()
        rc = pip_returncode if pip_returncode is not None else (0 if (not raw_out or raw_out.lower().startswith("no broken requirements found")) else 1)

    tolerated_headless = []
    unexpected_conflicts = []
    for raw_line in raw_out.splitlines():
        line = raw_line.strip()
        if not line or line.lower().startswith("no broken requirements found"):
            continue
        if _EASYOCR_HEADLESS_RE.match(line):
            tolerated_headless.append(line)
        else:
            unexpected_conflicts.append(line)

    if rc != 0 and not tolerated_headless and not unexpected_conflicts:
        unexpected_conflicts.append(raw_out or f"pip check failed with exit code {rc}")

    exp_cv_ver = PINNED_RUNTIME_SPECS.get("opencv-python", "4.11.0.86")
    act_cv_ver = _pkg_version("opencv-python") if opencv_version is None else (None if opencv_version == "" else opencv_version)
    act_hl_ver = _pkg_version("opencv-python-headless") if headless_version is None else (None if headless_version == "" else headless_version)

    cv_errors = []
    if act_hl_ver is not None:
        cv_errors.append(f"Conflicting opencv-python-headless=={act_hl_ver} is installed (must be removed so cv2.imshow works)")
    if act_cv_ver is None:
        cv_errors.append(f"Required GUI package opencv-python=={exp_cv_ver} is not installed")
    elif str(act_cv_ver).split("+")[0] != exp_cv_ver:
        cv_errors.append(f"opencv-python version mismatch: installed={act_cv_ver}, expected=={exp_cv_ver}")

    try:
        mod_cv2 = cv2_module
        if mod_cv2 is None:
            import cv2 as mod_cv2
        if not callable(getattr(mod_cv2, "imshow", None)):
            cv_errors.append("cv2 module is missing callable cv2.imshow GUI function")
    except Exception as e:
        cv_errors.append(f"Failed to import cv2: {type(e).__name__}: {e}")

    ok = (len(unexpected_conflicts) == 0) and (len(cv_errors) == 0)
    return ok, {
        "ok": ok,
        "opencv_python_version": act_cv_ver,
        "opencv_headless_version": act_hl_ver,
        "tolerated_easyocr_headless": tolerated_headless,
        "unexpected_conflicts": unexpected_conflicts,
        "opencv_errors": cv_errors,
    }


if __name__ == "__main__":
    import shutil
    ap = argparse.ArgumentParser()
    ap.add_argument("--strict", action="store_true", help="Require all runtime libraries and AI models to be present and verified")
    ap.add_argument("--verify-ready", action="store_true", help="Exit 0 only if venv/.ready exists and matches current dependencies & models")
    ap.add_argument("--write-ready", action="store_true", help="Verify environment & models and write venv/.ready atomically")
    ap.add_argument("--verify-pip-deps", action="store_true", help="Run pip check and verify OpenCV GUI replacement & zero other conflicts")
    ap.add_argument("--camera", action="store_true", help="Also test opening camera source from mersad_config.json")
    ap.add_argument("--json", action="store_true", help="Print JSON diagnostic report")
    args = ap.parse_args()

    if args.verify_pip_deps:
        ok_pip, pip_info = verify_pip_deps()
        if args.json:
            print(json.dumps(pip_info, indent=2, ensure_ascii=False))
        else:
            if ok_pip:
                print(
                    f"PIP_DEPS_OK: opencv-python=={pip_info['opencv_python_version']} verified with cv2.imshow "
                    f"(tolerated easyocr headless notices: {len(pip_info['tolerated_easyocr_headless'])})"
                )
            else:
                print("PIP_DEPS_FAILED: Dependency verification failed:")
                for err in pip_info["opencv_errors"] + pip_info["unexpected_conflicts"]:
                    print(f"  - {err}")
        sys.exit(0 if ok_pip else 1)

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
