#!/usr/bin/env python3
"""
MERSAD AI — PREVIEW 0.1 | Standalone File, Code, Audit Chain & Model Integrity Verifier
أداة التحقق من سلامة الملفات والنماذج وسلسلة التدقيق
"""
import argparse
import hashlib
import json
import os
import sys

REQUIRED_SOURCE_FILES = (
    "mersad_live.py",
    "server.py",
    "registry.py",
    "notify.py",
    "analytics.py",
    "insights.py",
    "camera_history.py",
    "dashboard.html",
    "prefetch.py",
    "check_install.py",
    "selftest.py",
    "mersad_ai.spec",
    "BUILD_EXE.bat",
    "setup.bat",
    "requirements.txt",
    "constraints-win-x64.txt",
    "README_AR.md",
    "SYSTEM_REQUIREMENTS.txt",
)


def sha256_file(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


def verify_package(root_dir=None, check_models=False):
    root = os.path.abspath(root_dir or os.path.dirname(os.path.abspath(__file__)))
    report = {
        "version": "MERSAD AI — PREVIEW 0.1",
        "root": root,
        "files": [],
        "missing_files": [],
        "models_status": "skipped",
        "models": [],
        "ok": True,
    }
    is_frozen_dist = os.path.isfile(os.path.join(root, "MERSAD_AI.exe"))
    expected = ("MERSAD_AI.exe", "dashboard.html", "README_AR.md") if is_frozen_dist else REQUIRED_SOURCE_FILES
    for fn in expected:
        p = os.path.join(root, fn)
        if not os.path.isfile(p) or os.path.islink(p):
            report["missing_files"].append(fn)
            report["ok"] = False
        else:
            report["files"].append({
                "file": fn,
                "size_bytes": os.path.getsize(p),
                "sha256": sha256_file(p),
            })

    if check_models:
        sys.path.insert(0, root)
        import check_install as _chk
        m_items = _chk.check_models_detailed(root)
        report["models"] = m_items
        models_ok = all(it.get("status") == "PASS" for it in m_items)
        report["models_status"] = "PASS" if models_ok else "MISSING_OR_CORRUPT"
        if not models_ok:
            report["ok"] = False

    return report


def main():
    ap = argparse.ArgumentParser(description="Verify MERSAD AI Preview 0.1 file and model integrity.")
    ap.add_argument("--root", default=None, help="Root directory to inspect")
    ap.add_argument("--check-models", action="store_true", help="Also require all 4 AI model weights to be present and verified")
    ap.add_argument("--json", action="store_true", help="Output JSON report")
    args = ap.parse_args()
    rep = verify_package(args.root, check_models=args.check_models)
    if args.json:
        print(json.dumps(rep, indent=2, ensure_ascii=False))
    else:
        print("======================================================================")
        print("  MERSAD AI — PREVIEW 0.1 | Integrity Verification Report")
        print("======================================================================")
        print(f"  Root Directory : {rep['root']}")
        print(f"  Files Checked  : {len(rep['files'])} present, {len(rep['missing_files'])} missing")
        if rep["missing_files"]:
            print(f"  Missing Files  : {', '.join(rep['missing_files'])}")
        if args.check_models:
            print(f"  Models Status  : {rep['models_status']}")
        print("  Overall Result :", "PASS" if rep["ok"] else "FAIL")
        print("======================================================================")
    sys.exit(0 if rep["ok"] else 1)


if __name__ == "__main__":
    main()
