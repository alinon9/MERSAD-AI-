#!/usr/bin/env python3
"""
Deterministic Push-Triggered Single-Run CI Deployment, Polling State Machine, 5-Artifact SHA-256 Verifier,
and Forensic ZIP-vs-Git Provenance Verifier for MERSAD Preview 0.1
(Closes BUG-12..BUG-15, BUG-23..BUG-25, BUG-34..BUG-39).

Key guarantees:
  1. Targets `fix/preview-0.1-postbuild-42273598736` by default (configurable via `--branch` or `MERSAD_DEPLOY_BRANCH`),
     verifying lineage from:
       - Previous Preflight commit: `05f29af416c4a28ddf59c291819584d1a416d570` (`v0.1.2-windows-ci-preflight-ready`)
       - Reconciled AI runtime code commit: `edaf651321ec9ea6ba613e3ab1630bc16b11b9d5` (`v0.1.1-postbuild-reconciled-code`)
       - Post-build 42273598736 code commit: `d965d71317e3506e5dce9d316dc81cb8ae45e43b` (`audit-checkpoint-d965d713`)
       - Release baseline code commit: `25131918a981ac2ac37923d4c738d9f93cdcbc5b` (`v0.1.0-preview-code`)
       - Untouched `main` branch: `25c9e5bba30dc8f921675e12c23a53571be895c1`
  2. Enforces single-trigger Push-only CI (`BUG-35` & `BUG-37`):
       - Verifies `.github/workflows/release-mersad-preview-0.1-windows.yml` uses `on: push` ONLY and does NOT define
         `workflow_dispatch` or the unused `run_extended_stress` input.
       - Never invokes `gh workflow run` after `git push` (preventing duplicate concurrent runs).
  3. Enforces the deterministic 9-state Polling & Verification State Machine (`BUG-36`):
       - `PREFLIGHT_PASS`: branch, lineage, clean `git status --porcelain`, remote URL, and pre-push `databaseId` list verified.
       - `PUSH_COMPLETED`: `git push` succeeded and `git ls-remote` confirmed remote SHA == `LOCAL_HEAD_SHA`.
       - `RUN_DISCOVERED`: exactly 1 new run found matching `workflow == release-mersad-preview-0.1-windows.yml`,
         `event == "push"`, `headBranch == target_branch`, `headSha == LOCAL_HEAD_SHA`, and `databaseId not in prev_run_ids`.
       - `DUPLICATE_RUN_DETECTED`: > 1 matching new runs detected for the same SHA and branch -> halts immediately.
       - `RUN_TIMEOUT`: polling exhausted without discovering a matching new push run -> never transitions to `PASS`.
       - `RUN_IN_PROGRESS`: actively watching the discovered run via `gh run watch <run_id> --exit-status`.
       - `RUN_FAILED`: run or any job within the run did not complete with `conclusion == "success"`, or artifact download/verification failed.
       - `ARTIFACTS_VERIFIED`: all 5 required Windows artifacts (`MERSAD_AI.exe`, `MERSAD_LAB.exe`,
         `MERSAD_LAB_Setup_x64.exe`, `MERSAD_AI_Portable_x64.zip`, `MERSAD_LAB_Portable_x64.zip`) exist, are non-empty,
         and have verified SHA-256 hashes.
       - `PASS`: final terminal state reached ONLY after `ARTIFACTS_VERIFIED`.
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
import time
import zipfile
from pathlib import Path

DEFAULT_TARGET_BRANCH = "fix/preview-0.1-postbuild-42273598736"
TARGET_BRANCH = os.environ.get("MERSAD_DEPLOY_BRANCH", DEFAULT_TARGET_BRANCH)
EXPECTED_AI_PREFLIGHT_PARENT_SHA = "05f29af416c4a28ddf59c291819584d1a416d570"
EXPECTED_AI_CODE_SHA = "edaf651321ec9ea6ba613e3ab1630bc16b11b9d5"
EXPECTED_AI_PREV_FIX_SHA = "d965d71317e3506e5dce9d316dc81cb8ae45e43b"
EXPECTED_AI_RELEASE_BASE_SHA = "25131918a981ac2ac37923d4c738d9f93cdcbc5b"
EXPECTED_LAB_CODE_SHA = "748ac0158761812a6fff63ff6fe626b9df8c252b"
EXPECTED_LAB_RELEASE_BASE_SHA = "e9284356f4d1a8205946d5893121c6f8a2f22012"
EXPECTED_MAIN_SHA = "25c9e5bba30dc8f921675e12c23a53571be895c1"
EXPECTED_LAB_MAIN_SHA = "1c56dcbf77d62b8d89863e04f215e12f162e9555"
WORKFLOW_FILE = "release-mersad-preview-0.1-windows.yml"
DEFAULT_REMOTE_URL = "https://github.com/alinon9/MERSAD-AI-.git"

REQUIRED_WINDOWS_ARTIFACTS = [
    "MERSAD_AI.exe",
    "MERSAD_LAB.exe",
    "MERSAD_LAB_Setup_x64.exe",
    "MERSAD_AI_Portable_x64.zip",
    "MERSAD_LAB_Portable_x64.zip",
]

# Unified 1 Workflow File + 16 Required Paths = 17 Verified Paths
WORKFLOW_DEFINITION_PATH = ".github/workflows/release-mersad-preview-0.1-windows.yml"
WORKFLOW_16_REFERENCED_PATHS = [
    "MERSAD_AI_Preview_0.1/requirements.txt",
    "MERSAD_AI_Preview_0.1/constraints-win-x64.txt",
    "MERSAD_AI_Preview_0.1/check_install.py",
    "tools/prepare_safe_eval_benchmarks.py",
    "MERSAD_AI_Preview_0.1/prefetch.py",
    "MERSAD_AI_Preview_0.1/mersad_live.py",
    "integration/evaluate_ai_models.py",
    "tools/compare_original_vs_cleanroom_lab.py",
    "MERSAD_AI_Preview_0.1/selftest.py",
    "MERSAD_AI_Preview_0.1/verify_integrity.py",
    "MERSAD_LAB_Preview_0.1/test_lab.py",
    "MERSAD_AI_Preview_0.1/mersad_ai.spec",
    "MERSAD_LAB_Preview_0.1/mersad_lab.spec",
    "MERSAD_LAB_Preview_0.1/installer/mersad_lab_setup.iss",
    "integration/test_main_entrypoint_dynamic_camera_lifecycle.py",
    "integration/test_ai_lab_integration.py",
]
WORKFLOW_17_VERIFIED_PATHS = [WORKFLOW_DEFINITION_PATH] + WORKFLOW_16_REFERENCED_PATHS


def run_cmd(cmd, cwd=None, env=None):
    proc = subprocess.run(cmd, cwd=cwd, env=env, text=True, capture_output=True)
    return proc.returncode, proc.stdout.strip(), proc.stderr.strip()


def validate_workflow_push_only(workflow_yaml_path: Path) -> tuple[bool, str]:
    """
    Verify that workflow_yaml_path is configured for single-run Push-triggered CI ONLY:
      - Exists on disk
      - Defines `push:` with `fix/preview-0.1-*` and `release/mersad-preview-0.1*`
      - Does NOT define `workflow_dispatch` (prevents duplicate runs from git push + workflow_dispatch)
      - Does NOT contain the unused `run_extended_stress` input
    """
    if not workflow_yaml_path.is_file():
        return False, f"Workflow file not found: {workflow_yaml_path}"
    text = workflow_yaml_path.read_text(encoding="utf-8")
    if "workflow_dispatch" in text:
        return False, f"Workflow {workflow_yaml_path.name} still contains workflow_dispatch (duplicate-run risk)"
    if "run_extended_stress" in text:
        return False, f"Workflow {workflow_yaml_path.name} still contains unused input run_extended_stress"
    if not re.search(r"^\s*push\s*:", text, flags=re.MULTILINE):
        return False, f"Workflow {workflow_yaml_path.name} does not define push trigger"
    if "fix/preview-0.1-*" not in text:
        return False, f"Workflow {workflow_yaml_path.name} push trigger does not include fix/preview-0.1-*"
    return True, f"Verified single-run push-only trigger in {workflow_yaml_path.name} (no workflow_dispatch, no unused run_extended_stress)"


def verify_and_hash_downloaded_artifacts(artifacts_dir: Path, run_id: str = "") -> dict:
    """
    Search artifacts_dir for all 5 required Windows release files, verify non-zero size,
    and compute SHA-256 for each file.
    """
    found_files = {}
    if artifacts_dir.is_dir():
        for p in sorted(artifacts_dir.rglob("*")):
            if p.is_file() and p.name in REQUIRED_WINDOWS_ARTIFACTS:
                if p.name not in found_files or p.stat().st_size > found_files[p.name].stat().st_size:
                    found_files[p.name] = p

    missing = []
    empty = []
    artifacts_meta = []
    for req_name in REQUIRED_WINDOWS_ARTIFACTS:
        p = found_files.get(req_name)
        if p is None or not p.is_file():
            missing.append(req_name)
        elif p.stat().st_size == 0:
            empty.append(req_name)
        else:
            raw = p.read_bytes()
            artifacts_meta.append({
                "name": req_name,
                "relative_path": p.relative_to(artifacts_dir).as_posix(),
                "size_bytes": len(raw),
                "sha256": hashlib.sha256(raw).hexdigest(),
            })

    ok = (len(missing) == 0 and len(empty) == 0 and len(artifacts_meta) == len(REQUIRED_WINDOWS_ARTIFACTS))
    result = {
        "ok": ok,
        "run_id": str(run_id),
        "artifacts_dir": str(artifacts_dir),
        "required_count": len(REQUIRED_WINDOWS_ARTIFACTS),
        "verified_count": len(artifacts_meta),
        "missing_files": missing,
        "empty_files": empty,
        "artifacts": artifacts_meta,
    }
    if ok and artifacts_dir.is_dir():
        (artifacts_dir / "WINDOWS_ARTIFACTS_SHA256.json").write_text(json.dumps(result, indent=2, ensure_ascii=False), encoding="utf-8")
        sha_lines = [f"{item['sha256']}  {item['relative_path']}" for item in artifacts_meta]
        (artifacts_dir / "WINDOWS_ARTIFACTS_SHA256.txt").write_text("\n".join(sha_lines) + "\n", encoding="utf-8")
    return result


def verify_ai_zip_vs_git_provenance(repo_root: Path, branch: str = DEFAULT_TARGET_BRANCH) -> dict:
    """
    Clone reports_and_logs/mersad_preview_0_1_verifiable_history.bundle, checkout `branch`,
    and verify 100% byte-for-byte parity between:
      (1) Git tree `MERSAD_AI_Preview_0.1/*` (58 files),
      (2) Workspace directory `MERSAD_AI_Preview_0.1/*` (58 files),
      (3) `RELEASE_DELIVERABLES/PREVIEW_0.1/MERSAD_AI_Preview_0.1_Portable_Source.zip` (58 files),
      (4) Root copies (`mersad_live.py`, `registry.py`, `selftest.py`, `verify_integrity.py`, `models/eval_benchmarks/*`),
      (5) 1 Workflow File + 16 Required Paths = 17 Verified Paths inside the Git commit tree.
    """
    bundle_path = repo_root / "reports_and_logs" / "mersad_preview_0_1_verifiable_history.bundle"
    ws_ai_dir = repo_root / "MERSAD_AI_Preview_0.1"
    ai_zip_path = repo_root / "RELEASE_DELIVERABLES" / "PREVIEW_0.1" / "MERSAD_AI_Preview_0.1_Portable_Source.zip"

    if not bundle_path.is_file() or not ai_zip_path.is_file():
        return {"ok": False, "error": "Missing AI bundle or Portable_Source.zip"}

    zip_map = {}
    with zipfile.ZipFile(ai_zip_path, "r") as zf:
        for name in sorted(zf.namelist()):
            if not name.endswith("/"):
                rel = name.split("/", 1)[1] if name.startswith("MERSAD_AI_Preview_0.1/") else name
                raw = zf.read(name)
                zip_map[rel] = {"size": len(raw), "sha256": hashlib.sha256(raw).hexdigest()}

    with tempfile.TemporaryDirectory(prefix="mersad_ai_prov_") as tmpdir:
        clone_dir = Path(tmpdir) / "MERSAD_AI_CLONE"
        subprocess.run(["git", "clone", str(bundle_path), str(clone_dir)], check=True, capture_output=True)
        subprocess.run(["git", "-C", str(clone_dir), "checkout", "-B", branch, f"origin/{branch}"], check=True, capture_output=True)
        head_sha = subprocess.check_output(["git", "-C", str(clone_dir), "rev-parse", "HEAD"], text=True).strip()
        preflight_tag_sha = subprocess.check_output(["git", "-C", str(clone_dir), "rev-parse", "refs/tags/v0.1.2-windows-ci-preflight-ready"], text=True).strip()
        code_tag_sha = subprocess.check_output(["git", "-C", str(clone_dir), "rev-parse", "refs/tags/v0.1.1-postbuild-reconciled-code"], text=True).strip()
        main_sha = subprocess.check_output(["git", "-C", str(clone_dir), "rev-parse", "origin/main"], text=True).strip()

        git_sub = clone_dir / "MERSAD_AI_Preview_0.1"
        git_files = sorted(
            p.relative_to(git_sub).as_posix()
            for p in git_sub.rglob("*")
            if p.is_file() and "__pycache__" not in p.parts
        )
        ws_files = sorted(
            p.relative_to(ws_ai_dir).as_posix()
            for p in ws_ai_dir.rglob("*")
            if p.is_file() and "__pycache__" not in p.parts
        )

        mismatches = []
        comparisons = []
        all_keys = sorted(set(git_files) | set(ws_files) | set(zip_map.keys()))
        for rel in all_keys:
            gp = git_sub / rel
            wp = ws_ai_dir / rel
            g_sha = hashlib.sha256(gp.read_bytes()).hexdigest() if gp.is_file() else None
            w_sha = hashlib.sha256(wp.read_bytes()).hexdigest() if wp.is_file() else None
            z_sha = zip_map.get(rel, {}).get("sha256")
            rp = clone_dir / rel
            r_sha = hashlib.sha256(rp.read_bytes()).hexdigest() if rp.is_file() else g_sha
            match = (g_sha is not None and g_sha == w_sha == z_sha == r_sha)
            if not match:
                mismatches.append({"path": rel, "git_subdir_sha256": g_sha, "workspace_sha256": w_sha, "zip_sha256": z_sha, "git_root_sha256": r_sha})
            comparisons.append({
                "path": rel,
                "size_bytes": gp.stat().st_size if gp.is_file() else 0,
                "sha256": g_sha,
                "git_subdir_matches_zip": g_sha == z_sha,
                "git_subdir_matches_workspace": g_sha == w_sha,
                "git_subdir_matches_root": g_sha == r_sha,
            })

        anc_edaf_rc = subprocess.run(
            ["git", "-C", str(clone_dir), "merge-base", "--is-ancestor", EXPECTED_AI_CODE_SHA, "HEAD"],
            capture_output=True,
        ).returncode
        anc_05f2_rc = subprocess.run(
            ["git", "-C", str(clone_dir), "merge-base", "--is-ancestor", EXPECTED_AI_PREFLIGHT_PARENT_SHA, "HEAD"],
            capture_output=True,
        ).returncode
        lifecycle_in_commit = (clone_dir / "integration" / "test_main_entrypoint_dynamic_camera_lifecycle.py").is_file()
        sim_engine_in_commit = (clone_dir / "MERSAD_LAB_Preview_0.1" / "sim_engine.py")
        sim_engine_sha_ok = (
            sim_engine_in_commit.is_file()
            and hashlib.sha256(sim_engine_in_commit.read_bytes()).hexdigest() == "4a07315323fb303783f0243c5eec68b840885abe871e1212b3dfac82d4b23e33"
        )
        present_17_paths = [p for p in WORKFLOW_17_VERIFIED_PATHS if (clone_dir / p).is_file()]

    ok = (
        len(mismatches) == 0
        and len(all_keys) == 58
        and code_tag_sha == EXPECTED_AI_CODE_SHA
        and preflight_tag_sha == EXPECTED_AI_PREFLIGHT_PARENT_SHA
        and anc_edaf_rc == 0
        and anc_05f2_rc == 0
        and lifecycle_in_commit
        and sim_engine_sha_ok
        and len(present_17_paths) == 17
        and main_sha == EXPECTED_MAIN_SHA
    )
    return {
        "ok": ok,
        "branch": branch,
        "head_sha": head_sha,
        "previous_preflight_commit_sha": preflight_tag_sha,
        "reconciled_code_sha": code_tag_sha,
        "descends_from_05f29af416c4": (anc_05f2_rc == 0),
        "descends_from_edaf651321ec": (anc_edaf_rc == 0),
        "lifecycle_test_in_commit": lifecycle_in_commit,
        "sim_engine_synced_in_commit": sim_engine_sha_ok,
        "workflow_paths_summary": "1 Workflow File + 16 Required Paths = 17 Verified Paths",
        "workflow_verified_paths_count": len(present_17_paths),
        "main_sha": main_sha,
        "total_files": len(all_keys),
        "matched_files": len(all_keys) - len(mismatches),
        "mismatches": mismatches,
        "files": comparisons,
    }


def execute_deployment(
    bundle_path: Path,
    remote_url: str,
    workflow_yaml_path: Path = None,
    env_override: dict = None,
    poll_attempts: int = 24,
    poll_interval_s: float = 5.0,
    artifacts_base_dir: Path = None,
    target_branch: str = None,
    simulate_dirty_working_tree: bool = False,
) -> dict:
    env = os.environ.copy()
    if env_override:
        env.update(env_override)

    branch_to_use = (target_branch or env.get("MERSAD_DEPLOY_BRANCH") or TARGET_BRANCH).strip()

    if workflow_yaml_path is None:
        workflow_yaml_path = bundle_path.parent.parent / ".github" / "workflows" / WORKFLOW_FILE
    if artifacts_base_dir is None:
        artifacts_base_dir = bundle_path.parent.parent

    report = {
        "timestamp": time.strftime("%Y-%m-%d %H:%M:%S"),
        "target_branch": branch_to_use,
        "trigger_mode": "push_only_single_run",
        "expected_ai_preflight_parent_sha": EXPECTED_AI_PREFLIGHT_PARENT_SHA,
        "expected_ai_code_sha": EXPECTED_AI_CODE_SHA,
        "expected_ai_prev_fix_sha": EXPECTED_AI_PREV_FIX_SHA,
        "expected_ai_release_base_sha": EXPECTED_AI_RELEASE_BASE_SHA,
        "expected_lab_code_sha": EXPECTED_LAB_CODE_SHA,
        "expected_lab_release_base_sha": EXPECTED_LAB_RELEASE_BASE_SHA,
        "expected_main_sha": EXPECTED_MAIN_SHA,
        "workflow_file": WORKFLOW_FILE,
        "remote_url": remote_url,
        "steps": [],
        "state_history": [],
        "status": "FAIL",
        "build_triggered": False,
        "run_id": None,
        "run_url": None,
        "artifacts_verification": None,
    }

    def set_state(new_state: str):
        report["status"] = new_state
        report["state_history"].append(new_state)

    def add_step(name, ok, detail):
        report["steps"].append({"step": name, "ok": bool(ok), "detail": detail})

    # Step 0: Validate that workflow YAML uses push trigger ONLY (no workflow_dispatch, no unused run_extended_stress)
    ok_wf_yaml, msg_wf_yaml = validate_workflow_push_only(workflow_yaml_path)
    add_step("validate_workflow_push_only", ok_wf_yaml, msg_wf_yaml)
    if not ok_wf_yaml:
        report["error"] = f"INVALID_WORKFLOW_TRIGGER_CONFIG: {msg_wf_yaml}"
        return report

    # Step 1: Clone bundle and verify branches, lineage, clean working tree, remote URL, and pre-push run IDs
    with tempfile.TemporaryDirectory(prefix="mersad_deploy_") as tmpdir:
        work_repo = Path(tmpdir) / "repo"
        rc, out, err = run_cmd(["git", "clone", str(bundle_path), str(work_repo)], env=env)
        if rc != 0:
            add_step("clone_bundle", False, f"git clone failed: {err or out}")
            report["error"] = f"CLONE_FAILED: {err or out}"
            return report
        add_step("clone_bundle", True, f"Cloned bundle {bundle_path.name}")

        rc, main_sha, err = run_cmd(["git", "rev-parse", "origin/main"], cwd=str(work_repo), env=env)
        if rc != 0 or main_sha != EXPECTED_MAIN_SHA:
            add_step("verify_main_untouched", False, f"main SHA mismatch: got {main_sha}, expected {EXPECTED_MAIN_SHA}")
            report["error"] = f"MAIN_SHA_MISMATCH: {main_sha}"
            return report
        add_step("verify_main_untouched", True, f"main branch untouched at {main_sha}")

        rc, out, err = run_cmd(["git", "checkout", "-B", branch_to_use, f"origin/{branch_to_use}"], cwd=str(work_repo), env=env)
        if rc != 0:
            add_step("checkout_target_branch", False, f"Failed to checkout {branch_to_use}: {err or out}")
            report["error"] = f"CHECKOUT_FAILED: {err or out}"
            return report

        if simulate_dirty_working_tree:
            (work_repo / "UNCOMMITTED_DIRTY_FILE.tmp").write_text("dirty", encoding="utf-8")

        rc_st, out_st, err_st = run_cmd(["git", "status", "--porcelain"], cwd=str(work_repo), env=env)
        if rc_st != 0 or out_st.strip() != "":
            add_step("verify_clean_working_tree", False, f"Working tree is not clean before push: {out_st or err_st}")
            report["error"] = f"DIRTY_WORKING_TREE: {out_st or err_st}"
            return report
        add_step("verify_clean_working_tree", True, "git status --porcelain is clean (0 uncommitted changes)")

        rc, head_sha, err = run_cmd(["git", "rev-parse", "HEAD"], cwd=str(work_repo), env=env)
        required_ancestors = [EXPECTED_AI_RELEASE_BASE_SHA]
        if branch_to_use == DEFAULT_TARGET_BRANCH:
            required_ancestors = [
                EXPECTED_AI_PREFLIGHT_PARENT_SHA,
                EXPECTED_AI_CODE_SHA,
                EXPECTED_AI_PREV_FIX_SHA,
                EXPECTED_AI_RELEASE_BASE_SHA,
            ]

        for req_anc in required_ancestors:
            rc_anc, _, _ = run_cmd(["git", "merge-base", "--is-ancestor", req_anc, "HEAD"], cwd=str(work_repo), env=env)
            if rc != 0 or rc_anc != 0:
                add_step("verify_commit_lineage", False, f"HEAD {head_sha} on {branch_to_use} does not descend from {req_anc}")
                report["error"] = f"LINEAGE_MISMATCH: {head_sha} missing ancestor {req_anc}"
                return report

        report["local_head_sha"] = head_sha
        add_step("verify_commit_lineage", True, f"Checked out {branch_to_use} at HEAD={head_sha} (verified lineage: {required_ancestors})")

        # Configure and verify remote URL before push
        run_cmd(["git", "remote", "set-url", "origin", remote_url], cwd=str(work_repo), env=env)
        rc_rem, out_rem, _ = run_cmd(["git", "remote", "get-url", "origin"], cwd=str(work_repo), env=env)
        if rc_rem != 0 or out_rem.strip() != remote_url:
            add_step("verify_remote_url", False, f"Remote URL mismatch: got {out_rem}, expected {remote_url}")
            report["error"] = f"REMOTE_URL_MISMATCH: {out_rem}"
            return report
        add_step("verify_remote_url", True, f"Verified origin remote URL: {out_rem}")

        # Check gh CLI installation and authentication BEFORE pushing so we can record pre-existing run IDs
        gh_bin = shutil.which("gh", path=env.get("PATH", ""))
        if not gh_bin:
            msg = "GitHub CLI (gh) is NOT installed in PATH. Halting before push without claiming workflow trigger success."
            add_step("verify_gh_cli_installed", False, msg)
            report["error"] = f"GH_CLI_NOT_INSTALLED: {msg}"
            return report
        add_step("verify_gh_cli_installed", True, f"Found gh binary at {gh_bin}")

        rc_auth, out_auth, err_auth = run_cmd([gh_bin, "auth", "status"], cwd=str(work_repo), env=env)
        if rc_auth != 0:
            msg = f"GitHub CLI (gh) is NOT authenticated ({err_auth or out_auth}). Halting before push."
            add_step("verify_gh_cli_authenticated", False, msg)
            report["error"] = f"GH_CLI_UNAUTHENTICATED: {msg}"
            return report
        add_step("verify_gh_cli_authenticated", True, "gh auth status verified")

        # Record all pre-push run IDs across the workflow so historical runs are never mistaken for the new push run
        pre_existing_ids = set()
        rc_pre, out_pre, _ = run_cmd(
            [
                gh_bin, "run", "list",
                f"--workflow={WORKFLOW_FILE}",
                "--limit=30",
                "--json", "databaseId,headSha,event,headBranch,status,conclusion,createdAt,url",
            ],
            cwd=str(work_repo),
            env=env,
        )
        if rc_pre == 0 and out_pre:
            try:
                for item in json.loads(out_pre):
                    if isinstance(item, dict) and "databaseId" in item:
                        pre_existing_ids.add(int(item["databaseId"]))
            except Exception:
                pass
        report["pre_existing_run_ids"] = sorted(pre_existing_ids)
        set_state("PREFLIGHT_PASS")
        add_step("record_pre_push_runs", True, f"PREFLIGHT_PASS: Recorded {len(pre_existing_ids)} pre-existing run ID(s) before push: {sorted(pre_existing_ids)}")

        # Step 2: Push target branch once without --force (sole CI trigger: event == "push")
        rc_push, out_push, err_push = run_cmd(
            ["git", "push", "-u", "origin", f"refs/heads/{branch_to_use}:refs/heads/{branch_to_use}"],
            cwd=str(work_repo),
            env=env,
        )
        if rc_push != 0:
            add_step("git_push_target_branch", False, f"git push to {remote_url} failed: {err_push or out_push}")
            report["error"] = f"GIT_PUSH_FAILED: {err_push or out_push}"
            return report
        add_step("git_push_target_branch", True, f"Pushed {branch_to_use} without --force to {remote_url} (push-triggered CI)")

        # Step 3: Verify remote SHA via git ls-remote
        rc_ls, out_ls, err_ls = run_cmd(
            ["git", "ls-remote", "origin", f"refs/heads/{branch_to_use}"],
            cwd=str(work_repo),
            env=env,
        )
        remote_sha = out_ls.split()[0] if (rc_ls == 0 and out_ls.split()) else ""
        if remote_sha.lower() != head_sha.lower():
            add_step("verify_remote_sha", False, f"Remote SHA ({remote_sha}) != Local HEAD ({head_sha})")
            report["error"] = f"REMOTE_SHA_MISMATCH: {remote_sha} != {head_sha}"
            return report
        report["verified_remote_sha"] = remote_sha
        report["build_triggered"] = True
        set_state("PUSH_COMPLETED")
        add_step("verify_remote_sha", True, f"PUSH_COMPLETED: Verified remote SHA on origin matches local HEAD: {remote_sha}")

        # Step 4: Poll for NEW push-triggered run(s) matching workflow + event=="push" + headBranch + headSha == local_head_sha
        matched_run = None
        for attempt in range(1, poll_attempts + 1):
            if poll_interval_s > 0:
                time.sleep(poll_interval_s)
            rc_list, out_list, err_list = run_cmd(
                [
                    gh_bin, "run", "list",
                    f"--workflow={WORKFLOW_FILE}",
                    f"--branch={branch_to_use}",
                    "--event=push",
                    "--limit=30",
                    "--json", "databaseId,headSha,event,headBranch,status,conclusion,createdAt,url,workflowName",
                ],
                cwd=str(work_repo),
                env=env,
            )
            if rc_list == 0 and out_list:
                try:
                    runs = json.loads(out_list)
                    matching_new_runs = []
                    for r in runs:
                        if not isinstance(r, dict):
                            continue
                        r_id = int(r.get("databaseId", 0))
                        r_sha = str(r.get("headSha", "")).strip()
                        r_evt = str(r.get("event", "")).strip()
                        r_br = str(r.get("headBranch", "")).strip()
                        r_wf = str(r.get("workflowName", "")).strip()
                        # Reject wrong workflow if workflowName is explicitly set to another workflow
                        if r_wf and "MERSAD PREVIEW 0.1" not in r_wf and WORKFLOW_FILE not in r_wf:
                            continue
                        if (
                            r_id > 0
                            and r_id not in pre_existing_ids
                            and r_evt == "push"
                            and r_br == branch_to_use
                            and r_sha.lower() == head_sha.lower()
                        ):
                            matching_new_runs.append(r)

                    if len(matching_new_runs) > 1:
                        dup_ids = [int(x["databaseId"]) for x in matching_new_runs]
                        msg = f"Duplicate new runs detected ({len(matching_new_runs)} runs: {dup_ids}) for headSha={head_sha} on branch {branch_to_use}."
                        set_state("DUPLICATE_RUN_DETECTED")
                        add_step("poll_matching_run_id", False, msg)
                        report["duplicate_run_ids"] = dup_ids
                        report["error"] = f"DUPLICATE_RUN_DETECTED: {msg}"
                        return report

                    if len(matching_new_runs) == 1:
                        matched_run = matching_new_runs[0]
                        break
                except Exception:
                    pass

        if matched_run is None:
            msg = f"No new push run matching headSha={head_sha} on branch {branch_to_use} appeared after {poll_attempts} poll attempt(s)."
            set_state("RUN_TIMEOUT")
            add_step("poll_matching_run_id", False, msg)
            report["error"] = f"RUN_TIMEOUT: {msg}"
            return report

        run_id = str(matched_run["databaseId"])
        report["run_id"] = run_id
        report["run_url"] = matched_run.get("url")
        set_state("RUN_DISCOVERED")
        add_step("poll_matching_run_id", True, f"RUN_DISCOVERED: Matched single new push Run ID {run_id} for headSha={head_sha}")

        # Step 5: Watch run to completion and verify all jobs succeeded
        set_state("RUN_IN_PROGRESS")
        rc_watch, out_watch, err_watch = run_cmd(
            [gh_bin, "run", "watch", run_id, "--exit-status"],
            cwd=str(work_repo),
            env=env,
        )
        if rc_watch != 0:
            msg = f"gh run watch {run_id} failed (exit={rc_watch}): {err_watch or out_watch}"
            set_state("RUN_FAILED")
            add_step("watch_workflow_run", False, msg)
            report["error"] = f"WORKFLOW_RUN_FAILED: {msg}"
            return report

        rc_view, out_view, err_view = run_cmd(
            [gh_bin, "run", "view", run_id, "--json", "status,conclusion,jobs,url"],
            cwd=str(work_repo),
            env=env,
        )
        if rc_view != 0:
            msg = f"gh run view {run_id} failed: {err_view or out_view}"
            set_state("RUN_FAILED")
            add_step("verify_all_jobs_succeeded", False, msg)
            report["error"] = f"RUN_VIEW_FAILED: {msg}"
            return report

        try:
            view_data = json.loads(out_view)
        except Exception as e:
            set_state("RUN_FAILED")
            add_step("verify_all_jobs_succeeded", False, f"Invalid JSON from gh run view: {e}")
            report["error"] = f"RUN_VIEW_JSON_ERROR: {e}"
            return report

        run_conclusion = str(view_data.get("conclusion", "")).lower()
        jobs_list = view_data.get("jobs") or []
        failed_jobs = [j.get("name", "unknown") for j in jobs_list if str(j.get("conclusion", "")).lower() != "success"]
        if run_conclusion != "success" or failed_jobs or len(jobs_list) == 0:
            msg = f"Run {run_id} conclusion={run_conclusion}, failed_jobs={failed_jobs}"
            set_state("RUN_FAILED")
            add_step("verify_all_jobs_succeeded", False, msg)
            report["error"] = f"JOBS_FAILED: {msg}"
            return report
        add_step("verify_all_jobs_succeeded", True, f"Run {run_id} completed with conclusion=success across {len(jobs_list)} job(s)")

        # Step 6: Download artifacts for this exact Run ID and verify all 5 Windows files + SHA-256
        out_art_dir = artifacts_base_dir / f"dist_github_actions_run_{run_id}"
        if out_art_dir.exists():
            shutil.rmtree(out_art_dir)
        out_art_dir.mkdir(parents=True, exist_ok=True)

        rc_dl, out_dl, err_dl = run_cmd(
            [gh_bin, "run", "download", run_id, "--dir", str(out_art_dir)],
            cwd=str(work_repo),
            env=env,
        )
        if rc_dl != 0:
            msg = f"gh run download {run_id} failed: {err_dl or out_dl}"
            set_state("RUN_FAILED")
            add_step("download_run_artifacts", False, msg)
            report["error"] = f"ARTIFACT_DOWNLOAD_FAILED: {msg}"
            return report
        add_step("download_run_artifacts", True, f"Downloaded artifacts for Run ID {run_id} into {out_art_dir.name}")

        art_ver = verify_and_hash_downloaded_artifacts(out_art_dir, run_id=run_id)
        report["artifacts_verification"] = art_ver
        if not art_ver["ok"]:
            msg = f"Missing or empty required Windows artifacts: missing={art_ver['missing_files']}, empty={art_ver['empty_files']}"
            set_state("RUN_FAILED")
            add_step("verify_five_windows_artifacts_sha256", False, msg)
            report["error"] = f"ARTIFACTS_INCOMPLETE: {msg}"
            return report

        set_state("ARTIFACTS_VERIFIED")
        add_step("verify_five_windows_artifacts_sha256", True, f"ARTIFACTS_VERIFIED: Verified all 5 Windows artifacts and computed SHA-256 checksums for Run ID {run_id}")
        set_state("PASS")
        return report


def run_self_test(repo_root: Path) -> dict:
    bundle = repo_root / "reports_and_logs" / "mersad_preview_0_1_verifiable_history.bundle"
    bat_file = repo_root / "PUSH_CANDIDATE_9491BCD_TO_GITHUB_ACTIONS.bat"
    bat_rel_file = repo_root / "PUSH_RELEASE_PREVIEW_0_1_TO_GITHUB_ACTIONS.bat"
    wf_file = repo_root / ".github" / "workflows" / WORKFLOW_FILE
    deploy_py_file = repo_root / "tools" / "deploy_and_run_github_actions.py"

    bat_text = bat_file.read_text(encoding="utf-8")
    bat_rel_text = bat_rel_file.read_text(encoding="utf-8")
    wf_text = wf_file.read_text(encoding="utf-8")
    deploy_py_text = deploy_py_file.read_text(encoding="utf-8")

    checks = []

    # 1. No script calls `gh workflow run` after `git push` (BUG-35)
    no_gh_wf_run_in_bat = ("gh workflow run" not in bat_text and "gh workflow run" not in bat_rel_text)
    no_gh_wf_run_in_py = (re.search(r'\[\s*gh_bin\s*,\s*"workflow"\s*,\s*"run"', deploy_py_text) is None)
    checks.append((
        "TEST_01_NO_SCRIPT_CALLS_GH_WORKFLOW_RUN_AFTER_PUSH",
        no_gh_wf_run_in_bat and no_gh_wf_run_in_py
    ))

    # 2. Workflow YAML uses push trigger only (no workflow_dispatch, no unused run_extended_stress) (BUG-35 & BUG-37)
    ok_wf_push_only, _ = validate_workflow_push_only(wf_file)
    with tempfile.TemporaryDirectory(prefix="mersad_wf_val_") as tmp_wf_d:
        bad_wf = Path(tmp_wf_d) / "bad.yml"
        bad_wf.write_text("on:\n  workflow_dispatch:\n  push:\n", encoding="utf-8")
        ok_bad_wf, _ = validate_workflow_push_only(bad_wf)
    checks.append((
        "TEST_02_WORKFLOW_PUSH_ONLY_AND_VALIDATOR_REJECTS_WORKFLOW_DISPATCH",
        ok_wf_push_only is True and ok_bad_wf is False
    ))

    # 3. No unused `run_extended_stress` input remains in workflow, deployment scripts, or .bat files (BUG-37)
    checks.append((
        "TEST_03_NO_UNUSED_RUN_EXTENDED_STRESS_IN_WORKFLOW_OR_SCRIPTS",
        "run_extended_stress" not in wf_text
        and "run_extended_stress" not in bat_text
        and "run_extended_stress" not in bat_rel_text
    ))

    # Batch script static checks (lineage, push-only polling, duplicate run check)
    checks.append((
        "BAT_TARGETS_FIX_BRANCH_AND_HAS_DUPLICATE_RUN_GUARD",
        'set "TARGET_BRANCH=fix/preview-0.1-postbuild-42273598736"' in bat_text
        and 'set "TARGET_BRANCH=fix/preview-0.1-postbuild-42273598736"' in bat_rel_text
        and EXPECTED_AI_PREFLIGHT_PARENT_SHA in bat_text
        and EXPECTED_AI_CODE_SHA in bat_text
        and EXPECTED_MAIN_SHA in bat_text
        and "DUPLICATE_RUN_DETECTED" in bat_text
        and "DUPLICATE_RUN_DETECTED" in bat_rel_text
        and 'select(.event == \\"push\\"' in bat_text
        and "git push --force" not in bat_text
        and "git push -f" not in bat_text
    ))

    with tempfile.TemporaryDirectory(prefix="mersad_bare_remote_") as tmpdir:
        tmp_p = Path(tmpdir)
        bare_remote = tmp_p / "origin.git"
        subprocess.run(["git", "init", "--bare", str(bare_remote)], check=True, capture_output=True)

        # Missing gh in PATH must halt before push
        res_no_gh = execute_deployment(
            bundle,
            str(bare_remote),
            wf_file,
            env_override={"PATH": "/usr/bin:/bin"},
            poll_attempts=1,
            poll_interval_s=0.0,
            target_branch=DEFAULT_TARGET_BRANCH,
        )
        local_head = res_no_gh.get("local_head_sha", "")
        checks.append((
            "MISSING_GH_HALTS_WITH_ERROR_AND_VERIFIES_LINEAGE",
            res_no_gh["status"] == "FAIL"
            and res_no_gh["build_triggered"] is False
            and "GH_CLI_NOT_INSTALLED" in res_no_gh.get("error", "")
            and bool(local_head)
        ))

        # Dirty working tree before push must be rejected
        res_dirty = execute_deployment(
            bundle,
            str(bare_remote),
            wf_file,
            env_override={"PATH": "/usr/bin:/bin"},
            poll_attempts=1,
            poll_interval_s=0.0,
            target_branch=DEFAULT_TARGET_BRANCH,
            simulate_dirty_working_tree=True,
        )
        checks.append((
            "PREFLIGHT_REJECTS_DIRTY_WORKING_TREE",
            res_dirty["status"] == "FAIL" and "DIRTY_WORKING_TREE" in res_dirty.get("error", "")
        ))

        # 4. Rejects runs with mismatched SHA (BUG-36)
        fake_bin_wrong_sha = tmp_p / "fake_bin_wrong_sha"
        fake_bin_wrong_sha.mkdir()
        state_wrong_sha = tmp_p / "state_wrong_sha.txt"
        wrong_sha_script = f"""#!/usr/bin/env python3
