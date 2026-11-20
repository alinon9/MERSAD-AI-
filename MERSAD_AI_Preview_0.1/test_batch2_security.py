#!/usr/bin/env python3
"""Batch 2 server-side regression tests for AUD-005/007/010/014."""
import contextlib
import io
import os
import tempfile
import threading
import urllib.error
import urllib.request
import unittest
from http.server import ThreadingHTTPServer
from unittest import mock

import notify
import server as mersad_server


class MersadBatch2SecurityTests(unittest.TestCase):
    def setUp(self):
        self.old_token = mersad_server.bus.token
        mersad_server.bus.token = "batch2-server-test-secret"
        mersad_server.bus.auth_failures.clear()
        self.httpd = ThreadingHTTPServer(("127.0.0.1", 0), mersad_server.H)
        self.thread = threading.Thread(target=self.httpd.serve_forever, daemon=True)
        self.thread.start()
        self.base = f"http://127.0.0.1:{self.httpd.server_address[1]}"

    def tearDown(self):
        self.httpd.shutdown()
        self.httpd.server_close()
        self.thread.join(timeout=2)
        mersad_server.bus.token = self.old_token
        mersad_server.bus.auth_failures.clear()

    def request(self, path="/", method="GET", headers=None, data=None):
        req = urllib.request.Request(self.base + path, method=method, headers=headers or {}, data=data)
        try:
            with urllib.request.urlopen(req, timeout=3) as response:
                return response.status, dict(response.headers), response.read()
        except urllib.error.HTTPError as exc:
            return exc.code, dict(exc.headers), exc.read()

    def test_bracketed_ipv6_host_is_parsed_and_wrong_port_rejected(self):
        # Supply a valid credential so this assertion isolates Host parsing
        # from the independent authentication layer.
        status, _, _ = self.request(
            "/",
            headers={
                "Host": f"[::1]:{self.httpd.server_address[1]}",
                "X-Mersad-Token": "batch2-server-test-secret",
            },
        )
        self.assertEqual(status, 200)

        wrong_status, _, _ = self.request(
            "/", headers={"Host": "localhost:1"}
        )
        self.assertEqual(wrong_status, 400)

    def test_post_without_origin_requires_explicit_header_even_with_cookie(self):
        status, _, body = self.request(
            "/api/does-not-exist",
            method="POST",
            headers={
                "Cookie": "mersad_k=batch2-server-test-secret",
                "Content-Type": "application/json",
            },
            data=b"{}",
        )
        self.assertEqual(status, 403)
        self.assertIn(b"X-Mersad-Token", body)

    def test_post_without_origin_accepts_explicit_auth_header(self):
        status, _, _ = self.request(
            "/api/does-not-exist",
            method="POST",
            headers={
                "X-Mersad-Token": "batch2-server-test-secret",
                "Content-Type": "application/json",
            },
            data=b"{}",
        )
        self.assertEqual(status, 404)

    def test_post_malformed_json_returns_http_400(self):
        route = "/api/batch2-test-malformed"
        mersad_server.bus.post[route] = lambda payload, ip: {"ok": True}
        try:
            status, _, _ = self.request(
                route,
                method="POST",
                headers={
                    "X-Mersad-Token": "batch2-server-test-secret",
                    "Content-Type": "application/json",
                },
                data=b"{",
            )
            self.assertEqual(status, 400)
        finally:
            mersad_server.bus.post.pop(route, None)

    def test_post_unexpected_handler_exception_returns_http_500(self):
        route = "/api/batch2-test-exception"
        def fail_handler(payload, ip):
            raise RuntimeError("private implementation detail")
        mersad_server.bus.post[route] = fail_handler
        try:
            status, _, body = self.request(
                route,
                method="POST",
                headers={
                    "X-Mersad-Token": "batch2-server-test-secret",
                    "Content-Type": "application/json",
                },
                data=b"{}",
            )
            self.assertEqual(status, 500)
            self.assertNotIn(b"private implementation detail", body)
        finally:
            mersad_server.bus.post.pop(route, None)

    def test_post_handled_business_rejection_remains_json_http_200(self):
        route = "/api/batch2-test-business"
        mersad_server.bus.post[route] = lambda payload, ip: {"ok": False, "reason": "not-applicable"}
        try:
            status, _, body = self.request(
                route,
                method="POST",
                headers={
                    "X-Mersad-Token": "batch2-server-test-secret",
                    "Content-Type": "application/json",
                },
                data=b"{}",
            )
            self.assertEqual(status, 200)
            self.assertFalse(__import__("json").loads(body.decode("utf-8"))["ok"])
        finally:
            mersad_server.bus.post.pop(route, None)

    def test_lan_startup_rejects_missing_tls_before_binding(self):
        with mock.patch.dict(
            os.environ,
            {
                "MERSAD_TLS_CERT": "",
                "MERSAD_TLS_KEY": "",
                "MERSAD_ALLOWED_HOSTS": "",
            },
            clear=False,
        ):
            with self.assertRaisesRegex(RuntimeError, "TLS"):
                mersad_server.start_server(port=0, host="0.0.0.0")

    def test_loopback_startup_does_not_print_session_secret_and_stops_cleanly(self):
        with tempfile.TemporaryDirectory(prefix="mersad_batch2_") as tmp:
            token_file = os.path.join(tmp, "session.token")
            out = io.StringIO()
            with mock.patch.dict(os.environ, {"MERSAD_TOKEN_FILE": token_file}, clear=False):
                with contextlib.redirect_stdout(out):
                    srv = mersad_server.start_server(port=0, host="127.0.0.1")
                try:
                    self.assertTrue(os.path.isfile(token_file))
                    with open(token_file, "r", encoding="utf-8") as handle:
                        stored_token = handle.read().strip()
                    self.assertTrue(stored_token)
                    self.assertNotIn(stored_token, out.getvalue())
                    self.assertNotIn(stored_token, out.getvalue())
                finally:
                    # Exercise the legacy direct shutdown path; it must also
                    # signal all long-lived SSE/MJPEG request loops to exit.
                    srv.shutdown()
                    srv.server_close()
                    srv._mersad_thread.join(timeout=2)
            self.assertTrue(mersad_server.bus.stop_event.is_set())
            self.assertFalse(srv._mersad_thread.is_alive())

    def test_telegram_remote_http_is_rejected(self):
        with mock.patch.dict(
            os.environ,
            {
                "TELEGRAM_API": "http://203.0.113.10",
                "MERSAD_ALLOW_INSECURE_TELEGRAM_TEST": "1",
            },
            clear=False,
        ):
            with self.assertRaises(ValueError):
                notify._telegram_api_base()

    def test_telegram_loopback_http_requires_explicit_test_opt_in(self):
        with mock.patch.dict(
            os.environ,
            {
                "TELEGRAM_API": "http://127.0.0.1:8780",
                "MERSAD_ALLOW_INSECURE_TELEGRAM_TEST": "1",
            },
            clear=False,
        ):
            self.assertEqual(notify._telegram_api_base(), "http://127.0.0.1:8780")

    def test_telegram_production_endpoint_defaults_to_https_allowlist(self):
        with mock.patch.dict(os.environ, {}, clear=True):
            self.assertEqual(notify._telegram_api_base(), "https://api.telegram.org")


if __name__ == "__main__":
    unittest.main(verbosity=2)
