# MERSAD AI V7 — Test Report

Date: 2026-10-26

## Executed checks

| Check | Result | Notes |
|---|---|---|
| `python -m compileall -q .` | PASS | All project Python modules compile. |
| `node --check` on inline JavaScript from `dashboard.html` | PASS | No JS syntax errors found. |
| `python selftest.py` | **175 PASS, 0 SKIP, 0 FAIL** | Final complete run. |
| `MERSAD_BLOCK_SKLEARN=1 python selftest.py` | **175 PASS, 0 SKIP, 0 FAIL** | Final complete run with the sklearn path disabled. |
| `python check_install.py --json` | Exit code 0 | Classification: `DEV_WITHOUT_HEAVY_WEIGHTS`. The core smoke checks had no reported failures, but heavy inference libraries/models were not installed in this container. |

## V7-specific coverage

- Authenticated API contract for `/api/analytics` and `/api/camera-health`.
- Period parameter (`24h`, `7d`, `30d`) handling.
- CSV content type, attachment name, and UTF-8 BOM.
- Live-only 24-hour count, previous-window comparison, 24 trend slots, class distribution, confidence bands, alert summaries and recommendations.
- Exclusion of plate-like identifiers/demo rows from aggregate analytics exports and spreadsheet-formula neutralization.
- Camera status persistence, duplicate transition suppression, online/downtime calculations based on known intervals, outage/recovery counts, and CSV export.
- Empty/legacy database handling.

## Limitations

1. No Windows executable build/run was performed in this Linux container. Run `.github/workflows/windows-build.yml` against this exact archive before release.
2. No physical RTSP/USB cameras were attached; real-world video throughput, reconnect timing, and Arabic plate OCR accuracy remain unverified.
3. Telegram was exercised through the existing mocked/local test harness, not a real bot in the field.
4. Earlier test reruns exposed intermittent shared-database startup/timing failures. Camera-history schema creation was changed to use the existing interprocess transaction lock; the final standard and no-sklearn runs both passed. Keep Windows CI as a required gate.
5. The exact V6 source archive was not supplied. This package is based on the available V5 source archive and the provided V6 release notes/report, so unprovided source changes from an independent V6 tree cannot be preserved or compared.

- V7.1 Stages 1–10 coverage (`175 PASS, 0 SKIP, 0 FAIL`): includes `--evaluate-plates` benchmark pipeline (`STAGE5-GAP17`, `STAGE7-GAP06`), non-blocking inference (`STAGE4-GAP08`), scheduled face cache (`STAGE6-GAP01`), and unified Windows build checks (`STAGE5-GAP18`, `STAGE7-GAP07`).