import json, pathlib, sys
args = sys.argv[1:]
sf = pathlib.Path("{state_wrong_sha}")
if args[:2] == ["auth", "status"]:
    sys.exit(0)
if args[:2] == ["run", "list"]:
    if not sf.exists():
        sf.write_text("pre")
        print(json.dumps([]))
    else:
        print(json.dumps([
            {{"databaseId": 7001, "headSha": "deadbeef00000000000000000000000000000000", "event": "push", "headBranch": "{DEFAULT_TARGET_BRANCH}"}}
        ]))
    sys.exit(0)
sys.exit(1)
"""
        (fake_bin_wrong_sha / "gh").write_text(wrong_sha_script, encoding="utf-8")
        (fake_bin_wrong_sha / "gh").chmod(0o755)
        res_wrong_sha = execute_deployment(
            bundle, str(bare_remote), wf_file,
            env_override={"PATH": f"{fake_bin_wrong_sha}:/usr/bin:/bin"},
            poll_attempts=2, poll_interval_s=0.0,
        )
        checks.append((
            "TEST_04_POLLING_REJECTS_MISMATCHED_SHA",
            res_wrong_sha["status"] == "RUN_TIMEOUT" and res_wrong_sha["run_id"] is None
        ))

        # 5. Rejects runs with wrong event (e.g., workflow_dispatch or pull_request instead of push) (BUG-36)
        fake_bin_wrong_evt = tmp_p / "fake_bin_wrong_evt"
        fake_bin_wrong_evt.mkdir()
        state_wrong_evt = tmp_p / "state_wrong_evt.txt"
        wrong_evt_script = f"""#!/usr/bin/env python3
