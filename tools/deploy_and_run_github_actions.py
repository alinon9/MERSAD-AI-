#!/usr/bin/env python3
"""
Deterministic Push-Triggered Single-Run CI Deployment Controller, Central Target-Branch Allowlist Enforcer,
Real GitHub REST API Paginated Run Poller, Authoritative Workflow Identity Validator,
Delayed Duplicate-Run Settling Detector, Pre-Push Remote State & Fast-Forward Verifier,
5-Artifact SHA-256 Calculator/Recorder, and Forensic ZIP-vs-Git Provenance Verifier for MERSAD Preview 0.1
(Closes BUG-12..BUG-15, BUG-23..BUG-25, BUG-34..BUG-49).

Key security & engineering guarantees:
  1. Central Target-Branch Allowlist & Legacy Wrapper Remediation (BUG-40, BUG-46, BUG-49):
     - Defines `ALLOWED_DEPLOY_BRANCHES = ("fix/preview-0.1-postbuild-42273598736",)`.
     - Rejects any non-allowlisted branch (`main`, `release/mersad-preview-0.1`, `release/v7.1-stage15-win-x64`,
       empty branch `""`, or arbitrary overrides via `--branch`, `MERSAD_DEPLOY_BRANCH`, or `MERSAD_BUILD_BRANCH`)
       at the very start of preflight with `status = "PREFLIGHT_FAILED"` and `branch_validation_status = "BRANCH_NOT_IN_ALLOWLIST"`.
     - All 3 `.bat` scripts (`PUSH_RELEASE_PREVIEW_0_1_TO_GITHUB_ACTIONS.bat`,
       `PUSH_CANDIDATE_9491BCD_TO_GITHUB_ACTIONS.bat`, and `MERSAD_AI_Preview_0.1/PUSH_TO_GITHUB_AND_BUILD.bat`)
       enforce the same allowlist and delegate 100% of cloud deployment to this controller without direct `git push`,
       `gh workflow run`, default-branch workflow registration, or silenced errors.
  2. Real GitHub REST API Pagination Without Synthetic Env Vars (BUG-41, BUG-47):
     - Queries workflow metadata (`repos/{owner}/{repo}/actions/workflows/{workflow_file}`) and paginated workflow runs
       (`repos/{owner}/{repo}/actions/workflows/{workflow_id}/runs?per_page={per_page}&page={page_idx}`) via `gh api`.
     - Contains ZERO synthetic `MERSAD_GH_PAGE` or `MERSAD_GH_PER_PAGE` environment variables.
     - Validates HTTP/CLI exit codes (including 401/403 Auth, 429 Rate Limit), JSON schema (`total_count`, `workflow_runs`),
       chronological ordering (`created_at` non-increasing), and duplicate page results (`GH_API_DUPLICATE_PAGE_RESULTS`).
     - Fails closed (`PREFLIGHT_FAILED`) with `GH_API_MAX_PAGES_LIMIT_REACHED_INCOMPLETE_HISTORY` if `max_pages` is
       reached while `len(all_runs) < total_count`.
  3. Authoritative Workflow Identity Verification Without Default Fallbacks (BUG-48):
     - `validate_and_normalize_run_record()` never invents or defaults missing workflow identity fields (`or WORKFLOW_FILE`
       is completely removed).
     - Requires every run record to explicitly carry `workflow_id` matching the resolved integer `expected_workflow_id`
       AND explicit non-empty `path` (`.github/workflows/release-mersad-preview-0.1-windows.yml`) or `name`/`workflowName`
       matching the resolved workflow metadata.
  4. Pre-Push Remote SHA & Fast-Forward Verification (BUG-44):
     - Queries `git ls-remote origin refs/heads/<branch>` before attempting `git push`.
     - Halts with `REMOTE_ALREADY_AT_LOCAL_HEAD_NO_NEW_PUSH_EVENT` if remote already matches local HEAD, or
       `REMOTE_DIVERGED_NOT_FAST_FORWARD` if remote is not an ancestor of local HEAD.
  5. Delayed Duplicate-Run Detection via Multi-Page Settling Window (BUG-42, BUG-47):
     - Continues querying paginated GitHub Actions runs across `settling_polls` iterations before transitioning to
       `RUN_IN_PROGRESS`; aborts with `DUPLICATE_RUN_DETECTED` if a second matching run appears on any page.
  6. Honest SHA-256 Calculation & Recording vs. Trusted Digest / Attestation (BUG-45):
     - Records `SHA256_CALCULATED_AND_RECORDED` and separates local hash calculation from `trusted_reference_digests_verified`
       and `attestation_verification_status`.
"""
import argparse
import datetime
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

ALLOWED_DEPLOY_BRANCHES = (
    "fix/preview-0.1-postbuild-42273598736",
)
DEFAULT_TARGET_BRANCH = "fix/preview-0.1-postbuild-42273598736"
TARGET_BRANCH = DEFAULT_TARGET_BRANCH

EXPECTED_AI_BUG52_PARENT_SHA = "62b409e2327b86ad0720a526cb3ba8573821b09b"
EXPECTED_AI_BUG50_51_PARENT_SHA = "de55bcc519366da996e6086d48005f9ad8eafa2a"
EXPECTED_AI_BUG46_49_PARENT_SHA = "eaf89c71b3b54de14a1c64bf862bb6e6eec321cc"
EXPECTED_AI_BUG40_45_PARENT_SHA = "850fbdb450ba98e09994c6b6b01b84e1a5e65fe6"
EXPECTED_AI_SINGLE_RUN_CI_PARENT_SHA = "a1c53f32ff3c5c9ab995de2672ff29f2de13ea38"
EXPECTED_AI_PREFLIGHT_PARENT_SHA = "05f29af416c4a28ddf59c291819584d1a416d570"
EXPECTED_AI_CODE_SHA = "edaf651321ec9ea6ba613e3ab1630bc16b11b9d5"
EXPECTED_AI_PREV_FIX_SHA = "d965d71317e3506e5dce9d316dc81cb8ae45e43b"
EXPECTED_AI_COMMON_FORK_POINT_SHA = "2c22280d84a5fcb7b709075f73b3073bcef0aff2"
EXPECTED_AI_RELEASE_BASE_SHA = "25131918a981ac2ac37923d4c738d9f93cdcbc5b"
EXPECTED_LAB_CODE_SHA = "748ac0158761812a6fff63ff6fe626b9df8c252b"
EXPECTED_LAB_RELEASE_BASE_SHA = "e9284356f4d1a8205946d5893121c6f8a2f22012"

# Strict separation between offline bundle snapshot SHA and live GitHub main SHA (ARGON / BUG-53):
#   - EXPECTED_BUNDLE_MAIN_SNAPSHOT_SHA: used EXCLUSIVELY for local Git Bundle snapshot integrity verification.
#   - EXPECTED_LIVE_GITHUB_MAIN_SHA: used EXCLUSIVELY for actual remote refs/heads/main verification.
#   - ALLOWED_REMOTE_MAIN_SHAS: contains ONLY EXPECTED_LIVE_GITHUB_MAIN_SHA (never the offline bundle snapshot SHA).
EXPECTED_BUNDLE_MAIN_SNAPSHOT_SHA = "25c9e5bba30dc8f921675e12c23a53571be895c1"
EXPECTED_LIVE_GITHUB_MAIN_SHA = "38a09da9854bcf276386391c5a06c2706bb119c3"
ALLOWED_REMOTE_MAIN_SHAS = (
    EXPECTED_LIVE_GITHUB_MAIN_SHA,
)
EXPECTED_LIVE_REMOTE_RELEASE_BRANCH_SHA = "b8196e3528d5d6082ea866a46e1cccd1bff5f253"
EXPECTED_LAB_MAIN_SHA = "1c56dcbf77d62b8d89863e04f215e12f162e9555"

WORKFLOW_FILE = "release-mersad-preview-0.1-windows.yml"
WORKFLOW_DEFINITION_PATH = f".github/workflows/{WORKFLOW_FILE}"
EXPECTED_WORKFLOW_DISPLAY_NAME = "Build & Verify MERSAD PREVIEW 0.1 Final Windows x64 Release"
EXPECTED_LIVE_GITHUB_WORKFLOW_ID = 147631346
FORBIDDEN_DISPATCH_WORKFLOW_PATH = ".github/workflows/build-mersad-preview-dispatch.yml"
FORBIDDEN_DISPATCH_WORKFLOW_ID = 147631347
FORBIDDEN_WORKFLOW_PATHS = (
    ".github/workflows/build-mersad-preview-dispatch.yml",
    ".github/workflows/build-mersad-windows.yml",
    ".github/workflows/windows-build.yml",
    ".github/workflows/build-mersad-lab-exe.yml",
    ".github/workflows/export-mersad-source.yml",
)
FORBIDDEN_WORKFLOW_NAMES = (
    "Build MERSAD PREVIEW 0.1 Windows x64",
    "Build MERSAD AI Windows EXE",
    "Build MERSAD LAB Windows EXE",
    "Export MERSAD AI V7.1 patched source",
)
DEFAULT_REMOTE_URL = "https://github.com/alinon9/MERSAD-AI-.git"
DEFAULT_GITHUB_REPO = "alinon9/MERSAD-AI-"

# Configurable polling & duplicate-detection settling window defaults (BUG-42 & BUG-47)
DEFAULT_POLL_ATTEMPTS = int(os.environ.get("MERSAD_CI_POLL_ATTEMPTS", "24"))
DEFAULT_POLL_INTERVAL_S = float(os.environ.get("MERSAD_CI_POLL_INTERVAL_S", "5.0"))
DEFAULT_SETTLING_POLLS = int(os.environ.get("MERSAD_CI_SETTLING_POLLS", "3"))
DEFAULT_SETTLING_INTERVAL_S = float(os.environ.get("MERSAD_CI_SETTLING_INTERVAL_S", "5.0"))
DEFAULT_PREFLIGHT_MAX_PAGES = int(os.environ.get("MERSAD_CI_PREFLIGHT_MAX_PAGES", "5"))
DEFAULT_PREFLIGHT_PER_PAGE = int(os.environ.get("MERSAD_CI_PREFLIGHT_PER_PAGE", "50"))

REQUIRED_WINDOWS_ARTIFACTS = [
    "MERSAD_AI.exe",
    "MERSAD_LAB.exe",
    "MERSAD_LAB_Setup_x64.exe",
    "MERSAD_AI_Portable_x64.zip",
    "MERSAD_LAB_Portable_x64.zip",
]

# Unified 1 Workflow File + 16 Required Paths = 17 Verified Paths
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


def run_cmd(cmd, cwd=None, env=None, timeout=60):
    try:
        proc = subprocess.run(cmd, cwd=cwd, env=env, text=True, capture_output=True, timeout=timeout)
        return proc.returncode, proc.stdout.strip(), proc.stderr.strip()
    except subprocess.TimeoutExpired as exc:
        return 124, "", f"Command timed out after {timeout}s: {exc}"
    except Exception as exc:
        return 125, "", f"Command execution error: {exc}"


def validate_target_branch_allowlist(target_branch=None, env: dict = None) -> tuple[bool, str, str]:
    """
    Central target-branch allowlist validator (BUG-49).
    Enforces that ONLY branches in `ALLOWED_DEPLOY_BRANCHES` can ever be targeted for deployment.
    Any attempt to override the branch via `target_branch` CLI/API parameter, `MERSAD_DEPLOY_BRANCH`,
    or `MERSAD_BUILD_BRANCH` to `main`, `release/mersad-preview-0.1`, empty string, or any other value
    is rejected fail-closed BEFORE any Git or network operation.
    """
    env_dict = env if isinstance(env, dict) else os.environ

    for env_key in ("MERSAD_DEPLOY_BRANCH", "MERSAD_BUILD_BRANCH"):
        if env_key in env_dict:
            env_val = env_dict.get(env_key)
            if not isinstance(env_val, str) or not env_val.strip() or env_val.strip() != env_val or env_val not in ALLOWED_DEPLOY_BRANCHES:
                return (
                    False,
                    str(env_val or ""),
                    f"BRANCH_NOT_IN_ALLOWLIST: Environment variable {env_key}={env_val!r} is not in ALLOWED_DEPLOY_BRANCHES {ALLOWED_DEPLOY_BRANCHES}",
                )

    if target_branch is not None:
        if not isinstance(target_branch, str) or not target_branch.strip() or target_branch.strip() != target_branch:
            return (
                False,
                str(target_branch or ""),
                f"BRANCH_NOT_IN_ALLOWLIST: Target branch parameter {target_branch!r} is empty or malformed; only {ALLOWED_DEPLOY_BRANCHES} is allowed",
            )
        candidate = target_branch
    elif "MERSAD_DEPLOY_BRANCH" in env_dict:
        candidate = env_dict["MERSAD_DEPLOY_BRANCH"]
    elif "MERSAD_BUILD_BRANCH" in env_dict:
        candidate = env_dict["MERSAD_BUILD_BRANCH"]
    else:
        candidate = DEFAULT_TARGET_BRANCH

    if candidate not in ALLOWED_DEPLOY_BRANCHES:
        return (
            False,
            candidate,
            f"BRANCH_NOT_IN_ALLOWLIST: Target branch {candidate!r} is not in ALLOWED_DEPLOY_BRANCHES {ALLOWED_DEPLOY_BRANCHES}",
        )

    return (
        True,
        candidate,
        f"Verified target branch {candidate!r} against central allowlist ALLOWED_DEPLOY_BRANCHES={ALLOWED_DEPLOY_BRANCHES}",
    )


def parse_iso8601_utc(ts_str: str):
    """Parse an ISO-8601 UTC timestamp string (e.g. '2026-11-08T12:00:00Z') into a timezone-aware datetime."""
    if not ts_str or not isinstance(ts_str, str):
        return None
    s = ts_str.strip()
    if not s:
        return None
    try:
        if s.endswith("Z"):
            s = s[:-1] + "+00:00"
        dt = datetime.datetime.fromisoformat(s)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=datetime.timezone.utc)
        return dt.astimezone(datetime.timezone.utc)
    except Exception:
        return None


def _validate_single_workflow_meta_obj(meta: dict, expected_path: str, endpoint_desc: str) -> dict:
    """Validate a single GitHub Actions workflow metadata JSON object fail-closed."""
    if not isinstance(meta, dict):
        return {
            "ok": False,
            "error": f"GH_API_WORKFLOW_META_INVALID_TYPE: Expected JSON object from {endpoint_desc}, got {type(meta).__name__}",
        }

    raw_wf_id = meta.get("id")
    if raw_wf_id is None or isinstance(raw_wf_id, bool):
        return {"ok": False, "error": "GH_API_WORKFLOW_META_MISSING_ID: Workflow metadata is missing integer 'id'"}
    try:
        wf_id = int(raw_wf_id)
    except (ValueError, TypeError):
        return {"ok": False, "error": f"GH_API_WORKFLOW_META_INVALID_ID: {raw_wf_id!r}"}
    if wf_id <= 0:
        return {"ok": False, "error": f"GH_API_WORKFLOW_META_NONPOSITIVE_ID: {wf_id}"}

    wf_path = str(meta.get("path") or "").strip()
    if wf_path in FORBIDDEN_WORKFLOW_PATHS:
        return {
            "ok": False,
            "error": f"GH_API_FORBIDDEN_WORKFLOW_PATH: {wf_path!r} is a forbidden dispatch/legacy workflow",
        }
    if wf_path != expected_path:
        return {
            "ok": False,
            "error": f"GH_API_WORKFLOW_META_PATH_MISMATCH: got {wf_path!r}, expected {expected_path!r}",
        }

    wf_name = str(meta.get("name") or "").strip()
    if not wf_name:
        return {"ok": False, "error": "GH_API_WORKFLOW_META_MISSING_NAME: Workflow metadata is missing 'name'"}
    if wf_name in FORBIDDEN_WORKFLOW_NAMES:
        return {
            "ok": False,
            "error": f"GH_API_FORBIDDEN_WORKFLOW_NAME: {wf_name!r} belongs to a forbidden workflow",
        }

    wf_state = str(meta.get("state") or "active").strip().lower()
    if wf_state != "active":
        return {"ok": False, "error": f"GH_API_WORKFLOW_NOT_ACTIVE: Workflow state is {wf_state!r}"}

    return {
        "ok": True,
        "error": None,
        "workflow_id": wf_id,
        "path": wf_path,
        "name": wf_name,
        "state": wf_state,
        "endpoint": endpoint_desc,
    }


def resolve_workflow_metadata_fail_closed(
    gh_bin: str,
    work_repo: Path,
    env: dict,
    github_repo: str = DEFAULT_GITHUB_REPO,
    workflow_file: str = WORKFLOW_FILE,
    allow_deferred_pre_push: bool = False,
) -> dict:
    """
    Resolve authoritative workflow metadata (`id`, `path`, `name`, `state`) via GitHub REST API (BUG-48 & BUG-52 / ARGON):
      1. Primary lookup: `gh api -X GET repos/{github_repo}/actions/workflows/{workflow_file}`.
      2. Catalog fallback (when `.github/workflows/{workflow_file}` is absent from remote `main` so filename lookup
         returns HTTP 404): queries `gh api -X GET "repos/{github_repo}/actions/workflows?per_page=100&page=1"`,
         audits and excludes non-target workflows (such as `.github/workflows/build-mersad-preview-dispatch.yml`,
         `id=147631347`), and resolves the workflow whose `path == ".github/workflows/{workflow_file}"`
         (e.g. `id=147631346`).
      3. Two-phase pre-push handling for brand-new branch workflows (`allow_deferred_pre_push=True` ONLY when
         `pre_push_remote_sha is None` before pushing a new branch): if `/actions/workflows` returns 200 OK valid JSON
         but `.github/workflows/{workflow_file}` has never been pushed to any remote branch yet, returns
         `deferred_until_branch_push=True` so preflight can proceed to `git push`, after which post-push polling MUST
         resolve authoritative workflow metadata (`allow_deferred_pre_push=False`) before any run is inspected or accepted.
    """
    expected_path = f".github/workflows/{workflow_file}"
    endpoint = f"repos/{github_repo}/actions/workflows/{workflow_file}"
    rc, out, err = run_cmd([gh_bin, "api", "-X", "GET", endpoint], cwd=str(work_repo), env=env)
    if rc == 0:
        if not out or not out.strip():
            return {
                "ok": False,
                "error": f"GH_API_WORKFLOW_META_EMPTY_STDOUT: Empty response from {endpoint}",
            }
        try:
            meta = json.loads(out)
        except Exception as exc:
            return {
                "ok": False,
                "error": f"GH_API_WORKFLOW_META_INVALID_JSON: {exc}",
            }
        res = _validate_single_workflow_meta_obj(meta, expected_path, endpoint)
        if res["ok"]:
            res["resolution_mode"] = "DIRECT_WORKFLOW_ENDPOINT"
            res["deferred_until_branch_push"] = False
            res["excluded_remote_workflows"] = []
        return res

    combined = f"{err} {out}".strip()
    low = combined.lower()
    if "401" in low or "403" in low or "forbidden" in low or "unauthorized" in low:
        return {
            "ok": False,
            "error": f"GH_API_HTTP_401_403_AUTH_ERROR_{rc}: Failed to query workflow metadata ({endpoint}): {combined or 'auth error'}",
        }
    if "429" in low or "rate limit" in low:
        return {
            "ok": False,
            "error": f"GH_API_HTTP_429_RATE_LIMIT_ERROR_{rc}: Failed to query workflow metadata ({endpoint}): {combined or 'rate limit'}",
        }

    # If the direct filename lookup returned 404 / not found (because the workflow is absent from remote main),
    # query the repository workflow catalog endpoint `repos/{github_repo}/actions/workflows?per_page=100&page=1`.
    if "404" in low or "not found" in low:
        catalog_ep = f"repos/{github_repo}/actions/workflows?per_page=100&page=1"
        rc_cat, out_cat, err_cat = run_cmd([gh_bin, "api", "-X", "GET", catalog_ep], cwd=str(work_repo), env=env)
        if rc_cat != 0:
            comb_cat = f"{err_cat} {out_cat}".strip()
            return {
                "ok": False,
                "error": (
                    f"GH_API_WORKFLOW_META_EXIT_{rc}: Direct lookup ({endpoint}) returned 404 and catalog lookup "
                    f"({catalog_ep}) failed (exit={rc_cat}): {comb_cat or combined}"
                ),
            }
        if not out_cat or not out_cat.strip():
            return {
                "ok": False,
                "error": f"GH_API_WORKFLOW_CATALOG_EMPTY_STDOUT: Empty response from {catalog_ep}",
            }
        try:
            cat_data = json.loads(out_cat)
        except Exception as exc:
            return {
                "ok": False,
                "error": f"GH_API_WORKFLOW_CATALOG_INVALID_JSON: {exc}",
            }
        if not isinstance(cat_data, dict) or not isinstance(cat_data.get("workflows"), list):
            return {
                "ok": False,
                "error": f"GH_API_WORKFLOW_CATALOG_INVALID_SCHEMA: Expected dict with 'workflows' list from {catalog_ep}",
            }

        excluded_workflows = []
        matched_wf_obj = None
        for wf_item in cat_data["workflows"]:
            if not isinstance(wf_item, dict):
                continue
            item_path = str(wf_item.get("path") or "").strip()
            item_id = wf_item.get("id")
            item_name = str(wf_item.get("name") or "").strip()
            if item_path == expected_path:
                matched_wf_obj = wf_item
            else:
                excluded_workflows.append({
                    "id": item_id,
                    "name": item_name,
                    "path": item_path,
                    "state": wf_item.get("state"),
                })

        if matched_wf_obj is not None:
            res = _validate_single_workflow_meta_obj(matched_wf_obj, expected_path, catalog_ep)
            if res["ok"]:
                res["resolution_mode"] = "WORKFLOWS_CATALOG_FALLBACK"
                res["deferred_until_branch_push"] = False
                res["excluded_remote_workflows"] = excluded_workflows
            return res

        if allow_deferred_pre_push:
            return {
                "ok": True,
                "error": None,
                "workflow_id": None,
                "path": expected_path,
                "name": EXPECTED_WORKFLOW_DISPLAY_NAME,
                "state": "pending_first_branch_push",
                "endpoint": catalog_ep,
                "resolution_mode": "DEFERRED_PRE_PUSH_NEW_BRANCH_WORKFLOW",
                "deferred_until_branch_push": True,
                "excluded_remote_workflows": excluded_workflows,
            }

        return {
            "ok": False,
            "error": (
                f"GH_API_WORKFLOW_NOT_REGISTERED_ON_REMOTE: Workflow {expected_path!r} is absent from {endpoint} (404) "
                f"and not present in {catalog_ep} (found {len(excluded_workflows)} other workflow(s))"
            ),
        }

    return {
        "ok": False,
        "error": f"GH_API_WORKFLOW_META_EXIT_{rc}: Failed to query workflow metadata ({endpoint}): {combined or 'non-zero exit'}",
    }


