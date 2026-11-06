#!/usr/bin/env python3
"""
Deterministic deployment, workflow_dispatch validator, Run ID poller, and 5-Artifact SHA-256 verifier
for MERSAD Preview 0.1 (Closes BUG-12, BUG-13, BUG-14, BUG-15).

Key guarantees:
  1. Validates workflow_dispatch inputs directly against .github/workflows/release-mersad-preview-0.1-windows.yml
     before invoking `gh workflow run`.
  2. Never sets status="PASS" merely because `gh workflow run` succeeded; transitions to status="DISPATCHED"
     first, then polls `gh run list` until a NEW workflow_dispatch run appears matching:
       - workflow == release-mersad-preview-0.1-windows.yml
       - event == "workflow_dispatch"
       - headBranch == "release/mersad-preview-0.1"
       - headSha == LOCAL_HEAD_SHA
       - databaseId not in pre_dispatch_run_ids
  3. Waits for completion via `gh run watch <run_id> --exit-status`, verifies via `gh run view <run_id> --json`
     that the run and every job succeeded (`conclusion == "success"`), downloads artifacts for that exact
     `run_id`, verifies all 5 required Windows artifacts exist (`MERSAD_AI.exe`, `MERSAD_LAB.exe`,
     `MERSAD_LAB_Setup_x64.exe`, `MERSAD_AI_Portable_x64.zip`, `MERSAD_LAB_Portable_x64.zip`),
     computes SHA-256 for each, and ONLY THEN sets status="PASS".
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
from pathlib import Path

TARGET_BRANCH = "release/mersad-preview-0.1"
EXPECTED_AI_CODE_SHA = "25131918a981ac2ac37923d4c738d9f93cdcbc5b"
EXPECTED_LAB_CODE_SHA = "e9284356f4d1a8205946d5893121c6f8a2f22012"
EXPECTED_MAIN_SHA = "25c9e5bba30dc8f921675e12c23a53571be895c1"
WORKFLOW_FILE = "release-mersad-preview-0.1-windows.yml"
DEFAULT_REMOTE_URL = "https://github.com/alinon9/MERSAD-AI-.git"

REQUIRED_WINDOWS_ARTIFACTS = [
    "MERSAD_AI.exe",
    "MERSAD_LAB.exe",
    "MERSAD_LAB_Setup_x64.exe",
    "MERSAD_AI_Portable_x64.zip",
    "MERSAD_LAB_Portable_x64.zip",
]


def run_cmd(cmd, cwd=None, env=None):
    proc = subprocess.run(cmd, cwd=cwd, env=env, text=True, capture_output=True)
    return proc.returncode, proc.stdout.strip(), proc.stderr.strip()


def parse_workflow_dispatch_inputs(workflow_yaml_path: Path) -> dict:
    """
    Parse `on.workflow_dispatch.inputs` from a GitHub Actions workflow YAML file
    without requiring PyYAML (uses PyYAML if available, plus deterministic indentation parser).
    """
    if not workflow_yaml_path.is_file():
        return {}
    text = workflow_yaml_path.read_text(encoding="utf-8")
    try:
        import yaml  # type: ignore
        data = yaml.safe_load(text)
        if isinstance(data, dict):
            on_block = data.get("on") or data.get(True) or {}
            if isinstance(on_block, dict):
                wd = on_block.get("workflow_dispatch") or {}
                if isinstance(wd, dict) and isinstance(wd.get("inputs"), dict):
                    return wd["inputs"]
    except Exception:
        pass

    inputs = {}
    lines = text.splitlines()
    in_wd = False
    in_inputs = False
    wd_indent = None
    inputs_indent = None
    cur_input_name = None
    cur_input_indent = None

    for raw_line in lines:
        stripped = raw_line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        indent = len(raw_line) - len(raw_line.lstrip(" "))
        if not in_wd:
            if re.match(r"^workflow_dispatch\s*:", stripped):
                in_wd = True
                wd_indent = indent
            continue
        if indent <= wd_indent and not re.match(r"^workflow_dispatch\s*:", stripped):
            break
        if not in_inputs:
            if re.match(r"^inputs\s*:", stripped):
                in_inputs = True
                inputs_indent = indent
            continue
        if indent <= inputs_indent:
            in_inputs = False
            break
        m_key = re.match(r"^([A-Za-z0-9_\-]+)\s*:\s*(.*)$", stripped)
        if not m_key:
            continue
        k, v = m_key.group(1), m_key.group(2).strip().strip('"')
        if cur_input_indent is None or indent == cur_input_indent:
            cur_input_indent = indent
            cur_input_name = k
            inputs[cur_input_name] = {}
        elif cur_input_name and indent > cur_input_indent:
            inputs[cur_input_name][k] = v
    return inputs


def validate_workflow_dispatch_call(workflow_yaml_path: Path, passed_inputs: dict) -> tuple[bool, str]:
    """Verify that workflow_yaml_path supports workflow_dispatch and defines all passed_inputs with valid types."""
    if not workflow_yaml_path.is_file():
        return False, f"Workflow file not found: {workflow_yaml_path}"
    text = workflow_yaml_path.read_text(encoding="utf-8")
    if "workflow_dispatch:" not in text:
        return False, f"Workflow {workflow_yaml_path.name} does not enable workflow_dispatch"
    defined_inputs = parse_workflow_dispatch_inputs(workflow_yaml_path)
    for k, v in (passed_inputs or {}).items():
        if k not in defined_inputs:
            return False, f"Input '{k}' is NOT defined under workflow_dispatch.inputs in {workflow_yaml_path.name} (defined: {list(defined_inputs.keys())})"
        inp_meta = defined_inputs[k] or {}
        inp_type = str(inp_meta.get("type", "string")).lower()
        if inp_type == "boolean" and str(v).lower() not in ("true", "false"):
            return False, f"Input '{k}' has type=boolean in {workflow_yaml_path.name}, but got non-boolean value '{v}'"
    return True, f"Validated {len(passed_inputs)} workflow_dispatch input(s) against {workflow_yaml_path.name}: {list(passed_inputs.keys())}"


def verify_and_hash_downloaded_artifacts(artifacts_dir: Path, run_id: str = "") -> dict:
    """
    Search artifacts_dir for all 5 required Windows release files, verify non-zero size,
    and compute SHA-256 for each file.
    """
    found_files = {}
    if artifacts_dir.is_dir():
        for p in sorted(artifacts_dir.rglob("*")):
            if p.is_file() and p.name in REQUIRED_WINDOWS_ARTIFACTS:
                # Prefer largest/non-empty match if multiple nested copies exist
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


def execute_deployment(
    bundle_path: Path,
    remote_url: str,
    workflow_yaml_path: Path = None,
    env_override: dict = None,
    poll_attempts: int = 24,
    poll_interval_s: float = 5.0,
    artifacts_base_dir: Path = None,
) -> dict:
    env = os.environ.copy()
    if env_override:
        env.update(env_override)

    if workflow_yaml_path is None:
        workflow_yaml_path = bundle_path.parent.parent / ".github" / "workflows" / WORKFLOW_FILE
    if artifacts_base_dir is None:
        artifacts_base_dir = bundle_path.parent.parent

    dispatch_inputs = {"run_extended_stress": "true"}

    report = {
        "timestamp": time.strftime("%Y-%m-%d %H:%M:%S"),
        "target_branch": TARGET_BRANCH,
        "expected_ai_code_sha": EXPECTED_AI_CODE_SHA,
        "expected_lab_code_sha": EXPECTED_LAB_CODE_SHA,
        "expected_main_sha": EXPECTED_MAIN_SHA,
        "workflow_file": WORKFLOW_FILE,
        "dispatch_inputs": dispatch_inputs,
        "remote_url": remote_url,
        "steps": [],
        "status": "FAIL",
        "build_triggered": False,
        "run_id": None,
        "run_url": None,
        "artifacts_verification": None,
    }

    def add_step(name, ok, detail):
        report["steps"].append({"step": name, "ok": bool(ok), "detail": detail})

    # Step 0: Validate workflow_dispatch inputs against the workflow YAML file
    ok_wf_yaml, msg_wf_yaml = validate_workflow_dispatch_call(workflow_yaml_path, dispatch_inputs)
    add_step("validate_workflow_dispatch_inputs", ok_wf_yaml, msg_wf_yaml)
    if not ok_wf_yaml:
        report["error"] = f"INVALID_WORKFLOW_DISPATCH_INPUT: {msg_wf_yaml}"
        return report

    # Step 1: Clone bundle and verify branches/commits
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

        rc, out, err = run_cmd(["git", "checkout", TARGET_BRANCH], cwd=str(work_repo), env=env)
        if rc != 0:
            add_step("checkout_release_branch", False, f"Failed to checkout {TARGET_BRANCH}: {err or out}")
            report["error"] = f"CHECKOUT_FAILED: {err or out}"
            return report

        rc, head_sha, err = run_cmd(["git", "rev-parse", "HEAD"], cwd=str(work_repo), env=env)
        rc_anc, _, _ = run_cmd(["git", "merge-base", "--is-ancestor", EXPECTED_AI_CODE_SHA, "HEAD"], cwd=str(work_repo), env=env)
        if rc != 0 or rc_anc != 0:
            add_step("verify_release_commit_lineage", False, f"HEAD {head_sha} does not descend from {EXPECTED_AI_CODE_SHA}")
            report["error"] = f"LINEAGE_MISMATCH: {head_sha}"
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
        if remote_sha.lower() != head_sha.lower():
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

        # Step 5: Record pre-dispatch run IDs so we never pick a stale run
        pre_existing_ids = set()
        rc_pre, out_pre, _ = run_cmd(
            [gh_bin, "run", "list", f"--workflow={WORKFLOW_FILE}", f"--branch={TARGET_BRANCH}", "--event=workflow_dispatch", "--limit=20", "--json", "databaseId"],
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
        add_step("record_pre_dispatch_runs", True, f"Recorded {len(pre_existing_ids)} pre-existing workflow_dispatch run ID(s): {sorted(pre_existing_ids)}")

        # Step 6: Trigger workflow_dispatch on release/mersad-preview-0.1
        wf_cmd = [gh_bin, "workflow", "run", WORKFLOW_FILE, "--ref", TARGET_BRANCH]
        for k, v in dispatch_inputs.items():
            wf_cmd.extend(["-f", f"{k}={v}"])
        rc_wf, out_wf, err_wf = run_cmd(wf_cmd, cwd=str(work_repo), env=env)
        if rc_wf != 0:
            add_step("trigger_workflow_dispatch", False, f"gh workflow run failed: {err_wf or out_wf}")
            report["error"] = f"GH_WORKFLOW_RUN_FAILED: {err_wf or out_wf}"
            return report

        report["build_triggered"] = True
        # IMPORTANT (BUG-15): Never set status="PASS" merely because workflow_dispatch was sent!
        report["status"] = "DISPATCHED"
        add_step("trigger_workflow_dispatch", True, f"Dispatched {WORKFLOW_FILE} on --ref {TARGET_BRANCH} (status=DISPATCHED)")

        # Step 7: Poll for the NEW run matching workflow + event=workflow_dispatch + headBranch + headSha == local_head_sha
        matched_run = None
        for attempt in range(1, poll_attempts + 1):
            if poll_interval_s > 0:
                time.sleep(poll_interval_s)
            rc_list, out_list, err_list = run_cmd(
                [
                    gh_bin, "run", "list",
                    f"--workflow={WORKFLOW_FILE}",
                    f"--branch={TARGET_BRANCH}",
                    "--event=workflow_dispatch",
                    "--limit=15",
                    "--json", "databaseId,headSha,event,headBranch,status,conclusion,createdAt,url",
                ],
                cwd=str(work_repo),
                env=env,
            )
            if rc_list == 0 and out_list:
                try:
                    runs = json.loads(out_list)
                    for r in runs:
                        if not isinstance(r, dict):
                            continue
                        r_id = int(r.get("databaseId", 0))
                        r_sha = str(r.get("headSha", "")).strip()
                        r_evt = str(r.get("event", "")).strip()
                        r_br = str(r.get("headBranch", "")).strip()
                        if (
                            r_id > 0
                            and r_id not in pre_existing_ids
                            and r_evt == "workflow_dispatch"
                            and r_br == TARGET_BRANCH
                            and r_sha.lower() == head_sha.lower()
                        ):
                            matched_run = r
                            break
                except Exception:
                    pass
            if matched_run is not None:
                break

        if matched_run is None:
            msg = f"No new workflow_dispatch run matching headSha={head_sha} on branch {TARGET_BRANCH} appeared after {poll_attempts} poll attempt(s)."
            add_step("poll_matching_run_id", False, msg)
            report["error"] = f"RUN_ID_POLL_TIMEOUT: {msg}"
            return report

        run_id = str(matched_run["databaseId"])
        report["run_id"] = run_id
        report["run_url"] = matched_run.get("url")
        add_step("poll_matching_run_id", True, f"Matched new workflow_dispatch Run ID {run_id} for headSha={head_sha}")

        # Step 8: Watch run to completion and verify all jobs succeeded
        rc_watch, out_watch, err_watch = run_cmd(
            [gh_bin, "run", "watch", run_id, "--exit-status"],
            cwd=str(work_repo),
            env=env,
        )
        if rc_watch != 0:
            msg = f"gh run watch {run_id} failed (exit={rc_watch}): {err_watch or out_watch}"
            add_step("watch_workflow_run", False, msg)
            report["status"] = "FAIL"
            report["error"] = f"WORKFLOW_RUN_FAILED: {msg}"
            return report

        rc_view, out_view, err_view = run_cmd(
            [gh_bin, "run", "view", run_id, "--json", "status,conclusion,jobs,url"],
            cwd=str(work_repo),
            env=env,
        )
        if rc_view != 0:
            msg = f"gh run view {run_id} failed: {err_view or out_view}"
            add_step("verify_all_jobs_succeeded", False, msg)
            report["status"] = "FAIL"
            report["error"] = f"RUN_VIEW_FAILED: {msg}"
            return report

        try:
            view_data = json.loads(out_view)
        except Exception as e:
            add_step("verify_all_jobs_succeeded", False, f"Invalid JSON from gh run view: {e}")
            report["status"] = "FAIL"
            report["error"] = f"RUN_VIEW_JSON_ERROR: {e}"
            return report

        run_conclusion = str(view_data.get("conclusion", "")).lower()
        jobs_list = view_data.get("jobs") or []
        failed_jobs = [j.get("name", "unknown") for j in jobs_list if str(j.get("conclusion", "")).lower() != "success"]
        if run_conclusion != "success" or failed_jobs:
            msg = f"Run {run_id} conclusion={run_conclusion}, failed_jobs={failed_jobs}"
            add_step("verify_all_jobs_succeeded", False, msg)
            report["status"] = "FAIL"
            report["error"] = f"JOBS_FAILED: {msg}"
            return report
        add_step("verify_all_jobs_succeeded", True, f"Run {run_id} completed with conclusion=success across {len(jobs_list)} job(s)")

        # Step 9: Download artifacts for this exact Run ID and verify all 5 Windows files + SHA-256
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
            add_step("download_run_artifacts", False, msg)
            report["status"] = "FAIL"
            report["error"] = f"ARTIFACT_DOWNLOAD_FAILED: {msg}"
            return report
        add_step("download_run_artifacts", True, f"Downloaded artifacts for Run ID {run_id} into {out_art_dir.name}")

        art_ver = verify_and_hash_downloaded_artifacts(out_art_dir, run_id=run_id)
        report["artifacts_verification"] = art_ver
        if not art_ver["ok"]:
            msg = f"Missing or empty required Windows artifacts: missing={art_ver['missing_files']}, empty={art_ver['empty_files']}"
            add_step("verify_five_windows_artifacts_sha256", False, msg)
            report["status"] = "FAIL"
            report["error"] = f"ARTIFACTS_INCOMPLETE: {msg}"
            return report

        add_step("verify_five_windows_artifacts_sha256", True, f"Verified all 5 Windows artifacts and computed SHA-256 checksums for Run ID {run_id}")
        report["status"] = "PASS"
        return report


def run_self_test(repo_root: Path) -> dict:
    bundle = repo_root / "reports_and_logs" / "mersad_preview_0_1_verifiable_history.bundle"
    bat_file = repo_root / "PUSH_CANDIDATE_9491BCD_TO_GITHUB_ACTIONS.bat"
    wf_file = repo_root / ".github" / "workflows" / WORKFLOW_FILE
    bat_text = bat_file.read_text(encoding="utf-8")

    checks = []
    # Check 1 & 2: Workflow YAML defines run_extended_stress (boolean) and rejects undefined inputs
    ok_valid_in, _ = validate_workflow_dispatch_call(wf_file, {"run_extended_stress": "true"})
    ok_undef_in, _ = validate_workflow_dispatch_call(wf_file, {"non_existent_input": "true"})
    ok_bad_bool, _ = validate_workflow_dispatch_call(wf_file, {"run_extended_stress": "not_a_boolean"})
    checks.append(("WORKFLOW_YAML_DEFINES_RUN_EXTENDED_STRESS_BOOLEAN", ok_valid_in is True))
    checks.append(("WORKFLOW_VALIDATOR_REJECTS_UNDEFINED_OR_INVALID_INPUTS", (not ok_undef_in) and (not ok_bad_bool)))

    # Check 3..6: Batch script static & structural checks
    checks.append(("BAT_USES_RELEASE_BRANCH", 'set "TARGET_BRANCH=release/mersad-preview-0.1"' in bat_text and "preview/mersad-ai-lab-0.1-20261105" not in bat_text))
    checks.append(("BAT_USES_FINAL_COMMITS", EXPECTED_AI_CODE_SHA in bat_text and EXPECTED_LAB_CODE_SHA in bat_text))
    checks.append(("BAT_PRESERVES_MAIN_AND_NO_FORCE", EXPECTED_MAIN_SHA in bat_text and "git push --force" not in bat_text and "git push -f" not in bat_text))
    checks.append(("BAT_POLLS_NEW_RUN_BY_HEAD_SHA_AND_EVENT", "select(.event == " in bat_text and ".headSha == " in bat_text and ".databaseId > !PREV_LATEST_RUN_ID!" in bat_text))

    with tempfile.TemporaryDirectory(prefix="mersad_bare_remote_") as tmpdir:
        tmp_p = Path(tmpdir)
        bare_remote = tmp_p / "origin.git"
        subprocess.run(["git", "init", "--bare", str(bare_remote)], check=True, capture_output=True)

        # Test A: Missing gh in PATH must halt with error after verifying local bare push and remote SHA
        res_no_gh = execute_deployment(bundle, str(bare_remote), wf_file, env_override={"PATH": "/usr/bin:/bin"}, poll_attempts=1, poll_interval_s=0.0)
        checks.append(("LOCAL_BARE_PUSH_AND_LS_REMOTE_SHA_MATCH", res_no_gh.get("verified_remote_sha") == res_no_gh.get("local_head_sha") and bool(res_no_gh.get("verified_remote_sha"))))
        checks.append(("MISSING_GH_HALTS_WITH_ERROR", res_no_gh["status"] == "FAIL" and res_no_gh["build_triggered"] is False and "GH_CLI_NOT_INSTALLED" in res_no_gh.get("error", "")))

        # Test B: Unauthenticated gh must halt with GH_CLI_UNAUTHENTICATED
        fake_bin_unauth = tmp_p / "fake_bin_unauth"
        fake_bin_unauth.mkdir()
        fake_gh_unauth = fake_bin_unauth / "gh"
        fake_gh_unauth.write_text("#!/bin/sh\nexit 1\n")
        fake_gh_unauth.chmod(0o755)
        res_unauth = execute_deployment(bundle, str(bare_remote), wf_file, env_override={"PATH": f"{fake_bin_unauth}:/usr/bin:/bin"}, poll_attempts=1, poll_interval_s=0.0)
        checks.append(("UNAUTH_GH_HALTS_WITH_ERROR", res_unauth["status"] == "FAIL" and res_unauth["build_triggered"] is False and "GH_CLI_UNAUTHENTICATED" in res_unauth.get("error", "")))

        # Test C: Dispatch succeeds, but only old/wrong-SHA runs exist -> status stays DISPATCHED (never PASS!)
        fake_bin_stale = tmp_p / "fake_bin_stale"
        fake_bin_stale.mkdir()
        fake_gh_stale = fake_bin_stale / "gh"
        stale_script = """#!/usr/bin/env python3
