#!/usr/bin/env python3
"""
Deterministic deployment & GitHub Actions workflow_dispatch runner for MERSAD Preview 0.1.
Enforces:
  1. Target branch: release/mersad-preview-0.1 (never historical preview/mersad-ai-lab-0.1-20261105).
  2. Code commits verified: AI 25131918a981ac2ac37923d4c738d9f93cdcbc5b, LAB e9284356f4d1a8205946d5893121c6f8a2f22012.
  3. Main branch untouched: 25c9e5bba30dc8f921675e12c23a53571be895c1.
  4. Push without --force, followed by remote SHA verification via git ls-remote.
  5. Explicit check for GitHub CLI (gh) installation and authentication (gh auth status);
     if missing or unauthenticated, exits non-zero with a clear error and never claims success.
"""
import argparse
import json
import os
import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path

TARGET_BRANCH = "release/mersad-preview-0.1"
EXPECTED_AI_CODE_SHA = "25131918a981ac2ac37923d4c738d9f93cdcbc5b"
EXPECTED_LAB_CODE_SHA = "e9284356f4d1a8205946d5893121c6f8a2f22012"
EXPECTED_MAIN_SHA = "25c9e5bba30dc8f921675e12c23a53571be895c1"
WORKFLOW_FILE = "release-mersad-preview-0.1-windows.yml"
DEFAULT_REMOTE_URL = "https://github.com/alinon9/MERSAD-AI-.git"


def run_cmd(cmd, cwd=None, env=None):
    proc = subprocess.run(cmd, cwd=cwd, env=env, text=True, capture_output=True)
    return proc.returncode, proc.stdout.strip(), proc.stderr.strip()