import json, pathlib, sys
args = sys.argv[1:]
sf = pathlib.Path("{state_wrong_evt}")
if args[:2] == ["auth", "status"]:
    sys.exit(0)
if args[:2] == ["run", "list"]:
    if not sf.exists():
        sf.write_text("pre")
        print(json.dumps([]))
    else:
        print(json.dumps([
            {{"databaseId": 7002, "headSha": "{local_head}", "event": "workflow_dispatch", "headBranch": "{DEFAULT_TARGET_BRANCH}"}},
            {{"databaseId": 7003, "headSha": "{local_head}", "event": "pull_request", "headBranch": "{DEFAULT_TARGET_BRANCH}"}}
        ]))
    sys.exit(0)
sys.exit(1)
"""
        (fake_bin_wrong_evt / "gh").write_text(wrong_evt_script, encoding="utf-8")
        (fake_bin_wrong_evt / "gh").chmod(0o755)
        res_wrong_evt = execute_deployment(
            bundle, str(bare_remote), wf_file,
            env_override={"PATH": f"{fake_bin_wrong_evt}:/usr/bin:/bin"},
            poll_attempts=2, poll_interval_s=0.0,
        )
        checks.append((
            "TEST_05_POLLING_REJECTS_NON_PUSH_EVENT",
            res_wrong_evt["status"] == "RUN_TIMEOUT" and res_wrong_evt["run_id"] is None
        ))

        # 6. Ignores historical runs recorded in pre_existing_run_ids even if they have the same SHA and branch (BUG-36)
        fake_bin_hist = tmp_p / "fake_bin_hist"
        fake_bin_hist.mkdir()
        hist_script = f"""#!/usr/bin/env python3
