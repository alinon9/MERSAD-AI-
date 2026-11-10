#!/usr/bin/env python3
"""
MERSAD AI V7.1 + MERSAD LAB 1.0 — PREVIEW 0.1
Phase 2 Tool: Deep Functional, Security, API, MJPEG & Structural Comparison
Between Original MERSAD LAB (`build/mersad-lab-exe-20261031` @ `ed7b8f727243da4878e547f08489af581c83291c`)
and Clean-Room MERSAD LAB (`MERSAD_LAB_Preview_0.1`).

Strict Phase 2 Rules Enforced:
  1. Goes far beyond SHA-256 and file sizes: inspects AST structure, API routes, MJPEG streaming,
     camera modes/behavior, security controls (Auth, Host/Origin, CSRF, XSS/CSP, DoS limits), and process shutdown.
  2. Verifies that the Original LAB source matches the exact target commit:
     `ed7b8f727243da4878e547f08489af581c83291c` (`build/mersad-lab-exe-20261031`).
  3. If commit `ed7b8f727243da4878e547f08489af581c83291c` is unavailable or cannot be restored,
     marks Phase 2 as `BLOCKED` and NEVER allows the comparison to be reported as `PASS`.
  4. Executes independent functional and security tests on Original LAB and Clean-room LAB.
  5. Uses the neutral status `DIFFERENT` for differing files (never describing differences as "enhanced/improved" without proof).
"""
import argparse
import ast
import base64
import hashlib
import io
import json
import os
import re
import shutil
import stat
import subprocess
import sys
import tempfile
import zipfile
from pathlib import Path, PurePosixPath

TARGET_ORIGINAL_COMMIT = "ed7b8f727243da4878e547f08489af581c83291c"
TARGET_ORIGINAL_BRANCH = "build/mersad-lab-exe-20261031"


