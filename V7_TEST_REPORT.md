# MERSAD AI V7.1 — Repair and Verification Report

**Date:** 2026-10-26

## Results actually executed in this environment

| Check | Result | What it proves |
|---|---|---|
| `python -m compileall -q .` | PASS | Python source compiles in the available Linux Python 3.13.5 environment. The exact final ZIP was extracted and compiled too. |
| Extracted inline JavaScript + `node --check` | PASS | Dashboard inline JavaScript has no syntax errors in the exact extracted final ZIP. |
| Standard `python -u selftest.py` | **136 PASS / 0 SKIP / 0 FAIL** | The exact final ZIP was extracted and passed the full suite at 136/136; an additional working-tree run also passed 136/136. |
| `MERSAD_BLOCK_SKLEARN=1 python -u selftest.py` | **136 PASS / 0 SKIP / 0 FAIL** | Full suite passed with the scikit-learn path disabled. |
| P0-E cross-process stress | PASS in each of the three final full-suite runs | Two OS processes create 100 distinct alerts, zero worker errors, valid audit chain, and exactly one Telegram polling-listener owner. |
| P1-C camera recovery/isolation | PASS in every final full-suite run, including exact-archive runs | Service survives offline-at-startup simulation, recovers after repeated reconnect failures, and fast camera receives 26 frames while slow camera receives only 2–3 in about 1.2 seconds. This is a deterministic fake-camera test, not physical-device throughput. |
| V7 SQLite network fallback | PASS | UNC-style path avoids WAL and selects DELETE journaling; a simulated WAL failure falls back safely. Mapped-drive behavior still needs a real Windows runner. |
| EasyOCR model handling | PASS | Missing/corrupt weights fail early; valid local weights initialize with downloads disabled (using mocked Reader in the unit tests). |
| `--verify-models` negative path | PASS | With models absent, command exits 2 and clearly lists required assets; this environment cannot validate the positive path using real weights. |
| `check_install.py --json` | Exit code 0 | Classification is `DEV_WITHOUT_HEAVY_WEIGHTS`; core smoke checks pass but environment is not a release-build environment. |
| `check_install.py --strict` | Exit code 1 (expected here) | Flags Python 3.13.5 instead of the target Python 3.11 x64, pinned package version differences, missing EasyOCR/Ultralytics and absent model weights. |

## Fixes made

1. **P0-E:** fixed inter-process lock state handling when setup fails, made Windows lock-file initialization explicit, scoped Telegram listener ownership, added orderly listener shutdown, and isolated native camera/image/network work from the database concurrency stress test. Concurrency assertions have not been weakened.
2. **P1-C:** retained independent camera reader workers, added bounded FFmpeg timeouts and safer cleanup sequencing; corrected the finite-source test to allow for latest-frame coalescing without reducing its required 18 processed fast frames; added a bounded watchdog so a stalled finite-camera test becomes a reported failure instead of hanging CI.
3. **SQLite:** explicit WAL/DELETE strategy and a safe rollback-journal fallback. Network shares are not recommended for the live database; local storage remains preferred.
4. **EasyOCR and model integrity:** `download_enabled=False`, explicit local weight validation, actionable missing/corrupt model errors, and no hidden downloads on the frozen EXE runtime path.
5. **Model verification:** introduced `--verify-models` for pre/post-build verification and configured both local Windows build scripts and CI to check the copied distribution, including after relocation.
6. **CSV link:** analytics export now uses the common query-token URL helper.
7. **Build reproducibility:** Python 3.11 x64 guard; repeated test runs before PyInstaller; post-build audit-chain and model checks.

## Required validation not possible in this environment

- No Windows 10/11 executable was built or executed here. The prepared Windows workflow must run against this archive and produce the artifact logs before the `.exe` is claimed as verified.
- No real RTSP/USB camera was connected. The slow/fast and reconnect tests use deterministic fake sources.
- No live Telegram bot token or external delivery endpoint was used. Telegram tests exercise a local/mock harness only.
- The positive `--verify-models` case on a complete real `models/` directory was not executed; only unit-level valid-model mocks and the CLI missing-model negative path passed.

## Provenance

The exact V6 source archive was not among the available attachments. This package is based on the available `MERSAD_AI_FIXED_5.zip` source with the documented V6 analytics and V7 camera-history functionality. Unprovided code changes in a separate V6 source tree cannot be compared or preserved automatically.
