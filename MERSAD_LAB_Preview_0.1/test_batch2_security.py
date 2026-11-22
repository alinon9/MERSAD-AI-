#!/usr/bin/env python3
"""Batch 2 focused LAB hardening tests (AUD-009)."""
import os
import re
import ssl
import tempfile
import urllib.error
import urllib.request
import unittest
from unittest import mock

from lab_server import LabServerController, _validate_lab_bind_policy


class LabBatch2SecurityTests(unittest.TestCase):
    def setUp(self):
        self.token = "batch2-lab-test-secret"
        self.ctrl = LabServerController(
            host="127.0.0.1", port=0, token=self.token, require_auth=False
        ).start()
        self.base = f"http://127.0.0.1:{self.ctrl.port}"

    def tearDown(self):
        self.ctrl.stop()

    def request_with_headers(self, path="/", headers=None):
        req = urllib.request.Request(self.base + path, headers=headers or {})
        try:
            with urllib.request.urlopen(req, timeout=3) as response:
                return response.status, dict(response.headers), response.read()
        except urllib.error.HTTPError as exc:
            return exc.code, dict(exc.headers), exc.read()

    def request(self, path="/", headers=None):
        status, _headers, body = self.request_with_headers(path, headers=headers)
        return status, body

    def test_bracketed_ipv6_host_header_is_parsed_without_truncation(self):
        status, _ = self.request(
            "/", headers={"Host": f"[::1]:{self.ctrl.port}"}
        )
        self.assertEqual(status, 200)

    def test_malformed_cookie_is_a_controlled_400(self):
        status, body = self.request("/", headers={"Cookie": "valid=value; broken"})
        self.assertEqual(status, 400)
        self.assertIn("Cookie", body.decode("utf-8"))

    def test_lan_health_requires_explicit_header_token(self):
        self.ctrl.state.allow_lan = True
        status, _ = self.request("/api/health")
        self.assertEqual(status, 401)

    def test_lan_bind_fails_closed_without_explicit_allowlist(self):
        with mock.patch.dict(
            os.environ,
            {"MERSAD_LAB_ALLOWED_HOSTS": "", "MERSAD_LAB_TOKEN": ""},
            clear=False,
        ):
            with self.assertRaises(ValueError):
                _validate_lab_bind_policy("0.0.0.0", allow_lan=True)

    def test_lan_bind_requires_explicit_flag(self):
        with self.assertRaises(ValueError):
            _validate_lab_bind_policy("0.0.0.0", allow_lan=False)

    def test_lan_bind_accepts_explicit_operator_policy(self):
        with tempfile.TemporaryDirectory(prefix="mersad_lab_tls_policy_") as tmp:
            cert = os.path.join(tmp, "lab-test-cert.pem")
            key = os.path.join(tmp, "lab-test-key.pem")
            with open(cert, "w", encoding="ascii") as f:
                f.write("test-certificate-placeholder")
            with open(key, "w", encoding="ascii") as f:
                f.write("test-private-key-placeholder")
            with mock.patch.dict(
                os.environ,
                {
                    "MERSAD_LAB_ALLOWED_HOSTS": "192.168.1.20,lab.local",
                    "MERSAD_LAB_TOKEN": "operator-configured-secret",
                    "MERSAD_LAB_TLS_CERT": cert,
                    "MERSAD_LAB_TLS_KEY": key,
                },
                clear=False,
            ):
                _validate_lab_bind_policy("0.0.0.0", allow_lan=True)

    def test_lan_bind_rejects_missing_tls_certificate_and_key(self):
        with mock.patch.dict(
            os.environ,
            {
                "MERSAD_LAB_ALLOWED_HOSTS": "lab.internal",
                "MERSAD_LAB_TOKEN": "operator-configured-secret",
                "MERSAD_LAB_TLS_CERT": "",
                "MERSAD_LAB_TLS_KEY": "",
            },
            clear=False,
        ):
            with self.assertRaisesRegex(ValueError, "TLS_CERT"):
                _validate_lab_bind_policy("0.0.0.0", allow_lan=True)

    def test_lan_bind_rejects_nonexistent_tls_files(self):
        with mock.patch.dict(
            os.environ,
            {
                "MERSAD_LAB_ALLOWED_HOSTS": "lab.internal",
                "MERSAD_LAB_TOKEN": "operator-configured-secret",
                "MERSAD_LAB_TLS_CERT": "missing-lab-cert.pem",
                "MERSAD_LAB_TLS_KEY": "missing-lab-key.pem",
            },
            clear=False,
        ):
            with self.assertRaisesRegex(ValueError, "files"):
                _validate_lab_bind_policy("0.0.0.0", allow_lan=True)

    def test_lan_controller_wraps_listener_with_tls_12(self):
        with tempfile.TemporaryDirectory(prefix="mersad_lab_tls_context_") as tmp:
            cert = os.path.join(tmp, "lab-test-cert.pem")
            key = os.path.join(tmp, "lab-test-key.pem")
            with open(cert, "w", encoding="ascii") as f:
                f.write("test-certificate-placeholder")
            with open(key, "w", encoding="ascii") as f:
                f.write("test-private-key-placeholder")
            env = {
                "MERSAD_LAB_ALLOWED_HOSTS": "lab.internal",
                "MERSAD_LAB_TOKEN": "operator-configured-secret",
                "MERSAD_LAB_TLS_CERT": cert,
                "MERSAD_LAB_TLS_KEY": key,
            }
            context = mock.Mock()
            context.wrap_socket.side_effect = lambda raw_socket, server_side: raw_socket
            with mock.patch.dict(os.environ, env, clear=False):
                with mock.patch("lab_server.ssl.SSLContext", return_value=context):
                    ctrl = LabServerController(
                        host="0.0.0.0", port=0,
                        token="operator-configured-secret", require_auth=True, allow_lan=True,
                    )
            try:
                self.assertEqual(context.minimum_version, ssl.TLSVersion.TLSv1_2)
                context.load_cert_chain.assert_called_once_with(certfile=cert, keyfile=key)
                context.wrap_socket.assert_called_once()
                self.assertEqual(context.wrap_socket.call_args.kwargs, {"server_side": True})
                self.assertEqual(ctrl.scheme, "https")
            finally:
                ctrl.httpd.server_close()

    def test_lab_ui_uses_external_script_and_strict_script_csp(self):
        status, headers, body = self.request_with_headers(
            "/", headers={"X-Lab-Token": self.token}
        )
        self.assertEqual(status, 200)
        html_text = body.decode("utf-8")
        self.assertRegex(html_text, r'<script\s+src="/lab\.js"\s+defer></script>')
        self.assertNotRegex(html_text, r'<script\b(?![^>]*\bsrc=)[^>]*>[\s\S]*?</script>')
        self.assertNotRegex(html_text, r'\son[a-z]+\s*=')
        csp = headers.get("Content-Security-Policy", "")
        self.assertIn("script-src 'self'", csp)
        self.assertNotIn("script-src 'self' 'unsafe-inline'", csp)
        self.assertIn("object-src 'none'", csp)
        self.assertIn("base-uri 'self'", csp)

    def test_lab_js_is_served_as_a_public_static_asset(self):
        self.ctrl.state.require_auth = True
        status, headers, body = self.request_with_headers("/lab.js")
        self.assertEqual(status, 200)
        self.assertIn("javascript", headers.get("Content-Type", "").lower())
        self.assertIn("function labAuthHeaders", body.decode("utf-8"))

    def test_specific_lan_bind_must_be_listed_and_have_token(self):
        with mock.patch.dict(
            os.environ,
            {"MERSAD_LAB_ALLOWED_HOSTS": "192.168.1.20", "MERSAD_LAB_TOKEN": ""},
            clear=False,
        ):
            with self.assertRaisesRegex(ValueError, "LAB token"):
                _validate_lab_bind_policy("192.168.1.20", allow_lan=True)
        with mock.patch.dict(
            os.environ,
            {"MERSAD_LAB_ALLOWED_HOSTS": "192.168.1.21", "MERSAD_LAB_TOKEN": "configured"},
            clear=False,
        ):
            with self.assertRaisesRegex(ValueError, "include the configured bind address"):
                _validate_lab_bind_policy("192.168.1.20", allow_lan=True, token="configured")


if __name__ == "__main__":
    unittest.main(verbosity=2)