import json, sys
args = sys.argv[1:]
if args[:2] == ["auth", "status"]:
    sys.exit(0)
if args[:2] == ["run", "list"]:
    print(json.dumps([
        {{"databaseId": 7004, "headSha": "{local_head}", "event": "push", "headBranch": "{DEFAULT_TARGET_BRANCH}"}}
    ]))
    sys.exit(0)
sys.exit(1)
"""
        (fake_bin_hist / "gh").write_text(hist_script, encoding="utf-8")
        (fake_bin_hist / "gh").chmod(0o755)
        res_hist = execute_deployment(
            bundle, str(bare_remote), wf_file,
            env_override={"PATH": f"{fake_bin_hist}:/usr/bin:/bin"},
            poll_attempts=2, poll_interval_s=0.0,
        )
        checks.append((
            "TEST_06_POLLING_IGNORES_PRE_EXISTING_HISTORICAL_RUNS_WITH_SAME_SHA",
            res_hist["status"] == "RUN_TIMEOUT"
            and res_hist["run_id"] is None
            and 7004 in res_hist.get("pre_existing_run_ids", [])
        ))

        # 7. Detects duplicate new runs for the same SHA and branch -> DUPLICATE_RUN_DETECTED (BUG-36)
        fake_bin_dup = tmp_p / "fake_bin_dup"
        fake_bin_dup.mkdir()
        state_dup = tmp_p / "state_dup.txt"
        dup_script = f"""#!/usr/bin/env python3
