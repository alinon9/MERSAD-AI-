#!/usr/bin/env python
"""MERSAD AI Windows desktop shell.

The existing AI process remains the owner of cameras, models, database and HTTP
APIs. This launcher starts that process on loopback and hosts its authenticated
dashboard in a native WebView2 window (no external browser tab).
"""
from __future__ import annotations

import argparse
import ctypes
import json
import os
import secrets
import socket
import subprocess
import sys
import time
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

APP_TITLE = "مرصاد الذكي | MERSAD AI"
WEBVIEW2_DOWNLOAD_URL = "https://developer.microsoft.com/en-us/microsoft-edge/webview2/"
WEBVIEW2_CLIENT_GUID = "{F3017226-FE2A-4295-8BDF-00C3A9A7E4C5}"
STARTUP_TIMEOUT_SECONDS = 240.0
BACKEND_SHUTDOWN_TIMEOUT_SECONDS = 15.0


def application_directory() -> Path:
    """Return the installed distribution folder, not PyInstaller's temp folder."""
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parent


def reserve_loopback_port() -> int:
    """Ask Windows for an available local TCP port."""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


def backend_command(root: Path, port: int, token: str) -> list[str]:
    """Build a private loopback-only command for the existing MERSAD engine."""
    common = [
        "--host", "127.0.0.1",
        "--port", str(port),
        "--token", token,
        "--no-window",
    ]
    if getattr(sys, "frozen", False):
        backend = root / "MERSAD_AI.exe"
        if not backend.is_file():
            raise FileNotFoundError(
                "MERSAD_AI.exe is missing beside MERSAD_Desktop.exe. "
                "Reinstall the complete MERSAD AI distribution."
            )
        return [str(backend), *common]

    source = root / "mersad_live.py"
    if not source.is_file():
        raise FileNotFoundError(f"MERSAD engine source was not found: {source}")
    return [sys.executable, "-u", str(source), *common]


def webview2_runtime_version() -> str | None:
    """Read the documented Evergreen WebView2 Runtime registry locations."""
    if sys.platform != "win32":
        return None
    try:
        import winreg
    except ImportError:
        return None

    locations = [
        (winreg.HKEY_LOCAL_MACHINE,
         rf"SOFTWARE\WOW6432Node\Microsoft\EdgeUpdate\Clients\{WEBVIEW2_CLIENT_GUID}"),
        (winreg.HKEY_CURRENT_USER,
         rf"Software\Microsoft\EdgeUpdate\Clients\{WEBVIEW2_CLIENT_GUID}"),
        (winreg.HKEY_LOCAL_MACHINE,
         rf"SOFTWARE\Microsoft\EdgeUpdate\Clients\{WEBVIEW2_CLIENT_GUID}"),
    ]
    for hive, subkey in locations:
        try:
            with winreg.OpenKey(hive, subkey) as key:
                value, _kind = winreg.QueryValueEx(key, "pv")
            version = str(value).strip()
            parts = [int(p) for p in version.split(".") if p.isdigit()]
            if parts and any(parts):
                return version
        except (OSError, ValueError, TypeError):
            continue
    return None


def wait_for_backend(
    process: subprocess.Popen,
    port: int,
    token: str,
    timeout: float = STARTUP_TIMEOUT_SECONDS,
) -> None:
    """Wait until the authenticated backend API is ready or fail with context."""
    deadline = time.monotonic() + max(1.0, float(timeout))
    endpoint = f"http://127.0.0.1:{port}/api/ping"
    last_error: Exception | None = None

    while time.monotonic() < deadline:
        exit_code = process.poll()
        if exit_code is not None:
            raise RuntimeError(
                f"MERSAD engine stopped during startup (exit code {exit_code}). "
                "Open the log file under the MERSAD data folder for details."
            )

        req = Request(
            endpoint,
            headers={
                "X-Mersad-Token": token,
                "Host": f"127.0.0.1:{port}",
                "Cache-Control": "no-store",
            },
            method="GET",
        )
        try:
            with urlopen(req, timeout=1.5) as response:
                payload = json.loads(response.read().decode("utf-8"))
                if response.status == 200 and payload.get("ok") is True:
                    return
                last_error = RuntimeError("Backend returned an unexpected readiness response")
        except (HTTPError, URLError, TimeoutError, OSError, ValueError) as exc:
            last_error = exc
        time.sleep(0.4)

    raise TimeoutError(
        f"MERSAD engine did not become ready within {timeout:.0f} seconds. "
        f"Last connection result: {last_error!r}"
    )


def request_backend_shutdown(port: int, token: str, timeout: float = 3.0) -> bool:
    """Ask the backend to execute its normal cleanup path."""
    req = Request(
        f"http://127.0.0.1:{port}/api/desktop/shutdown",
        data=b"{}",
        headers={
            "X-Mersad-Token": token,
            "Content-Type": "application/json",
            "Host": f"127.0.0.1:{port}",
            "Cache-Control": "no-store",
        },
        method="POST",
    )
    try:
        with urlopen(req, timeout=timeout) as response:
            payload = json.loads(response.read().decode("utf-8"))
            return response.status == 200 and payload.get("ok") is True
    except (HTTPError, URLError, TimeoutError, OSError, ValueError):
        return False


