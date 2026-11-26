#!/usr/bin/env python3
"""Launch the frozen Windows MERSAD_AI.exe and verify authenticated /dashboard.js."""
from __future__ import annotations
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.request


def main() -> int:
    if len(sys.argv) != 2:
        print("usage: windows_frozen_dashboard_smoke.py path\\to\\MERSAD_AI.exe", file=sys.stderr)
        return 2
    exe = Path(sys.argv[1]).resolve()
    if not exe.is_file():
        raise FileNotFoundError(exe)
    asset = exe.parent / "dashboard.js"
    if not asset.is_file():
        raise FileNotFoundError(f"Frozen distribution is missing {asset}")
    alpr_asset = exe.parent / "alpr-diagnostics.js"
    if not alpr_asset.is_file():
        raise FileNotFoundError(f"Frozen distribution is missing {alpr_asset}")

    token = "PR5_FROZEN_SMOKE_TOKEN_2026"
    port = 18765
    with tempfile.TemporaryDirectory(prefix="mersad_pr5_frozen_smoke_") as data_dir:
        log_path = Path(data_dir) / "frozen_server.log"
        env = os.environ.copy()
        env.update({
            "MERSAD_TOKEN": token,
            "MERSAD_DATA_DIR": data_dir,
            "TELEGRAM_TOKEN": "",
            "TELEGRAM_CHAT_ID": "",
            "PYTHONUTF8": "1",
        })
        with log_path.open("wb") as log:
            flags = getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0)
            proc = subprocess.Popen(
                [str(exe), "--host", "127.0.0.1", "--port", str(port),
                 "--no-window", "--no-telegram-listener", "--allow-degraded-preview",
                 "--device", "cpu", "--no-vehicles"],
                cwd=str(exe.parent), env=env, stdout=log, stderr=subprocess.STDOUT,
                creationflags=flags,
            )
            try:
                deadline = time.monotonic() + 75
                last_error = None
                while time.monotonic() < deadline:
                    if proc.poll() is not None:
                        break
                    headers = {"X-Mersad-Token": token, "Host": f"127.0.0.1:{port}"}
                    try:
                        for route, expected_marker in (
                            ("/", b"/purify.min.js"),
                            ("/dashboard.js", b"MERSAD-PR5-FIND001-DELEGATION-V3"),
                            ("/camera-connect.js", b'open.addEventListener("click"'),
                            ("/alpr-diagnostics.js", b"/api/alpr-diagnostics"),
                            ("/purify.min.js", b"DOMPurify 3.4.18"),
                            ("/dompurify-guard.js", b"MERSAD_DOM_XSS_GUARD"),
                        ):
                            req = urllib.request.Request(f"http://127.0.0.1:{port}{route}", headers=headers)
                            with urllib.request.urlopen(req, timeout=2) as response:
                                body = response.read()
                                ctype = response.headers.get("Content-Type", "")
                                nosniff = response.headers.get("X-Content-Type-Options", "")
                                csp = response.headers.get("Content-Security-Policy", "")
                                if response.status != 200:
                                    raise RuntimeError(f"unexpected HTTP status for {route}: {response.status}")
                                if "javascript" not in ctype.lower() and route != "/":
                                    raise RuntimeError(f"unexpected Content-Type for {route}: {ctype}")
                                if nosniff.lower() != "nosniff":
                                    raise RuntimeError(f"missing nosniff header for {route}: {nosniff}")
                                if expected_marker not in body:
                                    raise RuntimeError(f"{route} does not contain required marker {expected_marker!r}")
                                if route == "/" and b'id="mc-open"' not in body:
                                    raise RuntimeError("frozen dashboard does not render the visible phone-camera launcher")
                                if route == "/" and b'src="/camera-connect.js"' not in body:
                                    raise RuntimeError("frozen dashboard does not load the phone-camera connection script")
                                if route == "/" and b'id="alpr-diag"' not in body:
                                    raise RuntimeError("frozen dashboard does not render the live ALPR diagnostics panel")
                                if route == "/" and b'src="/alpr-diagnostics.js"' not in body:
                                    raise RuntimeError("frozen dashboard does not load the ALPR diagnostics script")
                                if route == "/" and ("script-src 'self'" not in csp or "trusted-types mersad-ui-html dompurify" not in csp):
                                    raise RuntimeError(f"dashboard CSP is missing strict script/Trusted Types directives: {csp}")
                                print(f"PASS: frozen EXE served {route} ({len(body)} bytes; {ctype}; nosniff={nosniff})")
                        api_req = urllib.request.Request(
                            f"http://127.0.0.1:{port}/api/alpr-diagnostics", headers=headers
                        )
                        with urllib.request.urlopen(api_req, timeout=3) as api_response:
                            api_payload = __import__("json").loads(api_response.read().decode("utf-8"))
                            if api_response.status != 200 or api_payload.get("ok") is not True or not isinstance(api_payload.get("cameras"), dict):
                                raise RuntimeError("frozen ALPR diagnostics API returned an invalid payload")
                            print("PASS: frozen EXE served authenticated /api/alpr-diagnostics")
                        return 0
                    except (OSError, urllib.error.URLError, TimeoutError) as exc:
                        last_error = exc
                        time.sleep(1)
                log.flush()
                log_text = log_path.read_text(encoding="utf-8", errors="replace")
                raise RuntimeError(
                    f"Frozen EXE did not serve /dashboard.js before timeout; process_exit={proc.poll()} "
                    f"last_http_error={last_error!r}\n--- frozen server log ---\n{log_text[-12000:]}"
                )
            finally:
                if proc.poll() is None:
                    proc.terminate()
                    try:
                        proc.wait(timeout=8)
                    except subprocess.TimeoutExpired:
                        subprocess.run(["taskkill", "/PID", str(proc.pid), "/T", "/F"],
                                       stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=False)
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as exc:
        print(f"FAIL: {exc}", file=sys.stderr)
        raise SystemExit(1)