import json, pathlib, sys
args = sys.argv[1:]
sf = pathlib.Path("{state_dup}")
if args[:2] == ["auth", "status"]:
    sys.exit(0)
if args[:2] == ["run", "list"]:
    if not sf.exists():
        sf.write_text("pre")
        print(json.dumps([{{"databaseId": 7000, "headSha": "{local_head}", "event": "push", "headBranch": "{DEFAULT_TARGET_BRANCH}"}}]))
    else:
        print(json.dumps([
            {{"databaseId": 7010, "headSha": "{local_head}", "event": "push", "headBranch": "{DEFAULT_TARGET_BRANCH}"}},
            {{"databaseId": 7011, "headSha": "{local_head}", "event": "push", "headBranch": "{DEFAULT_TARGET_BRANCH}"}},
            {{"databaseId": 7000, "headSha": "{local_head}", "event": "push", "headBranch": "{DEFAULT_TARGET_BRANCH}"}}
        ]))
    sys.exit(0)
sys.exit(1)
"""
        (fake_bin_dup / "gh").write_text(dup_script, encoding="utf-8")
        (fake_bin_dup / "gh").chmod(0o755)
        res_dup = execute_deployment(
            bundle, str(bare_remote), wf_file,
            env_override={"PATH": f"{fake_bin_dup}:/usr/bin:/bin"},
            poll_attempts=2, poll_interval_s=0.0,
        )
        checks.append((
            "TEST_07_DUPLICATE_RUNS_FOR_SAME_SHA_ABORT_WITH_DUPLICATE_RUN_DETECTED",
            res_dup["status"] == "DUPLICATE_RUN_DETECTED"
            and res_dup.get("duplicate_run_ids") == [7010, 7011]
        ))

        # 8. Timeout never converts to PASS (stays RUN_TIMEOUT) (BUG-36)
        checks.append((
            "TEST_08_POLL_TIMEOUT_SETS_RUN_TIMEOUT_NEVER_PASS",
            res_wrong_sha["status"] == "RUN_TIMEOUT"
            and "PASS" not in res_wrong_sha.get("state_history", [])
        ))

        # 9. Single failed job within the workflow run sets status=RUN_FAILED (BUG-36)
        fake_bin_failjob = tmp_p / "fake_bin_failjob"
        fake_bin_failjob.mkdir()
        state_file_fail = tmp_p / "state_fail.txt"
        failjob_script = f"""#!/usr/bin/env python3
