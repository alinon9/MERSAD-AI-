# MERSAD AI Desktop, Camera Integration & License Plate Upgrade
## Implementation Scope and Acceptance Criteria

**Status:** Implementation branch initialized. Code changes and executable tests are still pending.
**Base:** security/release-closure-aud006-20261122
**Source inspection:** fix/preview-0.1-plate-camera-20261123 @ 6c6311d983e9b7094b68adf31ace2b570ef59f33

## Critical source findings

1. The current runtime is a Python/OpenCV application with a local HTTP server and an HTML dashboard. In `mersad_live.py`, the normal GUI path calls `webbrowser.open(...)`, so the default experience is a browser rather than an application-owned desktop window.
2. The project already has a camera manager in `dashboard.html` and `camera-ui.js`, with device enumeration through `/api/camera_devices`, dynamic registration/removal, and stream display.
3. `mersad_live.py` already supports numeric webcam indexes, HTTP(S) video URLs, RTSP/RTSPS, multiple camera sources, reconnection workers, and camera health telemetry.
4. The normal plate pipeline is not a complete trained Yemeni plate detector: `find_plates()` can use an optional custom YOLO model, but otherwise uses a classical contour/geometry fallback. The vehicle detector YOLOv8n is not itself a dedicated plate detector.
5. OCR already uses EasyOCR Arabic/English, multiple preprocessing retries, normalization and temporal voting. Accuracy work must measure the detection and crop stages as well as OCR; lowering thresholds is not an acceptable fix.
6. Existing tests include plate-model evaluation and a 10-step dynamic-camera lifecycle integration test. Preserve them and add targeted desktop/camera tests.
7. Current Windows release workflow bundles a PyInstaller `--onedir` application and serves dashboard assets. A desktop shell must be added without breaking diagnostics, headless mode, security controls, or existing packaging gates.

## Workstream A — License plate detection and OCR

- Trace the production call path from camera frame to vehicle detection, plate detection/cropping, OCR, temporal voting, registry writes and alert dispatch.
- Determine whether the registered custom plate model is actually used by the live inference path and identify fallback behavior.
- Add structured diagnostics for original frame dimensions, plate candidate dimensions, image sharpness/brightness, OCR engine, preprocessing attempts, confidence and inference latency.
- Do not log camera credentials or sensitive raw URLs.
- Add a dedicated plate detection model only after verifying provenance, license, architecture compatibility, SHA-256 and reproducible packaging.
- Preserve Arabic/English support and current normalization/confirmation rules.
- Do not auto-register low-confidence or ambiguous OCR output as a confirmed plate; retain operator review.
- Evaluate against the existing ground-truth benchmark and clearly separate synthetic/LAB samples from real-world samples.
- Report detection precision/recall, OCR exact-match, digit-match, CER, false reads, latency and sample count. Insufficient real-world data must remain NOT_TESTED.

## Workstream B — Camera integration

- Extend the existing manager rather than introducing a competing subsystem.
- Maintain USB/webcam and Windows virtual camera support.
- Retain phone IP streams over supported HTTP/MJPEG URLs and supported DroidCam virtual-camera integration.
- Retain RTSP/RTSPS support and add ONVIF WS-Discovery only if a suitable dependency and network security model can be justified.
- Require explicit stream test and live preview before saving a source where possible.
- Display the actual returned resolution, FPS, online/reconnecting/offline state, and clear Arabic diagnostics.
- Ensure failed/unavailable cameras do not block other sources.
- Keep credentials out of logs, exported reports, and browser URLs; use secure local credential storage if persistence is introduced.
- Do not enable public-network binding by default; preserve existing loopback/TLS/allowlist rules.

## Workstream C — Native Windows desktop shell

- Evaluate pywebview with Edge WebView2 first because it can host the existing dashboard with minimal UI rewrite. Compare PySide6 only if pywebview is unsuitable for the existing CSP/auth/streaming model.
- Open the dashboard inside an application-owned window; do not use an external browser tab in normal GUI mode.
- Keep the local HTTP server on loopback and preserve the existing authenticated session model.
- Preserve CLI diagnostics, `--no-window`, model verification, audit verification and automated test entry points.
- Implement an orderly shutdown: stop capture and inference workers, release VideoCapture handles, stop HTTP server, close database connections, flush audit/log state, and release the WebView.
- Handle a missing WebView2 runtime with a clear actionable message and documented install/runtime strategy.
- Keep the existing `--onedir` packaging unless verified tests justify a change. Include all new runtime dependencies and assets in the frozen build.

## Security and privacy invariants

Do not weaken authentication, HttpOnly/SameSite cookies, CSRF/Origin validation, host-header validation, loopback default binding, TLS requirements for LAN, explicit host allowlists, credential redaction, SHA-256 model checks, HMAC audit chain, database safety, face blurring, or evidence retention policy.
Do not add facial identification or biometric identity tracking as part of this scope. Limit this upgrade to plate reading, camera ingestion, operator review, and desktop usability.

## Required implementation tests

- Existing full self-test in standard and optional-dependency-degraded modes.
- Existing plate evaluation suite.
- Existing 10-step main-entrypoint dynamic-camera lifecycle test.
- USB/device discovery unit tests using mocks when physical devices are unavailable.
- Local HTTP/MJPEG and RTSP connection tests using controlled test streams.
- Invalid URL, authentication failure, stalled stream, reconnect, add/remove and multi-camera isolation tests.
- Credential/secret redaction tests.
- Desktop launch test proving no external browser is opened.
- Desktop shutdown and worker/resource cleanup tests.
- Frozen Windows EXE runtime, dashboard/CSP assets, model hashes and Arabic-path tests.
- Physical smartphone/CCTV tests must be marked NOT_TESTED unless performed on real hardware.

## Release gate

Do not merge until the relevant tests and Windows workflow complete successfully. Keep the PR in draft while acceptance is incomplete. Do not report physical camera tests or real-world Yemeni plate accuracy as PASS without actual evidence.

## Final report requirements

Provide an Arabic report with:
- Root causes and evidence.
- Changed files and commits.
- Implemented functionality.
- Camera protocols/devices actually tested.
- Before/after plate metrics and sample counts.
- Desktop shell choice and lifecycle details.
- PASS / FAIL / NOT_TESTED for every acceptance group.
- Windows workflow run and artifact URL/hash if produced.
- Remaining limitations and a practical hardware test checklist.
