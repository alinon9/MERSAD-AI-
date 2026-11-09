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
    print("PASS: Windows cp1252 EasyOCR progress encoding regression (2/2)")