import json, sys
args = sys.argv[1:]
if args[:2] == ["auth", "status"]:
    sys.exit(0)
if args[:2] == ["workflow", "run"]:
    sys.exit(0)
if args[:2] == ["run", "list"]:
    # Return an old pre-existing run (1001) and a run with a wrong headSha (1002)
    print(json.dumps([
        {"databaseId": 1001, "headSha": "OLD_SHA", "event": "workflow_dispatch", "headBranch": "release/mersad-preview-0.1"},
        {"databaseId": 1002, "headSha": "WRONG_SHA_9999", "event": "workflow_dispatch", "headBranch": "release/mersad-preview-0.1"}
    ]))
    sys.exit(0)
sys.exit(1)
"""
        fake_gh_stale.write_text(stale_script, encoding="utf-8")
        fake_gh_stale.chmod(0o755)
        res_stale = execute_deployment(bundle, str(bare_remote), wf_file, env_override={"PATH": f"{fake_bin_stale}:/usr/bin:/bin"}, poll_attempts=2, poll_interval_s=0.0)
        checks.append((
            "DISPATCH_WITHOUT_NEW_MATCHING_SHA_RUN_STAYS_DISPATCHED_NEVER_PASS",
            res_stale["status"] == "DISPATCHED" and res_stale["run_id"] is None and "RUN_ID_POLL_TIMEOUT" in res_stale.get("error", "")
        ))

        # Test D: New matching headSha run appears, job fails -> status=FAIL
        local_head = res_no_gh["local_head_sha"]
        fake_bin_failjob = tmp_p / "fake_bin_failjob"
        fake_bin_failjob.mkdir()
        state_file_fail = tmp_p / "state_fail.txt"
        failjob_script = f"""#!/usr/bin/env python3