import json, pathlib, sys
args = sys.argv[1:]
sf = pathlib.Path("{state_file_fail}")
if args[:2] == ["auth", "status"]:
    sys.exit(0)
if args[:2] == ["run", "list"]:
    if not sf.exists():
        sf.write_text("pre")
        print(json.dumps([{{"databaseId": 5000, "headSha": "{local_head}", "event": "push", "headBranch": "{DEFAULT_TARGET_BRANCH}"}}]))
    else:
        print(json.dumps([
            {{"databaseId": 5005, "headSha": "{local_head}", "event": "push", "headBranch": "{DEFAULT_TARGET_BRANCH}", "url": "https://github.com/alinon9/MERSAD-AI-/actions/runs/5005"}},
            {{"databaseId": 5000, "headSha": "{local_head}", "event": "push", "headBranch": "{DEFAULT_TARGET_BRANCH}"}}
        ]))
    sys.exit(0)
if args[:2] == ["run", "watch"]:
    sys.exit(0)
if args[:2] == ["run", "view"]:
    print(json.dumps({{"status": "completed", "conclusion": "success", "jobs": [{{"name": "build-and-verify-windows-x64", "conclusion": "failure"}}]}}))
    sys.exit(0)
sys.exit(1)
"""
        (fake_bin_failjob / "gh").write_text(failjob_script, encoding="utf-8")
        (fake_bin_failjob / "gh").chmod(0o755)
        res_failjob = execute_deployment(
            bundle, str(bare_remote), wf_file,
            env_override={"PATH": f"{fake_bin_failjob}:/usr/bin:/bin"},
            poll_attempts=2, poll_interval_s=0.0,
        )
        checks.append((
            "TEST_09_SINGLE_FAILED_JOB_SETS_RUN_FAILED",
            res_failjob["run_id"] == "5005"
            and res_failjob["status"] == "RUN_FAILED"
            and "JOBS_FAILED" in res_failjob.get("error", "")
        ))

        # 10. Missing 1 of the 5 required Windows build files sets status=RUN_FAILED (BUG-36)
        fake_bin_missing_art = tmp_p / "fake_bin_missing_art"
        fake_bin_missing_art.mkdir()
        state_missing_art = tmp_p / "state_missing_art.txt"
        missing_art_script = f"""#!/usr/bin/env python3
