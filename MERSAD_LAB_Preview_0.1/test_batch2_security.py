#!/usr/bin/env python3
"""Batch 2 focused LAB hardening tests (AUD-009)."""
import os
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

    def request(self, path="/", headers=None):
        req = urllib.request.Request(self.base + path, headers=headers or {})
        try:
            with urllib.request.urlopen(req, timeout=3) as response:
                return response.status, response.read()
        except urllib.error.HTTPError as exc:
            return exc.code, exc.read()

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
        with mock.patch.dict(
            os.environ,
            {
                "MERSAD_LAB_ALLOWED_HOSTS": "192.168.1.20,lab.local",
                "MERSAD_LAB_TOKEN": "operator-configured-secret",
            },
            clear=False,
        ):
            _validate_lab_bind_policy("0.0.0.0", allow_lan=True)

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
