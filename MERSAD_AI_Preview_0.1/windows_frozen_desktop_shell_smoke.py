"""Smoke-test a frozen MERSAD_Desktop.exe without opening a GUI window."""
from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path


def main() -> int:
    if len(sys.argv) != 2:
        print("usage: windows_frozen_desktop_shell_smoke.py path\\to\\MERSAD_Desktop.exe", file=sys.stderr)
        return 2
    exe = Path(sys.argv[1]).resolve()
    if not exe.is_file():
        raise FileNotFoundError(exe)
    backend = exe.parent / "MERSAD_AI.exe"
    if not backend.is_file():
        raise FileNotFoundError(f"Desktop distribution is missing backend executable: {backend}")

    env = os.environ.copy()
    env["PYTHONUTF8"] = "1"
    env["PYTHONIOENCODING"] = "utf-8"
    result = subprocess.run(
        [str(exe), "--self-test"],
        cwd=str(exe.parent),
        env=env,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=90,
        check=False,
    )
    if result.returncode != 0:
        raise RuntimeError(
            "Frozen desktop shell self-test failed.\n"
            f"exit code: {result.returncode}\n"
            f"stdout:\n{result.stdout[-5000:]}\n"
            f"stderr:\n{result.stderr[-5000:]}"
        )
    print("PASS: MERSAD_Desktop.exe loads the packaged pywebview runtime and locates MERSAD_AI.exe")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as exc:
        print(f"FAIL: {exc}", file=sys.stderr)
        raise SystemExit(1)