import json, pathlib, sys
args = sys.argv[1:]
sf = pathlib.Path("{state_file_fail}")
if args[:2] == ["auth", "status"]:
    sys.exit(0)
if args[:2] == ["workflow", "run"]:
    sf.write_text("dispatched")
    sys.exit(0)
if args[:2] == ["run", "list"]:
    if not sf.exists():
        print(json.dumps([{{"databaseId": 5000, "headSha": "{local_head}", "event": "workflow_dispatch", "headBranch": "release/mersad-preview-0.1"}}]))
    else:
        print(json.dumps([
            {{"databaseId": 5005, "headSha": "{local_head}", "event": "workflow_dispatch", "headBranch": "release/mersad-preview-0.1", "url": "https://github.com/alinon9/MERSAD-AI-/actions/runs/5005"}},
            {{"databaseId": 5000, "headSha": "{local_head}", "event": "workflow_dispatch", "headBranch": "release/mersad-preview-0.1"}}
        ]))
    sys.exit(0)
if args[:2] == ["run", "watch"]:
    sys.exit(0)
if args[:2] == ["run", "view"]:
    print(json.dumps({{"status": "completed", "conclusion": "failure", "jobs": [{{"name": "build-and-verify-windows-x64", "conclusion": "failure"}}]}}))
    sys.exit(0)