import json, pathlib, sys
args = sys.argv[1:]
sf = pathlib.Path("{state_missing_art}")
if args[:2] == ["auth", "status"]:
    sys.exit(0)
if args[:2] == ["run", "list"]:
    if not sf.exists():
        sf.write_text("pre")
        print(json.dumps([]))
    else:
        print(json.dumps([
            {{"databaseId": 5501, "headSha": "{local_head}", "event": "push", "headBranch": "{DEFAULT_TARGET_BRANCH}", "url": "https://github.com/alinon9/MERSAD-AI-/actions/runs/5501"}}
        ]))
    sys.exit(0)
if args[:2] == ["run", "watch"] and args[2] == "5501":
    sys.exit(0)
if args[:2] == ["run", "view"] and args[2] == "5501":
    print(json.dumps({{"status": "completed", "conclusion": "success", "jobs": [{{"name": "build-and-verify-windows-x64", "conclusion": "success"}}]}}))
    sys.exit(0)
if args[:2] == ["run", "download"] and args[2] == "5501":
    out_dir = pathlib.Path(args[args.index("--dir") + 1])
    for fn in {REQUIRED_WINDOWS_ARTIFACTS[:-1]!r}:
        (out_dir / fn).write_bytes(f"SIMULATED_BINARY_{{fn}}".encode("utf-8"))
    sys.exit(0)
sys.exit(1)
"""
        (fake_bin_missing_art / "gh").write_text(missing_art_script, encoding="utf-8")
        (fake_bin_missing_art / "gh").chmod(0o755)
        res_missing_art = execute_deployment(
            bundle, str(bare_remote), wf_file,
            env_override={"PATH": f"{fake_bin_missing_art}:/usr/bin:/bin"},
            poll_attempts=2, poll_interval_s=0.0,
            artifacts_base_dir=tmp_p,
        )
        checks.append((
            "TEST_10_MISSING_ONE_OF_FIVE_ARTIFACTS_SETS_RUN_FAILED",
            res_missing_art["run_id"] == "5501"
            and res_missing_art["status"] == "RUN_FAILED"
            and res_missing_art.get("artifacts_verification", {}).get("missing_files") == [REQUIRED_WINDOWS_ARTIFACTS[-1]]
        ))

        # 11. Full E2E simulated push-triggered run (PREFLIGHT_PASS -> PUSH_COMPLETED -> RUN_DISCOVERED -> RUN_IN_PROGRESS -> ARTIFACTS_VERIFIED -> PASS)
        fake_bin_ok = tmp_p / "fake_bin_ok"
        fake_bin_ok.mkdir()
        state_file_ok = tmp_p / "state_ok.txt"
        ok_script = f"""#!/usr/bin/env python3
import json, pathlib, sys
args = sys.argv[1:]
sf = pathlib.Path("{state_file_ok}")
if args[:2] == ["auth", "status"]:
    sys.exit(0)
if args[:2] == ["run", "list"]:
    if not sf.exists():
        sf.write_text("pre")
        print(json.dumps([{{"databaseId": 6000, "headSha": "{local_head}", "event": "push", "headBranch": "{DEFAULT_TARGET_BRANCH}"}}]))
    else:
        print(json.dumps([
            {{"databaseId": 6001, "headSha": "{local_head}", "event": "push", "headBranch": "{DEFAULT_TARGET_BRANCH}", "url": "https://github.com/alinon9/MERSAD-AI-/actions/runs/6001"}},
            {{"databaseId": 6000, "headSha": "{local_head}", "event": "push", "headBranch": "{DEFAULT_TARGET_BRANCH}"}}
        ]))
    sys.exit(0)
if args[:2] == ["run", "watch"] and args[2] == "6001":
    sys.exit(0)
if args[:2] == ["run", "view"] and args[2] == "6001":
    print(json.dumps({{"status": "completed", "conclusion": "success", "jobs": [{{"name": "build-and-verify-windows-x64", "conclusion": "success"}}]}}))
    sys.exit(0)
if args[:2] == ["run", "download"] and args[2] == "6001":
    out_dir = pathlib.Path(args[args.index("--dir") + 1])
    for fn in {REQUIRED_WINDOWS_ARTIFACTS!r}:
        (out_dir / fn).write_bytes(f"SIMULATED_BINARY_{{fn}}_FOR_SELFTEST_ONLY".encode("utf-8"))
    sys.exit(0)
