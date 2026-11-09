"""Regression tests for Windows cp1252 console encoding in prefetch.py.

This test deliberately avoids importing mersad_live or heavy runtime packages.
It extracts and executes only the small console-configuration function from
prefetch.py, so it can run independently and fail only on this regression.
"""
import ast
import io
import pathlib
import sys


PREFETCH = pathlib.Path(__file__).with_name("prefetch.py")


class Cp1252Sink:
    def __init__(self):
        self.encoding = "cp1252"
        self.errors = "strict"
        self.data = bytearray()

    def write(self, value):
        encoded = value.encode(self.encoding, errors=self.errors)
        self.data.extend(encoded)
        return len(value)

    def reconfigure(self, *, encoding, errors):
        self.encoding = encoding
        self.errors = errors


def load_configure_function():
    tree = ast.parse(PREFETCH.read_text(encoding="utf-8"), filename=str(PREFETCH))
    function = next(
        node for node in tree.body
        if isinstance(node, ast.FunctionDef) and node.name == "configure_utf8_console"
    )
    isolated = ast.Module(body=[function], type_ignores=[])
    namespace = {"sys": sys}
    exec(compile(isolated, str(PREFETCH), "exec"), namespace)
    return namespace["configure_utf8_console"]


def test_cp1252_stream_is_reconfigured_before_unicode_progress():
    configure = load_configure_function()
    old_out, old_err = sys.stdout, sys.stderr
    fake_out, fake_err = Cp1252Sink(), Cp1252Sink()
    try:
        sys.stdout, sys.stderr = fake_out, fake_err
        configure()
        # This is the exact glyph used by EasyOCR 1.7.2's progress bar.
        assert fake_out.encoding.lower().replace("_", "-") == "utf-8"
        assert fake_err.encoding.lower().replace("_", "-") == "utf-8"
        assert fake_out.errors == "strict"
        fake_out.write("EasyOCR progress █ 100%")
        fake_err.write("EasyOCR diagnostic ✓")
        assert "█" in fake_out.data.decode("utf-8")
        assert "✓" in fake_err.data.decode("utf-8")
    finally:
        sys.stdout, sys.stderr = old_out, old_err


def test_original_cp1252_failure_is_reproduced():
    stream = Cp1252Sink()
    try:
        stream.write("EasyOCR progress █")
    except UnicodeEncodeError:
        return
    raise AssertionError("Regression fixture failed: cp1252 unexpectedly encoded U+2588")


if __name__ == "__main__":
    test_cp1252_stream_is_reconfigured_before_unicode_progress()
    test_original_cp1252_failure_is_reproduced()
    test_easyocr_transient_gateway_download_retries()
    print("PASS: Windows EasyOCR console + transient download regression (3/3)")


def test_easyocr_transient_gateway_download_retries():
    import ast
    import os
    import pathlib
    import socket
    import tempfile
    import time
    import urllib.error
    from types import SimpleNamespace

    source = PREFETCH.read_text(encoding="utf-8")
    tree = ast.parse(source, filename=str(PREFETCH))
    function = next(
        node for node in tree.body
        if isinstance(node, ast.FunctionDef) and node.name == "install_easyocr_download_retries"
    )
    namespace = {
        "urllib": urllib,
        "os": os,
        "socket": socket,
        "time": time,
        "print": lambda *args, **kwargs: None,
    }
    exec(compile(ast.Module(body=[function], type_ignores=[]), str(PREFETCH), "exec"), namespace)

    with tempfile.TemporaryDirectory() as folder:
        target = pathlib.Path(folder) / "temp.zip"
        attempts = {"count": 0}

        def flaky_download(url, filename=None, reporthook=None, data=None):
            attempts["count"] += 1
            if attempts["count"] < 3:
                raise urllib.error.HTTPError(url, 504, "Gateway Time-out", {}, None)
            pathlib.Path(filename).write_bytes(b"complete-archive")
            return filename, None

        utils = SimpleNamespace(urlretrieve=flaky_download)
        namespace["install_easyocr_download_retries"](utils, retries=4, base_delay=0)
        result = utils.urlretrieve("https://example.invalid/model.zip", str(target))
        assert attempts["count"] == 3, attempts
        assert result[0] == str(target)
        assert target.read_bytes() == b"complete-archive"

    # Permanent errors must not be retried or hidden.
    attempts = {"count": 0}

    def forbidden(url, filename=None, reporthook=None, data=None):
        attempts["count"] += 1
        raise urllib.error.HTTPError(url, 403, "Forbidden", {}, None)

    utils = SimpleNamespace(urlretrieve=forbidden)
    namespace["install_easyocr_download_retries"](utils, retries=4, base_delay=0)
    try:
        utils.urlretrieve("https://example.invalid/model.zip", "unused.zip")
    except urllib.error.HTTPError as exc:
        assert exc.code == 403
    else:
        raise AssertionError("HTTP 403 must fail immediately")
    assert attempts["count"] == 1, attempts
