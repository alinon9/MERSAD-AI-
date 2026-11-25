"""Regression tests for the MERSAD Windows desktop shell."""
from __future__ import annotations

import json
import socket
import subprocess
import sys
import threading
import tempfile
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from unittest.mock import Mock, patch

import desktop_shell


class DesktopShellTests(unittest.TestCase):
    def test_source_backend_command_is_loopback_only_and_headless(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "mersad_live.py").write_text("# source", encoding="utf-8")
            with patch.object(desktop_shell.sys, "frozen", False, create=True):
                command = desktop_shell.backend_command(root, 8123, "test-secret")
        self.assertEqual(command[0], sys.executable)
        self.assertIn("--host", command)
        self.assertEqual(command[command.index("--host") + 1], "127.0.0.1")
        self.assertEqual(command[command.index("--port") + 1], "8123")
        self.assertEqual(command[command.index("--token") + 1], "test-secret")
        self.assertIn("--no-window", command)

    def test_frozen_backend_command_uses_sibling_exe(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            backend = root / "MERSAD_AI.exe"
            backend.write_bytes(b"test")
            with patch.object(desktop_shell.sys, "frozen", True, create=True):
                command = desktop_shell.backend_command(root, 8124, "another-secret")
        self.assertEqual(command[0], str(backend))
        self.assertIn("--no-window", command)

    def test_missing_frozen_backend_is_reported(self):
        with tempfile.TemporaryDirectory() as tmp:
            with patch.object(desktop_shell.sys, "frozen", True, create=True):
                with self.assertRaises(FileNotFoundError):
                    desktop_shell.backend_command(Path(tmp), 8125, "x")

    def test_readiness_probe_sends_explicit_authentication(self):
        received = {}

        class Handler(BaseHTTPRequestHandler):
            def do_GET(self):
                received["token"] = self.headers.get("X-Mersad-Token")
                received["host"] = self.headers.get("Host")
                body = json.dumps({"ok": True}).encode("utf-8")
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

            def log_message(self, *_args):
                pass

        server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        worker = threading.Thread(target=server.serve_forever, daemon=True)
        worker.start()
        try:
            process = Mock()
            process.poll.return_value = None
            desktop_shell.wait_for_backend(
                process, server.server_address[1], "probe-secret", timeout=2.0
            )
        finally:
            server.shutdown()
            server.server_close()
            worker.join(timeout=2.0)

        self.assertEqual(received.get("token"), "probe-secret")
        self.assertEqual(received.get("host"), f"127.0.0.1:{server.server_address[1]}")

    def test_shutdown_request_uses_token_and_json(self):
        received = {}

        class Handler(BaseHTTPRequestHandler):
            def do_POST(self):
                received["path"] = self.path
                received["token"] = self.headers.get("X-Mersad-Token")
                received["content_type"] = self.headers.get("Content-Type")
                length = int(self.headers.get("Content-Length", "0"))
                received["body"] = self.rfile.read(length)
                body = json.dumps({"ok": True}).encode("utf-8")
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

            def log_message(self, *_args):
                pass

        server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        worker = threading.Thread(target=server.serve_forever, daemon=True)
        worker.start()
        try:
            ok = desktop_shell.request_backend_shutdown(
                server.server_address[1], "shutdown-secret"
            )
        finally:
            server.shutdown()
            server.server_close()
            worker.join(timeout=2.0)

        self.assertTrue(ok)
        self.assertEqual(received.get("path"), "/api/desktop/shutdown")
        self.assertEqual(received.get("token"), "shutdown-secret")
        self.assertEqual(received.get("content_type"), "application/json")
        self.assertEqual(received.get("body"), b"{}")

    def test_readiness_fails_when_backend_exits(self):
        process = Mock()
        process.poll.return_value = 17
        with self.assertRaisesRegex(RuntimeError, "exit code 17"):
            desktop_shell.wait_for_backend(process, 8126, "token", timeout=1.0)


if __name__ == "__main__":
    unittest.main(verbosity=2)