sys.exit(1)
"""
        (fake_bin_failjob / "gh").write_text(failjob_script, encoding="utf-8")
        (fake_bin_failjob / "gh").chmod(0o755)
        res_failjob = execute_deployment(bundle, str(bare_remote), wf_file, env_override={"PATH": f"{fake_bin_failjob}:/usr/bin:/bin"}, poll_attempts=2, poll_interval_s=0.0)
        checks.append((
            "NEW_RUN_WITH_FAILED_JOB_REJECTED_AS_FAIL",
            res_failjob["run_id"] == "5005" and res_failjob["status"] == "FAIL" and "JOBS_FAILED" in res_failjob.get("error", "")
        ))

        # Test E: Full end-to-end simulated workflow run (new Run ID 6001 matching headSha -> watch -> view success -> download all 5 artifacts -> SHA-256 verified -> status=PASS)
        fake_bin_ok = tmp_p / "fake_bin_ok"
        fake_bin_ok.mkdir()
        state_file_ok = tmp_p / "state_ok.txt"
        ok_script = f"""#!/usr/bin/env python3
import json, pathlib, sys
args = sys.argv[1:]
sf = pathlib.Path("{state_file_ok}")
if args[:2] == ["auth", "status"]:
    sys.exit(0)
if args[:2] == ["workflow", "run"]:
    sf.write_text("dispatched")
    sys.exit(0)