def execute_deployment(bundle_path: Path, remote_url: str, env_override=None, skip_gh_precheck_for_git_test=False) -> dict:
    env = os.environ.copy()
    if env_override:
        env.update(env_override)

    report = {
        "timestamp": time.strftime("%Y-%m-%d %H:%M:%S"),
        "target_branch": TARGET_BRANCH,
        "expected_ai_code_sha": EXPECTED_AI_CODE_SHA,
        "expected_lab_code_sha": EXPECTED_LAB_CODE_SHA,
        "expected_main_sha": EXPECTED_MAIN_SHA,
        "workflow_file": WORKFLOW_FILE,
        "remote_url": remote_url,
        "steps": [],
        "status": "FAIL",
        "build_triggered": False,
        "run_id": None,
    }

    def add_step(name, ok, detail):
        report["steps"].append({"step": name, "ok": bool(ok), "detail": detail})

    # Step 1: Clone bundle and verify branches/commits
    with tempfile.TemporaryDirectory(prefix="mersad_deploy_") as tmpdir:
        work_repo = Path(tmpdir) / "repo"
        rc, out, err = run_cmd(["git", "clone", str(bundle_path), str(work_repo)], env=env)
        if rc != 0:
            add_step("clone_bundle", False, f"git clone failed: {err or out}")
            return report
        add_step("clone_bundle", True, f"Cloned bundle {bundle_path.name}")

        rc, main_sha, err = run_cmd(["git", "rev-parse", "origin/main"], cwd=str(work_repo), env=env)
        if rc != 0 or main_sha != EXPECTED_MAIN_SHA:
            add_step("verify_main_untouched", False, f"main SHA mismatch: got {main_sha}, expected {EXPECTED_MAIN_SHA}")
            return report
        add_step("verify_main_untouched", True, f"main branch untouched at {main_sha}")

        rc, out, err = run_cmd(["git", "checkout", TARGET_BRANCH], cwd=str(work_repo), env=env)
        if rc != 0:
            add_step("checkout_release_branch", False, f"Failed to checkout {TARGET_BRANCH}: {err or out}")
            return report

        rc, head_sha, err = run_cmd(["git", "rev-parse", "HEAD"], cwd=str(work_repo), env=env)
        rc_anc, _, _ = run_cmd(["git", "merge-base", "--is-ancestor", EXPECTED_AI_CODE_SHA, "HEAD"], cwd=str(work_repo), env=env)
        if rc != 0 or rc_anc != 0:
            add_step("verify_release_commit_lineage", False, f"HEAD {head_sha} does not descend from {EXPECTED_AI_CODE_SHA}")
            return report
        report["local_head_sha"] = head_sha
        add_step("verify_release_commit_lineage", True, f"Checked out {TARGET_BRANCH} at HEAD={head_sha} (contains code commit {EXPECTED_AI_CODE_SHA})")

        # Step 2: Push to remote without --force
        run_cmd(["git", "remote", "set-url", "origin", remote_url], cwd=str(work_repo), env=env)
        rc_push, out_push, err_push = run_cmd(
            ["git", "push", "-u", "origin", f"refs/heads/{TARGET_BRANCH}:refs/heads/{TARGET_BRANCH}"],
            cwd=str(work_repo),
            env=env,
        )
        if rc_push != 0:
            add_step("git_push_release_branch", False, f"git push to {remote_url} failed: {err_push or out_push}")
            report["error"] = f"GIT_PUSH_FAILED: {err_push or out_push}"
            return report
        add_step("git_push_release_branch", True, f"Pushed {TARGET_BRANCH} without --force to {remote_url}")

        # Step 3: Verify remote SHA via git ls-remote
        rc_ls, out_ls, err_ls = run_cmd(
            ["git", "ls-remote", "origin", f"refs/heads/{TARGET_BRANCH}"],
            cwd=str(work_repo),
            env=env,
        )
        remote_sha = out_ls.split()[0] if (rc_ls == 0 and out_ls.split()) else ""
        if remote_sha != head_sha:
            add_step("verify_remote_sha", False, f"Remote SHA ({remote_sha}) != Local HEAD ({head_sha})")
            report["error"] = f"REMOTE_SHA_MISMATCH: {remote_sha} != {head_sha}"
            return report
        report["verified_remote_sha"] = remote_sha
        add_step("verify_remote_sha", True, f"Verified remote SHA on origin matches local HEAD: {remote_sha}")

        # Step 4: Check gh CLI installation and authentication
        gh_bin = shutil.which("gh", path=env.get("PATH", ""))
        if not gh_bin:
            msg = "GitHub CLI (gh) is NOT installed in PATH. Halting without claiming workflow trigger success."
            add_step("verify_gh_cli_installed", False, msg)
            report["error"] = f"GH_CLI_NOT_INSTALLED: {msg}"
            return report
        add_step("verify_gh_cli_installed", True, f"Found gh binary at {gh_bin}")

        rc_auth, out_auth, err_auth = run_cmd([gh_bin, "auth", "status"], cwd=str(work_repo), env=env)
        if rc_auth != 0:
            msg = f"GitHub CLI (gh) is NOT authenticated ({err_auth or out_auth}). Halting without claiming workflow trigger success."
            add_step("verify_gh_cli_authenticated", False, msg)
            report["error"] = f"GH_CLI_UNAUTHENTICATED: {msg}"
            return report
        add_step("verify_gh_cli_authenticated", True, "gh auth status verified")

        # Step 5: Trigger workflow_dispatch on release/mersad-preview-0.1
        rc_wf, out_wf, err_wf = run_cmd(
            [gh_bin, "workflow", "run", WORKFLOW_FILE, "--ref", TARGET_BRANCH, "-f", "run_extended_stress=true"],
            cwd=str(work_repo),
            env=env,
        )
        if rc_wf != 0:
            add_step("trigger_workflow_dispatch", False, f"gh workflow run failed: {err_wf or out_wf}")
            report["error"] = f"GH_WORKFLOW_RUN_FAILED: {err_wf or out_wf}"
            return report
        report["build_triggered"] = True
        add_step("trigger_workflow_dispatch", True, f"Triggered {WORKFLOW_FILE} on --ref {TARGET_BRANCH}")
        report["status"] = "PASS"
        return report