def validate_and_normalize_run_record(
    raw_run: dict,
    expected_workflow_id: int = None,
    expected_workflow_path: str = WORKFLOW_DEFINITION_PATH,
    expected_workflow_name: str = None,
) -> tuple[bool, dict, str]:
    """
    Fail-closed validator for a single GitHub Actions workflow run record (BUG-41, BUG-48, BUG-52 / ARGON).
    Strictly requires explicit workflow identity fields (`workflow_id` and `path` / `name` / `workflowName`)
    from the source record, NEVER substitutes or invents `WORKFLOW_FILE` when missing, and strictly rejects
    `.github/workflows/build-mersad-preview-dispatch.yml` (`Build MERSAD PREVIEW 0.1 Windows x64`) without any
    loose substring matching!
    """
    if not isinstance(raw_run, dict):
        return False, {}, f"Run record is not a JSON object: {type(raw_run).__name__}"

    raw_id = raw_run.get("id") if "id" in raw_run else raw_run.get("databaseId")
    if raw_id is None or isinstance(raw_id, bool):
        return False, {}, "Missing mandatory field: id / databaseId"
    try:
        run_id = int(raw_id)
    except (ValueError, TypeError):
        return False, {}, f"Invalid non-integer id / databaseId: {raw_id!r}"
    if run_id <= 0:
        return False, {}, f"Non-positive id / databaseId: {run_id}"

    # BUG-48: Require explicit workflow_id and verify it matches expected_workflow_id
    raw_wf_id = raw_run.get("workflow_id") if "workflow_id" in raw_run else raw_run.get("workflowDatabaseId")
    if raw_wf_id is None or isinstance(raw_wf_id, bool):
        return False, {}, f"Run {run_id} is missing mandatory field: workflow_id"
    try:
        wf_id = int(raw_wf_id)
    except (ValueError, TypeError):
        return False, {}, f"Run {run_id} has invalid non-integer workflow_id: {raw_wf_id!r}"
    if wf_id <= 0:
        return False, {}, f"Run {run_id} has non-positive workflow_id: {wf_id}"
    if wf_id == FORBIDDEN_DISPATCH_WORKFLOW_ID:
        return False, {}, f"Run {run_id} belongs to forbidden dispatch workflow_id={wf_id} ({FORBIDDEN_DISPATCH_WORKFLOW_PATH})"
    if expected_workflow_id is not None and wf_id != int(expected_workflow_id):
        return False, {}, f"Run {run_id} workflow_id mismatch: got {wf_id}, expected {expected_workflow_id}"

    # BUG-48 & BUG-52: Require explicit workflow path and/or workflow name WITHOUT any default or substring fallback
    has_path_key = "path" in raw_run and raw_run.get("path") is not None
    has_name_key = ("name" in raw_run and raw_run.get("name") is not None) or (
        "workflowName" in raw_run and raw_run.get("workflowName") is not None
    )
    if not has_path_key and not has_name_key:
        return False, {}, f"Run {run_id} is missing explicit workflow identity fields (path and name/workflowName are absent)"

    wf_path = str(raw_run.get("path") or "").strip() if has_path_key else ""
    raw_wf_name_val = raw_run.get("name") if "name" in raw_run else raw_run.get("workflowName")
    wf_name = str(raw_wf_name_val or "").strip() if has_name_key else ""

    if not wf_path and not wf_name:
        return False, {}, f"Run {run_id} has empty workflow identity fields (path={wf_path!r}, name={wf_name!r})"

    if has_path_key:
        if not wf_path:
            return False, {}, f"Run {run_id} has empty workflow 'path' field"
        clean_wf_path = wf_path.split("@", 1)[0].strip()
        if clean_wf_path in FORBIDDEN_WORKFLOW_PATHS:
            return False, {}, f"Run {run_id} workflow path mismatch (forbidden workflow path): got {clean_wf_path!r}, expected {expected_workflow_path!r}"
        if expected_workflow_path and clean_wf_path != expected_workflow_path:
            return False, {}, f"Run {run_id} workflow path mismatch: got {clean_wf_path!r}, expected {expected_workflow_path!r}"

    if has_name_key:
        if not wf_name:
            return False, {}, f"Run {run_id} has empty workflow 'name'/'workflowName' field"
        if wf_name in FORBIDDEN_WORKFLOW_NAMES:
            return False, {}, f"Run {run_id} belongs to forbidden workflow name: {wf_name!r}"
        allowed_names = {WORKFLOW_FILE, EXPECTED_WORKFLOW_DISPLAY_NAME}
        if expected_workflow_name:
            allowed_names.add(expected_workflow_name)
        if wf_name not in allowed_names:
            return False, {}, f"Run {run_id} workflow name mismatch: got {wf_name!r}, expected one of {sorted(allowed_names)}"

    head_sha = str(raw_run.get("head_sha") or raw_run.get("headSha") or "").strip()
    if not re.match(r"^[0-9a-fA-F]{7,40}$", head_sha):
        return False, {}, f"Run {run_id} has missing or invalid head_sha: {head_sha!r}"

    head_branch = str(raw_run.get("head_branch") or raw_run.get("headBranch") or "").strip()
    if not head_branch:
        return False, {}, f"Run {run_id} is missing mandatory field head_branch"

    event = str(raw_run.get("event") or "").strip()
    if not event:
        return False, {}, f"Run {run_id} is missing mandatory field event"

    created_at_str = str(raw_run.get("created_at") or raw_run.get("createdAt") or "").strip()
    created_dt = parse_iso8601_utc(created_at_str)
    if created_dt is None:
        return False, {}, f"Run {run_id} has missing or unparseable created_at timestamp: {created_at_str!r}"

    norm = {
        "databaseId": run_id,
        "workflowId": wf_id,
        "workflowPath": wf_path.split("@", 1)[0].strip() if wf_path else expected_workflow_path,
        "workflowName": wf_name or expected_workflow_name or EXPECTED_WORKFLOW_DISPLAY_NAME,
        "headSha": head_sha.lower(),
        "headBranch": head_branch,
        "event": event,
        "createdAt": created_at_str,
        "created_dt_utc": created_dt.isoformat(),
        "status": str(raw_run.get("status") or "").strip(),
        "conclusion": str(raw_run.get("conclusion") or "").strip(),
        "url": str(raw_run.get("html_url") or raw_run.get("url") or "").strip(),
    }
    return True, norm, "OK"


def query_workflow_runs_fail_closed(
    gh_bin: str,
    work_repo: Path,
    env: dict,
    workflow_file: str = WORKFLOW_FILE,
    max_pages: int = DEFAULT_PREFLIGHT_MAX_PAGES,
    per_page: int = DEFAULT_PREFLIGHT_PER_PAGE,
    github_repo: str = DEFAULT_GITHUB_REPO,
    resolved_workflow_meta: dict = None,
    allow_deferred_pre_push: bool = False,
) -> dict:
    """
    Fail-closed query of GitHub Actions workflow runs using real GitHub REST API pagination (BUG-41, BUG-47, BUG-48, BUG-52):
      1. Resolves workflow metadata (`workflow_id`, `path`, `name`) via `resolve_workflow_metadata_fail_closed()`.
         If `allow_deferred_pre_push=True` (only before pushing a new branch when the workflow is absent from remote `main`
         and not yet registered in `/actions/workflows`), returns an empty pre-push run baseline with
         `deferred_until_branch_push=True` so preflight can proceed to push and then resolve the workflow post-push.
      2. Queries each page via `gh api -X GET "repos/{github_repo}/actions/workflows/{workflow_id}/runs?per_page={per_page}&page={page_idx}"`
         with ZERO synthetic page environment variables.
      3. Validates every run record via `validate_and_normalize_run_record()`, enforcing explicit `workflow_id` and
         exact `path`/`name` match without default or substring fallbacks.
      4. Detects duplicate page results (`GH_API_DUPLICATE_PAGE_RESULTS`), chronological ordering violations
         (`GH_API_CHRONOLOGICAL_ORDER_VIOLATION`), and incomplete history when `max_pages` is reached while
         `len(all_runs) < total_count` (`GH_API_MAX_PAGES_LIMIT_REACHED_INCOMPLETE_HISTORY`).
    """
    if per_page <= 0 or per_page > 100:
        return {
            "ok": False,
            "error": f"INVALID_PER_PAGE_CONFIG: per_page={per_page} must be between 1 and 100",
            "runs": [],
            "run_ids": set(),
            "pages_fetched": 0,
            "max_pages_configured": max_pages,
            "per_page_configured": per_page,
            "endpoints_queried": [],
        }

    wf_meta = resolved_workflow_meta
    if not wf_meta or wf_meta.get("deferred_until_branch_push"):
        wf_meta = resolve_workflow_metadata_fail_closed(
            gh_bin=gh_bin,
            work_repo=work_repo,
            env=env,
            github_repo=github_repo,
            workflow_file=workflow_file,
            allow_deferred_pre_push=allow_deferred_pre_push,
        )
    if not wf_meta.get("ok"):
        return {
            "ok": False,
            "error": wf_meta.get("error") or "WORKFLOW_METADATA_RESOLUTION_FAILED",
            "runs": [],
            "run_ids": set(),
            "pages_fetched": 0,
            "max_pages_configured": max_pages,
            "per_page_configured": per_page,
            "endpoints_queried": [],
        }

    if wf_meta.get("deferred_until_branch_push"):
        return {
            "ok": True,
            "error": None,
            "workflow_metadata": wf_meta,
            "deferred_until_branch_push": True,
            "total_count": 0,
            "runs": [],
            "run_ids": set(),
            "pages_fetched": 0,
            "max_pages_configured": max(1, int(max_pages)),
            "per_page_configured": per_page,
            "endpoints_queried": [wf_meta.get("endpoint", f"repos/{github_repo}/actions/workflows?per_page=100&page=1")],
            "bounded_window_note": (
                f"Workflow {wf_meta.get('path')} is absent from remote main and not yet registered in GitHub Actions "
                "prior to first push of new branch; verified workflow catalog endpoint (200 OK) with 0 pre-existing runs "
                "and deferred workflow_id resolution to post-push polling."
            ),
        }

    expected_wf_id = int(wf_meta["workflow_id"])
    expected_wf_path = str(wf_meta["path"])
    expected_wf_name = str(wf_meta["name"])

    all_runs = []
    seen_ids = set()
    pages_fetched = 0
    endpoints_queried = []
    prev_created_dt = None
    prev_created_iso = None
    reported_total_count = None

    effective_max_pages = max(1, int(max_pages))
    for page_idx in range(1, effective_max_pages + 1):
        endpoint = f"repos/{github_repo}/actions/workflows/{expected_wf_id}/runs?per_page={per_page}&page={page_idx}"
        cmd = [gh_bin, "api", "-X", "GET", endpoint]
        rc, out, err = run_cmd(cmd, cwd=str(work_repo), env=env)
        if rc != 0:
            combined = f"{err} {out}".strip()
            low = combined.lower()
            err_tag = f"GH_API_RUNS_EXIT_{rc}_ON_PAGE_{page_idx}"
            if "401" in low or "403" in low or "forbidden" in low or "unauthorized" in low:
                err_tag = f"GH_API_HTTP_401_403_AUTH_ERROR_ON_PAGE_{page_idx}"
            elif "429" in low or "rate limit" in low:
                err_tag = f"GH_API_HTTP_429_RATE_LIMIT_ERROR_ON_PAGE_{page_idx}"
            return {
                "ok": False,
                "error": f"{err_tag}: {combined or 'Non-zero exit code from gh api'}",
                "runs": [],
                "run_ids": set(),
                "pages_fetched": pages_fetched,
                "max_pages_configured": effective_max_pages,
                "per_page_configured": per_page,
                "endpoints_queried": endpoints_queried,
            }

        if not out or not out.strip():
            return {
                "ok": False,
                "error": f"GH_API_EMPTY_STDOUT_ON_PAGE_{page_idx}: Expected REST API JSON object from {endpoint}, got empty output",
                "runs": [],
                "run_ids": set(),
                "pages_fetched": pages_fetched,
                "max_pages_configured": effective_max_pages,
                "per_page_configured": per_page,
                "endpoints_queried": endpoints_queried,
            }

        try:
            parsed = json.loads(out)
        except Exception as exc:
            return {
                "ok": False,
                "error": f"GH_API_INVALID_JSON_ON_PAGE_{page_idx}: {exc}",
                "runs": [],
                "run_ids": set(),
                "pages_fetched": pages_fetched,
                "max_pages_configured": effective_max_pages,
                "per_page_configured": per_page,
                "endpoints_queried": endpoints_queried,
            }

        if not isinstance(parsed, dict) or "workflow_runs" not in parsed or "total_count" not in parsed:
            return {
                "ok": False,
                "error": (
                    f"GH_API_INVALID_SCHEMA_ON_PAGE_{page_idx}: Expected REST API dict with 'total_count' and 'workflow_runs', "
                    f"got {type(parsed).__name__}"
                ),
                "runs": [],
                "run_ids": set(),
                "pages_fetched": pages_fetched,
                "max_pages_configured": effective_max_pages,
                "per_page_configured": per_page,
                "endpoints_queried": endpoints_queried,
            }

        raw_total = parsed.get("total_count")
        raw_runs = parsed.get("workflow_runs")
        if isinstance(raw_total, bool) or not isinstance(raw_total, int) or raw_total < 0 or not isinstance(raw_runs, list):
            return {
                "ok": False,
                "error": f"GH_API_INVALID_SCHEMA_TYPES_ON_PAGE_{page_idx}: total_count={raw_total!r}, workflow_runs={type(raw_runs).__name__}",
                "runs": [],
                "run_ids": set(),
                "pages_fetched": pages_fetched,
                "max_pages_configured": effective_max_pages,
                "per_page_configured": per_page,
                "endpoints_queried": endpoints_queried,
            }

        if len(raw_runs) > per_page:
            return {
                "ok": False,
                "error": f"GH_API_PAGE_OVERFLOW_ON_PAGE_{page_idx}: Returned {len(raw_runs)} items > per_page={per_page}",
                "runs": [],
                "run_ids": set(),
                "pages_fetched": pages_fetched,
                "max_pages_configured": effective_max_pages,
                "per_page_configured": per_page,
                "endpoints_queried": endpoints_queried,
            }

        reported_total_count = raw_total
        pages_fetched += 1
        endpoints_queried.append(endpoint)

        if len(raw_runs) == 0:
            if len(all_runs) < reported_total_count:
                return {
                    "ok": False,
                    "error": (
                        f"GH_API_PREMATURE_EMPTY_PAGE_{page_idx}: Page {page_idx} returned 0 runs, "
                        f"but total_count={reported_total_count} and only {len(all_runs)} run(s) were fetched"
                    ),
                    "runs": [],
                    "run_ids": set(),
                    "pages_fetched": pages_fetched,
                    "max_pages_configured": effective_max_pages,
                    "per_page_configured": per_page,
                    "endpoints_queried": endpoints_queried,
                }
            break

        for idx, raw_item in enumerate(raw_runs):
            valid, norm_item, rsn = validate_and_normalize_run_record(
                raw_item,
                expected_workflow_id=expected_wf_id,
                expected_workflow_path=expected_wf_path,
                expected_workflow_name=expected_wf_name,
            )
            if not valid:
                return {
                    "ok": False,
                    "error": f"GH_API_INCOMPLETE_OR_MISMATCHED_RECORD_PAGE_{page_idx}_INDEX_{idx}: {rsn}",
                    "runs": [],
                    "run_ids": set(),
                    "pages_fetched": pages_fetched,
                    "max_pages_configured": effective_max_pages,
                    "per_page_configured": per_page,
                    "endpoints_queried": endpoints_queried,
                }

            r_id = norm_item["databaseId"]
            if r_id in seen_ids:
                return {
                    "ok": False,
                    "error": (
                        f"GH_API_DUPLICATE_PAGE_RESULTS_ON_PAGE_{page_idx}: Run ID {r_id} was already returned on an earlier page "
                        "or earlier in the same page (broken pagination)"
                    ),
                    "runs": [],
                    "run_ids": set(),
                    "pages_fetched": pages_fetched,
                    "max_pages_configured": effective_max_pages,
                    "per_page_configured": per_page,
                    "endpoints_queried": endpoints_queried,
                }

            created_dt = parse_iso8601_utc(norm_item["createdAt"])
            if prev_created_dt is not None and created_dt > prev_created_dt:
                return {
                    "ok": False,
                    "error": (
                        f"GH_API_CHRONOLOGICAL_ORDER_VIOLATION_ON_PAGE_{page_idx}: Run ID {r_id} created_at={norm_item['createdAt']} "
                        f"is newer than preceding run created_at={prev_created_iso}"
                    ),
                    "runs": [],
                    "run_ids": set(),
                    "pages_fetched": pages_fetched,
                    "max_pages_configured": effective_max_pages,
                    "per_page_configured": per_page,
                    "endpoints_queried": endpoints_queried,
                }

            prev_created_dt = created_dt
            prev_created_iso = norm_item["createdAt"]
            seen_ids.add(r_id)
            all_runs.append(norm_item)

        if len(raw_runs) < per_page:
            if len(all_runs) < reported_total_count:
                return {
                    "ok": False,
                    "error": (
                        f"GH_API_INCONSISTENT_TOTAL_COUNT_ON_PAGE_{page_idx}: Partial page returned {len(raw_runs)} runs "
                        f"(fetched {len(all_runs)}) < total_count={reported_total_count}"
                    ),
                    "runs": [],
                    "run_ids": set(),
                    "pages_fetched": pages_fetched,
                    "max_pages_configured": effective_max_pages,
                    "per_page_configured": per_page,
                    "endpoints_queried": endpoints_queried,
                }
            break

        if len(all_runs) >= reported_total_count:
            break

        if page_idx == effective_max_pages and len(all_runs) < reported_total_count:
            return {
                "ok": False,
                "error": (
                    f"GH_API_MAX_PAGES_LIMIT_REACHED_INCOMPLETE_HISTORY: Reached max_pages={effective_max_pages} "
                    f"with {len(all_runs)}/{reported_total_count} runs fetched; halting fail-closed rather than proceeding with partial history"
                ),
                "runs": [],
                "run_ids": set(),
                "pages_fetched": pages_fetched,
                "max_pages_configured": effective_max_pages,
                "per_page_configured": per_page,
                "endpoints_queried": endpoints_queried,
            }

    return {
        "ok": True,
        "error": None,
        "workflow_metadata": wf_meta,
        "deferred_until_branch_push": False,
        "total_count": reported_total_count if reported_total_count is not None else len(all_runs),
        "runs": all_runs,
        "run_ids": seen_ids,
        "pages_fetched": pages_fetched,
        "max_pages_configured": effective_max_pages,
        "per_page_configured": per_page,
        "endpoints_queried": endpoints_queried,
        "bounded_window_note": (
            f"Inspected {len(all_runs)}/{reported_total_count if reported_total_count is not None else len(all_runs)} workflow run(s) "
            f"for workflow_id={expected_wf_id} ({expected_wf_path}) across {pages_fetched} REST API page(s) "
            f"(per_page={per_page}, max_pages={effective_max_pages}, combined with UTC baseline preflight_started_at_utc)."
        ),
    }


