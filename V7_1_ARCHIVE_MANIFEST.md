# MERSAD AI V7.1 — Package Manifest

This archive contains the hardened Python source, dashboard, source and Windows build launchers, pinned dependency manifests, PyInstaller specification, Windows CI workflow, and V7.1 release/test reports.

## Intentionally not bundled

- `models/` weights (`yunet.onnx`, `sface.onnx`, `yolov8n.pt`, and EasyOCR `.pth` files): excluded to keep the source archive small. The first Windows setup/build needs Internet access to download and validate these assets. The complete `dist/MERSAD_AI/` distribution must include the verified `models/` folder.
- Local runtime data such as `mersad.db`, audit/evidence folders, log files, secrets, HMAC keys, virtual environments, caches, and prior build outputs.

## Build and verification

- Target: Windows 10/11 x64 with Python 3.11 x64.
- Run `BUILD_EXE.bat` on Windows. It performs strict setup/model checks, three standard self-test runs, one no-scikit-learn run, PyInstaller `--onedir` packaging, audit-chain verification, and bundled-model verification.
- The Windows CI workflow additionally repeats tests and verifies the copied distribution after relocation to a path containing Arabic characters and spaces.
- `--verify-models` checks model files without downloading them.

## Provenance and limits

The available source base was `MERSAD_AI_FIXED_5.zip` plus the supplied V6 release notes/test report; the full V6 source archive was not available in this conversation. The V7.1 ZIP has not itself been built as a Windows EXE in the current Linux environment, and real RTSP/USB camera and real Telegram delivery tests remain field validation gates.

## Final archive verification

The final ZIP was extracted in the current Linux environment. `compileall`, dashboard JavaScript syntax, standard self-tests (136/136), and no-scikit-learn self-tests (136/136) all passed. This does not substitute for Windows EXE, physical-camera, or real Telegram validation.