def run_self_test(repo_root: Path) -> dict:
    bundle = repo_root / "reports_and_logs" / "mersad_preview_0_1_verifiable_history.bundle"
    bat_file = repo_root / "PUSH_CANDIDATE_9491BCD_TO_GITHUB_ACTIONS.bat"
    bat_text = bat_file.read_text(encoding="utf-8")

    checks = []
    checks.append(("BAT_USES_RELEASE_BRANCH", 'set "TARGET_BRANCH=release/mersad-preview-0.1"' in bat_text and "preview/mersad-ai-lab-0.1-20261105" not in bat_text))
    checks.append(("BAT_USES_FINAL_COMMITS", EXPECTED_AI_CODE_SHA in bat_text and EXPECTED_LAB_CODE_SHA in bat_text))
    checks.append(("BAT_PRESERVES_MAIN_AND_NO_FORCE", EXPECTED_MAIN_SHA in bat_text and "git push --force" not in bat_text and "git push -f" not in bat_text and " -f " not in bat_text.split("gh workflow run")[0]))
    checks.append(("BAT_VERIFIES_REMOTE_SHA", "git ls-remote origin" in bat_text and 'if /i not "!REMOTE_SHA!"=="!LOCAL_HEAD_SHA!"' in bat_text))
    checks.append(("BAT_FAILS_WHEN_GH_MISSING_OR_UNAUTH", "where gh >nul 2>&1" in bat_text and "gh auth status >nul 2>&1" in bat_text))

    with tempfile.TemporaryDirectory(prefix="mersad_bare_remote_") as tmpdir:
        bare_remote = Path(tmpdir) / "origin.git"
        subprocess.run(["git", "init", "--bare", str(bare_remote)], check=True, capture_output=True)

        # Test A: Missing gh in PATH must fail AFTER verifying local bare push and remote SHA
        res_no_gh = execute_deployment(bundle, str(bare_remote), env_override={"PATH": "/usr/bin:/bin"})
        checks.append(("LOCAL_BARE_PUSH_AND_LS_REMOTE_SHA_MATCH", res_no_gh.get("verified_remote_sha") == res_no_gh.get("local_head_sha") and bool(res_no_gh.get("verified_remote_sha"))))
        checks.append(("MISSING_GH_HALTS_WITH_ERROR", res_no_gh["status"] == "FAIL" and res_no_gh["build_triggered"] is False and "GH_CLI_NOT_INSTALLED" in res_no_gh.get("error", "")))

        # Test B: Unauthenticated gh must fail with GH_CLI_UNAUTHENTICATED
        fake_bin_dir = Path(tmpdir) / "fake_bin_unauth"
        fake_bin_dir.mkdir()
        fake_gh = fake_bin_dir / "gh"
        fake_gh.write_text("#!/bin/sh\nexit 1\n")
        fake_gh.chmod(0o755)
        res_unauth = execute_deployment(bundle, str(bare_remote), env_override={"PATH": f"{fake_bin_dir}:/usr/bin:/bin"})
        checks.append(("UNAUTH_GH_HALTS_WITH_ERROR", res_unauth["status"] == "FAIL" and res_unauth["build_triggered"] is False and "GH_CLI_UNAUTHENTICATED" in res_unauth.get("error", "")))

    all_ok = all(ok for _, ok in checks)
    return {"all_passed": all_ok, "checks": [{"name": k, "passed": v} for k, v in checks]}


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--self-test", action="store_true")
    ap.add_argument("--live", action="store_true")
    args = ap.parse_args()
    root = Path(__file__).resolve().parent.parent
    if args.self_test:
        st = run_self_test(root)
        print(json.dumps(st, indent=2, ensure_ascii=False))
        sys.exit(0 if st["all_passed"] else 1)
    if args.live:
        rep = execute_deployment(root / "reports_and_logs" / "mersad_preview_0_1_verifiable_history.bundle", DEFAULT_REMOTE_URL)
        print(json.dumps(rep, indent=2, ensure_ascii=False))
        sys.exit(0 if rep["status"] == "PASS" else 1)