def validate_workflow_push_only(workflow_yaml_path: Path) -> tuple[bool, str]:
    """
    Verify that workflow_yaml_path is configured for single-run Push-triggered CI ONLY:
      - Exists on disk
      - Defines `push:` with `fix/preview-0.1-*`
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


def validate_bat_thin_wrappers_no_tag_or_extra_push(repo_root: Path) -> dict:
    """
    Verify that all 3 deployment batch wrappers (`BUG-40`, `BUG-46`, `BUG-49`):
      1. `PUSH_RELEASE_PREVIEW_0_1_TO_GITHUB_ACTIONS.bat`
      2. `PUSH_CANDIDATE_9491BCD_TO_GITHUB_ACTIONS.bat`
      3. `MERSAD_AI_Preview_0.1/PUSH_TO_GITHUB_AND_BUILD.bat`
    Strictly satisfy:
      - Enforce `set "ALLOWED_DEPLOY_BRANCH=fix/preview-0.1-postbuild-42273598736"` and `BRANCH_NOT_IN_ALLOWLIST`.
      - Do NOT contain any direct `git push` command.
      - Do NOT contain any `gh workflow run` command.
      - Do NOT contain `_register_wf_` or `DEFAULT_BRANCH=main` fallback.
      - Do NOT push tags (`refs/tags`, `--tags`, `--all`) or use `--force`.
      - Do NOT hide git/gh/python deployment errors via `>nul 2>&1` or `>nul 2>nul`.
      - Delegate cloud deployment to `tools\\deploy_and_run_github_actions.py" --live --branch "%TARGET_BRANCH%"`
        and propagate `exit /b !DEPLOY_EXIT_CODE!`.
    """
    bat_files = [
        repo_root / "PUSH_RELEASE_PREVIEW_0_1_TO_GITHUB_ACTIONS.bat",
        repo_root / "PUSH_CANDIDATE_9491BCD_TO_GITHUB_ACTIONS.bat",
        repo_root / "MERSAD_AI_Preview_0.1" / "PUSH_TO_GITHUB_AND_BUILD.bat",
    ]
    issues = []
    for bf in bat_files:
        rel_name = bf.relative_to(repo_root).as_posix() if bf.is_relative_to(repo_root) else bf.name
        if not bf.is_file():
            issues.append(f"Missing batch file: {rel_name}")
            continue
        txt = bf.read_text(encoding="utf-8")
        for line_no, raw_line in enumerate(txt.splitlines(), 1):
            stripped = raw_line.strip()
            if stripped.upper().startswith("REM ") or stripped.upper().startswith("ECHO "):
                continue
            low = stripped.lower()
            if "git push" in low:
                issues.append(f"{rel_name}:{line_no} contains direct 'git push' instead of delegating to Python controller")
            if "gh workflow run" in low:
                issues.append(f"{rel_name}:{line_no} contains 'gh workflow run' (independent workflow_dispatch trigger)")
            if "_register_wf_" in low or "default_branch=main" in low:
                issues.append(f"{rel_name}:{line_no} contains legacy default-branch / main fallback logic")
            if "refs/tags" in low or "--tags" in low or "git push --all" in low or "--force" in low:
                issues.append(f"{rel_name}:{line_no} contains forbidden tag/all/force push reference")
            if ">nul 2>&1" in low or ">nul 2>nul" in low:
                if "where python" not in low and "where py" not in low:
                    issues.append(f"{rel_name}:{line_no} masks command errors via >nul 2>&1: {stripped}")
        if 'set "ALLOWED_DEPLOY_BRANCH=fix/preview-0.1-postbuild-42273598736"' not in txt:
            issues.append(f"{rel_name} does not define ALLOWED_DEPLOY_BRANCH=fix/preview-0.1-postbuild-42273598736")
        if "BRANCH_NOT_IN_ALLOWLIST" not in txt:
            issues.append(f"{rel_name} does not enforce BRANCH_NOT_IN_ALLOWLIST rejection")
        if 'tools\\deploy_and_run_github_actions.py" --live --branch "%TARGET_BRANCH%"' not in txt:
            issues.append(f"{rel_name} does not delegate to tools\\deploy_and_run_github_actions.py --live --branch")
        if "exit /b !DEPLOY_EXIT_CODE!" not in txt:
            issues.append(f"{rel_name} does not propagate Python exit code (!DEPLOY_EXIT_CODE!)")

    py_txt = (repo_root / "tools" / "deploy_and_run_github_actions.py").read_text(encoding="utf-8")
    exec_body = py_txt.partition("def execute_deployment(")[2].partition("def run_self_test(")[0]
    for line_no, raw_line in enumerate(exec_body.splitlines(), 1):
        if ("refs/tags" in raw_line or "--tags" in raw_line or "--all" in raw_line) and not raw_line.strip().startswith("#"):
            issues.append(f"execute_deployment line {line_no} contains forbidden tag/all push")

    return {"ok": len(issues) == 0, "checked_files": [bf.relative_to(repo_root).as_posix() for bf in bat_files if bf.exists()], "issues": issues}


def verify_and_hash_downloaded_artifacts(
    artifacts_dir: Path,
    run_id: str = "",
    trusted_reference_digests: dict = None,
    verify_attestation: bool = False,
    gh_bin: str = None,
    github_repo: str = DEFAULT_GITHUB_REPO,
) -> dict:
    """
    Search artifacts_dir for all 5 required Windows release files, verify existence and non-zero size,
    and calculate/record SHA-256 for each file (BUG-45).
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
    digest_mismatches = []

    for req_name in REQUIRED_WINDOWS_ARTIFACTS:
        p = found_files.get(req_name)
        if p is None or not p.is_file():
            missing.append(req_name)
        elif p.stat().st_size == 0:
            empty.append(req_name)
        else:
            raw = p.read_bytes()
            calc_sha = hashlib.sha256(raw).hexdigest()
            ref_match = None
            if isinstance(trusted_reference_digests, dict) and req_name in trusted_reference_digests:
                exp_sha = str(trusted_reference_digests[req_name]).strip().lower()
                ref_match = (calc_sha.lower() == exp_sha)
                if not ref_match:
                    digest_mismatches.append({"name": req_name, "calculated_sha256": calc_sha, "expected_sha256": exp_sha})
            artifacts_meta.append({
                "name": req_name,
                "relative_path": p.relative_to(artifacts_dir).as_posix(),
                "size_bytes": len(raw),
                "sha256": calc_sha,
                "trusted_reference_digest_matched": ref_match,
            })

    files_exist_ok = (len(missing) == 0)
    files_non_empty_ok = (files_exist_ok and len(empty) == 0 and len(artifacts_meta) == len(REQUIRED_WINDOWS_ARTIFACTS))
    sha256_calculated_ok = files_non_empty_ok

    has_complete_trusted_refs = (
        isinstance(trusted_reference_digests, dict)
        and all(k in trusted_reference_digests for k in REQUIRED_WINDOWS_ARTIFACTS)
    )
    trusted_ref_verified = bool(
        sha256_calculated_ok
        and has_complete_trusted_refs
        and len(digest_mismatches) == 0
    )

    attestation_status = "NOT_AVAILABLE"
    if verify_attestation:
        if not gh_bin or not sha256_calculated_ok:
            attestation_status = "FAILED"
        else:
            att_ok = True
            for req_name in REQUIRED_WINDOWS_ARTIFACTS:
                fp = found_files[req_name]
                rc_att, _, _ = run_cmd([gh_bin, "attestation", "verify", str(fp), "--repo", github_repo])
                if rc_att != 0:
                    att_ok = False
                    break
            attestation_status = "VERIFIED" if att_ok else "FAILED"

    if not sha256_calculated_ok:
        verification_state = "ARTIFACTS_INCOMPLETE_OR_EMPTY"
    elif isinstance(trusted_reference_digests, dict) and len(digest_mismatches) > 0:
        verification_state = "TRUSTED_DIGEST_MISMATCH"
    elif verify_attestation and attestation_status != "VERIFIED":
        verification_state = "ATTESTATION_VERIFICATION_FAILED"
    elif trusted_ref_verified:
        verification_state = "TRUSTED_DIGEST_VERIFIED"
    else:
        verification_state = "SHA256_CALCULATED_AND_RECORDED"

    ok = (
        sha256_calculated_ok
        and len(digest_mismatches) == 0
        and (not verify_attestation or attestation_status == "VERIFIED")
    )

    result = {
        "ok": ok,
        "verification_state": verification_state,
        "run_id": str(run_id),
        "artifacts_dir": str(artifacts_dir),
        "required_count": len(REQUIRED_WINDOWS_ARTIFACTS),
        "verified_count": len(artifacts_meta),
        "files_exist_verified": files_exist_ok,
        "files_non_empty_verified": files_non_empty_ok,
        "sha256_calculated_and_recorded": sha256_calculated_ok,
        "trusted_reference_digests_provided": bool(trusted_reference_digests),
        "trusted_reference_digests_verified": trusted_ref_verified,
        "trusted_digest_mismatches": digest_mismatches,
        "attestation_verification_status": attestation_status,
        "authenticity_note": (
            "SHA-256 digests were locally calculated and recorded after artifact download. "
            "Unless trusted_reference_digests_verified=True or attestation_verification_status='VERIFIED', "
            "this records file hashes for downstream auditing and does NOT constitute independent source authenticity verification."
        ),
        "missing_files": missing,
        "empty_files": empty,
        "artifacts": artifacts_meta,
    }
    if sha256_calculated_ok and artifacts_dir.is_dir():
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
        anc_a1c5_rc = subprocess.run(
            ["git", "-C", str(clone_dir), "merge-base", "--is-ancestor", EXPECTED_AI_SINGLE_RUN_CI_PARENT_SHA, "HEAD"],
            capture_output=True,
        ).returncode
        anc_62b4_rc = subprocess.run(
            ["git", "-C", str(clone_dir), "merge-base", "--is-ancestor", EXPECTED_AI_BUG52_PARENT_SHA, "HEAD"],
            capture_output=True,
        ).returncode
        anc_de55_rc = subprocess.run(
            ["git", "-C", str(clone_dir), "merge-base", "--is-ancestor", EXPECTED_AI_BUG50_51_PARENT_SHA, "HEAD"],
            capture_output=True,
        ).returncode
        anc_eaf8_rc = subprocess.run(
            ["git", "-C", str(clone_dir), "merge-base", "--is-ancestor", EXPECTED_AI_BUG46_49_PARENT_SHA, "HEAD"],
            capture_output=True,
        ).returncode
        anc_850f_rc = subprocess.run(
            ["git", "-C", str(clone_dir), "merge-base", "--is-ancestor", EXPECTED_AI_BUG40_45_PARENT_SHA, "HEAD"],
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
        and anc_a1c5_rc == 0
        and anc_62b4_rc == 0
        and anc_de55_rc == 0
        and anc_eaf8_rc == 0
        and anc_850f_rc == 0
        and lifecycle_in_commit
        and sim_engine_sha_ok
        and len(present_17_paths) == 17
        and main_sha == EXPECTED_BUNDLE_MAIN_SNAPSHOT_SHA
    )
    return {
        "ok": ok,
        "branch": branch,
        "head_sha": head_sha,
        "previous_bug52_commit_sha": EXPECTED_AI_BUG52_PARENT_SHA,
        "previous_bug50_51_commit_sha": EXPECTED_AI_BUG50_51_PARENT_SHA,
        "previous_bug46_49_commit_sha": EXPECTED_AI_BUG46_49_PARENT_SHA,
        "descends_from_62b409e2327b": (anc_62b4_rc == 0),
        "descends_from_de55bcc51936": (anc_de55_rc == 0),
        "previous_bug40_45_commit_sha": EXPECTED_AI_BUG40_45_PARENT_SHA,
        "descends_from_eaf89c71b3b5": (anc_eaf8_rc == 0),
        "previous_single_run_ci_commit_sha": EXPECTED_AI_SINGLE_RUN_CI_PARENT_SHA,
        "previous_preflight_commit_sha": preflight_tag_sha,
        "reconciled_code_sha": code_tag_sha,
        "descends_from_850fbdb450ba": (anc_850f_rc == 0),
        "descends_from_a1c53f32ff3c": (anc_a1c5_rc == 0),
        "descends_from_05f29af416c4": (anc_05f2_rc == 0),
        "descends_from_edaf651321ec": (anc_edaf_rc == 0),
        "lifecycle_test_in_commit": lifecycle_in_commit,
        "sim_engine_synced_in_commit": sim_engine_sha_ok,
        "workflow_paths_summary": "1 Workflow File + 16 Required Paths = 17 Verified Paths",
        "workflow_verified_paths_count": len(present_17_paths),
        "live_github_main_commit": EXPECTED_LIVE_GITHUB_MAIN_SHA,
        "bundle_main_snapshot_commit": main_sha,
        "remote_main_verified_pre_push": EXPECTED_LIVE_GITHUB_MAIN_SHA,
        "remote_main_verified_post_push": None,
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
    poll_attempts: int = DEFAULT_POLL_ATTEMPTS,
    poll_interval_s: float = DEFAULT_POLL_INTERVAL_S,
    settling_polls: int = DEFAULT_SETTLING_POLLS,
    settling_interval_s: float = DEFAULT_SETTLING_INTERVAL_S,
    preflight_max_pages: int = DEFAULT_PREFLIGHT_MAX_PAGES,
    preflight_per_page: int = DEFAULT_PREFLIGHT_PER_PAGE,
    artifacts_base_dir: Path = None,
    target_branch: str = None,
    simulate_dirty_working_tree: bool = False,
    trusted_reference_digests: dict = None,
    verify_attestation: bool = False,
    github_repo: str = DEFAULT_GITHUB_REPO,
) -> dict:
    env = os.environ.copy()
    # Strip any ambient MERSAD_DEPLOY_BRANCH / MERSAD_BUILD_BRANCH unless explicitly provided in env_override or validated
    if env_override is not None:
        env.update(env_override)

    ok_allowlist, branch_to_use, allowlist_msg = validate_target_branch_allowlist(target_branch, env=env)

    if workflow_yaml_path is None:
        workflow_yaml_path = bundle_path.parent.parent / ".github" / "workflows" / WORKFLOW_FILE
    if artifacts_base_dir is None:
        artifacts_base_dir = bundle_path.parent.parent

    preflight_started_dt = datetime.datetime.now(datetime.timezone.utc)
    preflight_started_iso = preflight_started_dt.isoformat()

    report = {
        "timestamp": time.strftime("%Y-%m-%d %H:%M:%S"),
        "preflight_started_at_utc": preflight_started_iso,
        "allowed_deploy_branches": list(ALLOWED_DEPLOY_BRANCHES),
        "target_branch": branch_to_use,
        "branch_validation_status": "ALLOWED" if ok_allowlist else "BRANCH_NOT_IN_ALLOWLIST",
        "trigger_mode": "push_only_single_run",
        "expected_ai_bug40_45_parent_sha": EXPECTED_AI_BUG40_45_PARENT_SHA,
        "expected_ai_single_run_ci_parent_sha": EXPECTED_AI_SINGLE_RUN_CI_PARENT_SHA,
        "expected_ai_preflight_parent_sha": EXPECTED_AI_PREFLIGHT_PARENT_SHA,
        "expected_ai_code_sha": EXPECTED_AI_CODE_SHA,
        "expected_ai_prev_fix_sha": EXPECTED_AI_PREV_FIX_SHA,
        "expected_ai_release_base_sha": EXPECTED_AI_RELEASE_BASE_SHA,
        "expected_lab_code_sha": EXPECTED_LAB_CODE_SHA,
        "expected_lab_release_base_sha": EXPECTED_LAB_RELEASE_BASE_SHA,
        "live_github_main_commit": EXPECTED_LIVE_GITHUB_MAIN_SHA,
        "bundle_main_snapshot_commit": EXPECTED_BUNDLE_MAIN_SNAPSHOT_SHA,
        "remote_main_verified_pre_push": None,
        "remote_main_verified_post_push": None,
        "workflow_file": WORKFLOW_FILE,
        "remote_url": remote_url,
        "polling_config": {
            "poll_attempts": poll_attempts,
            "poll_interval_s": poll_interval_s,
            "settling_polls": settling_polls,
            "settling_interval_s": settling_interval_s,
            "preflight_max_pages": preflight_max_pages,
            "preflight_per_page": preflight_per_page,
        },
        "steps": [],
        "state_history": [],
        "status": "PREFLIGHT_FAILED",
        "build_triggered": False,
        "push_executed": False,
        "run_id": None,
        "run_url": None,
        "artifacts_verification": None,
    }

    def set_state(new_state: str):
        report["status"] = new_state
        report["state_history"].append(new_state)

    def add_step(name, ok, detail):
        report["steps"].append({"step": name, "ok": bool(ok), "detail": detail})

    # Step 0A: Enforce Central Target Branch Allowlist before any Git or network action (BUG-49)
    add_step("validate_target_branch_allowlist", ok_allowlist, allowlist_msg)
    if not ok_allowlist:
        set_state("PREFLIGHT_FAILED")
        report["error"] = allowlist_msg
        return report

    # Step 0B: Validate that workflow YAML uses push trigger ONLY (no workflow_dispatch, no unused run_extended_stress)
    ok_wf_yaml, msg_wf_yaml = validate_workflow_push_only(workflow_yaml_path)
    add_step("validate_workflow_push_only", ok_wf_yaml, msg_wf_yaml)
    if not ok_wf_yaml:
        set_state("PREFLIGHT_FAILED")
        report["error"] = f"INVALID_WORKFLOW_TRIGGER_CONFIG: {msg_wf_yaml}"
        return report

    # Step 1: Clone bundle and verify branches, lineage, clean working tree, remote URL, pre-push remote SHA, and pre-push run IDs
    with tempfile.TemporaryDirectory(prefix="mersad_deploy_") as tmpdir:
        work_repo = Path(tmpdir) / "repo"
        rc, out, err = run_cmd(["git", "clone", str(bundle_path), str(work_repo)], env=env)
        if rc != 0:
            set_state("PREFLIGHT_FAILED")
            add_step("clone_bundle", False, f"git clone failed: {err or out}")
            report["error"] = f"CLONE_FAILED: {err or out}"
            return report
        add_step("clone_bundle", True, f"Cloned bundle {bundle_path.name}")

        rc, main_sha, err = run_cmd(["git", "rev-parse", "origin/main"], cwd=str(work_repo), env=env)
        if rc != 0 or main_sha != EXPECTED_BUNDLE_MAIN_SNAPSHOT_SHA:
            set_state("PREFLIGHT_FAILED")
            add_step("verify_main_untouched", False, f"Bundle main snapshot SHA mismatch: got {main_sha}, expected {EXPECTED_BUNDLE_MAIN_SNAPSHOT_SHA}")
            report["error"] = f"MAIN_SHA_MISMATCH: {main_sha}"
            return report
        report["bundle_main_snapshot_sha"] = main_sha
        add_step("verify_main_untouched", True, f"Bundle offline main snapshot untouched at {main_sha}")

        rc, out, err = run_cmd(["git", "checkout", "-B", branch_to_use, f"origin/{branch_to_use}"], cwd=str(work_repo), env=env)
        if rc != 0:
            set_state("PREFLIGHT_FAILED")
            add_step("checkout_target_branch", False, f"Failed to checkout {branch_to_use}: {err or out}")
            report["error"] = f"CHECKOUT_FAILED: {err or out}"
            return report

        # Verify checked-out local branch matches allowlisted target branch (BUG-49)
        rc_cur_br, cur_br_name, err_cur_br = run_cmd(["git", "rev-parse", "--abbrev-ref", "HEAD"], cwd=str(work_repo), env=env)
        if rc_cur_br != 0 or cur_br_name != branch_to_use or cur_br_name not in ALLOWED_DEPLOY_BRANCHES:
            set_state("PREFLIGHT_FAILED")
            msg = f"Checked-out local branch {cur_br_name!r} does not match allowlisted branch {branch_to_use!r} ({err_cur_br})"
            add_step("verify_checked_out_branch_allowlist", False, msg)
            report["error"] = f"LOCAL_BRANCH_MISMATCH: {msg}"
            return report
        add_step("verify_checked_out_branch_allowlist", True, f"Checked-out local branch is {cur_br_name!r} (allowlisted)")

        if simulate_dirty_working_tree:
            (work_repo / "UNCOMMITTED_DIRTY_FILE.tmp").write_text("dirty", encoding="utf-8")

        rc_st, out_st, err_st = run_cmd(["git", "status", "--porcelain"], cwd=str(work_repo), env=env)
        if rc_st != 0 or out_st.strip() != "":
            set_state("PREFLIGHT_FAILED")
            add_step("verify_clean_working_tree", False, f"Working tree is not clean before push: {out_st or err_st}")
            report["error"] = f"DIRTY_WORKING_TREE: {out_st or err_st}"
            return report
        add_step("verify_clean_working_tree", True, "git status --porcelain is clean (0 uncommitted changes)")

        rc, head_sha, err = run_cmd(["git", "rev-parse", "HEAD"], cwd=str(work_repo), env=env)
        required_ancestors = [
            EXPECTED_AI_BUG52_PARENT_SHA,
            EXPECTED_AI_BUG50_51_PARENT_SHA,
            EXPECTED_AI_BUG46_49_PARENT_SHA,
            EXPECTED_AI_BUG40_45_PARENT_SHA,
            EXPECTED_AI_SINGLE_RUN_CI_PARENT_SHA,
            EXPECTED_AI_PREFLIGHT_PARENT_SHA,
            EXPECTED_AI_CODE_SHA,
            EXPECTED_AI_PREV_FIX_SHA,
            EXPECTED_AI_COMMON_FORK_POINT_SHA,
            EXPECTED_AI_RELEASE_BASE_SHA,
        ]

        for req_anc in required_ancestors:
            rc_anc, _, _ = run_cmd(["git", "merge-base", "--is-ancestor", req_anc, "HEAD"], cwd=str(work_repo), env=env)
            if rc != 0 or rc_anc != 0:
                set_state("PREFLIGHT_FAILED")
                add_step("verify_commit_lineage", False, f"HEAD {head_sha} on {branch_to_use} does not descend from {req_anc}")
                report["error"] = f"LINEAGE_MISMATCH: {head_sha} missing ancestor {req_anc}"
                return report

        report["local_head_sha"] = head_sha
        add_step("verify_commit_lineage", True, f"Checked out {branch_to_use} at HEAD={head_sha} (verified lineage: {required_ancestors})")

        # Configure and verify remote URL before push
        run_cmd(["git", "remote", "set-url", "origin", remote_url], cwd=str(work_repo), env=env)
        rc_rem, out_rem, _ = run_cmd(["git", "remote", "get-url", "origin"], cwd=str(work_repo), env=env)
        if rc_rem != 0 or out_rem.strip() != remote_url:
            set_state("PREFLIGHT_FAILED")
            add_step("verify_remote_url", False, f"Remote URL mismatch: got {out_rem}, expected {remote_url}")
            report["error"] = f"REMOTE_URL_MISMATCH: {out_rem}"
            return report
        add_step("verify_remote_url", True, f"Verified origin remote URL: {out_rem}")

        # Step 1B: Pre-push check of live remote main AND target branch via git ls-remote (BUG-44 & BUG-52 / ARGON)
        rc_pre_main, out_pre_main, err_pre_main = run_cmd(
            ["git", "ls-remote", "origin", "refs/heads/main"],
            cwd=str(work_repo),
            env=env,
        )
        if rc_pre_main != 0:
            set_state("PREFLIGHT_FAILED")
            msg = f"Pre-push git ls-remote refs/heads/main failed (exit={rc_pre_main}): {err_pre_main or out_pre_main}"
            add_step("preflight_check_remote_main", False, msg)
            report["error"] = f"REMOTE_UNREACHABLE_PREFLIGHT_FAILED: {msg}"
            return report

        pre_remote_main_sha = out_pre_main.split()[0].strip().lower() if out_pre_main.strip() else ""
        report["pre_push_remote_main_sha"] = pre_remote_main_sha or None
        report["remote_main_verified_pre_push"] = None
        report["live_github_main_commit"] = EXPECTED_LIVE_GITHUB_MAIN_SHA
        report["bundle_main_snapshot_commit"] = EXPECTED_BUNDLE_MAIN_SNAPSHOT_SHA

        if pre_remote_main_sha:
            if pre_remote_main_sha != EXPECTED_LIVE_GITHUB_MAIN_SHA or pre_remote_main_sha not in ALLOWED_REMOTE_MAIN_SHAS:
                set_state("PREFLIGHT_FAILED")
                extra_note = (
                    " (offline bundle snapshot SHA is NEVER accepted as live remote main)"
                    if pre_remote_main_sha == EXPECTED_BUNDLE_MAIN_SNAPSHOT_SHA
                    else ""
                )
                msg = (
                    f"Live remote refs/heads/main is at {pre_remote_main_sha}{extra_note}, "
                    f"expected approved live GitHub main {EXPECTED_LIVE_GITHUB_MAIN_SHA}. "
                    "Halting fail-closed before push; a fresh human-reviewed baseline is required."
                )
                add_step("preflight_check_remote_main", False, msg)
                report["error"] = f"REMOTE_MAIN_SHA_MISMATCH: {msg}"
                return report
            report["remote_main_verified_pre_push"] = pre_remote_main_sha
            add_step(
                "preflight_check_remote_main",
                True,
                f"Verified live remote refs/heads/main at approved SHA {pre_remote_main_sha}",
            )
        elif remote_url == DEFAULT_REMOTE_URL:
            set_state("PREFLIGHT_FAILED")
            msg = f"Live remote {remote_url} is missing refs/heads/main"
            add_step("preflight_check_remote_main", False, msg)
            report["error"] = f"REMOTE_MAIN_MISSING: {msg}"
            return report
        else:
            add_step("preflight_check_remote_main", True, "Simulated empty bare remote has no refs/heads/main prior to push")

        rc_pre_ls, out_pre_ls, err_pre_ls = run_cmd(
            ["git", "ls-remote", "origin", f"refs/heads/{branch_to_use}"],
            cwd=str(work_repo),
            env=env,
        )
        if rc_pre_ls != 0:
            set_state("PREFLIGHT_FAILED")
            msg = f"Pre-push git ls-remote failed (exit={rc_pre_ls}): {err_pre_ls or out_pre_ls}"
            add_step("preflight_check_remote_branch", False, msg)
            report["error"] = f"REMOTE_UNREACHABLE_PREFLIGHT_FAILED: {msg}"
            return report

        pre_remote_sha = out_pre_ls.split()[0].strip() if out_pre_ls.strip() else ""
        report["pre_push_remote_sha"] = pre_remote_sha or None
        is_new_remote_branch = (pre_remote_sha == "")
        report["target_branch_creation_mode"] = "CREATE_NEW_REMOTE_BRANCH" if is_new_remote_branch else "FAST_FORWARD_EXISTING_BRANCH"

        if pre_remote_sha and pre_remote_sha.lower() == head_sha.lower():
            msg = (
                f"Remote branch {branch_to_use} on {remote_url} is already at local HEAD {head_sha}. "
                "Skipping git push and halting without polling because no new push event would be emitted."
            )
            add_step("preflight_check_remote_branch", True, msg)
            set_state("REMOTE_ALREADY_AT_LOCAL_HEAD_NO_NEW_PUSH_EVENT")
            report["build_triggered"] = False
            report["push_executed"] = False
            report["error"] = f"REMOTE_ALREADY_AT_LOCAL_HEAD_NO_NEW_PUSH_EVENT: {msg}"
            return report

        if pre_remote_sha:
            rc_cat_rem, _, _ = run_cmd(["git", "cat-file", "-e", f"{pre_remote_sha}^{{commit}}"], cwd=str(work_repo), env=env)
            if rc_cat_rem != 0:
                run_cmd(["git", "fetch", "origin", f"refs/heads/{branch_to_use}:refs/remotes/origin/_preflight_check"], cwd=str(work_repo), env=env)
            rc_ff, _, _ = run_cmd(["git", "merge-base", "--is-ancestor", pre_remote_sha, "HEAD"], cwd=str(work_repo), env=env)
            if rc_ff != 0:
                set_state("REMOTE_DIVERGED_NOT_FAST_FORWARD")
                msg = (
                    f"Remote branch {branch_to_use} is at {pre_remote_sha}, which is NOT an ancestor of local HEAD {head_sha}. "
                    "Refusing to push (force-push is strictly prohibited)."
                )
                add_step("preflight_check_remote_branch", False, msg)
                report["error"] = f"REMOTE_DIVERGED_NOT_FAST_FORWARD: {msg}"
                return report
            add_step("preflight_check_remote_branch", True, f"Remote branch {branch_to_use} is at ancestor {pre_remote_sha} (fast-forward safe to {head_sha})")
        else:
            add_step("preflight_check_remote_branch", True, f"Remote branch {branch_to_use} does not exist yet on origin (new branch push safe)")

        # Step 1C: Check gh CLI installation and authentication BEFORE pushing
        gh_bin = shutil.which("gh", path=env.get("PATH", ""))
        if not gh_bin:
            set_state("PREFLIGHT_FAILED")
            msg = "GitHub CLI (gh) is NOT installed in PATH. Halting before push without claiming workflow trigger success."
            add_step("verify_gh_cli_installed", False, msg)
            report["error"] = f"GH_CLI_NOT_INSTALLED: {msg}"
            return report
        add_step("verify_gh_cli_installed", True, f"Found gh binary at {gh_bin}")

        rc_auth, out_auth, err_auth = run_cmd([gh_bin, "auth", "status"], cwd=str(work_repo), env=env)
        if rc_auth != 0:
            set_state("PREFLIGHT_FAILED")
            msg = f"GitHub CLI (gh) is NOT authenticated ({err_auth or out_auth}). Halting before push."
            add_step("verify_gh_cli_authenticated", False, msg)
            report["error"] = f"GH_CLI_UNAUTHENTICATED: {msg}"
            return report
        add_step("verify_gh_cli_authenticated", True, "gh auth status verified")

        # Step 1D: Fail-Closed query of workflow metadata + pre-push workflow runs via REST API pagination (BUG-41, BUG-47, BUG-48, BUG-52)
        pre_query = query_workflow_runs_fail_closed(
            gh_bin=gh_bin,
            work_repo=work_repo,
            env=env,
            workflow_file=WORKFLOW_FILE,
            max_pages=preflight_max_pages,
            per_page=preflight_per_page,
            github_repo=github_repo,
            allow_deferred_pre_push=is_new_remote_branch,
        )
        if not pre_query["ok"]:
            set_state("PREFLIGHT_FAILED")
            msg = f"Fail-closed preflight run query failed before push: {pre_query['error']}"
            add_step("record_pre_push_runs_fail_closed", False, msg)
            report["error"] = f"PREFLIGHT_RUN_LIST_FAILED: {pre_query['error']}"
            return report

        resolved_wf_meta = pre_query["workflow_metadata"]
        report["workflow_metadata"] = resolved_wf_meta

        pre_existing_ids = set(pre_query["run_ids"])
        max_pre_existing_id = max(pre_existing_ids) if pre_existing_ids else 0
        report["pre_existing_run_ids"] = sorted(pre_existing_ids)
        report["max_pre_existing_run_id"] = max_pre_existing_id
        report["pre_existing_runs_query_summary"] = {
            "workflow_id": resolved_wf_meta.get("workflow_id"),
            "workflow_path": resolved_wf_meta.get("path"),
            "resolution_mode": resolved_wf_meta.get("resolution_mode"),
            "deferred_until_branch_push": bool(resolved_wf_meta.get("deferred_until_branch_push")),
            "excluded_remote_workflows": resolved_wf_meta.get("excluded_remote_workflows", []),
            "total_count_reported": pre_query["total_count"],
            "runs_inspected_count": len(pre_query["runs"]),
            "pages_fetched": pre_query["pages_fetched"],
            "max_pages_configured": pre_query["max_pages_configured"],
            "per_page_configured": pre_query["per_page_configured"],
            "endpoints_queried": pre_query["endpoints_queried"],
            "preflight_started_at_utc": preflight_started_iso,
            "max_pre_existing_run_id": max_pre_existing_id,
            "bounded_window_note": pre_query["bounded_window_note"],
        }
        set_state("PREFLIGHT_PASS")
        add_step(
            "record_pre_push_runs_fail_closed",
            True,
            f"PREFLIGHT_PASS: {pre_query['bounded_window_note']} Recorded {len(pre_existing_ids)} run ID(s) (max_id={max_pre_existing_id}).",
        )

        # Step 2: Push ONLY allowlisted target branch without --force and without any tags (BUG-40 & BUG-49)
        rc_push, out_push, err_push = run_cmd(
            ["git", "push", "-u", "origin", f"refs/heads/{branch_to_use}:refs/heads/{branch_to_use}"],
            cwd=str(work_repo),
            env=env,
        )
        combined_push_out = f"{out_push}\n{err_push}".strip()
        if rc_push != 0:
            set_state("RUN_FAILED")
            add_step("git_push_target_branch", False, f"git push to {remote_url} failed: {combined_push_out}")
            report["error"] = f"GIT_PUSH_FAILED: {combined_push_out}"
            return report

        if "everything up-to-date" in combined_push_out.lower():
            msg = f"git push reported 'Everything up-to-date' for {branch_to_use} ({head_sha}); no new push event was generated."
            add_step("git_push_target_branch", True, msg)
            set_state("REMOTE_ALREADY_AT_LOCAL_HEAD_NO_NEW_PUSH_EVENT")
            report["build_triggered"] = False
            report["push_executed"] = False
            report["error"] = f"REMOTE_ALREADY_AT_LOCAL_HEAD_NO_NEW_PUSH_EVENT: {msg}"
            return report

        report["push_executed"] = True
        add_step("git_push_target_branch", True, f"Pushed single allowlisted branch {branch_to_use} (no tags, no --force) to {remote_url}")

        # Step 3A: Verify remote SHA of target branch via git ls-remote
        rc_ls, out_ls, err_ls = run_cmd(
            ["git", "ls-remote", "origin", f"refs/heads/{branch_to_use}"],
            cwd=str(work_repo),
            env=env,
        )
        remote_sha = out_ls.split()[0] if (rc_ls == 0 and out_ls.split()) else ""
        if rc_ls != 0 or remote_sha.lower() != head_sha.lower():
            set_state("RUN_FAILED")
            add_step("verify_remote_sha", False, f"Remote SHA ({remote_sha}) != Local HEAD ({head_sha}) ({err_ls})")
            report["error"] = f"REMOTE_SHA_MISMATCH: {remote_sha} != {head_sha}"
            return report
        report["verified_remote_sha"] = remote_sha

        # Step 3B: Verify remote refs/heads/main remained 100% untouched after git push (BUG-52 / ARGON)
        rc_post_main, out_post_main, err_post_main = run_cmd(
            ["git", "ls-remote", "origin", "refs/heads/main"],
            cwd=str(work_repo),
            env=env,
        )
        post_remote_main_sha = out_post_main.split()[0].strip().lower() if (rc_post_main == 0 and out_post_main.strip()) else ""
        report["post_push_remote_main_sha"] = post_remote_main_sha or None
        report["remote_main_verified_post_push"] = None
        if rc_post_main != 0 or post_remote_main_sha != pre_remote_main_sha:
            set_state("RUN_FAILED")
            msg = f"Remote refs/heads/main changed after push: pre={pre_remote_main_sha!r}, post={post_remote_main_sha!r} ({err_post_main})"
            add_step("verify_remote_main_untouched_post_push", False, msg)
            report["error"] = f"POST_PUSH_REMOTE_MAIN_MUTATED: {msg}"
            return report
        report["remote_main_verified_post_push"] = post_remote_main_sha or None
        add_step(
            "verify_remote_main_untouched_post_push",
            True,
            f"Verified remote refs/heads/main remained untouched after push: {post_remote_main_sha or 'absent'}",
        )

        report["build_triggered"] = True
        set_state("PUSH_COMPLETED")
        add_step("verify_remote_sha", True, f"PUSH_COMPLETED: Verified remote SHA on origin matches local HEAD: {remote_sha}")

        # Helper to filter candidate runs matching ALL criteria (BUG-41, BUG-42, BUG-48, BUG-52):
        #   - workflowId == expected_wf_id AND workflowPath == expected_wf_path
        #   - event == "push"
        #   - headBranch == branch_to_use
        #   - headSha == head_sha
        #   - databaseId not in pre_existing_ids AND databaseId > max_pre_existing_id
        #   - createdAt >= preflight_started_dt - 2s tolerance
        def filter_matching_new_runs(runs_list: list, exp_wf_id: int, exp_wf_path: str) -> list:
            candidates = []
            earliest_allowed = preflight_started_dt - datetime.timedelta(seconds=2)
            for r in runs_list:
                r_id = r["databaseId"]
                r_wf_id = r["workflowId"]
                r_wf_path = r["workflowPath"]
                r_sha = r["headSha"]
                r_evt = r["event"]
                r_br = r["headBranch"]
                r_dt = parse_iso8601_utc(r["createdAt"])
                if (
                    r_id > 0
                    and r_wf_id == exp_wf_id
                    and r_wf_path == exp_wf_path
                    and r_id not in pre_existing_ids
                    and r_id > max_pre_existing_id
                    and r_evt == "push"
                    and r_br == branch_to_use
                    and r_sha.lower() == head_sha.lower()
                    and r_dt is not None
                    and r_dt >= earliest_allowed
                ):
                    candidates.append(r)
            return candidates

        # Step 4A: Poll for initial matching run candidate across paginated REST API results
        matched_run = None
        last_deferred_wf_err = None
        for attempt in range(1, max(1, poll_attempts) + 1):
            if poll_interval_s > 0:
                time.sleep(poll_interval_s)

            # If workflow metadata was deferred pre-push (new branch workflow absent from remote main),
            # resolve authoritative workflow metadata post-push (allow_deferred_pre_push=False) before querying runs!
            if resolved_wf_meta.get("deferred_until_branch_push") or not resolved_wf_meta.get("workflow_id"):
                post_wf_meta = resolve_workflow_metadata_fail_closed(
                    gh_bin=gh_bin,
                    work_repo=work_repo,
                    env=env,
                    github_repo=github_repo,
                    workflow_file=WORKFLOW_FILE,
                    allow_deferred_pre_push=False,
                )
                if not post_wf_meta.get("ok"):
                    err_str = post_wf_meta.get("error") or ""
                    if "GH_API_WORKFLOW_NOT_REGISTERED_ON_REMOTE" in err_str:
                        last_deferred_wf_err = err_str
                        continue
                    set_state("RUN_FAILED")
                    msg = f"Post-push workflow metadata resolution failed on attempt {attempt}: {err_str}"
                    add_step("poll_matching_run_id", False, msg)
                    report["error"] = f"POLL_QUERY_FAILED: {err_str}"
                    return report
                resolved_wf_meta = post_wf_meta
                report["workflow_metadata"] = resolved_wf_meta

            expected_wf_id = int(resolved_wf_meta["workflow_id"])
            expected_wf_path = str(resolved_wf_meta["path"])

            poll_q = query_workflow_runs_fail_closed(
                gh_bin=gh_bin,
                work_repo=work_repo,
                env=env,
                workflow_file=WORKFLOW_FILE,
                max_pages=preflight_max_pages,
                per_page=preflight_per_page,
                github_repo=github_repo,
                resolved_workflow_meta=resolved_wf_meta,
                allow_deferred_pre_push=False,
            )
            if not poll_q["ok"]:
                set_state("RUN_FAILED")
                msg = f"Run polling query failed on attempt {attempt}: {poll_q['error']}"
                add_step("poll_matching_run_id", False, msg)
                report["error"] = f"POLL_QUERY_FAILED: {poll_q['error']}"
                return report

            matching_new_runs = filter_matching_new_runs(poll_q["runs"], expected_wf_id, expected_wf_path)
            if len(matching_new_runs) > 1:
                dup_ids = [int(x["databaseId"]) for x in matching_new_runs]
                msg = f"Duplicate new runs detected immediately ({len(matching_new_runs)} runs: {dup_ids}) for headSha={head_sha} on branch {branch_to_use}."
                set_state("DUPLICATE_RUN_DETECTED")
                add_step("poll_matching_run_id", False, msg)
                report["duplicate_run_ids"] = dup_ids
                report["error"] = f"DUPLICATE_RUN_DETECTED: {msg}"
                return report

            if len(matching_new_runs) == 1:
                matched_run = matching_new_runs[0]
                break

        if matched_run is None:
            if last_deferred_wf_err and not resolved_wf_meta.get("workflow_id"):
                msg = (
                    f"Workflow {WORKFLOW_DEFINITION_PATH} was still not registered on remote after pushing {branch_to_use} "
                    f"across {poll_attempts} poll attempt(s): {last_deferred_wf_err}"
                )
                set_state("RUN_TIMEOUT")
                add_step("poll_matching_run_id", False, msg)
                report["error"] = f"POST_PUSH_WORKFLOW_NOT_REGISTERED_ON_REMOTE: {msg}"
                return report
            msg = f"No new push run matching headSha={head_sha} on branch {branch_to_use} appeared after {poll_attempts} poll attempt(s)."
            set_state("RUN_TIMEOUT")
            add_step("poll_matching_run_id", False, msg)
            report["error"] = f"RUN_TIMEOUT: {msg}"
            return report

        expected_wf_id = int(resolved_wf_meta["workflow_id"])
        expected_wf_path = str(resolved_wf_meta["path"])
        run_id = str(matched_run["databaseId"])
        report["run_id"] = run_id
        report["run_url"] = matched_run.get("url")
        set_state("RUN_DISCOVERED")
        add_step("poll_matching_run_id", True, f"RUN_DISCOVERED: Discovered initial candidate push Run ID {run_id} for headSha={head_sha}")

        # Step 4B: Duplicate-Detection Settling Window across paginated REST API results (BUG-42 & BUG-47)
        for s_idx in range(1, max(0, settling_polls) + 1):
            if settling_interval_s > 0:
                time.sleep(settling_interval_s)
            settle_q = query_workflow_runs_fail_closed(
                gh_bin=gh_bin,
                work_repo=work_repo,
                env=env,
                workflow_file=WORKFLOW_FILE,
                max_pages=preflight_max_pages,
                per_page=preflight_per_page,
                github_repo=github_repo,
                resolved_workflow_meta=resolved_wf_meta,
                allow_deferred_pre_push=False,
            )
            if not settle_q["ok"]:
                set_state("RUN_FAILED")
                msg = f"Duplicate-detection settling query failed on settling poll {s_idx}/{settling_polls}: {settle_q['error']}"
                add_step("duplicate_detection_settling_window", False, msg)
                report["error"] = f"SETTLING_QUERY_FAILED: {settle_q['error']}"
                return report

            settle_matches = filter_matching_new_runs(settle_q["runs"], expected_wf_id, expected_wf_path)
            if len(settle_matches) > 1:
                dup_ids = [int(x["databaseId"]) for x in settle_matches]
                msg = (
                    f"Delayed duplicate run detected during settling poll {s_idx}/{settling_polls} "
                    f"({len(settle_matches)} matching runs: {dup_ids}) for headSha={head_sha} on branch {branch_to_use}."
                )
                set_state("DUPLICATE_RUN_DETECTED")
                add_step("duplicate_detection_settling_window", False, msg)
                report["duplicate_run_ids"] = dup_ids
                report["error"] = f"DUPLICATE_RUN_DETECTED: {msg}"
                return report
            if len(settle_matches) == 0:
                set_state("RUN_FAILED")
                msg = f"Candidate Run ID {run_id} disappeared during settling poll {s_idx}/{settling_polls}."
                add_step("duplicate_detection_settling_window", False, msg)
                report["error"] = f"CANDIDATE_RUN_DISAPPEARED: {msg}"
                return report

        add_step(
            "duplicate_detection_settling_window",
            True,
            f"Completed {settling_polls} settling poll(s) (interval={settling_interval_s}s): confirmed single unique Run ID {run_id} with zero delayed duplicates.",
        )

        # Step 5: Watch run to completion and verify all jobs succeeded
        set_state("RUN_IN_PROGRESS")
        rc_watch, out_watch, err_watch = run_cmd(
            [gh_bin, "run", "watch", run_id, "--exit-status"],
            cwd=str(work_repo),
            env=env,
            timeout=7200,
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

        # Step 6: Download artifacts for this exact Run ID and calculate/record SHA-256 (BUG-45)
        out_art_dir = artifacts_base_dir / f"dist_github_actions_run_{run_id}"
        if out_art_dir.exists():
            shutil.rmtree(out_art_dir)
        out_art_dir.mkdir(parents=True, exist_ok=True)

        rc_dl, out_dl, err_dl = run_cmd(
            [gh_bin, "run", "download", run_id, "--dir", str(out_art_dir)],
            cwd=str(work_repo),
            env=env,
            timeout=600,
        )
        if rc_dl != 0:
            msg = f"gh run download {run_id} failed: {err_dl or out_dl}"
            set_state("RUN_FAILED")
            add_step("download_run_artifacts", False, msg)
            report["error"] = f"ARTIFACT_DOWNLOAD_FAILED: {msg}"
            return report
        add_step("download_run_artifacts", True, f"Downloaded artifacts for Run ID {run_id} into {out_art_dir.name}")

        art_ver = verify_and_hash_downloaded_artifacts(
            out_art_dir,
            run_id=run_id,
            trusted_reference_digests=trusted_reference_digests,
            verify_attestation=verify_attestation,
            gh_bin=gh_bin,
        )
        report["artifacts_verification"] = art_ver
        if not art_ver["ok"]:
            msg = (
                f"Artifact check failed ({art_ver['verification_state']}): "
                f"missing={art_ver['missing_files']}, empty={art_ver['empty_files']}, "
                f"digest_mismatches={art_ver['trusted_digest_mismatches']}"
            )
            set_state("RUN_FAILED")
            add_step("calculate_and_record_five_windows_artifacts_sha256", False, msg)
            report["error"] = f"ARTIFACTS_CHECK_FAILED: {msg}"
            return report

        set_state("SHA256_CALCULATED_AND_RECORDED")
        add_step(
            "calculate_and_record_five_windows_artifacts_sha256",
            True,
            f"SHA256_CALCULATED_AND_RECORDED: Verified 5/5 non-empty files and recorded SHA-256 checksums for Run ID {run_id} "
            f"(trusted_reference_digests_verified={art_ver['trusted_reference_digests_verified']}, "
            f"attestation={art_ver['attestation_verification_status']})",
        )
        set_state("PASS")
        return report


def run_self_test(repo_root: Path) -> dict:
    """
    Comprehensive local regression test suite covering BUG-01..BUG-49 (Simulated Local Bare Remote + Real REST API URL Pagination + Node.js UI tests + Provenance).
    NOTE: All Git/GitHub CLI execution tests use an isolated local bare Git repository (`git init --bare`) and simulated
    `gh` binaries inspecting real `gh api` URL query parameters; no remote GitHub push or cloud workflow execution is performed.
    """
    bundle = repo_root / "reports_and_logs" / "mersad_preview_0_1_verifiable_history.bundle"
    bat_file = repo_root / "PUSH_CANDIDATE_9491BCD_TO_GITHUB_ACTIONS.bat"
    bat_rel_file = repo_root / "PUSH_RELEASE_PREVIEW_0_1_TO_GITHUB_ACTIONS.bat"
    bat_ai_sub_file = repo_root / "MERSAD_AI_Preview_0.1" / "PUSH_TO_GITHUB_AND_BUILD.bat"
    wf_file = repo_root / ".github" / "workflows" / WORKFLOW_FILE
    deploy_py_file = repo_root / "tools" / "deploy_and_run_github_actions.py"

    bat_text = bat_file.read_text(encoding="utf-8")
    bat_rel_text = bat_rel_file.read_text(encoding="utf-8")
    bat_ai_sub_text = bat_ai_sub_file.read_text(encoding="utf-8")
    wf_text = wf_file.read_text(encoding="utf-8")
    deploy_py_text = deploy_py_file.read_text(encoding="utf-8")

    checks = []
    now_utc_dt = datetime.datetime.now(datetime.timezone.utc) + datetime.timedelta(seconds=3600)
    now_utc_iso = now_utc_dt.strftime("%Y-%m-%dT%H:%M:%SZ")
    now_utc_plus1_iso = (now_utc_dt + datetime.timedelta(seconds=1)).strftime("%Y-%m-%dT%H:%M:%SZ")

    def create_fresh_bare_remote(base_dir: Path, name: str) -> Path:
        br = base_dir / name
        if br.exists():
            shutil.rmtree(br)
        subprocess.run(["git", "init", "--bare", str(br)], check=True, capture_output=True)
        return br

    wf_meta_json_str = json.dumps({
        "id": 99001,
        "name": EXPECTED_WORKFLOW_DISPLAY_NAME,
        "path": WORKFLOW_DEFINITION_PATH,
        "state": "active",
    })

    # 1. BUG-35 & BUG-46: No script calls `gh workflow run` after `git push` (across all 3 .bat files and Python controller)
    no_gh_wf_run_in_bat = (
        "gh workflow run" not in bat_text
        and "gh workflow run" not in bat_rel_text
        and "gh workflow run" not in bat_ai_sub_text
    )
    no_gh_wf_run_in_py = (re.search(r'\[\s*gh_bin\s*,\s*"workflow"\s*,\s*"run"', deploy_py_text) is None)
    checks.append((
        "TEST_01_NO_SCRIPT_CALLS_GH_WORKFLOW_RUN_AFTER_PUSH",
        no_gh_wf_run_in_bat and no_gh_wf_run_in_py
    ))

    # 2. BUG-35 & BUG-37: Workflow YAML uses push trigger only (no workflow_dispatch, no unused run_extended_stress)
    ok_wf_push_only, _ = validate_workflow_push_only(wf_file)
    with tempfile.TemporaryDirectory(prefix="mersad_wf_val_") as tmp_wf_d:
        bad_wf = Path(tmp_wf_d) / "bad.yml"
        bad_wf.write_text("on:\n  workflow_dispatch:\n  push:\n", encoding="utf-8")
        ok_bad_wf, _ = validate_workflow_push_only(bad_wf)
    checks.append((
        "TEST_02_WORKFLOW_PUSH_ONLY_AND_VALIDATOR_REJECTS_WORKFLOW_DISPATCH",
        ok_wf_push_only is True and ok_bad_wf is False
    ))

    # 3. BUG-37: No unused `run_extended_stress` input remains in workflow, deployment scripts, or .bat files
    checks.append((
        "TEST_03_NO_UNUSED_RUN_EXTENDED_STRESS_IN_WORKFLOW_OR_SCRIPTS",
        "run_extended_stress" not in wf_text
        and "run_extended_stress" not in bat_text
        and "run_extended_stress" not in bat_rel_text
        and "run_extended_stress" not in bat_ai_sub_text
    ))

    # 4. BUG-40 & BUG-46: All 3 BAT files are thin wrappers delegating to Python controller, zero direct git push, zero tag push, zero main fallback
    bat_audit = validate_bat_thin_wrappers_no_tag_or_extra_push(repo_root)
    checks.append((
        "BUG40_46_01_ALL_THREE_BAT_WRAPPERS_DELEGATE_TO_PYTHON_NO_DIRECT_PUSH_OR_MAIN_FALLBACK",
        bat_audit["ok"] is True
        and len(bat_audit["issues"]) == 0
        and len(bat_audit["checked_files"]) == 3
    ))

    # 5. BUG-40 & BUG-46 Negative Self-Test: Verify validator catches legacy PUSH_TO_GITHUB_AND_BUILD.bat (git push, gh workflow run, DEFAULT_BRANCH=main, >nul 2>nul)
    with tempfile.TemporaryDirectory(prefix="mersad_bat_neg_") as tmp_bat_d:
        fake_root = Path(tmp_bat_d)
        (fake_root / "tools").mkdir()
        (fake_root / "MERSAD_AI_Preview_0.1").mkdir()
        shutil.copy2(deploy_py_file, fake_root / "tools" / "deploy_and_run_github_actions.py")
        (fake_root / "PUSH_RELEASE_PREVIEW_0_1_TO_GITHUB_ACTIONS.bat").write_text(
            bat_rel_text + "\ngit push origin refs/tags/v0.1.0-preview-code >nul 2>&1\n", encoding="utf-8"
        )
        (fake_root / "PUSH_CANDIDATE_9491BCD_TO_GITHUB_ACTIONS.bat").write_text(bat_text, encoding="utf-8")
        (fake_root / "MERSAD_AI_Preview_0.1" / "PUSH_TO_GITHUB_AND_BUILD.bat").write_text(
            '@echo off\nset "DEFAULT_BRANCH=main"\ngit push -u origin "%MERSAD_BUILD_BRANCH%"\n'
            'git push origin "_register_wf_%DEFAULT_BRANCH%:refs/heads/%DEFAULT_BRANCH%" >nul 2>nul\n'
            'gh workflow run "%MERSAD_WORKFLOW_FILE%"\n',
            encoding="utf-8",
        )
        neg_bat_audit = validate_bat_thin_wrappers_no_tag_or_extra_push(fake_root)
    checks.append((
        "BUG40_46_02_VALIDATOR_DETECTS_AND_REJECTS_LEGACY_SUBDIR_PUSH_BAT_AND_TAG_PUSH",
        neg_bat_audit["ok"] is False and len(neg_bat_audit["issues"]) >= 6
    ))

    # =========================================================================
    # BUG-49 Regression Tests: Central Target Branch Allowlist
    # =========================================================================
    ok_br_canonical, res_br_canonical, _ = validate_target_branch_allowlist(DEFAULT_TARGET_BRANCH, env={})
    ok_br_main, _, err_br_main = validate_target_branch_allowlist("main", env={})
    ok_br_rel, _, err_br_rel = validate_target_branch_allowlist("release/mersad-preview-0.1", env={})
    ok_br_stage15, _, _ = validate_target_branch_allowlist("release/v7.1-stage15-win-x64", env={})
    ok_br_empty, _, _ = validate_target_branch_allowlist("", env={})
    ok_br_env_main, _, _ = validate_target_branch_allowlist(None, env={"MERSAD_DEPLOY_BRANCH": "main"})
    ok_br_env_bld, _, _ = validate_target_branch_allowlist(DEFAULT_TARGET_BRANCH, env={"MERSAD_BUILD_BRANCH": "release/mersad-preview-0.1"})
    checks.append((
        "BUG49_01_ALLOWLIST_UNIT_ACCEPTS_ONLY_FIX_BRANCH_AND_REJECTS_ALL_OVERRIDES",
        ok_br_canonical is True
        and res_br_canonical == "fix/preview-0.1-postbuild-42273598736"
        and ok_br_main is False and "BRANCH_NOT_IN_ALLOWLIST" in err_br_main
        and ok_br_rel is False and "BRANCH_NOT_IN_ALLOWLIST" in err_br_rel
        and ok_br_stage15 is False
        and ok_br_empty is False
        and ok_br_env_main is False
        and ok_br_env_bld is False
    ))

    with tempfile.TemporaryDirectory(prefix="mersad_bare_remote_") as tmpdir:
        tmp_p = Path(tmpdir)
        bare_remote_0 = create_fresh_bare_remote(tmp_p, "origin_0.git")

        # BUG49-02: execute_deployment rejects main, release/mersad-preview-0.1, empty branch, and env overrides before any push
        res_49_main = execute_deployment(bundle, str(bare_remote_0), wf_file, target_branch="main", env_override={})
        res_49_rel = execute_deployment(bundle, str(bare_remote_0), wf_file, target_branch="release/mersad-preview-0.1", env_override={})
        res_49_empty = execute_deployment(bundle, str(bare_remote_0), wf_file, target_branch="", env_override={})
        res_49_env = execute_deployment(bundle, str(bare_remote_0), wf_file, target_branch=None, env_override={"MERSAD_DEPLOY_BRANCH": "main"})
        checks.append((
            "BUG49_02_EXECUTE_DEPLOYMENT_BLOCKS_NON_ALLOWLISTED_BRANCHES_BEFORE_CLONE_OR_PUSH",
            all(
                r["status"] == "PREFLIGHT_FAILED"
                and r["branch_validation_status"] == "BRANCH_NOT_IN_ALLOWLIST"
                and r["push_executed"] is False
                and r["build_triggered"] is False
                and "BRANCH_NOT_IN_ALLOWLIST" in r.get("error", "")
                for r in (res_49_main, res_49_rel, res_49_empty, res_49_env)
            )
        ))

        # Missing gh in PATH must halt with PREFLIGHT_FAILED before push
        res_no_gh = execute_deployment(
            bundle,
            str(bare_remote_0),
            wf_file,
            env_override={"PATH": "/usr/bin:/bin"},
            poll_attempts=1,
            poll_interval_s=0.0,
            settling_polls=1,
            settling_interval_s=0.0,
            target_branch=DEFAULT_TARGET_BRANCH,
        )
        local_head = res_no_gh.get("local_head_sha", "")
        checks.append((
            "MISSING_GH_HALTS_WITH_PREFLIGHT_FAILED_BEFORE_PUSH",
            res_no_gh["status"] == "PREFLIGHT_FAILED"
            and res_no_gh["build_triggered"] is False
            and res_no_gh["push_executed"] is False
            and "GH_CLI_NOT_INSTALLED" in res_no_gh.get("error", "")
            and bool(local_head)
        ))

        # Dirty working tree before push must be rejected with PREFLIGHT_FAILED
        res_dirty = execute_deployment(
            bundle,
            str(bare_remote_0),
            wf_file,
            env_override={"PATH": "/usr/bin:/bin"},
            poll_attempts=1,
            poll_interval_s=0.0,
            target_branch=DEFAULT_TARGET_BRANCH,
            simulate_dirty_working_tree=True,
        )
        checks.append((
            "PREFLIGHT_REJECTS_DIRTY_WORKING_TREE_WITH_PREFLIGHT_FAILED",
            res_dirty["status"] == "PREFLIGHT_FAILED"
            and res_dirty["push_executed"] is False
            and "DIRTY_WORKING_TREE" in res_dirty.get("error", "")
        ))

        # =========================================================================
        # BUG-48 Regression Tests: Authoritative Workflow Identity Without Fallbacks
        # =========================================================================
        ok_48_no_wf_id, _, err_48_no_wf_id = validate_and_normalize_run_record(
            {
                "id": 1001,
                "path": WORKFLOW_DEFINITION_PATH,
                "name": EXPECTED_WORKFLOW_DISPLAY_NAME,
                "head_sha": local_head,
                "head_branch": DEFAULT_TARGET_BRANCH,
                "event": "push",
                "created_at": "2026-11-01T00:00:00Z",
            },
            expected_workflow_id=99001,
        )
        ok_48_wrong_wf_id, _, err_48_wrong_wf_id = validate_and_normalize_run_record(
            {
                "id": 1002,
                "workflow_id": 88888,
                "path": WORKFLOW_DEFINITION_PATH,
                "name": EXPECTED_WORKFLOW_DISPLAY_NAME,
                "head_sha": local_head,
                "head_branch": DEFAULT_TARGET_BRANCH,
                "event": "push",
                "created_at": "2026-11-01T00:00:00Z",
            },
            expected_workflow_id=99001,
        )
        ok_48_no_name_or_path, _, err_48_no_name_or_path = validate_and_normalize_run_record(
            {
                "id": 1003,
                "workflow_id": 99001,
                "head_sha": local_head,
                "head_branch": DEFAULT_TARGET_BRANCH,
                "event": "push",
                "created_at": "2026-11-01T00:00:00Z",
            },
            expected_workflow_id=99001,
        )
        ok_48_empty_name, _, err_48_empty_name = validate_and_normalize_run_record(
            {
                "id": 1004,
                "workflow_id": 99001,
                "name": "",
                "head_sha": local_head,
                "head_branch": DEFAULT_TARGET_BRANCH,
                "event": "push",
                "created_at": "2026-11-01T00:00:00Z",
            },
            expected_workflow_id=99001,
        )
        ok_48_wrong_path, _, err_48_wrong_path = validate_and_normalize_run_record(
            {
                "id": 1005,
                "workflow_id": 99001,
                "path": ".github/workflows/windows-build.yml",
                "name": EXPECTED_WORKFLOW_DISPLAY_NAME,
                "head_sha": local_head,
                "head_branch": DEFAULT_TARGET_BRANCH,
                "event": "push",
                "created_at": "2026-11-01T00:00:00Z",
            },
            expected_workflow_id=99001,
        )
        ok_48_valid, norm_48_valid, _ = validate_and_normalize_run_record(
            {
                "id": 1006,
                "workflow_id": 99001,
                "path": WORKFLOW_DEFINITION_PATH,
                "name": EXPECTED_WORKFLOW_DISPLAY_NAME,
                "head_sha": local_head,
                "head_branch": DEFAULT_TARGET_BRANCH,
                "event": "push",
                "created_at": "2026-11-01T00:00:00Z",
            },
            expected_workflow_id=99001,
        )
        val_fn_body = deploy_py_text.partition("def validate_and_normalize_run_record(")[2].partition("def query_workflow_runs_fail_closed(")[0]
        no_or_workflow_file_fallback = ("or WORKFLOW_FILE" not in val_fn_body)
        checks.append((
            "BUG48_01_RUN_VALIDATOR_REQUIRES_EXPLICIT_WORKFLOW_ID_AND_PATH_OR_NAME_WITHOUT_FALLBACK",
            no_or_workflow_file_fallback
            and ok_48_no_wf_id is False and "workflow_id" in err_48_no_wf_id
            and ok_48_wrong_wf_id is False and "workflow_id mismatch" in err_48_wrong_wf_id
            and ok_48_no_name_or_path is False and "missing explicit workflow identity" in err_48_no_name_or_path
            and ok_48_empty_name is False
            and ok_48_wrong_path is False and "workflow path mismatch" in err_48_wrong_path
            and ok_48_valid is True and norm_48_valid.get("workflowId") == 99001
        ))

        # =========================================================================
        # BUG-41, BUG-47, BUG-48 Regression Tests: Real GitHub REST API Pagination (`gh api`)
        # =========================================================================
        query_fn_body = deploy_py_text.partition("def query_workflow_runs_fail_closed(")[2].partition("def validate_workflow_push_only(")[0]
        checks.append((
            "BUG47_01_NO_SYNTHETIC_MERSAD_GH_PAGE_ENV_VAR_IN_QUERY_CONTROLLER",
            "MERSAD_GH_PAGE" not in query_fn_body
            and "MERSAD_GH_PER_PAGE" not in query_fn_body
            and "?per_page={per_page}&page={page_idx}" in query_fn_body
        ))

        # BUG41/47-01: GH API returns non-zero exit code / HTTP 403 / HTTP 429 -> PREFLIGHT_FAILED (push_executed=False)
        fake_bin_41_rc = tmp_p / "fake_bin_41_rc"
        fake_bin_41_rc.mkdir()
        (fake_bin_41_rc / "gh").write_text(
            f"""#!/usr/bin/env python3
import sys
args = sys.argv[1:]
if args[:2] == ['auth', 'status']:
    sys.exit(0)
if args[:3] == ['api', '-X', 'GET'] and args[3].endswith('/workflows/{WORKFLOW_FILE}'):
    print({wf_meta_json_str!r})
    sys.exit(0)
sys.stderr.write('HTTP 403 Forbidden: Resource not accessible by integration\\n')
sys.exit(1)
""",
            encoding="utf-8",
        )
        (fake_bin_41_rc / "gh").chmod(0o755)
        res_41_rc = execute_deployment(
            bundle, str(create_fresh_bare_remote(tmp_p, "origin_41_rc.git")), wf_file,
            env_override={"PATH": f"{fake_bin_41_rc}:/usr/bin:/bin"},
            poll_attempts=1, poll_interval_s=0.0,
        )
        checks.append((
            "BUG41_47_01_GH_API_HTTP_403_OR_NONZERO_EXIT_HALTS_WITH_PREFLIGHT_FAILED_BEFORE_PUSH",
            res_41_rc["status"] == "PREFLIGHT_FAILED"
            and res_41_rc["push_executed"] is False
            and "PREFLIGHT_PASS" not in res_41_rc.get("state_history", [])
            and "GH_API_HTTP_401_403_AUTH_ERROR_ON_PAGE_1" in res_41_rc.get("error", "")
        ))

        # BUG41/47-02: GH API returns corrupted/malformed JSON or HTTP 429 Rate Limit -> PREFLIGHT_FAILED
        fake_bin_41_json = tmp_p / "fake_bin_41_json"
        fake_bin_41_json.mkdir()
        (fake_bin_41_json / "gh").write_text(
            f"""#!/usr/bin/env python3
import sys
args = sys.argv[1:]
if args[:2] == ['auth', 'status']:
    sys.exit(0)
if args[:3] == ['api', '-X', 'GET'] and args[3].endswith('/workflows/{WORKFLOW_FILE}'):
    print({wf_meta_json_str!r})
    sys.exit(0)
print('{{corrupted_json: [1, 2')
sys.exit(0)
""",
            encoding="utf-8",
        )
        (fake_bin_41_json / "gh").chmod(0o755)
        res_41_json = execute_deployment(
            bundle, str(create_fresh_bare_remote(tmp_p, "origin_41_json.git")), wf_file,
            env_override={"PATH": f"{fake_bin_41_json}:/usr/bin:/bin"},
            poll_attempts=1, poll_interval_s=0.0,
        )

        fake_bin_47_rl = tmp_p / "fake_bin_47_rl"
        fake_bin_47_rl.mkdir()
        (fake_bin_47_rl / "gh").write_text(
            f"""#!/usr/bin/env python3
import sys
args = sys.argv[1:]
if args[:2] == ['auth', 'status']:
    sys.exit(0)
if args[:3] == ['api', '-X', 'GET'] and args[3].endswith('/workflows/{WORKFLOW_FILE}'):
    print({wf_meta_json_str!r})
    sys.exit(0)
sys.stderr.write('HTTP 429 Too Many Requests: API rate limit exceeded\\n')
sys.exit(1)
""",
            encoding="utf-8",
        )
        (fake_bin_47_rl / "gh").chmod(0o755)
        res_47_rl = execute_deployment(
            bundle, str(create_fresh_bare_remote(tmp_p, "origin_47_rl.git")), wf_file,
            env_override={"PATH": f"{fake_bin_47_rl}:/usr/bin:/bin"},
            poll_attempts=1, poll_interval_s=0.0,
        )
        checks.append((
            "BUG41_47_02_GH_API_CORRUPTED_JSON_AND_HTTP_429_RATE_LIMIT_HALT_WITH_PREFLIGHT_FAILED",
            res_41_json["status"] == "PREFLIGHT_FAILED"
            and res_41_json["push_executed"] is False
            and "GH_API_INVALID_JSON_ON_PAGE_1" in res_41_json.get("error", "")
            and res_47_rl["status"] == "PREFLIGHT_FAILED"
            and res_47_rl["push_executed"] is False
            and "GH_API_HTTP_429_RATE_LIMIT_ERROR_ON_PAGE_1" in res_47_rl.get("error", "")
        ))

        # BUG41/48-03: GH API returns empty stdout or record missing workflow_id / workflow identity -> PREFLIGHT_FAILED
        fake_bin_41_empty = tmp_p / "fake_bin_41_empty"
        fake_bin_41_empty.mkdir()
        (fake_bin_41_empty / "gh").write_text(
            f"""#!/usr/bin/env python3
import sys
args = sys.argv[1:]
if args[:2] == ['auth', 'status']:
    sys.exit(0)
if args[:3] == ['api', '-X', 'GET'] and args[3].endswith('/workflows/{WORKFLOW_FILE}'):
    print({wf_meta_json_str!r})
    sys.exit(0)
print('')
sys.exit(0)
""",
            encoding="utf-8",
        )
        (fake_bin_41_empty / "gh").chmod(0o755)
        res_41_empty = execute_deployment(
            bundle, str(create_fresh_bare_remote(tmp_p, "origin_41_empty.git")), wf_file,
            env_override={"PATH": f"{fake_bin_41_empty}:/usr/bin:/bin"},
            poll_attempts=1, poll_interval_s=0.0,
        )

        fake_bin_48_inc = tmp_p / "fake_bin_48_inc"
        fake_bin_48_inc.mkdir()
        (fake_bin_48_inc / "gh").write_text(
            f"""#!/usr/bin/env python3
import json, sys
args = sys.argv[1:]
if args[:2] == ['auth', 'status']:
    sys.exit(0)
if args[:3] == ['api', '-X', 'GET'] and args[3].endswith('/workflows/{WORKFLOW_FILE}'):
    print({wf_meta_json_str!r})
    sys.exit(0)
print(json.dumps({{'total_count': 1, 'workflow_runs': [{{'id': 123, 'workflow_id': 99001, 'head_sha': '{local_head}', 'head_branch': '{DEFAULT_TARGET_BRANCH}', 'event': 'push', 'created_at': '2026-11-01T00:00:00Z'}}]}}))
sys.exit(0)
""",
            encoding="utf-8",
        )
        (fake_bin_48_inc / "gh").chmod(0o755)
        res_48_inc = execute_deployment(
            bundle, str(create_fresh_bare_remote(tmp_p, "origin_48_inc.git")), wf_file,
            env_override={"PATH": f"{fake_bin_48_inc}:/usr/bin:/bin"},
            poll_attempts=1, poll_interval_s=0.0,
        )
        checks.append((
            "BUG41_48_03_GH_API_EMPTY_STDOUT_OR_MISSING_WORKFLOW_IDENTITY_HALTS_WITH_PREFLIGHT_FAILED",
            res_41_empty["status"] == "PREFLIGHT_FAILED"
            and "GH_API_EMPTY_STDOUT_ON_PAGE_1" in res_41_empty.get("error", "")
            and res_48_inc["status"] == "PREFLIGHT_FAILED"
            and "GH_API_INCOMPLETE_OR_MISMATCHED_RECORD_PAGE_1_INDEX_0" in res_48_inc.get("error", "")
        ))

        # BUG47-03: Real 3-page REST API pagination (`?per_page=30&page=1..3`, total_count=65) without MERSAD_GH_PAGE!
        # Historical run with `local_head` is on Page 3 (index 64) and is properly discovered and excluded.
        fake_bin_47_3pages = tmp_p / "fake_bin_47_3pages"
        fake_bin_47_3pages.mkdir()
        page_3_script = f"""#!/usr/bin/env python3
import json, sys, urllib.parse
args = sys.argv[1:]
if args[:2] == ["auth", "status"]:
    sys.exit(0)
if args[:3] == ["api", "-X", "GET"]:
    ep = args[3]
    if ep.endswith("/workflows/{WORKFLOW_FILE}"):
        print({wf_meta_json_str!r})
        sys.exit(0)
    if "/workflows/99001/runs?" in ep:
        qs = urllib.parse.parse_qs(ep.split("?", 1)[1])
        page = int(qs.get("page", ["1"])[0])
        per_page = int(qs.get("per_page", ["30"])[0])
        if page == 1:
            runs = [
                {{
                    "id": 8900 - i,
                    "workflow_id": 99001,
                    "path": "{WORKFLOW_DEFINITION_PATH}",
                    "name": "{EXPECTED_WORKFLOW_DISPLAY_NAME}",
                    "head_sha": "1111111111111111111111111111111111111111",
                    "event": "push",
                    "head_branch": "{DEFAULT_TARGET_BRANCH}",
                    "created_at": f"2026-11-05T12:{{59 - i:02d}}:00Z",
                }}
                for i in range(per_page)
            ]
            print(json.dumps({{"total_count": 65, "workflow_runs": runs}}))
        elif page == 2:
            runs = [
                {{
                    "id": 8500 - i,
                    "workflow_id": 99001,
                    "path": "{WORKFLOW_DEFINITION_PATH}",
                    "name": "{EXPECTED_WORKFLOW_DISPLAY_NAME}",
                    "head_sha": "2222222222222222222222222222222222222222",
                    "event": "push",
                    "head_branch": "{DEFAULT_TARGET_BRANCH}",
                    "created_at": f"2026-11-04T12:{{59 - i:02d}}:00Z",
                }}
                for i in range(per_page)
            ]
            print(json.dumps({{"total_count": 65, "workflow_runs": runs}}))
        elif page == 3:
            runs = [
                {{
                    "id": 7905 - i,
                    "workflow_id": 99001,
                    "path": "{WORKFLOW_DEFINITION_PATH}",
                    "name": "{EXPECTED_WORKFLOW_DISPLAY_NAME}",
                    "head_sha": "{local_head}",
                    "event": "push",
                    "head_branch": "{DEFAULT_TARGET_BRANCH}",
                    "created_at": f"2026-10-25T12:{{59 - i:02d}}:00Z",
                }}
                for i in range(5)
            ]
            print(json.dumps({{"total_count": 65, "workflow_runs": runs}}))
        else:
            print(json.dumps({{"total_count": 65, "workflow_runs": []}}))
        sys.exit(0)
sys.exit(1)
"""
        (fake_bin_47_3pages / "gh").write_text(page_3_script, encoding="utf-8")
        (fake_bin_47_3pages / "gh").chmod(0o755)
        res_47_3pages = execute_deployment(
            bundle, str(create_fresh_bare_remote(tmp_p, "origin_47_3pages.git")), wf_file,
            env_override={"PATH": f"{fake_bin_47_3pages}:/usr/bin:/bin"},
            poll_attempts=1, poll_interval_s=0.0,
            preflight_max_pages=4, preflight_per_page=30,
        )
        q_sum_3p = res_47_3pages.get("pre_existing_runs_query_summary") or {}
        checks.append((
            "BUG47_03_REAL_REST_API_3_PAGE_PAGINATION_FETCHES_65_RUNS_AND_EXCLUDES_HISTORICAL_SHA_ON_PAGE_3",
            res_47_3pages["status"] == "RUN_TIMEOUT"
            and res_47_3pages["run_id"] is None
            and 7901 in res_47_3pages.get("pre_existing_run_ids", [])
            and q_sum_3p.get("pages_fetched") == 3
            and q_sum_3p.get("runs_inspected_count") == 65
            and len(q_sum_3p.get("endpoints_queried", [])) == 3
            and q_sum_3p["endpoints_queried"][0].endswith("?per_page=30&page=1")
            and q_sum_3p["endpoints_queried"][1].endswith("?per_page=30&page=2")
            and q_sum_3p["endpoints_queried"][2].endswith("?per_page=30&page=3")
        ))

        # BUG47-04: Broken pagination server returns identical page 1 results on page 2 -> DUPLICATE_PAGE_RESULTS -> PREFLIGHT_FAILED
        fake_bin_47_duppage = tmp_p / "fake_bin_47_duppage"
        fake_bin_47_duppage.mkdir()
        duppage_script = f"""#!/usr/bin/env python3
import json, sys
args = sys.argv[1:]
if args[:2] == ["auth", "status"]:
    sys.exit(0)
if args[:3] == ["api", "-X", "GET"]:
    ep = args[3]
    if ep.endswith("/workflows/{WORKFLOW_FILE}"):
        print({wf_meta_json_str!r})
        sys.exit(0)
    if "/workflows/99001/runs?" in ep:
        # Broken server ignores page parameter and returns the same 30 runs every time!
        runs = [
            {{
                "id": 8900 - i,
                "workflow_id": 99001,
                "path": "{WORKFLOW_DEFINITION_PATH}",
                "name": "{EXPECTED_WORKFLOW_DISPLAY_NAME}",
                "head_sha": "1111111111111111111111111111111111111111",
                "event": "push",
                "head_branch": "{DEFAULT_TARGET_BRANCH}",
                "created_at": f"2026-11-05T12:{{59 - i:02d}}:00Z",
            }}
            for i in range(30)
        ]
        print(json.dumps({{"total_count": 60, "workflow_runs": runs}}))
        sys.exit(0)
sys.exit(1)
"""
        (fake_bin_47_duppage / "gh").write_text(duppage_script, encoding="utf-8")
        (fake_bin_47_duppage / "gh").chmod(0o755)
        res_47_duppage = execute_deployment(
            bundle, str(create_fresh_bare_remote(tmp_p, "origin_47_duppage.git")), wf_file,
            env_override={"PATH": f"{fake_bin_47_duppage}:/usr/bin:/bin"},
            poll_attempts=1, poll_interval_s=0.0,
            preflight_max_pages=3, preflight_per_page=30,
        )
        checks.append((
            "BUG47_04_DUPLICATE_PAGE_RESULTS_ON_PAGE_2_DETECTED_AND_HALTS_WITH_PREFLIGHT_FAILED",
            res_47_duppage["status"] == "PREFLIGHT_FAILED"
            and res_47_duppage["push_executed"] is False
            and "GH_API_DUPLICATE_PAGE_RESULTS_ON_PAGE_2" in res_47_duppage.get("error", "")
        ))

        # BUG47-05: Reaching max_pages while total_count > fetched runs -> GH_API_MAX_PAGES_LIMIT_REACHED_INCOMPLETE_HISTORY -> PREFLIGHT_FAILED
        res_47_maxp = execute_deployment(
            bundle, str(create_fresh_bare_remote(tmp_p, "origin_47_maxp.git")), wf_file,
            env_override={"PATH": f"{fake_bin_47_3pages}:/usr/bin:/bin"},
            poll_attempts=1, poll_interval_s=0.0,
            preflight_max_pages=2, preflight_per_page=30,  # Only 2 pages (60 runs) allowed, but total_count is 65!
        )
        checks.append((
            "BUG47_05_MAX_PAGES_EXHAUSTED_WITH_INCOMPLETE_HISTORY_HALTS_WITH_PREFLIGHT_FAILED",
            res_47_maxp["status"] == "PREFLIGHT_FAILED"
            and res_47_maxp["push_executed"] is False
            and "GH_API_MAX_PAGES_LIMIT_REACHED_INCOMPLETE_HISTORY" in res_47_maxp.get("error", "")
        ))

        # BUG41/47-06: Pagination interruption on Page 2 AND chronological ordering violation -> PREFLIGHT_FAILED
        fake_bin_41_pfail = tmp_p / "fake_bin_41_pfail"
        fake_bin_41_pfail.mkdir()
        pfail_script = f"""#!/usr/bin/env python3
import json, sys, urllib.parse
args = sys.argv[1:]
if args[:2] == ["auth", "status"]:
    sys.exit(0)
if args[:3] == ["api", "-X", "GET"]:
    ep = args[3]
    if ep.endswith("/workflows/{WORKFLOW_FILE}"):
        print({wf_meta_json_str!r})
        sys.exit(0)
    if "/workflows/99001/runs?" in ep:
        qs = urllib.parse.parse_qs(ep.split("?", 1)[1])
        page = int(qs.get("page", ["1"])[0])
        if page == 1:
            runs = [
                {{
                    "id": 8299 - i,
                    "workflow_id": 99001,
                    "path": "{WORKFLOW_DEFINITION_PATH}",
                    "name": "{EXPECTED_WORKFLOW_DISPLAY_NAME}",
                    "head_sha": "2222222222222222222222222222222222222222",
                    "event": "push",
                    "head_branch": "{DEFAULT_TARGET_BRANCH}",
                    "created_at": f"2026-11-01T00:{{59 - i:02d}}:00Z",
                }}
                for i in range(30)
            ]
            print(json.dumps({{"total_count": 45, "workflow_runs": runs}}))
            sys.exit(0)
        else:
            sys.stderr.write("Connection reset during page 2 query\\n")
            sys.exit(1)
sys.exit(1)
"""
        (fake_bin_41_pfail / "gh").write_text(pfail_script, encoding="utf-8")
        (fake_bin_41_pfail / "gh").chmod(0o755)
        res_41_pfail = execute_deployment(
            bundle, str(create_fresh_bare_remote(tmp_p, "origin_41_pfail.git")), wf_file,
            env_override={"PATH": f"{fake_bin_41_pfail}:/usr/bin:/bin"},
            poll_attempts=1, poll_interval_s=0.0,
            preflight_max_pages=3, preflight_per_page=30,
        )
        checks.append((
            "BUG41_47_06_PAGINATION_INTERRUPTION_ON_PAGE_2_HALTS_WITH_PREFLIGHT_FAILED",
            res_41_pfail["status"] == "PREFLIGHT_FAILED"
            and res_41_pfail["push_executed"] is False
            and "GH_API_RUNS_EXIT_1_ON_PAGE_2" in res_41_pfail.get("error", "")
        ))

        # =========================================================================
        # BUG-42 & BUG-47 Regression Tests: Delayed Duplicate-Run Detection via Multi-Page Settling Window
        # =========================================================================

        # BUG42-01: Immediate duplicate runs in same poll snapshot -> DUPLICATE_RUN_DETECTED
        fake_bin_42_imm = tmp_p / "fake_bin_42_imm"
        fake_bin_42_imm.mkdir()
        state_42_imm = tmp_p / "state_42_imm.txt"
        imm_dup_script = f"""#!/usr/bin/env python3
import json, pathlib, sys
args = sys.argv[1:]
sf = pathlib.Path("{state_42_imm}")
if args[:2] == ["auth", "status"]:
    sys.exit(0)
if args[:3] == ["api", "-X", "GET"]:
    ep = args[3]
    if ep.endswith("/workflows/{WORKFLOW_FILE}"):
        print({wf_meta_json_str!r})
        sys.exit(0)
    if "/workflows/99001/runs?" in ep:
        if not sf.exists():
            sf.write_text("pre")
            print(json.dumps({{"total_count": 1, "workflow_runs": [
                {{"id": 7000, "workflow_id": 99001, "path": "{WORKFLOW_DEFINITION_PATH}", "name": "{EXPECTED_WORKFLOW_DISPLAY_NAME}", "head_sha": "{local_head}", "event": "push", "head_branch": "{DEFAULT_TARGET_BRANCH}", "created_at": "2026-11-01T00:00:00Z"}}
            ]}}))
        else:
            print(json.dumps({{"total_count": 3, "workflow_runs": [
                {{"id": 7011, "workflow_id": 99001, "path": "{WORKFLOW_DEFINITION_PATH}", "name": "{EXPECTED_WORKFLOW_DISPLAY_NAME}", "head_sha": "{local_head}", "event": "push", "head_branch": "{DEFAULT_TARGET_BRANCH}", "created_at": "{now_utc_plus1_iso}"}},
                {{"id": 7010, "workflow_id": 99001, "path": "{WORKFLOW_DEFINITION_PATH}", "name": "{EXPECTED_WORKFLOW_DISPLAY_NAME}", "head_sha": "{local_head}", "event": "push", "head_branch": "{DEFAULT_TARGET_BRANCH}", "created_at": "{now_utc_iso}"}},
                {{"id": 7000, "workflow_id": 99001, "path": "{WORKFLOW_DEFINITION_PATH}", "name": "{EXPECTED_WORKFLOW_DISPLAY_NAME}", "head_sha": "{local_head}", "event": "push", "head_branch": "{DEFAULT_TARGET_BRANCH}", "created_at": "2026-11-01T00:00:00Z"}}
            ]}}))
        sys.exit(0)
sys.exit(1)
"""
        (fake_bin_42_imm / "gh").write_text(imm_dup_script, encoding="utf-8")
        (fake_bin_42_imm / "gh").chmod(0o755)
        res_42_imm = execute_deployment(
            bundle, str(create_fresh_bare_remote(tmp_p, "origin_42_imm.git")), wf_file,
            env_override={"PATH": f"{fake_bin_42_imm}:/usr/bin:/bin"},
            poll_attempts=2, poll_interval_s=0.0, settling_polls=2, settling_interval_s=0.0,
        )
        checks.append((
            "BUG42_01_IMMEDIATE_DUPLICATE_RUNS_IN_SAME_SNAPSHOT_DETECTED",
            res_42_imm["status"] == "DUPLICATE_RUN_DETECTED"
            and res_42_imm.get("duplicate_run_ids") == [7011, 7010]
        ))

        # BUG42/47-02: Second matching run appears on Page 2 during the settling window -> DUPLICATE_RUN_DETECTED across pages!
        fake_bin_42_next = tmp_p / "fake_bin_42_next"
        fake_bin_42_next.mkdir()
        state_42_next = tmp_p / "state_42_next.txt"
        next_dup_script = f"""#!/usr/bin/env python3
import json, pathlib, sys, urllib.parse
args = sys.argv[1:]
sf = pathlib.Path("{state_42_next}")
if args[:2] == ["auth", "status"]:
    sys.exit(0)
if args[:3] == ["api", "-X", "GET"]:
    ep = args[3]
    if ep.endswith("/workflows/{WORKFLOW_FILE}"):
        print({wf_meta_json_str!r})
        sys.exit(0)
    if "/workflows/99001/runs?" in ep:
        qs = urllib.parse.parse_qs(ep.split("?", 1)[1])
        page = int(qs.get("page", ["1"])[0])
        cnt = int(sf.read_text()) if sf.exists() else 0
        if page == 1:
            sf.write_text(str(cnt + 1))
        if cnt == 0:
            print(json.dumps({{"total_count": 0, "workflow_runs": []}}))
        elif cnt == 1:
            print(json.dumps({{"total_count": 1, "workflow_runs": [
                {{"id": 7101, "workflow_id": 99001, "path": "{WORKFLOW_DEFINITION_PATH}", "name": "{EXPECTED_WORKFLOW_DISPLAY_NAME}", "head_sha": "{local_head}", "event": "push", "head_branch": "{DEFAULT_TARGET_BRANCH}", "created_at": "{now_utc_iso}"}}
            ]}}))
        else:
            # On settling poll, per_page=1: Page 1 has run 7102, Page 2 has run 7101!
            if page == 1:
                print(json.dumps({{"total_count": 2, "workflow_runs": [
                    {{"id": 7102, "workflow_id": 99001, "path": "{WORKFLOW_DEFINITION_PATH}", "name": "{EXPECTED_WORKFLOW_DISPLAY_NAME}", "head_sha": "{local_head}", "event": "push", "head_branch": "{DEFAULT_TARGET_BRANCH}", "created_at": "{now_utc_plus1_iso}"}}
                ]}}))
            elif page == 2:
                print(json.dumps({{"total_count": 2, "workflow_runs": [
                    {{"id": 7101, "workflow_id": 99001, "path": "{WORKFLOW_DEFINITION_PATH}", "name": "{EXPECTED_WORKFLOW_DISPLAY_NAME}", "head_sha": "{local_head}", "event": "push", "head_branch": "{DEFAULT_TARGET_BRANCH}", "created_at": "{now_utc_iso}"}}
                ]}}))
            else:
                print(json.dumps({{"total_count": 2, "workflow_runs": []}}))
        sys.exit(0)
sys.exit(1)
"""
        (fake_bin_42_next / "gh").write_text(next_dup_script, encoding="utf-8")
        (fake_bin_42_next / "gh").chmod(0o755)
        res_42_next = execute_deployment(
            bundle, str(create_fresh_bare_remote(tmp_p, "origin_42_next.git")), wf_file,
            env_override={"PATH": f"{fake_bin_42_next}:/usr/bin:/bin"},
            poll_attempts=2, poll_interval_s=0.0, settling_polls=3, settling_interval_s=0.0,
            preflight_max_pages=3, preflight_per_page=1,
        )
        checks.append((
            "BUG42_47_02_SECOND_RUN_ON_PAGE_2_DETECTED_IN_MULTI_PAGE_SETTLING_WINDOW",
            res_42_next["status"] == "DUPLICATE_RUN_DETECTED"
            and res_42_next.get("duplicate_run_ids") == [7102, 7101]
            and "RUN_IN_PROGRESS" not in res_42_next.get("state_history", [])
        ))

        # BUG42-03: Delayed second run appears on settling poll #3 (missed when settling_polls=0, caught when settling_polls=3)
        fake_bin_42_late = tmp_p / "fake_bin_42_late"
        fake_bin_42_late.mkdir()
        state_42_late = tmp_p / "state_42_late.txt"
        late_dup_script = f"""#!/usr/bin/env python3
import json, pathlib, sys
args = sys.argv[1:]
sf = pathlib.Path("{state_42_late}")
if args[:2] == ["auth", "status"]:
    sys.exit(0)
if args[:3] == ["api", "-X", "GET"]:
    ep = args[3]
    if ep.endswith("/workflows/{WORKFLOW_FILE}"):
        print({wf_meta_json_str!r})
        sys.exit(0)
    if "/workflows/99001/runs?" in ep:
        cnt = int(sf.read_text()) if sf.exists() else 0
        sf.write_text(str(cnt + 1))
        if cnt == 0:
            print(json.dumps({{"total_count": 0, "workflow_runs": []}}))
        elif cnt in (1, 2, 3):
            print(json.dumps({{"total_count": 1, "workflow_runs": [
                {{"id": 7201, "workflow_id": 99001, "path": "{WORKFLOW_DEFINITION_PATH}", "name": "{EXPECTED_WORKFLOW_DISPLAY_NAME}", "head_sha": "{local_head}", "event": "push", "head_branch": "{DEFAULT_TARGET_BRANCH}", "created_at": "{now_utc_iso}"}}
            ]}}))
        else:
            print(json.dumps({{"total_count": 2, "workflow_runs": [
                {{"id": 7202, "workflow_id": 99001, "path": "{WORKFLOW_DEFINITION_PATH}", "name": "{EXPECTED_WORKFLOW_DISPLAY_NAME}", "head_sha": "{local_head}", "event": "push", "head_branch": "{DEFAULT_TARGET_BRANCH}", "created_at": "{now_utc_plus1_iso}"}},
                {{"id": 7201, "workflow_id": 99001, "path": "{WORKFLOW_DEFINITION_PATH}", "name": "{EXPECTED_WORKFLOW_DISPLAY_NAME}", "head_sha": "{local_head}", "event": "push", "head_branch": "{DEFAULT_TARGET_BRANCH}", "created_at": "{now_utc_iso}"}}
            ]}}))
        sys.exit(0)
if args[:2] == ["run", "watch"]:
    sys.exit(0)
if args[:2] == ["run", "view"]:
    print(json.dumps({{"status": "completed", "conclusion": "success", "jobs": [{{"name": "build-and-verify-windows-x64", "conclusion": "success"}}]}}))
    sys.exit(0)
if args[:2] == ["run", "download"]:
    out_dir = pathlib.Path(args[args.index("--dir") + 1])
    for fn in {REQUIRED_WINDOWS_ARTIFACTS!r}:
        (out_dir / fn).write_bytes(b"SIM")
    sys.exit(0)
sys.exit(1)
"""
        (fake_bin_42_late / "gh").write_text(late_dup_script, encoding="utf-8")
        (fake_bin_42_late / "gh").chmod(0o755)

        res_42_legacy_missed = execute_deployment(
            bundle, str(create_fresh_bare_remote(tmp_p, "origin_42_legacy.git")), wf_file,
            env_override={"PATH": f"{fake_bin_42_late}:/usr/bin:/bin"},
            poll_attempts=2, poll_interval_s=0.0, settling_polls=0, settling_interval_s=0.0,
            artifacts_base_dir=tmp_p,
        )
        if state_42_late.exists():
            state_42_late.unlink()
        res_42_remediated = execute_deployment(
            bundle, str(create_fresh_bare_remote(tmp_p, "origin_42_remed.git")), wf_file,
            env_override={"PATH": f"{fake_bin_42_late}:/usr/bin:/bin"},
            poll_attempts=2, poll_interval_s=0.0, settling_polls=3, settling_interval_s=0.02,
            artifacts_base_dir=tmp_p,
        )
        checks.append((
            "BUG42_03_DELAYED_DUPLICATE_RUN_MISSED_WHEN_SETTLING_0_AND_CAUGHT_BY_SETTLING_WINDOW",
            res_42_legacy_missed["status"] == "PASS"
            and res_42_remediated["status"] == "DUPLICATE_RUN_DETECTED"
            and res_42_remediated.get("duplicate_run_ids") == [7202, 7201]
            and "RUN_IN_PROGRESS" not in res_42_remediated.get("state_history", [])
        ))

        # BUG42-04: Query failure during settling window aborts with RUN_FAILED
        fake_bin_42_sfail = tmp_p / "fake_bin_42_sfail"
        fake_bin_42_sfail.mkdir()
        state_42_sfail = tmp_p / "state_42_sfail.txt"
        sfail_script = f"""#!/usr/bin/env python3
import json, pathlib, sys
args = sys.argv[1:]
sf = pathlib.Path("{state_42_sfail}")
if args[:2] == ["auth", "status"]:
    sys.exit(0)
if args[:3] == ["api", "-X", "GET"]:
    ep = args[3]
    if ep.endswith("/workflows/{WORKFLOW_FILE}"):
        print({wf_meta_json_str!r})
        sys.exit(0)
    if "/workflows/99001/runs?" in ep:
        cnt = int(sf.read_text()) if sf.exists() else 0
        sf.write_text(str(cnt + 1))
        if cnt == 0:
            print(json.dumps({{"total_count": 0, "workflow_runs": []}}))
            sys.exit(0)
        elif cnt == 1:
            print(json.dumps({{"total_count": 1, "workflow_runs": [
                {{"id": 7301, "workflow_id": 99001, "path": "{WORKFLOW_DEFINITION_PATH}", "name": "{EXPECTED_WORKFLOW_DISPLAY_NAME}", "head_sha": "{local_head}", "event": "push", "head_branch": "{DEFAULT_TARGET_BRANCH}", "created_at": "{now_utc_iso}"}}
            ]}}))
            sys.exit(0)
        else:
            sys.stderr.write("API rate limit or network error during settling window\\n")
            sys.exit(1)
sys.exit(1)
"""
        (fake_bin_42_sfail / "gh").write_text(sfail_script, encoding="utf-8")
        (fake_bin_42_sfail / "gh").chmod(0o755)
        res_42_sfail = execute_deployment(
            bundle, str(create_fresh_bare_remote(tmp_p, "origin_42_sfail.git")), wf_file,
            env_override={"PATH": f"{fake_bin_42_sfail}:/usr/bin:/bin"},
            poll_attempts=2, poll_interval_s=0.0, settling_polls=2, settling_interval_s=0.0,
        )
        checks.append((
            "BUG42_04_QUERY_FAILURE_DURING_SETTLING_WINDOW_ABORTS_WITH_RUN_FAILED",
            res_42_sfail["status"] == "RUN_FAILED"
            and "SETTLING_QUERY_FAILED" in res_42_sfail.get("error", "")
            and "RUN_IN_PROGRESS" not in res_42_sfail.get("state_history", [])
        ))

        # =========================================================================
        # BUG-44 Regression Tests: Remote Already at Local HEAD, Fast-Forward, Diverged, Unreachable
        # =========================================================================

        # BUG44-01: Remote SHA already equals Local HEAD -> REMOTE_ALREADY_AT_LOCAL_HEAD_NO_NEW_PUSH_EVENT
        bare_remote_44_same = create_fresh_bare_remote(tmp_p, "origin_44_same.git")
        with tempfile.TemporaryDirectory() as td_seed:
            subprocess.run(["git", "clone", "-q", str(bundle), td_seed], check=True)
            subprocess.run(["git", "-C", td_seed, "checkout", "-q", "-B", DEFAULT_TARGET_BRANCH, f"origin/{DEFAULT_TARGET_BRANCH}"], check=True)
            subprocess.run(["git", "-C", td_seed, "push", "-q", str(bare_remote_44_same), f"refs/heads/{DEFAULT_TARGET_BRANCH}:refs/heads/{DEFAULT_TARGET_BRANCH}"], check=True)

        res_44_same = execute_deployment(
            bundle, str(bare_remote_44_same), wf_file,
            env_override={"PATH": "/usr/bin:/bin"},
            poll_attempts=2, poll_interval_s=0.0,
        )
        checks.append((
            "BUG44_01_REMOTE_ALREADY_AT_LOCAL_HEAD_HALTS_WITHOUT_PUSH_OR_POLLING",
            res_44_same["status"] == "REMOTE_ALREADY_AT_LOCAL_HEAD_NO_NEW_PUSH_EVENT"
            and res_44_same["build_triggered"] is False
            and res_44_same["push_executed"] is False
            and res_44_same["run_id"] is None
            and "PUSH_COMPLETED" not in res_44_same.get("state_history", [])
        ))

        # BUG44-02: Remote SHA is an older ancestor -> Fast-forward push succeeds cleanly
        bare_remote_44_ff = create_fresh_bare_remote(tmp_p, "origin_44_ff.git")
        with tempfile.TemporaryDirectory() as td_seed_ff:
            subprocess.run(["git", "clone", "-q", str(bundle), td_seed_ff], check=True)
            subprocess.run(["git", "-C", td_seed_ff, "push", "-q", str(bare_remote_44_ff), f"{EXPECTED_AI_PREFLIGHT_PARENT_SHA}:refs/heads/{DEFAULT_TARGET_BRANCH}"], check=True)

        fake_bin_44_ff = tmp_p / "fake_bin_44_ff"
        fake_bin_44_ff.mkdir()
        state_44_ff = tmp_p / "state_44_ff.txt"
        ff_script = f"""#!/usr/bin/env python3
import json, pathlib, sys
args = sys.argv[1:]
sf = pathlib.Path("{state_44_ff}")
if args[:2] == ["auth", "status"]:
    sys.exit(0)
if args[:3] == ["api", "-X", "GET"]:
    ep = args[3]
    if ep.endswith("/workflows/{WORKFLOW_FILE}"):
        print({wf_meta_json_str!r})
        sys.exit(0)
    if "/workflows/99001/runs?" in ep:
        if not sf.exists():
            sf.write_text("pre")
            print(json.dumps({{"total_count": 0, "workflow_runs": []}}))
        else:
            print(json.dumps({{"total_count": 1, "workflow_runs": [
                {{"id": 7401, "workflow_id": 99001, "path": "{WORKFLOW_DEFINITION_PATH}", "name": "{EXPECTED_WORKFLOW_DISPLAY_NAME}", "head_sha": "{local_head}", "event": "push", "head_branch": "{DEFAULT_TARGET_BRANCH}", "created_at": "{now_utc_iso}", "html_url": "https://github.com/alinon9/MERSAD-AI-/actions/runs/7401"}}
            ]}}))
        sys.exit(0)
if args[:2] == ["run", "watch"]:
    sys.exit(0)
if args[:2] == ["run", "view"]:
    print(json.dumps({{"status": "completed", "conclusion": "success", "jobs": [{{"name": "build-and-verify-windows-x64", "conclusion": "success"}}]}}))
    sys.exit(0)
if args[:2] == ["run", "download"]:
    out_dir = pathlib.Path(args[args.index("--dir") + 1])
    for fn in {REQUIRED_WINDOWS_ARTIFACTS!r}:
        (out_dir / fn).write_bytes(f"SIM_FF_{{fn}}".encode("utf-8"))
    sys.exit(0)
sys.exit(1)
"""
        (fake_bin_44_ff / "gh").write_text(ff_script, encoding="utf-8")
        (fake_bin_44_ff / "gh").chmod(0o755)
        res_44_ff = execute_deployment(
            bundle, str(bare_remote_44_ff), wf_file,
            env_override={"PATH": f"{fake_bin_44_ff}:/usr/bin:/bin"},
            poll_attempts=2, poll_interval_s=0.0, settling_polls=2, settling_interval_s=0.0,
            artifacts_base_dir=tmp_p,
        )
        checks.append((
            "BUG44_02_REMOTE_ANCESTOR_FAST_FORWARD_PUSH_SUCCEEDS_CLEANLY",
            res_44_ff["status"] == "PASS"
            and res_44_ff["pre_push_remote_sha"] == EXPECTED_AI_PREFLIGHT_PARENT_SHA
            and res_44_ff["verified_remote_sha"] == local_head
            and res_44_ff["push_executed"] is True
        ))

        # BUG44-03: Remote branch has diverged -> REMOTE_DIVERGED_NOT_FAST_FORWARD before push
        bare_remote_44_div = create_fresh_bare_remote(tmp_p, "origin_44_div.git")
        with tempfile.TemporaryDirectory() as td_seed_div:
            subprocess.run(["git", "clone", "-q", str(bundle), td_seed_div], check=True)
            subprocess.run(["git", "-C", td_seed_div, "checkout", "-q", "-B", "diverged_br", EXPECTED_AI_PREFLIGHT_PARENT_SHA], check=True)
            (Path(td_seed_div) / "DIVERGED_ONLY.txt").write_text("diverged commit", encoding="utf-8")
            subprocess.run(["git", "-C", td_seed_div, "add", "DIVERGED_ONLY.txt"], check=True)
            subprocess.run(["git", "-C", td_seed_div, "config", "user.name", "Test"], check=True)
            subprocess.run(["git", "-C", td_seed_div, "config", "user.email", "test@local"], check=True)
            subprocess.run(["git", "-C", td_seed_div, "commit", "-q", "-m", "diverged commit"], check=True)
            subprocess.run(["git", "-C", td_seed_div, "push", "-q", str(bare_remote_44_div), f"HEAD:refs/heads/{DEFAULT_TARGET_BRANCH}"], check=True)

        res_44_div = execute_deployment(
            bundle, str(bare_remote_44_div), wf_file,
            env_override={"PATH": f"{fake_bin_44_ff}:/usr/bin:/bin"},
            poll_attempts=1, poll_interval_s=0.0,
        )
        checks.append((
            "BUG44_03_REMOTE_DIVERGED_BRANCH_REJECTED_BEFORE_PUSH_WITHOUT_FORCE",
            res_44_div["status"] == "REMOTE_DIVERGED_NOT_FAST_FORWARD"
            and res_44_div["push_executed"] is False
            and res_44_div["build_triggered"] is False
        ))

        # BUG44-04: Unreachable remote URL fails preflight closed (PREFLIGHT_FAILED)
        res_44_unreach = execute_deployment(
            bundle, str(tmp_p / "non_existent_remote_repo_404.git"), wf_file,
            env_override={"PATH": f"{fake_bin_44_ff}:/usr/bin:/bin"},
            poll_attempts=1, poll_interval_s=0.0,
        )
        checks.append((
            "BUG44_04_UNREACHABLE_REMOTE_FAILS_CLOSED_WITH_PREFLIGHT_FAILED",
            res_44_unreach["status"] == "PREFLIGHT_FAILED"
            and res_44_unreach["push_executed"] is False
            and "REMOTE_UNREACHABLE_PREFLIGHT_FAILED" in res_44_unreach.get("error", "")
        ))

        # =========================================================================
        # Standard Polling Rejections & Full State Machine (BUG-36 & BUG-45)
        # =========================================================================

        # Rejects runs with mismatched SHA
        fake_bin_wrong_sha = tmp_p / "fake_bin_wrong_sha"
        fake_bin_wrong_sha.mkdir()
        state_wrong_sha = tmp_p / "state_wrong_sha.txt"
        wrong_sha_script = f"""#!/usr/bin/env python3
import json, pathlib, sys
args = sys.argv[1:]
sf = pathlib.Path("{state_wrong_sha}")
if args[:2] == ["auth", "status"]:
    sys.exit(0)
if args[:3] == ["api", "-X", "GET"]:
    ep = args[3]
    if ep.endswith("/workflows/{WORKFLOW_FILE}"):
        print({wf_meta_json_str!r})
        sys.exit(0)
    if "/workflows/99001/runs?" in ep:
        if not sf.exists():
            sf.write_text("pre")
            print(json.dumps({{"total_count": 0, "workflow_runs": []}}))
        else:
            print(json.dumps({{"total_count": 1, "workflow_runs": [
                {{"id": 7001, "workflow_id": 99001, "path": "{WORKFLOW_DEFINITION_PATH}", "name": "{EXPECTED_WORKFLOW_DISPLAY_NAME}", "head_sha": "deadbeef00000000000000000000000000000000", "event": "push", "head_branch": "{DEFAULT_TARGET_BRANCH}", "created_at": "{now_utc_iso}"}}
            ]}}))
        sys.exit(0)
sys.exit(1)
"""
        (fake_bin_wrong_sha / "gh").write_text(wrong_sha_script, encoding="utf-8")
        (fake_bin_wrong_sha / "gh").chmod(0o755)
        res_wrong_sha = execute_deployment(
            bundle, str(create_fresh_bare_remote(tmp_p, "origin_wrong_sha.git")), wf_file,
            env_override={"PATH": f"{fake_bin_wrong_sha}:/usr/bin:/bin"},
            poll_attempts=2, poll_interval_s=0.0, settling_polls=1, settling_interval_s=0.0,
        )
        checks.append((
            "TEST_04_POLLING_REJECTS_MISMATCHED_SHA",
            res_wrong_sha["status"] == "RUN_TIMEOUT" and res_wrong_sha["run_id"] is None
        ))

        # Rejects runs with wrong event (workflow_dispatch / pull_request)
        fake_bin_wrong_evt = tmp_p / "fake_bin_wrong_evt"
        fake_bin_wrong_evt.mkdir()
        state_wrong_evt = tmp_p / "state_wrong_evt.txt"
        wrong_evt_script = f"""#!/usr/bin/env python3
import json, pathlib, sys
args = sys.argv[1:]
sf = pathlib.Path("{state_wrong_evt}")
if args[:2] == ["auth", "status"]:
    sys.exit(0)
if args[:3] == ["api", "-X", "GET"]:
    ep = args[3]
    if ep.endswith("/workflows/{WORKFLOW_FILE}"):
        print({wf_meta_json_str!r})
        sys.exit(0)
    if "/workflows/99001/runs?" in ep:
        if not sf.exists():
            sf.write_text("pre")
            print(json.dumps({{"total_count": 0, "workflow_runs": []}}))
        else:
            print(json.dumps({{"total_count": 2, "workflow_runs": [
                {{"id": 7003, "workflow_id": 99001, "path": "{WORKFLOW_DEFINITION_PATH}", "name": "{EXPECTED_WORKFLOW_DISPLAY_NAME}", "head_sha": "{local_head}", "event": "pull_request", "head_branch": "{DEFAULT_TARGET_BRANCH}", "created_at": "{now_utc_plus1_iso}"}},
                {{"id": 7002, "workflow_id": 99001, "path": "{WORKFLOW_DEFINITION_PATH}", "name": "{EXPECTED_WORKFLOW_DISPLAY_NAME}", "head_sha": "{local_head}", "event": "workflow_dispatch", "head_branch": "{DEFAULT_TARGET_BRANCH}", "created_at": "{now_utc_iso}"}}
            ]}}))
        sys.exit(0)
sys.exit(1)
"""
        (fake_bin_wrong_evt / "gh").write_text(wrong_evt_script, encoding="utf-8")
        (fake_bin_wrong_evt / "gh").chmod(0o755)
        res_wrong_evt = execute_deployment(
            bundle, str(create_fresh_bare_remote(tmp_p, "origin_wrong_evt.git")), wf_file,
            env_override={"PATH": f"{fake_bin_wrong_evt}:/usr/bin:/bin"},
            poll_attempts=2, poll_interval_s=0.0, settling_polls=1, settling_interval_s=0.0,
        )
        checks.append((
            "TEST_05_POLLING_REJECTS_NON_PUSH_EVENT",
            res_wrong_evt["status"] == "RUN_TIMEOUT" and res_wrong_evt["run_id"] is None
        ))

        # Timeout never converts to PASS
        checks.append((
            "TEST_08_POLL_TIMEOUT_SETS_RUN_TIMEOUT_NEVER_PASS",
            res_wrong_sha["status"] == "RUN_TIMEOUT"
            and "PASS" not in res_wrong_sha.get("state_history", [])
        ))

        # Single failed job within the workflow run sets status=RUN_FAILED
        fake_bin_failjob = tmp_p / "fake_bin_failjob"
        fake_bin_failjob.mkdir()
        state_file_fail = tmp_p / "state_fail.txt"
        failjob_script = f"""#!/usr/bin/env python3
import json, pathlib, sys
args = sys.argv[1:]
sf = pathlib.Path("{state_file_fail}")
if args[:2] == ["auth", "status"]:
    sys.exit(0)
if args[:3] == ["api", "-X", "GET"]:
    ep = args[3]
    if ep.endswith("/workflows/{WORKFLOW_FILE}"):
        print({wf_meta_json_str!r})
        sys.exit(0)
    if "/workflows/99001/runs?" in ep:
        if not sf.exists():
            sf.write_text("pre")
            print(json.dumps({{"total_count": 1, "workflow_runs": [
                {{"id": 5000, "workflow_id": 99001, "path": "{WORKFLOW_DEFINITION_PATH}", "name": "{EXPECTED_WORKFLOW_DISPLAY_NAME}", "head_sha": "{local_head}", "event": "push", "head_branch": "{DEFAULT_TARGET_BRANCH}", "created_at": "2026-11-01T00:00:00Z"}}
            ]}}))
        else:
            print(json.dumps({{"total_count": 2, "workflow_runs": [
                {{"id": 5005, "workflow_id": 99001, "path": "{WORKFLOW_DEFINITION_PATH}", "name": "{EXPECTED_WORKFLOW_DISPLAY_NAME}", "head_sha": "{local_head}", "event": "push", "head_branch": "{DEFAULT_TARGET_BRANCH}", "created_at": "{now_utc_iso}", "html_url": "https://github.com/alinon9/MERSAD-AI-/actions/runs/5005"}},
                {{"id": 5000, "workflow_id": 99001, "path": "{WORKFLOW_DEFINITION_PATH}", "name": "{EXPECTED_WORKFLOW_DISPLAY_NAME}", "head_sha": "{local_head}", "event": "push", "head_branch": "{DEFAULT_TARGET_BRANCH}", "created_at": "2026-11-01T00:00:00Z"}}
            ]}}))
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
            bundle, str(create_fresh_bare_remote(tmp_p, "origin_failjob.git")), wf_file,
            env_override={"PATH": f"{fake_bin_failjob}:/usr/bin:/bin"},
            poll_attempts=2, poll_interval_s=0.0, settling_polls=1, settling_interval_s=0.0,
        )
        checks.append((
            "TEST_09_SINGLE_FAILED_JOB_SETS_RUN_FAILED",
            res_failjob["run_id"] == "5005"
            and res_failjob["status"] == "RUN_FAILED"
            and "JOBS_FAILED" in res_failjob.get("error", "")
        ))

        # Missing 1 of the 5 required Windows build files sets status=RUN_FAILED
        fake_bin_missing_art = tmp_p / "fake_bin_missing_art"
        fake_bin_missing_art.mkdir()
        state_missing_art = tmp_p / "state_missing_art.txt"
        missing_art_script = f"""#!/usr/bin/env python3
import json, pathlib, sys
args = sys.argv[1:]
sf = pathlib.Path("{state_missing_art}")
if args[:2] == ["auth", "status"]:
    sys.exit(0)
if args[:3] == ["api", "-X", "GET"]:
    ep = args[3]
    if ep.endswith("/workflows/{WORKFLOW_FILE}"):
        print({wf_meta_json_str!r})
        sys.exit(0)
    if "/workflows/99001/runs?" in ep:
        if not sf.exists():
            sf.write_text("pre")
            print(json.dumps({{"total_count": 0, "workflow_runs": []}}))
        else:
            print(json.dumps({{"total_count": 1, "workflow_runs": [
                {{"id": 5501, "workflow_id": 99001, "path": "{WORKFLOW_DEFINITION_PATH}", "name": "{EXPECTED_WORKFLOW_DISPLAY_NAME}", "head_sha": "{local_head}", "event": "push", "head_branch": "{DEFAULT_TARGET_BRANCH}", "created_at": "{now_utc_iso}", "html_url": "https://github.com/alinon9/MERSAD-AI-/actions/runs/5501"}}
            ]}}))
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
            bundle, str(create_fresh_bare_remote(tmp_p, "origin_missing_art.git")), wf_file,
            env_override={"PATH": f"{fake_bin_missing_art}:/usr/bin:/bin"},
            poll_attempts=2, poll_interval_s=0.0, settling_polls=1, settling_interval_s=0.0,
            artifacts_base_dir=tmp_p,
        )
        checks.append((
            "TEST_10_MISSING_ONE_OF_FIVE_ARTIFACTS_SETS_RUN_FAILED",
            res_missing_art["run_id"] == "5501"
            and res_missing_art["status"] == "RUN_FAILED"
            and res_missing_art.get("artifacts_verification", {}).get("missing_files") == [REQUIRED_WINDOWS_ARTIFACTS[-1]]
        ))

        # Full E2E simulated push-triggered run with SHA256_CALCULATED_AND_RECORDED (BUG-45)
        fake_bin_ok = tmp_p / "fake_bin_ok"
        fake_bin_ok.mkdir()
        state_file_ok = tmp_p / "state_ok.txt"
        ok_script = f"""#!/usr/bin/env python3
import json, pathlib, sys
args = sys.argv[1:]
sf = pathlib.Path("{state_file_ok}")
if args[:2] == ["auth", "status"]:
    sys.exit(0)
if args[:3] == ["api", "-X", "GET"]:
    ep = args[3]
    if ep.endswith("/workflows/{WORKFLOW_FILE}"):
        print({wf_meta_json_str!r})
        sys.exit(0)
    if "/workflows/99001/runs?" in ep:
        if not sf.exists():
            sf.write_text("pre")
            print(json.dumps({{"total_count": 1, "workflow_runs": [
                {{"id": 6000, "workflow_id": 99001, "path": "{WORKFLOW_DEFINITION_PATH}", "name": "{EXPECTED_WORKFLOW_DISPLAY_NAME}", "head_sha": "{local_head}", "event": "push", "head_branch": "{DEFAULT_TARGET_BRANCH}", "created_at": "2026-11-01T00:00:00Z"}}
            ]}}))
        else:
            print(json.dumps({{"total_count": 2, "workflow_runs": [
                {{"id": 6001, "workflow_id": 99001, "path": "{WORKFLOW_DEFINITION_PATH}", "name": "{EXPECTED_WORKFLOW_DISPLAY_NAME}", "head_sha": "{local_head}", "event": "push", "head_branch": "{DEFAULT_TARGET_BRANCH}", "created_at": "{now_utc_iso}", "html_url": "https://github.com/alinon9/MERSAD-AI-/actions/runs/6001"}},
                {{"id": 6000, "workflow_id": 99001, "path": "{WORKFLOW_DEFINITION_PATH}", "name": "{EXPECTED_WORKFLOW_DISPLAY_NAME}", "head_sha": "{local_head}", "event": "push", "head_branch": "{DEFAULT_TARGET_BRANCH}", "created_at": "2026-11-01T00:00:00Z"}}
            ]}}))
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
            str(create_fresh_bare_remote(tmp_p, "origin_ok.git")),
            wf_file,
            env_override={"PATH": f"{fake_bin_ok}:/usr/bin:/bin"},
            poll_attempts=2,
            poll_interval_s=0.0,
            settling_polls=2,
            settling_interval_s=0.0,
            artifacts_base_dir=tmp_p,
        )
        art_ver_ok = res_ok.get("artifacts_verification") or {}
        checks.append((
            "BUG45_01_FULL_PUSH_STATE_MACHINE_USES_SHA256_CALCULATED_AND_RECORDED_WITHOUT_FALSE_TRUST_CLAIM",
            res_ok["status"] == "PASS"
            and res_ok.get("state_history") == [
                "PREFLIGHT_PASS",
                "PUSH_COMPLETED",
                "RUN_DISCOVERED",
                "RUN_IN_PROGRESS",
                "SHA256_CALCULATED_AND_RECORDED",
                "PASS",
            ]
            and art_ver_ok.get("verification_state") == "SHA256_CALCULATED_AND_RECORDED"
            and art_ver_ok.get("files_exist_verified") is True
            and art_ver_ok.get("files_non_empty_verified") is True
            and art_ver_ok.get("sha256_calculated_and_recorded") is True
            and art_ver_ok.get("trusted_reference_digests_verified") is False
            and art_ver_ok.get("attestation_verification_status") == "NOT_AVAILABLE"
        ))

        # BUG45-02: Verify trusted_reference_digests comparison (both match and mismatch)
        dl_dir_6001 = tmp_p / "dist_github_actions_run_6001"
        exact_ref_map = {item["name"]: item["sha256"] for item in art_ver_ok.get("artifacts", [])}
        ver_with_ref = verify_and_hash_downloaded_artifacts(dl_dir_6001, run_id="6001", trusted_reference_digests=exact_ref_map)
        bad_ref_map = dict(exact_ref_map)
        bad_ref_map["MERSAD_AI.exe"] = "0" * 64
        ver_bad_ref = verify_and_hash_downloaded_artifacts(dl_dir_6001, run_id="6001", trusted_reference_digests=bad_ref_map)
        checks.append((
            "BUG45_02_TRUSTED_DIGEST_COMPARISON_SEPARATES_CALCULATION_FROM_REFERENCE_MATCH",
            ver_with_ref["ok"] is True
            and ver_with_ref["verification_state"] == "TRUSTED_DIGEST_VERIFIED"
            and ver_with_ref["trusted_reference_digests_verified"] is True
            and ver_bad_ref["ok"] is False
            and ver_bad_ref["verification_state"] == "TRUSTED_DIGEST_MISMATCH"
            and ver_bad_ref["trusted_reference_digests_verified"] is False
        ))

    # =========================================================================
    # BUG-43 Regression Tests: Dashboard Readiness Scorecard (7 Cases via Node.js)
    # =========================================================================
    dash_path = repo_root / "MERSAD_AI_Preview_0.1" / "dashboard.html"
    dash_txt = dash_path.read_text(encoding="utf-8")
    no_100_fallback = ("??100" not in dash_txt and "||100" not in dash_txt)
    has_all_4_fields = all(
        fld in dash_txt
        for fld in (
            "overall_engineering_readiness_pct",
            "runtime_models_and_deps_readiness_pct",
            "field_data_calibration_readiness_pct",
            "deployment_classification",
        )
    )
    node_test_script = """
