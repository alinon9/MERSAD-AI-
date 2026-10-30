# MERSAD AI — V7 Operational Enhanced

**Date:** 2026-10-26

## What's new

### 1. Operations Command Center
- Added an authenticated `مركز القيادة` dashboard tab.
- Compares live (non-demo) sightings in the last 24 hours with the preceding 24-hour period.
- Displays a 24-slot hourly trend, vehicle-class distribution, confidence bands, camera health counters, and alert/dispatch summaries.
- Generates transparent rule-based recommendations for offline/reconnecting cameras, low FPS, low OCR confidence, unresolved dispatches, and small sample sizes.

### 2. Persistent camera reliability history
- Added `camera_status_history` SQLite table, created idempotently and serialized across multiple processes.
- Records startup and changes between `online`, `reconnecting`, `offline`, and `unknown`.
- Shows observed online/downtime, approximate uptime, coverage, outage count, recovery count, and recent transitions for 24 hours, 7 days, or 30 days.
- Does not infer uptime during periods when the app was stopped or when no camera status was observed.

### 3. Privacy-conscious exports and authenticated API
- `/api/analytics`
- `/api/analytics/export.csv`
- `/api/camera-health?period=24h|7d|30d`
- `/api/camera-health/export.csv?period=24h|7d|30d`
- CSV output is UTF-8 with BOM and neutralizes values that spreadsheet applications might interpret as formulas.
- Analytics CSV contains aggregated metrics only. It intentionally excludes plate values, person names, biometric embeddings, and evidence paths.

### 4. Reliability and build integration
- Added analytics and camera-history modules to `mersad_ai.spec` and `BUILD_EXE.bat` hidden imports.
- Added health/analytics smoke checks to `check_install.py` and 10 V7-related self-tests/integration checks.
- Made camera-history schema creation use the existing interprocess SQLite transaction lock to avoid simultaneous-startup schema races.
- Improved POSIX read-only install-directory detection, including tests running as root.
- Tightened Windows CI to stop when dependency checks, self-tests, model preparation, PyInstaller, or standalone verification fails.

## Test status

- Python compilation: PASS.
- Dashboard JavaScript syntax (`node --check`): PASS.
- `python selftest.py`: **187 PASS / 0 SKIP / 0 FAIL** in final successful run.
- `MERSAD_BLOCK_SKLEARN=1 python selftest.py`: **187 PASS / 0 SKIP / 0 FAIL** in final successful run.
- `python check_install.py --json`: exit code 0; environment is classified as development without heavy AI weights, because this Linux container does not contain EasyOCR/Ultralytics weights and the target runtime is Windows Python 3.11 x64.

## Source archive and release limitation

The supplied attachments included the V6 test report and V6 release notes, but **not the V6 source archive**. This enhancement package therefore starts from the available `MERSAD_AI_FIXED_5.zip` source, reconstructs the documented V6 analytics design, and adds the new V7 camera-reliability feature. It cannot preserve unprovided code changes that might exist only in a separate V6 source tree.

The Windows EXE was **not** built or run in this Linux environment. Real camera throughput, field Arabic OCR accuracy, actual Telegram delivery, and Windows CI remain release gates.

- V7.1 Stages 1–13 engineering remediation completed (**187 PASS / 0 SKIP / 0 FAIL**), including `--evaluate-plates` two-stage vehicle/plate evaluation.
