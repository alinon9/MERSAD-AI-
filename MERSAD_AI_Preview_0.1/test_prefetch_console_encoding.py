"""Regression tests for Windows cp1252 console encoding in prefetch.py."""
import importlib.util
import io
import pathlib
import subprocess
import sys


PREFETCH = pathlib.Path(__file__).with_name("prefetch.py")


class Cp1252Sink(io.TextIOBase):
    """Minimal text stream that reproduces the failing Windows cp1252 encode."""
    encoding = "cp1252"

    def __init__(self):
        self.buffer = io.BytesIO()

    def writable(self):
        return True

    def write(self, text):
        encoded = text.encode(self.encoding, errors="strict")
        self.buffer.write(encoded)
        return len(text)

    def flush(self):
        return None


def test_console_reconfigure_to_utf8():
    spec = importlib.util.spec_from_file_location("mersad_prefetch_test", PREFETCH)
    module = importlib.util.module_from_spec(spec)
    # prefetch.py imports mersad_live; test this helper via isolated AST-free
    # import only when project dependencies are installed in CI.
    spec.loader.exec_module(module)
    stream = Cp1252Sink()
    calls = []

    class ReconfigurableStream:
        def reconfigure(self, *, encoding, errors):
            calls.append((encoding, errors))
            self.encoding = encoding
            self.errors = errors

    old_out, old_err = sys.stdout, sys.stderr
    fake_out, fake_err = ReconfigurableStream(), ReconfigurableStream()
    try:
        sys.stdout, sys.stderr = fake_out, fake_err
        module.configure_utf8_console()
    finally:
        sys.stdout, sys.stderr = old_out, old_err
    assert calls == [("utf-8", "strict"), ("utf-8", "strict")]
    # Demonstrate the original failure and UTF-8 success independently.
    try:
        stream.write("progress █")
    except UnicodeEncodeError:
        pass
    else:
        raise AssertionError("cp1252 must reject the EasyOCR progress block")
    assert "progress █".encode("utf-8").decode("utf-8") == "progress █"


if __name__ == "__main__":
    test_console_reconfigure_to_utf8()
    print("PASS: Windows cp1252 EasyOCR progress regression")
