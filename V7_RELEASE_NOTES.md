# MERSAD AI — V7.1 Hardened Operational Build

**Date:** 2026-10-26

## Operational hardening

### P0-E — Cross-process database and listener stability
- Hardened the re-entrant inter-process SQLite lock so lock depth changes only after successful acquisition and is restored safely if sidecar setup fails.
- Initializes a byte before Windows CRT byte-range locking and scopes Telegram listener lock names to a hash of the configured bot token.
- Added bounded listener shutdown waiting so the process can release its single-owner polling lock cleanly.
- Reworked the multiprocessing stress fixture to synchronize both workers, verify exactly one listener owner, keep the database/audit workload separate from unrelated native image encoding and outbound network threads, and report ownership/child exit diagnostics. The assertions still require 100 unique alerts, intact audit chain, no worker errors, and exactly one listener owner.

### P1-C — Camera fault isolation and fair progress
- Camera open/read/reconnect work remains in a separate worker per camera; RTSP/HTTP capture uses bounded FFmpeg open/read timeouts.
- Main startup no longer synchronously opens each camera, reducing the risk that one unreachable stream blocks server startup or other cameras.
- Improved shutdown ordering by signalling workers, releasing captures, and joining readers with a bounded timeout.
- Added a watchdog to the finite-camera self-test so a deadlocked test case is reported as a failure instead of hanging the whole CI job.
- Improved the slow-vs-fast camera test fixture to give the live latest-frame pipeline input headroom while still requiring at least 18 frames from the fast stream and verifying it makes progress substantially faster than the deliberately slow stream.

### Storage, model integrity, and export
- Added SQLite journaling selection: use WAL on local paths, choose DELETE journaling for detected UNC/mapped remote Windows paths, and fall back to DELETE if a local filesystem rejects WAL. An explicit error recommends a local data path if DELETE cannot be established.
- EasyOCR now validates local detector/recognizer weights before initialization and calls `Reader(..., download_enabled=False)`; missing/corrupt weights fail with actionable setup guidance instead of triggering runtime downloads.
- Frozen distributions prefer packaged resources over stale writable app-data resources, verify YuNet, SFace, YOLOv8n, and EasyOCR assets, and fail clearly if the complete `models/` folder is absent or damaged.
- Added `MERSAD_AI.exe --verify-models` / `python mersad_live.py --verify-models` for an explicit post-build check of every required model. The command exits nonzero and does not download missing files; the check prefers the distribution folder rather than stale models in writable app data.
- Fixed the Command Center analytics CSV link to pass through the same query-token helper as other authenticated export links.

### Release/build guardrails
- `setup.bat` now requires Python 3.11 64-bit, matching the pinned Windows build environment.
- `BUILD_EXE.bat` runs three standard self-test passes and a fourth pass with scikit-learn disabled before PyInstaller, then verifies both the audit chain and bundled AI models after build.
- Windows CI is configured for three standard and two no-scikit-learn test passes, strict dependency/model checks, a `--onedir` EXE build, post-build audit/model verification, and a relocated distribution path containing Arabic characters and spaces.

## Verification completed in the available Linux environment

- `python -m compileall -q .`: PASS.
- `node --check` on the extracted inline dashboard JavaScript: PASS.
- Exact final ZIP was extracted and checked: Python compilation and dashboard `node --check` passed. The extracted archive passed `python -u selftest.py` and `MERSAD_BLOCK_SKLEARN=1 python -u selftest.py`, each **136 PASS / 0 SKIP / 0 FAIL**. An additional final working-tree full-suite run also passed 136/136.
- P0-E and P1-C passed in every final full-suite run, including the exact-archive runs.
- `python mersad_live.py --verify-models` correctly exited with code 2 and explicitly listed missing models in this model-free environment (negative-path test).
- `check_install.py --json`: exit code 0, classified as `DEV_WITHOUT_HEAVY_WEIGHTS`.
- `check_install.py --strict`: exit code 1 as expected here because this is Linux/Python 3.13.5, not the pinned Windows/Python 3.11 build environment, and EasyOCR/Ultralytics plus model weights are absent.

## Release limitations — must remain visible

This package was not built as a Windows `.exe` in this Linux environment. Windows CI and a real Windows 10/11 smoke test are still required before describing the EXE as built or production-ready. No physical RTSP/USB camera or real Telegram bot was available; actual camera throughput, field Arabic OCR accuracy, and real Telegram delivery are not claimed as verified. The Windows workflow is prepared to exercise these gates when run on a Windows runner.

The supplied V6 report and release notes did not include the V6 source archive. This lineage remains a hardened enhancement of the available `MERSAD_AI_FIXED_5.zip` plus the documented V6 analytics and V7 camera-history features; it cannot guarantee preservation of source-only changes from an unavailable independent V6 source tree.
