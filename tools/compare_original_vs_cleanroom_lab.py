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
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import zipfile
from pathlib import Path

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


def verify_original_commit(pres_dir: Path) -> dict:
    """Verify whether pres_dir contains the authentic Original LAB from commit ed7b8f727243da4878e547f08489af581c83291c."""
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
        detected_sha = commit_file.read_text(encoding="utf-8", errors="ignore").strip().split()[0].lower()

    py_files = [p.name for p in pres_dir.rglob("*.py") if "__pycache__" not in str(p)]
    if not py_files:
        return {
            "verified": False,
            "detected_commit": detected_sha,
            "reason": (
                f"Commit {TARGET_ORIGINAL_COMMIT} ({TARGET_ORIGINAL_BRANCH}) has not been restored yet "
                "(0 Python source files present in MERSAD_LAB_Original_ed7b8f72)."
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
        "reason": f"Verified exact commit {TARGET_ORIGINAL_COMMIT} with {len(py_files)} Python files.",
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
    try:
        proc = subprocess.run(cmd, cwd=str(lab_dir), env=env, capture_output=True, text=True, timeout=60)
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
    args = ap.parse_args()

    orig_in = Path(args.original_source)
    pres_dir = Path(args.preserve_original_dir)
    clean_dir = Path(args.cleanroom_dir)

    pres_dir.mkdir(parents=True, exist_ok=True)
    if orig_in.exists():
        if orig_in.is_file() and orig_in.suffix.lower() == ".zip":
            with zipfile.ZipFile(orig_in, "r") as zf:
                zf.extractall(pres_dir)
        elif orig_in.is_dir() and orig_in.resolve() != pres_dir.resolve():
            shutil.copytree(orig_in, pres_dir, dirs_exist_ok=True)

    commit_verification = verify_original_commit(pres_dir)
    orig_verified = bool(commit_verification["verified"])

    orig_tree = collect_tree(pres_dir) if orig_verified else {}
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
        run_independent_lab_functional_and_security_suite(pres_dir, "Original_LAB_ed7b8f72")
        if orig_verified
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
        "> **قاعدة صارمة:** نظراً لعدم توفر أرشيف الالتزام `ed7b8f727243da4878e547f08489af581c83291c` في بيئة الفحص الحالية دون اتصال بـ GitHub، فإن حالة المقارنة تُصنف رسمياً **`BLOCKED`** ولا يُسمح باعتبار المقارنة ناجحة (`PASS`) حتى استعادة الالتزام المحدد وتشغيل هذه الأداة عليه.",
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

    if args.require_unblocked and overall_phase2_status != "PASS":
        print(f"[BLOCKED/FAILED] Phase 2 status is {overall_phase2_status}. Cannot mark Phase 2 as PASS without verified commit {TARGET_ORIGINAL_COMMIT}.", file=sys.stderr)
        sys.exit(2)
    sys.exit(0)


if __name__ == "__main__":
    main()