def stop_backend(process: subprocess.Popen | None, port: int, token: str) -> None:
    """Stop cleanly first; use process termination only as a last resort."""
    if process is None or process.poll() is not None:
        return

    request_backend_shutdown(port, token)
    try:
        process.wait(timeout=BACKEND_SHUTDOWN_TIMEOUT_SECONDS)
        return
    except subprocess.TimeoutExpired:
        pass

    process.terminate()
    try:
        process.wait(timeout=5.0)
    except subprocess.TimeoutExpired:
        process.kill()
        try:
            process.wait(timeout=3.0)
        except subprocess.TimeoutExpired:
            pass


def show_error(message: str) -> None:
    """Show a Windows-native error dialog, with a console fallback for development."""
    if sys.platform == "win32":
        try:
            ctypes.windll.user32.MessageBoxW(None, message, APP_TITLE, 0x10 | 0x1000)
            return
        except Exception:
            pass
    print(f"{APP_TITLE}: {message}", file=sys.stderr)


def self_test() -> int:
    """Validate the frozen shell payload without opening a window or starting AI."""
    try:
        import webview
        if not callable(getattr(webview, "create_window", None)):
            raise RuntimeError("pywebview is present but create_window is unavailable")
        if getattr(sys, "frozen", False):
            backend = application_directory() / "MERSAD_AI.exe"
            if not backend.is_file():
                raise FileNotFoundError(f"Missing backend executable: {backend}")
        print("PASS: desktop shell imports pywebview and resolves its backend payload")
        return 0
    except Exception as exc:
        print(f"FAIL: desktop shell package check: {exc}", file=sys.stderr)
        return 1


def run_desktop() -> int:
    if sys.platform != "win32":
        show_error("واجهة مرصاد المكتبية متاحة حالياً على Windows فقط.")
        return 2

    runtime_version = webview2_runtime_version()
    if not runtime_version:
        show_error(
            "مكوّن تشغيل نافذة مرصاد غير موجود.\n\n"
            "ثبّت Microsoft Edge WebView2 Runtime ثم أعد تشغيل مرصاد:\n"
            f"{WEBVIEW2_DOWNLOAD_URL}\n\n"
            "هذا مكوّن عرض مدمج داخل البرنامج، ولا يفتح متصفحاً خارجياً."
        )
        return 3

    try:
        import webview
    except Exception as exc:
        show_error(f"تعذّر تحميل مكوّن واجهة سطح المكتب:\n{exc}")
        return 4

    root = application_directory()
    port = reserve_loopback_port()
    token = secrets.token_urlsafe(32)
    command = backend_command(root, port, token)

    local_app_data = os.environ.get("LOCALAPPDATA")
    log_root = Path(local_app_data) if local_app_data else Path.home() / ".mersad"
    log_dir = log_root / "MERSAD_AI" / "logs"
    log_dir.mkdir(parents=True, exist_ok=True)
    log_path = log_dir / "desktop-backend.log"

    process = None
    log_handle = None
    try:
        log_handle = log_path.open("ab", buffering=0)
        creation_flags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
        env = os.environ.copy()
        env.setdefault("PYTHONUTF8", "1")
        env.setdefault("PYTHONIOENCODING", "utf-8")
        process = subprocess.Popen(
            command,
            cwd=str(root),
            env=env,
            stdin=subprocess.DEVNULL,
            stdout=log_handle,
            stderr=subprocess.STDOUT,
            creationflags=creation_flags,
        )
        wait_for_backend(process, port, token)
        dashboard_url = f"http://127.0.0.1:{port}/?k={token}"

        webview.create_window(
            APP_TITLE,
            url=dashboard_url,
            width=1360,
            height=820,
            min_size=(960, 640),
            resizable=True,
            text_select=True,
            background_color="#0b1220",
        )
        # Explicitly use the app runtime, not an external Edge browser window.
        webview.start(gui="edgechromium", debug=False)
        return 0
    except Exception as exc:
        show_error(
            "تعذّر تشغيل واجهة مرصاد المكتبية.\n\n"
            f"{exc}\n\n"
            f"سجل التشغيل:\n{log_path}"
        )
        return 5
    finally:
        stop_backend(process, port, token)
        if log_handle:
            try:
                log_handle.close()
            except OSError:
                pass


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=APP_TITLE)
    parser.add_argument("--self-test", action="store_true", help="Check the packaged desktop shell")
    args = parser.parse_args(argv)
    if args.self_test:
        return self_test()
    return run_desktop()


if __name__ == "__main__":
    raise SystemExit(main())