if args[:2] == ["run", "list"]:
    if not sf.exists():
        print(json.dumps([{{"databaseId": 6000, "headSha": "{local_head}", "event": "workflow_dispatch", "headBranch": "release/mersad-preview-0.1"}}]))
    else:
        print(json.dumps([
            {{"databaseId": 6001, "headSha": "{local_head}", "event": "workflow_dispatch", "headBranch": "release/mersad-preview-0.1", "url": "https://github.com/alinon9/MERSAD-AI-/actions/runs/6001"}},
            {{"databaseId": 6000, "headSha": "{local_head}", "event": "workflow_dispatch", "headBranch": "release/mersad-preview-0.1"}}
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
            "FULL_E2E_WATCH_DOWNLOAD_AND_5_ARTIFACT_SHA256_PASS",
            res_ok["status"] == "PASS"
            and res_ok["run_id"] == "6001"
            and res_ok.get("artifacts_verification", {}).get("ok") is True
            and res_ok.get("artifacts_verification", {}).get("verified_count") == 5
        ))

    # Check 13: Verify 4-stage model breakdown never converts NOT_TESTED to PASS
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

    # Check 14: Verify MERSAD LAB Git bundle provenance (14/14 files match e9284356f4d1a8205946d5893121c6f8a2f22012)
    import importlib.util
    spec_lp = importlib.util.spec_from_file_location("verify_mersad_lab_provenance", str(repo_root / "tools" / "verify_mersad_lab_provenance.py"))
    mod_lp = importlib.util.module_from_spec(spec_lp)
    spec_lp.loader.exec_module(mod_lp)
    lab_prov = mod_lp.verify_lab_provenance(repo_root)
    checks.append((
        "MERSAD_LAB_GIT_BUNDLE_PROVENANCE_14_OF_14_SHA256_MATCH",
        lab_prov["status"] == "PASS" and lab_prov["matched_files_count"] == 14 and lab_prov["verified_head_commit"] == EXPECTED_LAB_CODE_SHA
    ))

    all_ok = all(ok for _, ok in checks)
    return {"all_passed": all_ok, "total_checks": len(checks), "passed_checks": sum(1 for _, ok in checks if ok), "checks": [{"name": k, "passed": v} for k, v in checks]}


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--self-test", action="store_true")
    ap.add_argument("--live", action="store_true")
    ap.add_argument("--verify-downloaded-artifacts", type=str, default="")
    ap.add_argument("--run-id", type=str, default="")
    args = ap.parse_args()
    root = Path(__file__).resolve().parent.parent
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
        )
        print(json.dumps(rep, indent=2, ensure_ascii=False))
        sys.exit(0 if rep["status"] == "PASS" else 1)