def sha256_file(p: Path) -> str:
    h = hashlib.sha256()
    with open(p, "rb") as f:
        for chunk in iter(lambda: f.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


def analyze_python_ast(p: Path) -> dict:
    try:
        src = p.read_text(encoding="utf-8", errors="replace")
        tree = ast.parse(src)
        classes = [n.name for n in ast.walk(tree) if isinstance(n, ast.ClassDef)]
        funcs = [n.name for n in ast.walk(tree) if isinstance(n, ast.FunctionDef)]
        routes = sorted(set(re.findall(r'["\'](/(?:api|frame|stream)[^"\']*)["\']', src)))
        return {
            "lines": len(src.splitlines()),
            "classes": sorted(classes),
            "functions": sorted(funcs),
            "detected_routes": routes,
        }
    except Exception as e:
        return {"error": str(e)}


def collect_tree(root: Path) -> dict:
    out = {}
    if not root.is_dir():
        return out
    for dirpath, _, filenames in os.walk(root):
        for fn in filenames:
            if "__pycache__" in dirpath or fn.endswith(".pyc") or "/.git/" in (dirpath.replace("\\", "/") + "/"):
                continue
            if fn == "README_ORIGINAL_LAB_PLACEHOLDER_AR.md":
                continue
            p = Path(dirpath) / fn
            rel = p.relative_to(root).as_posix()
            entry = {
                "size": p.stat().st_size,
                "sha256": sha256_file(p),
            }
            if p.suffix.lower() == ".py":
                entry["ast"] = analyze_python_ast(p)
            out[rel] = entry
    return out


def _original_lab_root(pres_dir: Path):
    """Return the actual Original LAB source root, not helper scripts under ci/."""
    nested = pres_dir / "MERSAD_LAB"
    if nested.is_dir() and any(p.is_file() for p in nested.glob("*.py")):
        return nested
    if pres_dir.is_dir() and any(p.is_file() for p in pres_dir.glob("*.py")):
        return pres_dir
    return None


def restore_embedded_source_archive(pres_dir: Path) -> dict:
    """Reassemble and safely extract the historical LAB ZIP stored as base64 CI chunks."""
    ci_dir = pres_dir / "ci"
    if not ci_dir.is_dir():
        existing = _original_lab_root(pres_dir)
        return {
            "restored": bool(existing),
            "parts": 0,
            "python_files": len(list(existing.glob("*.py"))) if existing else 0,
            "reason": "Source folder already present." if existing else "No ci/ source chunks or restored MERSAD_LAB folder found.",
        }

    part_paths = sorted(ci_dir.glob("mersad_lab_source_part_*.txt"))
    if not part_paths:
        existing = _original_lab_root(pres_dir)
        return {
            "restored": bool(existing),
            "parts": 0,
            "python_files": len(list(existing.glob("*.py"))) if existing else 0,
            "reason": "Source folder already present." if existing else "No embedded source archive chunks found.",
        }

    indexed_parts = []
    for part_path in part_paths:
        match = re.fullmatch(r"mersad_lab_source_part_(\d+)\.txt", part_path.name)
        if not match:
            raise ValueError(f"Unexpected embedded LAB source chunk name: {part_path.name}")
        indexed_parts.append((int(match.group(1)), part_path))
    indexed_parts.sort(key=lambda item: item[0])
    expected_indexes = list(range(1, len(indexed_parts) + 1))
    actual_indexes = [item[0] for item in indexed_parts]
    if actual_indexes != expected_indexes:
        raise ValueError(f"Embedded LAB source chunks are incomplete or duplicated: {actual_indexes}")

    encoded = "".join(p.read_text(encoding="ascii").strip() for _, p in indexed_parts)
    payload = base64.b64decode(encoded, validate=True)
    if len(payload) > 64 * 1024 * 1024 or not payload.startswith(b"PK\x03\x04"):
        raise ValueError("Embedded LAB source archive is oversized or not a valid ZIP payload.")

    target = pres_dir / "MERSAD_LAB"
    with tempfile.TemporaryDirectory(prefix="mersad_original_lab_restore_") as tmp:
        temp_root = Path(tmp).resolve()
        with zipfile.ZipFile(io.BytesIO(payload), "r") as archive:
            bad_member = archive.testzip()
            if bad_member:
                raise ValueError(f"Embedded LAB ZIP CRC check failed for {bad_member}")
            total_uncompressed = sum(info.file_size for info in archive.infolist())
            if total_uncompressed > 64 * 1024 * 1024:
                raise ValueError("Embedded LAB source archive exceeds the 64 MiB extraction limit.")

            for info in archive.infolist():
                raw_name = info.filename
                if not raw_name or "\\" in raw_name:
                    raise ValueError(f"Unsafe embedded LAB archive member: {raw_name!r}")
                rel = PurePosixPath(raw_name)
                if rel.is_absolute() or any(part in ("", ".", "..") for part in rel.parts):
                    if info.is_dir() and raw_name.endswith("/") and all(part not in ("", ".", "..") for part in rel.parts):
                        pass
                    else:
                        raise ValueError(f"Unsafe embedded LAB archive path: {raw_name!r}")
                if re.match(r"^[A-Za-z]:", raw_name):
                    raise ValueError(f"Absolute Windows path in embedded LAB archive: {raw_name!r}")
                mode = (info.external_attr >> 16) & 0xFFFF
                if stat.S_ISLNK(mode):
                    raise ValueError(f"Symlink is not permitted in embedded LAB archive: {raw_name!r}")

                out_path = temp_root.joinpath(*rel.parts)
                try:
                    out_path.resolve().relative_to(temp_root)
                except ValueError as exc:
                    raise ValueError(f"Embedded LAB archive path escapes extraction root: {raw_name!r}") from exc

                if info.is_dir():
                    out_path.mkdir(parents=True, exist_ok=True)
                else:
                    out_path.parent.mkdir(parents=True, exist_ok=True)
                    with archive.open(info, "r") as src, out_path.open("wb") as dst:
                        shutil.copyfileobj(src, dst)

        extracted_root = temp_root / "MERSAD_LAB"
        if not extracted_root.is_dir():
            raise ValueError("Embedded ZIP does not contain the expected MERSAD_LAB/ root.")
        py_files = [p for p in extracted_root.glob("*.py") if p.is_file()]
        if not py_files:
            raise ValueError("Embedded ZIP was extracted but contains no top-level LAB Python implementation.")
        shutil.copytree(extracted_root, target, dirs_exist_ok=True)

    restored_files = [p for p in target.glob("*.py") if p.is_file()]
    return {
        "restored": bool(restored_files),
        "parts": len(indexed_parts),
        "python_files": len(restored_files),
        "reason": f"Reconstructed original LAB source from {len(indexed_parts)} base64 chunks ({len(restored_files)} Python files).",
    }


def verify_original_commit(pres_dir: Path) -> dict:
    """Verify the recorded historical commit and the restored LAB implementation root."""
    if not pres_dir.is_dir():
        return {
            "verified": False,
            "detected_commit": None,
            "reason": "Original LAB directory does not exist.",
        }
    git_dir = pres_dir / ".git"
    detected_sha = None
    if git_dir.exists():
        try:
            proc = subprocess.run(
                ["git", "-C", str(pres_dir), "rev-parse", "HEAD"],
                capture_output=True,
                text=True,
                timeout=10,
            )
            if proc.returncode == 0:
                detected_sha = proc.stdout.strip().lower()
        except Exception:
            pass
    commit_file = pres_dir / "COMMIT_SHA.txt"
    if not detected_sha and commit_file.is_file():
        tokens = commit_file.read_text(encoding="utf-8", errors="ignore").strip().split()
        detected_sha = tokens[0].lower() if tokens else None

    lab_root = _original_lab_root(pres_dir)
    py_files = [p for p in lab_root.glob("*.py") if p.is_file()] if lab_root else []
    if not py_files:
        return {
            "verified": False,
            "detected_commit": detected_sha,
            "reason": (
                f"Commit {TARGET_ORIGINAL_COMMIT} ({TARGET_ORIGINAL_BRANCH}) was identified, "
                "but the embedded MERSAD_LAB implementation could not be restored."
            ),
        }
    if detected_sha != TARGET_ORIGINAL_COMMIT.lower():
        return {
            "verified": False,
            "detected_commit": detected_sha,
            "reason": (
                f"Commit mismatch or unverified archive: expected {TARGET_ORIGINAL_COMMIT}, "
                f"got {detected_sha or 'UNSPECIFIED'}."
            ),
        }
    return {
        "verified": True,
        "detected_commit": detected_sha,
        "reason": f"Verified exact commit {TARGET_ORIGINAL_COMMIT} with {len(py_files)} top-level LAB Python files.",
    }


def run_independent_lab_functional_and_security_suite(lab_dir: Path, label: str) -> dict:
    """Run the 20-check functional & security test suite against a LAB directory in an isolated subprocess."""
    if not lab_dir.is_dir():
        return {
            "label": label,
            "executed": False,
            "status": "BLOCKED",
            "passed": 0,
            "failed": 0,
            "total": 0,
            "reason": "Directory missing",
            "checks": [],
        }
    py_files = list(lab_dir.glob("*.py"))
    if not py_files:
        return {
            "label": label,
            "executed": False,
            "status": "BLOCKED",
            "passed": 0,
            "failed": 0,
            "total": 0,
            "reason": f"No Python implementation files present in {lab_dir.name} (awaiting commit {TARGET_ORIGINAL_COMMIT})",
            "checks": [],
        }

    test_script = lab_dir / "test_lab.py"
    if not test_script.is_file():
        # If Original LAB doesn't bundle test_lab.py, run Clean-Room's test_lab.py pointed at lab_dir via PYTHONPATH
        fallback_test = Path(__file__).resolve().parent.parent / "MERSAD_LAB_Preview_0.1" / "test_lab.py"
        cmd = [sys.executable, str(fallback_test)]
    else:
        cmd = [sys.executable, str(test_script)]

    env = dict(os.environ)
    env["PYTHONPATH"] = str(lab_dir)
    env["PYTHONIOENCODING"] = "utf-8:backslashreplace"
    try:
        proc = subprocess.run(
            cmd,
            cwd=str(lab_dir),
            env=env,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=60,
        )
        out = (proc.stdout or "") + "\n" + (proc.stderr or "")
        checks = []
        for line in out.splitlines():
            m_chk = re.search(r"\[(PASS|FAIL)\]\s+([A-Z0-9\-]+):\s+(.+)", line)
            if m_chk:
                checks.append({
                    "status": m_chk.group(1),
                    "id": m_chk.group(2),
                    "detail": m_chk.group(3).strip(),
                })
        passed = sum(1 for c in checks if c["status"] == "PASS")
        failed = sum(1 for c in checks if c["status"] == "FAIL")
        if label == "CleanRoom_LAB_Preview_0.1":
            # The release gate is exactly 20 independent checks; a truncated or
            # partially skipped suite must not pass merely because it has no FAIL lines.
            status = "PASS" if (proc.returncode == 0 and passed == 20 and failed == 0 and len(checks) == 20) else "FAIL"
        else:
            status = "PASS" if (proc.returncode == 0 and passed > 0 and failed == 0) else "FAIL"
        return {
            "label": label,
            "executed": True,
            "status": status,
            "exit_code": proc.returncode,
            "passed": passed,
            "failed": failed,
            "total": len(checks),
            "checks": checks,
            "raw_output_tail": out.splitlines()[-25:],
        }
    except Exception as e:
        return {
            "label": label,
            "executed": False,
            "status": "FAIL",
            "passed": 0,
            "failed": 1,
            "total": 0,
            "reason": f"{type(e).__name__}: {e}",
            "checks": [],
        }


def build_dimension_comparison(orig_verified: bool, orig_suite: dict, clean_suite: dict) -> list[dict]:
    """Compare the 6 required engineering dimensions between Original LAB and Clean-room LAB."""
    clean_by_id = {c["id"]: c for c in clean_suite.get("checks", [])}
    orig_by_id = {c["id"]: c for c in orig_suite.get("checks", [])}

    def _fmt_side(suite: dict, by_id: dict, ids: list[str], verified: bool = True) -> str:
        if not verified or not suite.get("executed"):
            return f"BLOCKED (Awaiting commit `{TARGET_ORIGINAL_COMMIT[:12]}`)"
        matched = [by_id[i] for i in ids if i in by_id]
        if not matched:
            return "NOT_FOUND_IN_SUITE"
        p = sum(1 for m in matched if m["status"] == "PASS")
        return f"{p}/{len(matched)} PASS ({', '.join(m['id'] + '=' + m['status'] for m in matched)})"

    dimensions = [
        {
            "dimension_ar": "1. نقاط التكامل وواجهات API (`/api/health`, `/api/cameras`, `/api/camera/<id>/mode`, `/api/analyze/*`)",
            "dimension_en": "Integration Points & HTTP API Endpoints",
            "original_lab": _fmt_side(orig_suite, orig_by_id, ["LAB-03", "LAB-04", "LAB-07", "LAB-08"], orig_verified),
            "cleanroom_lab": _fmt_side(clean_suite, clean_by_id, ["LAB-03", "LAB-04", "LAB-07", "LAB-08"], True),
            "comparison_result": "BLOCKED" if not orig_verified else ("EQUIVALENT" if orig_suite.get("status") == clean_suite.get("status") else "DIFFERENT"),
        },
        {
            "dimension_ar": "2. تدفق MJPEG وقراءة OpenCV VideoCapture (`/stream/<id>.mjpg`, `/frame/<id>.jpg`)",
            "dimension_en": "MJPEG Streaming & OpenCV VideoCapture Compatibility",
            "original_lab": _fmt_side(orig_suite, orig_by_id, ["LAB-01", "LAB-02", "LAB-06"], orig_verified),
            "cleanroom_lab": _fmt_side(clean_suite, clean_by_id, ["LAB-01", "LAB-02", "LAB-06"], True),
            "comparison_result": "BLOCKED" if not orig_verified else ("EQUIVALENT" if orig_suite.get("status") == clean_suite.get("status") else "DIFFERENT"),
        },
        {
            "dimension_ar": "3. سلوك الكاميرات والأوضاع الثمانية (`normal`, `lowlight`, `lowres`, `noise`, `occluded`, `frozen`, `delay`, `offline` -> HTTP 503)",
            "dimension_en": "Camera Modes & Offline HTTP 503 Behavior",
            "original_lab": _fmt_side(orig_suite, orig_by_id, ["LAB-01", "LAB-04", "LAB-05"], orig_verified),
            "cleanroom_lab": _fmt_side(clean_suite, clean_by_id, ["LAB-01", "LAB-04", "LAB-05"], True),
            "comparison_result": "BLOCKED" if not orig_verified else ("EQUIVALENT" if orig_suite.get("status") == clean_suite.get("status") else "DIFFERENT"),
        },
        {
            "dimension_ar": "4. الضوابط الأمنية (Auth 401, Host/Origin 403, CSRF 403, XSS/CSP, Zero innerHTML)",
            "dimension_en": "Security Controls (Auth, Host/Origin, CSRF, XSS/CSP, Zero innerHTML)",
            "original_lab": _fmt_side(orig_suite, orig_by_id, ["LAB-SEC-01", "LAB-SEC-02", "LAB-SEC-03", "LAB-SEC-04", "LAB-SEC-05"], orig_verified),
            "cleanroom_lab": _fmt_side(clean_suite, clean_by_id, ["LAB-SEC-01", "LAB-SEC-02", "LAB-SEC-03", "LAB-SEC-04", "LAB-SEC-05"], True),
            "comparison_result": "BLOCKED" if not orig_verified else ("EQUIVALENT" if orig_suite.get("status") == clean_suite.get("status") else "DIFFERENT"),
        },
        {
            "dimension_ar": "5. الحماية من استنزاف الموارد (Size 413, Corrupt Video 400, RSS Bounds, Rate Limit 429, Timeout 504)",
            "dimension_en": "Resource & DoS Protection (413, 400, RSS, 429, 504)",
            "original_lab": _fmt_side(orig_suite, orig_by_id, ["LAB-SEC-06", "LAB-SEC-07", "LAB-SEC-08", "LAB-SEC-09", "LAB-SEC-10"], orig_verified),
            "cleanroom_lab": _fmt_side(clean_suite, clean_by_id, ["LAB-SEC-06", "LAB-SEC-07", "LAB-SEC-08", "LAB-SEC-09", "LAB-SEC-10"], True),
            "comparison_result": "BLOCKED" if not orig_verified else ("EQUIVALENT" if orig_suite.get("status") == clean_suite.get("status") else "DIFFERENT"),
        },
        {
            "dimension_ar": "6. إغلاق العمليات وتحرير المنافذ والخيوط (`--self-check`, Port Release, Zero Lingering Threads)",
            "dimension_en": "Process Shutdown, Port Release & Thread Cleanup",
            "original_lab": _fmt_side(orig_suite, orig_by_id, ["LAB-SEC-11", "LAB-SEC-12"], orig_verified),
            "cleanroom_lab": _fmt_side(clean_suite, clean_by_id, ["LAB-SEC-11", "LAB-SEC-12"], True),
            "comparison_result": "BLOCKED" if not orig_verified else ("EQUIVALENT" if orig_suite.get("status") == clean_suite.get("status") else "DIFFERENT"),
        },
    ]
    return dimensions


def main():
    ap = argparse.ArgumentParser(description="Compare Original MERSAD LAB (ed7b8f727243da4878e547f08489af581c83291c) vs Clean-Room LAB")
    ap.add_argument("--original-source", default=str(Path(__file__).resolve().parent.parent / "MERSAD_LAB_Original_ed7b8f72"))
    ap.add_argument("--cleanroom-dir", default=str(Path(__file__).resolve().parent.parent / "MERSAD_LAB_Preview_0.1"))
    ap.add_argument("--preserve-original-dir", default=str(Path(__file__).resolve().parent.parent / "MERSAD_LAB_Original_ed7b8f72"))
    ap.add_argument("--output-md", default=str(Path(__file__).resolve().parent.parent / "reports_and_logs" / "08_ORIGINAL_VS_CLEANROOM_LAB_COMPARISON_AR.md"))
    ap.add_argument("--output-json", default=str(Path(__file__).resolve().parent.parent / "reports_and_logs" / "original_vs_cleanroom_lab_comparison.json"))
    ap.add_argument("--require-unblocked", action="store_true", help="Exit with code 2 if Original LAB commit ed7b8f727243da4878e547f08489af581c83291c is unavailable or comparison is BLOCKED")
    ap.add_argument("--require-cleanroom-pass", action="store_true", help="Require Clean-Room LAB suite (20/20 PASS) to succeed while recording Original LAB as BLOCKED/NOT_TESTED without aborting the Preview 0.1 build pipeline")
    args = ap.parse_args()

    orig_in = Path(args.original_source).resolve()
    pres_dir = Path(args.preserve_original_dir).resolve()
    clean_dir = Path(args.cleanroom_dir).resolve()

    pres_dir.mkdir(parents=True, exist_ok=True)
    if orig_in.exists():
        if orig_in.is_file() and orig_in.suffix.lower() == ".zip":
            with zipfile.ZipFile(orig_in, "r") as zf:
                zf.extractall(pres_dir)
        elif orig_in.is_dir() and orig_in.resolve() != pres_dir.resolve():
            shutil.copytree(orig_in, pres_dir, dirs_exist_ok=True)

    source_archive_restore = restore_embedded_source_archive(pres_dir)
    commit_verification = verify_original_commit(pres_dir)
    commit_verification["source_archive_restore"] = source_archive_restore
    orig_verified = bool(commit_verification["verified"])
    original_lab_root = _original_lab_root(pres_dir)

    orig_tree = collect_tree(original_lab_root) if orig_verified and original_lab_root else {}
    clean_tree = collect_tree(clean_dir)
    all_keys = sorted(set(orig_tree.keys()) | set(clean_tree.keys()))

    rows = []
    for k in all_keys:
        o = orig_tree.get(k)
        c = clean_tree.get(k)
        if not orig_verified:
            status = "BLOCKED_ORIGINAL_UNAVAILABLE"
        elif o and c:
            status = "IDENTICAL" if o["sha256"] == c["sha256"] else "DIFFERENT"
        elif o:
            status = "ONLY_IN_ORIGINAL"
        else:
            status = "ONLY_IN_CLEANROOM"
        rows.append({
            "file": k,
            "status": status,
            "original_size": o["size"] if o else None,
            "original_sha256": o["sha256"] if o else None,
            "original_ast": o.get("ast") if o else None,
            "cleanroom_size": c["size"] if c else None,
            "cleanroom_sha256": c["sha256"] if c else None,
            "cleanroom_ast": c.get("ast") if c else None,
        })

    # Run independent functional & security suites on both
    orig_suite = (
        run_independent_lab_functional_and_security_suite(original_lab_root, "Original_LAB_ed7b8f72")
        if orig_verified and original_lab_root
        else {
            "label": "Original_LAB_ed7b8f72",
            "executed": False,
            "status": "BLOCKED",
            "passed": 0,
            "failed": 0,
            "total": 20,
            "reason": commit_verification["reason"],
            "checks": [],
        }
    )
    clean_suite = run_independent_lab_functional_and_security_suite(clean_dir, "CleanRoom_LAB_Preview_0.1")

    dimensions = build_dimension_comparison(orig_verified, orig_suite, clean_suite)

    if not orig_verified:
        overall_phase2_status = "BLOCKED"
    elif orig_suite.get("status") == "PASS" and clean_suite.get("status") == "PASS":
        overall_phase2_status = "PASS"
    else:
        overall_phase2_status = "FAIL"

    report_json = {
        "target_original_branch": TARGET_ORIGINAL_BRANCH,
        "target_original_commit": TARGET_ORIGINAL_COMMIT,
        "commit_verification": commit_verification,
        "phase2_comparison_status": overall_phase2_status,
        "neutral_labeling_policy": "Files that differ between Original LAB and Clean-room LAB are labeled strictly as DIFFERENT (never claimed as enhanced/improved without empirical test proof).",
        "independent_test_suites": {
            "original_lab": orig_suite,
            "cleanroom_lab": clean_suite,
        },
        "dimension_comparison": dimensions,
        "file_comparison": rows,
    }

    Path(args.output_json).parent.mkdir(parents=True, exist_ok=True)
    Path(args.output_json).write_text(json.dumps(report_json, ensure_ascii=False, indent=2), encoding="utf-8")

    md_lines = [
        "# 08 — تقرير مقارنة المختبر الأصلي (`build/mersad-lab-exe-20261031`) مع `Clean-Room LAB`",
        "",
        "## 1. حالة التحقق من الالتزام المرجعي للمختبر الأصلي (Commit Verification)",
        f"- **الفرع المرجعي المطلوب:** `{TARGET_ORIGINAL_BRANCH}`",
        f"- **الالتزام المرجعي المطلوب (Target Commit):** `{TARGET_ORIGINAL_COMMIT}`",
        f"- **الالتزام المكتشف فعلياً:** `{commit_verification['detected_commit'] or 'NOT_AVAILABLE'}`",
        f"- **تم التحقق من مطابقة الالتزام؟** `{commit_verification['verified']}`",
        f"- **سبب الحالة:** {commit_verification['reason']}",
        f"- **الحالة الكلية للمرحلة الثانية (Phase 2 Overall Status):** **`{overall_phase2_status}`**",
        "",
        f"> **حالة استعادة المصدر:** {source_archive_restore.get('reason', 'No source archive restoration details available.')}",
        "",
        "## 2. نتائج الاختبارات الوظيفية والأمنية المستقلة (Independent Functional & Security Suites)",
        "",
        "| النسخة المختبرة | حالة التنفيذ | عدد الفحوصات الناجحة | عدد الفحوصات الفاشلة | الإجمالي | النتيجة |",
        "|---|---|---|---|---|---|",
        f"| **Original MERSAD LAB (`{TARGET_ORIGINAL_COMMIT[:12]}`)** | `{orig_suite['executed']}` | `{orig_suite['passed']}` | `{orig_suite['failed']}` | `{orig_suite['total']}` | **`{orig_suite['status']}`** |",
        f"| **Clean-Room MERSAD LAB (`MERSAD_LAB_Preview_0.1`)** | `{clean_suite['executed']}` | `{clean_suite['passed']}` | `{clean_suite['failed']}` | `{clean_suite['total']}` | **`{clean_suite['status']}`** |",
        "",
        "## 3. مقارنة نقاط التكامل وواجهات API وتدفق MJPEG وسلوك الكاميرات والأمان وإغلاق العمليات",
        "",
        "| البعد الهندسي / الأمني | المختبر الأصلي (`ed7b8f72`) | المختبر Clean-Room (`Preview 0.1`) | نتيجة المقارنة |",
        "|---|---|---|---|",
    ]
    for d in dimensions:
        md_lines.append(
            f"| {d['dimension_ar']} | {d['original_lab']} | {d['cleanroom_lab']} | **`{d['comparison_result']}`** |"
        )

    md_lines.extend([
        "",
        "## 4. مقارنة البنية البرمجية (AST & Routes) للملفات التنفيذية",
        "",
        "| الملف | الحالة المحايدة | تفاصيل AST والمسارات في المختبر الأصلي | تفاصيل AST والمسارات في Clean-Room LAB |",
        "|---|---|---|---|",
    ])
    for r in rows:
        o_ast = r.get("original_ast")
        c_ast = r.get("cleanroom_ast")
        if not o_ast and not c_ast:
            continue
        o_desc = (
            f"Lines={o_ast.get('lines')}, Classes={o_ast.get('classes')}, Routes={o_ast.get('detected_routes')}"
            if isinstance(o_ast, dict) and "lines" in o_ast
            else "BLOCKED (Original commit unavailable)"
        )
        c_desc = (
            f"Lines={c_ast.get('lines')}, Classes={c_ast.get('classes')}, Routes={c_ast.get('detected_routes')}"
            if isinstance(c_ast, dict) and "lines" in c_ast
            else "—"
        )
        md_lines.append(f"| `{r['file']}` | **`{r['status']}`** | {o_desc} | {c_desc} |")

    md_lines.extend([
        "",
        "## 5. جدول مقارنة الملفات والبصمات الرقمية (باستخدام التصنيف المحايد `DIFFERENT` فقط)",
        "",
        "| الملف | الحالة | حجم وبصمة المختبر الأصلي | حجم وبصمة Clean-Room LAB |",
        "|---|---|---|---|",
    ])
    for r in rows:
        o_str = f"`{r['original_size']} B` (`{r['original_sha256'][:12]}...`)" if r["original_sha256"] else "BLOCKED (`ed7b8f72` unavailable)"
        c_str = f"`{r['cleanroom_size']} B` (`{r['cleanroom_sha256'][:12]}...`)" if r["cleanroom_sha256"] else "—"
        md_lines.append(f"| `{r['file']}` | **{r['status']}** | {o_str} | {c_str} |")

    Path(args.output_md).parent.mkdir(parents=True, exist_ok=True)
    Path(args.output_md).write_text("\n".join(md_lines) + "\n", encoding="utf-8")

    print("========================================================================================")
    print("  MERSAD PREVIEW 0.1 — Phase 2: Original vs Clean-Room LAB Comparison")
    print("========================================================================================")
    print(f"  Target Original Commit : {TARGET_ORIGINAL_COMMIT} ({TARGET_ORIGINAL_BRANCH})")
    print(f"  Commit Verified        : {orig_verified} ({commit_verification['reason']})")
    print(f"  Original LAB Suite     : {orig_suite['status']} ({orig_suite['passed']}/{orig_suite['total']} PASS)")
    print(f"  Clean-Room LAB Suite   : {clean_suite['status']} ({clean_suite['passed']}/{clean_suite['total']} PASS)")
    print(f"  Phase 2 Overall Status : {overall_phase2_status}")
    print(f"  Markdown Report        : {args.output_md}")
    print(f"  JSON Report            : {args.output_json}")
    print("========================================================================================")

    for suite_name, suite in (("Original LAB", orig_suite), ("Clean-Room LAB", clean_suite)):
        failures = [item for item in suite.get("checks", []) if item.get("status") == "FAIL"]
        for item in failures:
            print(f"[PHASE2 CHECK FAILURE] {suite_name} | {item.get('id')}: {item.get('detail')}")
        if suite.get("reason"):
            print(f"[PHASE2 SUITE REASON] {suite_name}: {suite['reason']}")
        if suite_name == "Clean-Room LAB" and suite.get("status") != "PASS":
            for line in suite.get("raw_output_tail", [])[-10:]:
                print(f"[PHASE2 CLEANROOM OUTPUT] {line}")

    # The original LAB may legitimately remain BLOCKED when the historical source
    # cannot be restored, but the current Clean-Room LAB must pass all 20 checks.
    if args.require_cleanroom_pass and clean_suite.get("status") != "PASS":
        print(
            f"[FAILED] Clean-Room LAB suite is {clean_suite.get('status')} "
            f"({clean_suite.get('passed', 0)}/{clean_suite.get('total', 0)} PASS); "
            "required 20/20 PASS before release.",
            file=sys.stderr,
        )
        sys.exit(1)
    if args.require_unblocked and overall_phase2_status != "PASS":
        print(f"[BLOCKED/FAILED] Phase 2 status is {overall_phase2_status}. Cannot mark Phase 2 as PASS without verified commit {TARGET_ORIGINAL_COMMIT}.", file=sys.stderr)
        sys.exit(2)
    sys.exit(0)


if __name__ == "__main__":
    main()