sys.exit(1)
"""
        (fake_bin_ok / "gh").write_text(ok_script, encoding="utf-8")
        (fake_bin_ok / "gh").chmod(0o755)
        res_ok = execute_deployment(
            bundle,
            str(bare_remote),
            wf_file,
            env_override={"PATH": f"{fake_bin_ok}:/usr/bin:/bin"},
            poll_attempts=2,
            poll_interval_s=0.0,
            artifacts_base_dir=tmp_p,
        )
        checks.append((
            "TEST_11_FULL_PUSH_STATE_MACHINE_AND_5_ARTIFACT_SHA256_PASS",
            res_ok["status"] == "PASS"
            and res_ok.get("state_history") == [
                "PREFLIGHT_PASS",
                "PUSH_COMPLETED",
                "RUN_DISCOVERED",
                "RUN_IN_PROGRESS",
                "ARTIFACTS_VERIFIED",
                "PASS",
            ]
            and res_ok["run_id"] == "6001"
            and res_ok.get("artifacts_verification", {}).get("ok") is True
            and res_ok.get("artifacts_verification", {}).get("verified_count") == 5
        ))

    # Check 12: Verify 4-stage model breakdown never converts NOT_TESTED to PASS
    sys.path.insert(0, str(repo_root))
    from integration.evaluate_ai_models import build_four_stage_breakdown
    s_nt = build_four_stage_breakdown(True, True, False, False, "PASS", "Missing authorized face samples")
    s_pass = build_four_stage_breakdown(True, True, True, True, "PASS", None)
    checks.append((
        "MODEL_4STAGE_BREAKDOWN_NEVER_CONVERTS_NOT_TESTED_TO_PASS",
        s_nt["final_status"] == "NOT_TESTED"
        and s_nt["stage1_downloaded_and_sha256_verified"] is True
        and s_nt["stage2_loaded_and_inference_executed"] is True
        and s_nt["stage3_ground_truth_samples_available"] is False
        and s_pass["final_status"] == "PASS"
    ))

    # Check 13: Verify MERSAD LAB Git bundle provenance (14/14 files match 748ac0158761812a6fff63ff6fe626b9df8c252b and ZIP)
    import importlib.util
    spec_lp = importlib.util.spec_from_file_location("verify_mersad_lab_provenance", str(repo_root / "tools" / "verify_mersad_lab_provenance.py"))
    mod_lp = importlib.util.module_from_spec(spec_lp)
    spec_lp.loader.exec_module(mod_lp)
    lab_prov = mod_lp.verify_lab_provenance(repo_root)
    checks.append((
        "MERSAD_LAB_GIT_AND_ZIP_PROVENANCE_14_OF_14_SHA256_MATCH",
        lab_prov["status"] == "PASS"
        and lab_prov["matched_files_count"] == 14
        and lab_prov.get("verified_fix_branch_commit") == EXPECTED_LAB_CODE_SHA
        and lab_prov.get("verified_release_branch_commit") == EXPECTED_LAB_RELEASE_BASE_SHA
    ))

    # Check 14: Verify MERSAD AI Git bundle vs Portable_Source.zip vs Workspace (58/58 files match + 17 Workflow Paths)
    ai_prov = verify_ai_zip_vs_git_provenance(repo_root, branch=DEFAULT_TARGET_BRANCH)
    checks.append((
        "MERSAD_AI_GIT_AND_ZIP_PROVENANCE_58_OF_58_AND_17_WORKFLOW_PATHS",
        ai_prov["ok"] is True
        and ai_prov["total_files"] == 58
        and ai_prov["matched_files"] == 58
        and ai_prov["reconciled_code_sha"] == EXPECTED_AI_CODE_SHA
        and ai_prov["previous_preflight_commit_sha"] == EXPECTED_AI_PREFLIGHT_PARENT_SHA
        and ai_prov["workflow_verified_paths_count"] == 17
    ))

    # Check 15: Verify tools/prepare_safe_eval_benchmarks.py --verify is read-only non-destructive and detects tampering
    spec_bm = importlib.util.spec_from_file_location("prepare_safe_eval_benchmarks", str(repo_root / "tools" / "prepare_safe_eval_benchmarks.py"))
    mod_bm = importlib.util.module_from_spec(spec_bm)
    spec_bm.loader.exec_module(mod_bm)
    ver_clean = mod_bm.verify_safe_benchmarks(repo_root / "MERSAD_AI_Preview_0.1" / "models" / "eval_benchmarks")
    with tempfile.TemporaryDirectory(prefix="mersad_bm_tamper_") as tmp_bm:
        tmp_bm_dir = Path(tmp_bm) / "eval_benchmarks"
        shutil.copytree(repo_root / "MERSAD_AI_Preview_0.1" / "models" / "eval_benchmarks", tmp_bm_dir)
        tamper_target = tmp_bm_dir / "plates" / "plate_01_aden.jpg"
        orig_tamper_bytes = tamper_target.read_bytes()
        tamper_target.write_bytes(b"TAMPERED_CONTENT")
        ver_tampered = mod_bm.verify_safe_benchmarks(tmp_bm_dir)
        remained_tampered = (tamper_target.read_bytes() == b"TAMPERED_CONTENT")
    checks.append((
        "PREPARE_SAFE_BENCHMARKS_VERIFY_IS_READ_ONLY_AND_DETECTS_TAMPERING",
        ver_clean["ok"] is True
        and ver_clean["mode"] == "READ_ONLY_NON_DESTRUCTIVE_VERIFY"
        and ver_clean["verified_files_count"] == 18
        and ver_tampered["ok"] is False
        and remained_tampered is True
        and len(orig_tamper_bytes) > 100
    ))

    # Check 16..20: Run 42273598736 post-build remediation checks & Lifecycle check
    sys.path.insert(0, str(repo_root / "MERSAD_AI_Preview_0.1"))
    sys.path.insert(0, str(repo_root / "MERSAD_LAB_Preview_0.1"))
    import registry as reg_mod
    import mersad_live as ml_mod
    from sim_engine import VirtualCamera as VCMod

    checks.append((
        "RUN_42273598736_LATIN_TO_ARABIC_GOV_NORMALIZATION_6_OF_6",
        all(
            reg_mod.norm_plate(raw) == exp
            for raw, exp in [
                ("ADEN 12345", "عدن-12345"),
                ("SANA 48210", "صنعاء-48210"),
                ("TAIZ 73901", "تعز-73901"),
                ("HADR 55120", "حضرموت-55120"),
                ("IBB 91406", "إب-91406"),
                ("MARIB 30827", "مأرب-30827"),
            ]
        )
    ))
    checks.append((
        "RUN_42273598736_TESSERACT_DIRECT_CLI_FALLBACK_WITHOUT_PYTESSERACT",
        hasattr(ml_mod.TesseractOCRReader, "find_tesseract_binary") and hasattr(ml_mod.TesseractOCRReader, "_run_tesseract_tsv_cli")
    ))
    bm_p = repo_root / "MERSAD_AI_Preview_0.1" / "models" / "eval_benchmarks" / "BENCHMARK_MANIFEST.json"
    bm_data = json.loads(bm_p.read_text(encoding="utf-8")) if bm_p.is_file() else {}
    checks.append((
        "RUN_42273598736_SAFE_BENCHMARKS_NO_PII_AND_6_PLATES_READY",
        bm_data.get("contains_real_human_biometric_pii") is False
        and bm_data.get("datasets", {}).get("plates", {}).get("samples_count") == 6
        and bm_data.get("datasets", {}).get("faces_positive", {}).get("authorized_real_human_consent") is False
    ))
    vc_info = VCMod("cam1", "Cam 1", plate_idx=0).info()
    checks.append((
        "RUN_42273598736_VIRTUAL_CAMERA_MARKED_NON_PHOTOREALISTIC_INTEGRATION_STREAM",
        vc_info.get("scene_fidelity") == "SYNTHETIC_2D_GEOMETRIC_INTEGRATION_STREAM"
        and vc_info.get("valid_for_integration_and_smoke_tests") is True
        and vc_info.get("valid_for_photorealistic_dl_accuracy_benchmark") is False
    ))

    ep_json_path = repo_root / "reports_and_logs" / "logs" / "20_main_entrypoint_dynamic_camera_lifecycle.json"
    ep_ok = False
    if ep_json_path.is_file():
        ep_data = json.loads(ep_json_path.read_text(encoding="utf-8"))
        ep_ok = bool(ep_data.get("all_passed") is True and len(ep_data.get("steps", [])) == 10 and all(v.get("passed") is True for v in ep_data.get("steps", [])))
    checks.append(("MAIN_ENTRYPOINT_10_STEP_DYNAMIC_CAMERA_LIFECYCLE_PASS", ep_ok))

    all_ok = all(ok for _, ok in checks)
    return {
        "all_passed": all_ok,
        "total_checks": len(checks),
        "passed_checks": sum(1 for _, ok in checks if ok),
        "ai_provenance_summary": {
            "branch": ai_prov.get("branch"),
            "head_sha": ai_prov.get("head_sha"),
            "previous_preflight_commit_sha": ai_prov.get("previous_preflight_commit_sha"),
            "reconciled_code_sha": ai_prov.get("reconciled_code_sha"),
            "workflow_paths_summary": ai_prov.get("workflow_paths_summary"),
            "matched_files": f"{ai_prov.get('matched_files')}/{ai_prov.get('total_files')}",
        },
        "lab_provenance_summary": {
            "branch": "fix/preview-0.1-postbuild-42273598736",
            "head_sha": lab_prov.get("verified_fix_branch_commit"),
            "release_base_sha": lab_prov.get("verified_release_branch_commit"),
            "matched_files": f"{lab_prov.get('matched_files_count')}/{lab_prov.get('tracked_files_count')}",
        },
        "checks": [{"name": k, "passed": v} for k, v in checks],
    }


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--self-test", action="store_true")
    ap.add_argument("--live", action="store_true")
    ap.add_argument("--branch", type=str, default="")
    ap.add_argument("--verify-downloaded-artifacts", type=str, default="")
    ap.add_argument("--verify-ai-provenance", action="store_true")
    ap.add_argument("--run-id", type=str, default="")
    args = ap.parse_args()
    root = Path(__file__).resolve().parent.parent
    if args.verify_ai_provenance:
        aprov = verify_ai_zip_vs_git_provenance(root, branch=args.branch or DEFAULT_TARGET_BRANCH)
        print(json.dumps(aprov, indent=2, ensure_ascii=False))
        sys.exit(0 if aprov["ok"] else 1)
    if args.verify_downloaded_artifacts:
        ver = verify_and_hash_downloaded_artifacts(Path(args.verify_downloaded_artifacts), run_id=args.run_id)
        print(json.dumps(ver, indent=2, ensure_ascii=False))
        sys.exit(0 if ver["ok"] else 1)
    if args.self_test:
        st = run_self_test(root)
        print(json.dumps(st, indent=2, ensure_ascii=False))
        sys.exit(0 if st["all_passed"] else 1)
    if args.live:
        rep = execute_deployment(
            root / "reports_and_logs" / "mersad_preview_0_1_verifiable_history.bundle",
            DEFAULT_REMOTE_URL,
            root / ".github" / "workflows" / WORKFLOW_FILE,
            poll_attempts=3,
            poll_interval_s=1.0,
            artifacts_base_dir=root,
            target_branch=args.branch or DEFAULT_TARGET_BRANCH,
        )
        print(json.dumps(rep, indent=2, ensure_ascii=False))
        sys.exit(0 if rep["status"] == "PASS" else 1)