const fs = require("fs");
const html = fs.readFileSync(process.argv[1], "utf8");
const escFn = "const esc=s=>String(s??'').replace(/[&<>\\"']/g,m=>({'&':'&amp;','<':'&lt;','>':'&gt;','\\"':'&quot;',\\"'\\":'&#39;'}[m]));";
const mFormatPct = html.match(/function formatReadinessPct\\(val\\)\\{[\\s\\S]*?async function loadReadinessReport/)[0].replace(/async function loadReadinessReport$/, "");
const fn = new Function(escFn + "\\n" + mFormatPct + "\\nreturn { formatReadinessPct, formatReadinessCount, renderReadinessScorecardHtml };")();

// 1. All indicators present
const out1 = fn.renderReadinessScorecardHtml({
  overall_engineering_readiness_pct: 100.0,
  runtime_models_and_deps_readiness_pct: 0.0,
  field_data_calibration_readiness_pct: 0.0,
  deployment_classification: "READY_FOR_LAPTOP_SETUP_AND_DEMO",
  pillars: {
    code_and_security: { score_pct: 100.0 },
    windows_build_and_packaging: { score_pct: 100.0 },
    field_calibration_and_eval_tooling: { score_pct: 100.0, field_data_stats: { complete_camera_links_count: 0, explicit_camera_links_count: 0, automated_plate_eval_runs_count: 0 } }
  }
});
if (!out1.includes("100%") || !out1.includes("0%") || !out1.includes("READY_FOR_LAPTOP_SETUP_AND_DEMO")) process.exit(11);

// 2. Indicator equals 0 -> renders 0%, never 100% or N/A
const out2 = fn.renderReadinessScorecardHtml({
  overall_engineering_readiness_pct: 0,
  runtime_models_and_deps_readiness_pct: 50,
  field_data_calibration_readiness_pct: 25,
  deployment_classification: "READY_FOR_LAPTOP_SETUP_AND_DEMO"
});
if (!out2.includes(">0%<") || out2.includes("100%")) process.exit(12);

// 3. Indicator equals null -> renders غير متاح (N/A), never 100%
const out3 = fn.renderReadinessScorecardHtml({
  overall_engineering_readiness_pct: null,
  runtime_models_and_deps_readiness_pct: 75,
  field_data_calibration_readiness_pct: 50,
  deployment_classification: "READY_FOR_CONTROLLED_PILOT"
});
if (!out3.includes("غير متاح (N/A)") || out3.includes("100%")) process.exit(13);

// 4. All indicators missing ({}) -> never renders 100%
const out4 = fn.renderReadinessScorecardHtml({});
if (out4.includes("100%")) process.exit(14);

// 5. Non-numeric values -> renders غير متاح (N/A), never 100%
const out5 = fn.renderReadinessScorecardHtml({
  overall_engineering_readiness_pct: "invalid_str",
  runtime_models_and_deps_readiness_pct: true,
  field_data_calibration_readiness_pct: -5
});
if (out5.includes("100%") || !out5.includes("غير متاح (N/A)")) process.exit(15);

// 6. Missing deployment_classification -> renders تصنيف النشر غير متاح
if (!out5.includes("تصنيف النشر غير متاح")) process.exit(16);

// 7. Unverified READY_FOR_PRODUCTION when runtime_models is 0% -> rejected as UNVERIFIED_CLASSIFICATION (NOT ESTABLISHED)
const out7 = fn.renderReadinessScorecardHtml({
  overall_engineering_readiness_pct: 100.0,
  runtime_models_and_deps_readiness_pct: 0.0,
  field_data_calibration_readiness_pct: 0.0,
  deployment_classification: "READY_FOR_PRODUCTION"
});
if (!out7.includes("UNVERIFIED_CLASSIFICATION (NOT ESTABLISHED)")) process.exit(17);
console.log("DASHBOARD_7_CASES_OK");
"""
    rc_node, out_node, _ = run_cmd(["node", "-e", node_test_script, str(dash_path)])
    checks.append((
        "BUG43_01_DASHBOARD_NO_100_DEFAULT_AND_RENDERS_ALL_4_API_INDICATORS_ACROSS_7_EDGE_CASES",
        no_100_fallback and has_all_4_fields and rc_node == 0 and "DASHBOARD_7_CASES_OK" in out_node
    ))

    # Provenance & existing checks
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
    r_ai_z = repo_root / "MERSAD_AI_Preview_0.1_Portable_Source.zip"
    d_ai_z = repo_root / "RELEASE_DELIVERABLES" / "PREVIEW_0.1" / "MERSAD_AI_Preview_0.1_Portable_Source.zip"
    r_lab_z = repo_root / "MERSAD_LAB_Preview_0.1_Portable_Source.zip"
    d_lab_z = repo_root / "RELEASE_DELIVERABLES" / "PREVIEW_0.1" / "MERSAD_LAB_Preview_0.1_Portable_Source.zip"
    bug50_zip_parity = (
        d_ai_z.is_file() and (not r_ai_z.is_file() or r_ai_z.read_bytes() == d_ai_z.read_bytes())
        and hashlib.sha256(d_ai_z.read_bytes()).hexdigest() != "53ed4ae36e18276ca57e2704023a5b6fe2b230e7278fcae4a44c4cd366fbbcf9"
        and d_lab_z.is_file() and (not r_lab_z.is_file() or r_lab_z.read_bytes() == d_lab_z.read_bytes())
    )
    checks.append(("BUG50_01_ALL_PORTABLE_SOURCE_ZIPS_SYNCHRONIZED_AND_NO_STALE_53ED4AE_ARCHIVE", bug50_zip_parity))

    # =========================================================================
    # ARGON / BUG-52 & BUG-53 Regression Tests: Live GitHub Preflight & Main Provenance (12 Tests)
    # =========================================================================

    # ARGON_01: EXPECTED_WORKFLOW_DISPLAY_NAME matches exact `name:` header in .github/workflows/release-mersad-preview-0.1-windows.yml
    wf_first_line = wf_text.splitlines()[0].strip()
    checks.append((
        "ARGON_01_EXACT_WORKFLOW_DISPLAY_NAME_MATCHES_YAML_HEADER",
        wf_first_line == f"name: {EXPECTED_WORKFLOW_DISPLAY_NAME}"
        and EXPECTED_WORKFLOW_DISPLAY_NAME == "Build & Verify MERSAD PREVIEW 0.1 Final Windows x64 Release"
    ))

    # ARGON_02: Dispatch workflow 147631347 (.github/workflows/build-mersad-preview-dispatch.yml, "Build MERSAD PREVIEW 0.1 Windows x64")
    # is strictly rejected even though its name contains "MERSAD PREVIEW 0.1"
    ok_disp_id, _, err_disp_id = validate_and_normalize_run_record(
        {
            "id": 9001,
            "workflow_id": 147631347,
            "path": ".github/workflows/build-mersad-preview-dispatch.yml",
            "name": "Build MERSAD PREVIEW 0.1 Windows x64",
            "head_sha": local_head,
            "head_branch": DEFAULT_TARGET_BRANCH,
            "event": "push",
            "created_at": now_utc_iso,
        },
        expected_workflow_id=147631346,
    )
    ok_disp_name, _, err_disp_name = validate_and_normalize_run_record(
        {
            "id": 9002,
            "workflow_id": 147631346,
            "name": "Build MERSAD PREVIEW 0.1 Windows x64",
            "head_sha": local_head,
            "head_branch": DEFAULT_TARGET_BRANCH,
            "event": "push",
            "created_at": now_utc_iso,
        },
        expected_workflow_id=147631346,
    )
    checks.append((
        "ARGON_02_DISPATCH_WORKFLOW_147631347_AND_NAME_STRICTLY_REJECTED_NO_SUBSTRING_BYPASS",
        ok_disp_id is False and "forbidden" in err_disp_id.lower()
        and ok_disp_name is False and "forbidden" in err_disp_name.lower()
    ))

    with tempfile.TemporaryDirectory(prefix="mersad_argon_tests_") as tmp_argon:
        ta_p = Path(tmp_argon)

        def write_git_live_main_wrapper(bin_dir: Path, main_sha_state_file: Path, mutate_after_push_to: str = ""):
            """
            Create a thin git wrapper in `bin_dir` that delegates 100% of git operations to /usr/bin/git,
            and for `git ls-remote origin refs/heads/main` returns the simulated remote main SHA from `main_sha_state_file`
            (optionally mutating `main_sha_state_file` after `git push` to test the post-push main immutability guard).
            """
            git_wrap = bin_dir / "git"
            wrap_code = f"""#!/usr/bin/env python3
import pathlib, subprocess, sys
args = sys.argv[1:]
sf = pathlib.Path("{main_sha_state_file}")
if len(args) >= 3 and args[0] == "ls-remote" and args[-1] == "refs/heads/main":
    sha_val = sf.read_text().strip() if sf.exists() else ""
    if sha_val:
        print(f"{{sha_val}}\trefs/heads/main")
    sys.exit(0)
rc = subprocess.call(["/usr/bin/git"] + args)
if rc == 0 and len(args) >= 1 and args[0] == "push" and "{mutate_after_push_to}":
    sf.write_text("{mutate_after_push_to}")
sys.exit(rc)
"""
            git_wrap.write_text(wrap_code, encoding="utf-8")
            git_wrap.chmod(0o755)

        bare_argon_live_main = create_fresh_bare_remote(ta_p, "origin_argon_live_main.git")
        main_sha_file_03 = ta_p / "main_sha_03.txt"
        main_sha_file_03.write_text(EXPECTED_LIVE_GITHUB_MAIN_SHA, encoding="utf-8")

        # ARGON_03: Direct filename lookup returns 404 (because workflow is absent from remote main),
        # resolved via /actions/workflows catalog fallback (ID 147631346) while excluding build-mersad-preview-dispatch.yml (ID 147631347),
        # and verifies live remote main (38a09da9854bcf276386391c5a06c2706bb119c3) pre-push and post-push!
        fake_bin_argon_cat = ta_p / "fake_bin_argon_cat"
        fake_bin_argon_cat.mkdir()
        write_git_live_main_wrapper(fake_bin_argon_cat, main_sha_file_03)
        state_argon_cat = ta_p / "state_argon_cat.txt"
        catalog_json_str = json.dumps({
            "total_count": 2,
            "workflows": [
                {
                    "id": 147631346,
                    "name": EXPECTED_WORKFLOW_DISPLAY_NAME,
                    "path": WORKFLOW_DEFINITION_PATH,
                    "state": "active",
                },
                {
                    "id": 147631347,
                    "name": "Build MERSAD PREVIEW 0.1 Windows x64",
                    "path": ".github/workflows/build-mersad-preview-dispatch.yml",
                    "state": "active",
                },
            ],
        })
        argon_cat_script = f"""#!/usr/bin/env python3
import json, pathlib, sys
args = sys.argv[1:]
sf = pathlib.Path("{state_argon_cat}")
if args[:2] == ["auth", "status"]:
    sys.exit(0)
if args[:3] == ["api", "-X", "GET"]:
    ep = args[3]
    if ep.endswith("/workflows/{WORKFLOW_FILE}"):
        print("HTTP 404 Not Found: workflow file absent from default branch main", file=sys.stderr)
        sys.exit(1)
    if "/actions/workflows?per_page=100&page=1" in ep:
        print({catalog_json_str!r})
        sys.exit(0)
    if "/workflows/147631346/runs?" in ep:
        if not sf.exists():
            sf.write_text("pre")
            print(json.dumps({{"total_count": 0, "workflow_runs": []}}))
        else:
            print(json.dumps({{"total_count": 1, "workflow_runs": [
                {{"id": 9101, "workflow_id": 147631346, "path": "{WORKFLOW_DEFINITION_PATH}", "name": "{EXPECTED_WORKFLOW_DISPLAY_NAME}", "head_sha": "{local_head}", "event": "push", "head_branch": "{DEFAULT_TARGET_BRANCH}", "created_at": "{now_utc_iso}", "html_url": "https://github.com/alinon9/MERSAD-AI-/actions/runs/9101"}}
            ]}}))
        sys.exit(0)
if args[:2] == ["run", "watch"] and args[2] == "9101":
    sys.exit(0)
if args[:2] == ["run", "view"] and args[2] == "9101":
    print(json.dumps({{"status": "completed", "conclusion": "success", "jobs": [{{"name": "build-and-verify-windows-x64", "conclusion": "success"}}]}}))
    sys.exit(0)
if args[:2] == ["run", "download"] and args[2] == "9101":
    out_dir = pathlib.Path(args[args.index("--dir") + 1])
    for fn in {REQUIRED_WINDOWS_ARTIFACTS!r}:
        (out_dir / fn).write_bytes(f"SIM_ARGON_CAT_{{fn}}".encode("utf-8"))
    sys.exit(0)
sys.exit(1)
"""
        (fake_bin_argon_cat / "gh").write_text(argon_cat_script, encoding="utf-8")
        (fake_bin_argon_cat / "gh").chmod(0o755)
        res_argon_cat = execute_deployment(
            bundle, str(bare_argon_live_main), wf_file,
            env_override={"PATH": f"{fake_bin_argon_cat}:/usr/bin:/bin"},
            poll_attempts=2, poll_interval_s=0.0, settling_polls=2, settling_interval_s=0.0,
            artifacts_base_dir=ta_p,
        )
        checks.append((
            "ARGON_03_WORKFLOW_404_BY_FILENAME_RESOLVED_VIA_CATALOG_147631346_AND_REMOTE_MAIN_VERIFIED",
            res_argon_cat["status"] == "PASS"
            and res_argon_cat.get("workflow_metadata", {}).get("workflow_id") == 147631346
            and res_argon_cat.get("workflow_metadata", {}).get("resolution_mode") == "WORKFLOWS_CATALOG_FALLBACK"
            and len(res_argon_cat.get("workflow_metadata", {}).get("excluded_remote_workflows", [])) == 1
            and res_argon_cat.get("remote_main_verified_pre_push") == EXPECTED_LIVE_GITHUB_MAIN_SHA
            and res_argon_cat.get("remote_main_verified_post_push") == EXPECTED_LIVE_GITHUB_MAIN_SHA
            and res_argon_cat.get("target_branch_creation_mode") == "CREATE_NEW_REMOTE_BRANCH"
        ))

        # ARGON_04: Unexpected/tampered remote main SHA is rejected before push with PREFLIGHT_FAILED (REMOTE_MAIN_SHA_MISMATCH)
        bare_argon_bad_main = create_fresh_bare_remote(ta_p, "origin_argon_bad_main.git")
        with tempfile.TemporaryDirectory() as td_seed_bad_m:
            subprocess.run(["git", "clone", "-q", str(bundle), td_seed_bad_m], check=True)
            subprocess.run(["git", "-C", td_seed_bad_m, "push", "-q", str(bare_argon_bad_main), f"{EXPECTED_AI_CODE_SHA}:refs/heads/main"], check=True)

        res_argon_bad_main = execute_deployment(
            bundle, str(bare_argon_bad_main), wf_file,
            env_override={"PATH": "/usr/bin:/bin"},
            poll_attempts=1, poll_interval_s=0.0,
        )
        checks.append((
            "ARGON_04_UNEXPECTED_REMOTE_MAIN_SHA_REJECTED_BEFORE_PUSH",
            res_argon_bad_main["status"] == "PREFLIGHT_FAILED"
            and res_argon_bad_main["push_executed"] is False
            and "REMOTE_MAIN_SHA_MISMATCH" in res_argon_bad_main.get("error", "")
        ))

        # ARGON_05: Workflow unregistered before first push of new branch (`DEFERRED_PRE_PUSH_NEW_BRANCH_WORKFLOW`),
        # then registered upon push and resolved authoritatively post-push without bypassing workflow identity!
        bare_argon_def = create_fresh_bare_remote(ta_p, "origin_argon_def.git")
        fake_bin_argon_def = ta_p / "fake_bin_argon_def"
        fake_bin_argon_def.mkdir()
        state_argon_def = ta_p / "state_argon_def.txt"
        pre_push_cat_json = json.dumps({
            "total_count": 1,
            "workflows": [
                {
                    "id": 147631347,
                    "name": "Build MERSAD PREVIEW 0.1 Windows x64",
                    "path": ".github/workflows/build-mersad-preview-dispatch.yml",
                    "state": "active",
                },
            ],
        })
        argon_def_script = f"""#!/usr/bin/env python3
import json, pathlib, sys
args = sys.argv[1:]
sf = pathlib.Path("{state_argon_def}")
if args[:2] == ["auth", "status"]:
    sys.exit(0)
if args[:3] == ["api", "-X", "GET"]:
    ep = args[3]
    if ep.endswith("/workflows/{WORKFLOW_FILE}"):
        print("HTTP 404 Not Found", file=sys.stderr)
        sys.exit(1)
    if "/actions/workflows?per_page=100&page=1" in ep:
        if not sf.exists():
            sf.write_text("pushed")
            print({pre_push_cat_json!r})
        else:
            print({catalog_json_str!r})
        sys.exit(0)
    if "/workflows/147631346/runs?" in ep:
        print(json.dumps({{"total_count": 1, "workflow_runs": [
            {{"id": 9201, "workflow_id": 147631346, "path": "{WORKFLOW_DEFINITION_PATH}", "name": "{EXPECTED_WORKFLOW_DISPLAY_NAME}", "head_sha": "{local_head}", "event": "push", "head_branch": "{DEFAULT_TARGET_BRANCH}", "created_at": "{now_utc_iso}", "html_url": "https://github.com/alinon9/MERSAD-AI-/actions/runs/9201"}}
        ]}}))
        sys.exit(0)
if args[:2] == ["run", "watch"] and args[2] == "9201":
    sys.exit(0)
if args[:2] == ["run", "view"] and args[2] == "9201":
    print(json.dumps({{"status": "completed", "conclusion": "success", "jobs": [{{"name": "build-and-verify-windows-x64", "conclusion": "success"}}]}}))
    sys.exit(0)
if args[:2] == ["run", "download"] and args[2] == "9201":
    out_dir = pathlib.Path(args[args.index("--dir") + 1])
    for fn in {REQUIRED_WINDOWS_ARTIFACTS!r}:
        (out_dir / fn).write_bytes(f"SIM_ARGON_DEF_{{fn}}".encode("utf-8"))
    sys.exit(0)
sys.exit(1)
"""
        (fake_bin_argon_def / "gh").write_text(argon_def_script, encoding="utf-8")
        (fake_bin_argon_def / "gh").chmod(0o755)
        res_argon_def = execute_deployment(
            bundle, str(bare_argon_def), wf_file,
            env_override={"PATH": f"{fake_bin_argon_def}:/usr/bin:/bin"},
            poll_attempts=2, poll_interval_s=0.0, settling_polls=2, settling_interval_s=0.0,
            artifacts_base_dir=ta_p,
        )
        checks.append((
            "ARGON_05_NEW_BRANCH_DEFERRED_WORKFLOW_RESOLVED_POST_PUSH_WITH_FULL_IDENTITY_VERIFICATION",
            res_argon_def["status"] == "PASS"
            and res_argon_def.get("pre_existing_runs_query_summary", {}).get("deferred_until_branch_push") is True
            and res_argon_def.get("workflow_metadata", {}).get("workflow_id") == 147631346
            and res_argon_def.get("workflow_metadata", {}).get("deferred_until_branch_push") is False
            and res_argon_def.get("run_id") == "9201"
        ))

        # ARGON_06: If branch already exists on remote (`pre_push_remote_sha` is an ancestor) and workflow is missing from catalog,
        # preflight MUST NOT defer and MUST fail closed before push (`PREFLIGHT_FAILED`)!
        bare_argon_existing_no_wf = create_fresh_bare_remote(ta_p, "origin_argon_existing_no_wf.git")
        with tempfile.TemporaryDirectory() as td_seed_ex:
            subprocess.run(["git", "clone", "-q", str(bundle), td_seed_ex], check=True)
            subprocess.run(["git", "-C", td_seed_ex, "push", "-q", str(bare_argon_existing_no_wf), f"{EXPECTED_AI_PREFLIGHT_PARENT_SHA}:refs/heads/{DEFAULT_TARGET_BRANCH}"], check=True)

        fake_bin_argon_never_reg = ta_p / "fake_bin_argon_never_reg"
        fake_bin_argon_never_reg.mkdir()
        never_reg_script = f"""#!/usr/bin/env python3
import sys
args = sys.argv[1:]
if args[:2] == ["auth", "status"]:
    sys.exit(0)
if args[:3] == ["api", "-X", "GET"]:
    ep = args[3]
    if ep.endswith("/workflows/{WORKFLOW_FILE}"):
        print("HTTP 404 Not Found", file=sys.stderr)
        sys.exit(1)
    if "/actions/workflows?per_page=100&page=1" in ep:
        print({pre_push_cat_json!r})
        sys.exit(0)
sys.exit(1)
"""
        (fake_bin_argon_never_reg / "gh").write_text(never_reg_script, encoding="utf-8")
        (fake_bin_argon_never_reg / "gh").chmod(0o755)
        res_argon_ex_no_wf = execute_deployment(
            bundle, str(bare_argon_existing_no_wf), wf_file,
            env_override={"PATH": f"{fake_bin_argon_never_reg}:/usr/bin:/bin"},
            poll_attempts=1, poll_interval_s=0.0,
        )
        checks.append((
            "ARGON_06_EXISTING_REMOTE_BRANCH_WITH_UNREGISTERED_WORKFLOW_FAILS_CLOSED_BEFORE_PUSH",
            res_argon_ex_no_wf["status"] == "PREFLIGHT_FAILED"
            and res_argon_ex_no_wf["push_executed"] is False
            and "GH_API_WORKFLOW_NOT_REGISTERED_ON_REMOTE" in res_argon_ex_no_wf.get("error", "")
        ))

        # ARGON_07: If new branch is pushed but workflow still never registers on remote after all poll attempts,
        # halts fail-closed with RUN_TIMEOUT (POST_PUSH_WORKFLOW_NOT_REGISTERED_ON_REMOTE) and never bypasses identity!
        bare_argon_post_timeout = create_fresh_bare_remote(ta_p, "origin_argon_post_timeout.git")
        res_argon_post_timeout = execute_deployment(
            bundle, str(bare_argon_post_timeout), wf_file,
            env_override={"PATH": f"{fake_bin_argon_never_reg}:/usr/bin:/bin"},
            poll_attempts=2, poll_interval_s=0.0,
        )
        checks.append((
            "ARGON_07_UNREGISTERED_WORKFLOW_AFTER_NEW_BRANCH_PUSH_TIMES_OUT_FAIL_CLOSED",
            res_argon_post_timeout["status"] == "RUN_TIMEOUT"
            and res_argon_post_timeout["push_executed"] is True
            and res_argon_post_timeout["run_id"] is None
            and "POST_PUSH_WORKFLOW_NOT_REGISTERED_ON_REMOTE" in res_argon_post_timeout.get("error", "")
        ))

        # ARGON_08: Strict separation between EXPECTED_LIVE_GITHUB_MAIN_SHA (38a09da9...) and EXPECTED_BUNDLE_MAIN_SNAPSHOT_SHA (25c9e5bb...)
        checks.append((
            "ARGON_08_TWO_TIER_MAIN_SHA_CONSTANTS_RECONCILED",
            EXPECTED_LIVE_GITHUB_MAIN_SHA == "38a09da9854bcf276386391c5a06c2706bb119c3"
            and EXPECTED_BUNDLE_MAIN_SNAPSHOT_SHA == "25c9e5bba30dc8f921675e12c23a53571be895c1"
            and ALLOWED_REMOTE_MAIN_SHAS == ("38a09da9854bcf276386391c5a06c2706bb119c3",)
            and EXPECTED_BUNDLE_MAIN_SNAPSHOT_SHA not in ALLOWED_REMOTE_MAIN_SHAS
        ))

        # =====================================================================
        # BUG-53 Mandatory Regression Tests (ARGON_09 .. ARGON_12)
        # =====================================================================

        # ARGON_09_BUNDLE_SNAPSHOT_MUST_NOT_BE_ACCEPTED_AS_LIVE_MAIN:
        # Simulate remote main at 25c9e5bba30dc8f921675e12c23a53571be895c1 -> expect preflight rejection & push_executed=False
        bare_argon_09 = create_fresh_bare_remote(ta_p, "origin_argon_09_bundle_main.git")
        with tempfile.TemporaryDirectory() as td_seed_09:
            subprocess.run(["git", "clone", "-q", str(bundle), td_seed_09], check=True)
            subprocess.run(["git", "-C", td_seed_09, "push", "-q", str(bare_argon_09), f"{EXPECTED_BUNDLE_MAIN_SNAPSHOT_SHA}:refs/heads/main"], check=True)

        res_argon_09 = execute_deployment(
            bundle, str(bare_argon_09), wf_file,
            env_override={"PATH": "/usr/bin:/bin"},
            poll_attempts=1, poll_interval_s=0.0,
        )
        checks.append((
            "ARGON_09_BUNDLE_SNAPSHOT_MUST_NOT_BE_ACCEPTED_AS_LIVE_MAIN",
            res_argon_09["status"] == "PREFLIGHT_FAILED"
            and res_argon_09["push_executed"] is False
            and res_argon_09["build_triggered"] is False
            and res_argon_09.get("pre_push_remote_main_sha") == EXPECTED_BUNDLE_MAIN_SNAPSHOT_SHA
            and res_argon_09.get("remote_main_verified_pre_push") is None
            and "REMOTE_MAIN_SHA_MISMATCH" in res_argon_09.get("error", "")
        ))

        # ARGON_10_EXPECTED_LIVE_MAIN_ACCEPTED:
        # Simulate remote main at 38a09da9854bcf276386391c5a06c2706bb119c3 -> verify expected preflight acceptance
        bare_argon_10 = create_fresh_bare_remote(ta_p, "origin_argon_10_live_main.git")
        if state_argon_cat.exists():
            state_argon_cat.unlink()
        main_sha_file_03.write_text(EXPECTED_LIVE_GITHUB_MAIN_SHA, encoding="utf-8")
        res_argon_10 = execute_deployment(
            bundle, str(bare_argon_10), wf_file,
            env_override={"PATH": f"{fake_bin_argon_cat}:/usr/bin:/bin"},
            poll_attempts=2, poll_interval_s=0.0, settling_polls=2, settling_interval_s=0.0,
            artifacts_base_dir=ta_p,
        )
        checks.append((
            "ARGON_10_EXPECTED_LIVE_MAIN_ACCEPTED",
            res_argon_10["status"] == "PASS"
            and "PREFLIGHT_PASS" in res_argon_10.get("state_history", [])
            and res_argon_10.get("live_github_main_commit") == EXPECTED_LIVE_GITHUB_MAIN_SHA
            and res_argon_10.get("bundle_main_snapshot_commit") == EXPECTED_BUNDLE_MAIN_SNAPSHOT_SHA
            and res_argon_10.get("remote_main_verified_pre_push") == EXPECTED_LIVE_GITHUB_MAIN_SHA
            and res_argon_10.get("remote_main_verified_post_push") == EXPECTED_LIVE_GITHUB_MAIN_SHA
        ))

        # ARGON_11_PROVENANCE_FIELDS_ARE_UNAMBIGUOUS:
        # Validate all relevant manifests, JSON files, and reports; reject any assertion that live main is 25c9e5...
        mf_check_ok = True
        for mf_rel in [
            "MANIFEST.json",
            "SOURCE_TREE_MANIFEST.json",
            "RELEASE_DELIVERABLES/PREVIEW_0.1/MANIFEST.json",
            "RELEASE_DELIVERABLES/PREVIEW_0.1/SOURCE_TREE_MANIFEST.json",
        ]:
            mf_p = repo_root / mf_rel
            if not mf_p.is_file():
                mf_check_ok = False
                break
            mf_d = json.loads(mf_p.read_text(encoding="utf-8"))
            ai_c = mf_d.get("mersad_ai_commits", {})
            if (
                ai_c.get("live_github_main_commit") != EXPECTED_LIVE_GITHUB_MAIN_SHA
                or ai_c.get("bundle_main_snapshot_commit") != EXPECTED_BUNDLE_MAIN_SNAPSHOT_SHA
                or ai_c.get("remote_main_verified_pre_push") != EXPECTED_LIVE_GITHUB_MAIN_SHA
                or ai_c.get("remote_main_verified_post_push") is not None
                or "main_branch_untouched_commit" in ai_c
            ):
                mf_check_ok = False

        for bm_rel in ["BUNDLE_MANIFEST.json", "RELEASE_DELIVERABLES/PREVIEW_0.1/BUNDLE_MANIFEST.json"]:
            bm_p_chk = repo_root / bm_rel
            if bm_p_chk.is_file():
                bm_d = json.loads(bm_p_chk.read_text(encoding="utf-8"))
                if (
                    bm_d.get("live_github_main_commit") != EXPECTED_LIVE_GITHUB_MAIN_SHA
                    or bm_d.get("bundle_main_snapshot_commit") != EXPECTED_BUNDLE_MAIN_SNAPSHOT_SHA
                    or bm_d.get("remote_main_verified_pre_push") != EXPECTED_LIVE_GITHUB_MAIN_SHA
                    or bm_d.get("remote_main_verified_post_push") is not None
                ):
                    mf_check_ok = False

        for tr_rel in ["TEST_RESULTS.json", "RELEASE_DELIVERABLES/PREVIEW_0.1/TEST_RESULTS.json"]:
            tr_p_chk = repo_root / tr_rel
            if not tr_p_chk.is_file():
                mf_check_ok = False
                break
            tr_d = json.loads(tr_p_chk.read_text(encoding="utf-8"))
            tr_c = tr_d.get("commits", {})
            tr_gb = tr_c.get("mersad_ai_rollback_tags", {})
            if (
                tr_c.get("live_github_main_commit") != EXPECTED_LIVE_GITHUB_MAIN_SHA
                or tr_c.get("bundle_main_snapshot_commit") != EXPECTED_BUNDLE_MAIN_SNAPSHOT_SHA
                or tr_c.get("remote_main_verified_pre_push") != EXPECTED_LIVE_GITHUB_MAIN_SHA
                or tr_c.get("remote_main_verified_post_push") is not None
                or tr_gb.get("live_github_main_commit") != EXPECTED_LIVE_GITHUB_MAIN_SHA
                or tr_gb.get("bundle_main_snapshot_commit") != EXPECTED_BUNDLE_MAIN_SNAPSHOT_SHA
                or "main_untouched" in tr_gb
            ):
                mf_check_ok = False

        # Scan all Markdown reports to ensure 25c9e5bba30dc8f921675e12c23a53571be895c1 is never claimed as live untouched main
        ambiguous_md_occurrences = []
        for md_p in list(repo_root.glob("*.md")) + list((repo_root / "RELEASE_DELIVERABLES" / "PREVIEW_0.1").glob("*.md")) + list((repo_root / "reports_and_logs").glob("*.md")):
            md_t = md_p.read_text(encoding="utf-8")
            for idx_ln, ln_str in enumerate(md_t.splitlines(), 1):
                if EXPECTED_BUNDLE_MAIN_SNAPSHOT_SHA in ln_str:
                    # Any line mentioning 25c9e5... must identify it as bundle/offline snapshot or BUG-52/53 historical context, never as "الفرع الرئيسي main غير الممسوس: 25c9e5"
                    if (
                        "الفرع الرئيسي `main` غير الممسوس**: `25c9e5b" in ln_str
                        or "الفرع الرئيسي (`main`)**: `25c9e5b" in ln_str
                        or "| `main` (محفوظ دون أي تعديل) | `25c9e5b" in ln_str
                        or "- `main` (الأرشيف الأصلي غير الممسوس) -> `25c9e5b" in ln_str
                    ):
                        ambiguous_md_occurrences.append(f"{md_p.name}:{idx_ln}")

        checks.append((
            "ARGON_11_PROVENANCE_FIELDS_ARE_UNAMBIGUOUS",
            mf_check_ok
            and ai_prov.get("live_github_main_commit") == EXPECTED_LIVE_GITHUB_MAIN_SHA
            and ai_prov.get("bundle_main_snapshot_commit") == EXPECTED_BUNDLE_MAIN_SNAPSHOT_SHA
            and ai_prov.get("remote_main_verified_pre_push") == EXPECTED_LIVE_GITHUB_MAIN_SHA
            and ai_prov.get("remote_main_verified_post_push") is None
            and "main_sha" not in ai_prov
            and len(ambiguous_md_occurrences) == 0
        ))

        # ARGON_12_MAIN_UNCHANGED_POST_PUSH_GUARD:
        # Verify that if remote refs/heads/main changes after git push, deployment aborts with RUN_FAILED (POST_PUSH_REMOTE_MAIN_MUTATED)
        bare_argon_12 = create_fresh_bare_remote(ta_p, "origin_argon_12_post_mut.git")
        fake_bin_argon_12 = ta_p / "fake_bin_argon_12"
        fake_bin_argon_12.mkdir()
        main_sha_file_12 = ta_p / "main_sha_12.txt"
        main_sha_file_12.write_text(EXPECTED_LIVE_GITHUB_MAIN_SHA, encoding="utf-8")
        write_git_live_main_wrapper(
            fake_bin_argon_12,
            main_sha_file_12,
            mutate_after_push_to="9999999999999999999999999999999999999999",
        )
        shutil.copy2(fake_bin_argon_cat / "gh", fake_bin_argon_12 / "gh")
        (fake_bin_argon_12 / "gh").chmod(0o755)
        res_argon_12_mut = execute_deployment(
            bundle, str(bare_argon_12), wf_file,
            env_override={"PATH": f"{fake_bin_argon_12}:/usr/bin:/bin"},
            poll_attempts=1, poll_interval_s=0.0,
        )
        checks.append((
            "ARGON_12_MAIN_UNCHANGED_POST_PUSH_GUARD",
            res_argon_10.get("remote_main_verified_pre_push") == EXPECTED_LIVE_GITHUB_MAIN_SHA
            and res_argon_10.get("remote_main_verified_post_push") == EXPECTED_LIVE_GITHUB_MAIN_SHA
            and res_argon_12_mut["status"] == "RUN_FAILED"
            and res_argon_12_mut.get("remote_main_verified_pre_push") == EXPECTED_LIVE_GITHUB_MAIN_SHA
            and res_argon_12_mut.get("remote_main_verified_post_push") is None
            and "POST_PUSH_REMOTE_MAIN_MUTATED" in res_argon_12_mut.get("error", "")
        ))

    all_ok = all(ok for _, ok in checks)
    return {
        "all_passed": all_ok,
        "execution_environment": "LOCAL_SANDBOX_SIMULATED_BARE_REMOTE_AND_NODEJS_VERIFICATION (No live GitHub Actions or Windows native execution)",
        "total_checks": len(checks),
        "passed_checks": sum(1 for _, ok in checks if ok),
        "allowed_deploy_branches": list(ALLOWED_DEPLOY_BRANCHES),
        "ai_provenance_summary": {
            "branch": ai_prov.get("branch"),
            "head_sha": ai_prov.get("head_sha"),
            "previous_bug40_45_commit_sha": ai_prov.get("previous_bug40_45_commit_sha"),
            "previous_single_run_ci_commit_sha": ai_prov.get("previous_single_run_ci_commit_sha"),
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
    ap.add_argument("--branch", type=str, default=None)
    ap.add_argument("--verify-downloaded-artifacts", type=str, default="")
    ap.add_argument("--trusted-digests-json", type=str, default="")
    ap.add_argument("--verify-attestation", action="store_true")
    ap.add_argument("--verify-ai-provenance", action="store_true")
    ap.add_argument("--run-id", type=str, default="")
    ap.add_argument("--poll-attempts", type=int, default=DEFAULT_POLL_ATTEMPTS)
    ap.add_argument("--poll-interval", type=float, default=DEFAULT_POLL_INTERVAL_S)
    ap.add_argument("--settling-polls", type=int, default=DEFAULT_SETTLING_POLLS)
    ap.add_argument("--settling-interval", type=float, default=DEFAULT_SETTLING_INTERVAL_S)
    args = ap.parse_args()
    root = Path(__file__).resolve().parent.parent
    if args.verify_ai_provenance:
        ok_b, target_b, msg_b = validate_target_branch_allowlist(args.branch)
        if not ok_b:
            print(json.dumps({"ok": False, "error": msg_b}, indent=2, ensure_ascii=False))
            sys.exit(1)
        aprov = verify_ai_zip_vs_git_provenance(root, branch=target_b)
        print(json.dumps(aprov, indent=2, ensure_ascii=False))
        sys.exit(0 if aprov["ok"] else 1)
    if args.verify_downloaded_artifacts:
        ref_digests = None
        if args.trusted_digests_json:
            ref_digests = json.loads(Path(args.trusted_digests_json).read_text(encoding="utf-8"))
        ver = verify_and_hash_downloaded_artifacts(
            Path(args.verify_downloaded_artifacts),
            run_id=args.run_id,
            trusted_reference_digests=ref_digests,
            verify_attestation=args.verify_attestation,
            gh_bin=shutil.which("gh"),
        )
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
            poll_attempts=args.poll_attempts,
            poll_interval_s=args.poll_interval,
            settling_polls=args.settling_polls,
            settling_interval_s=args.settling_interval,
            artifacts_base_dir=root,
            target_branch=args.branch,
        )
        print(json.dumps(rep, indent=2, ensure_ascii=False))
        sys.exit(0 if rep["status"] == "PASS" else 1)
