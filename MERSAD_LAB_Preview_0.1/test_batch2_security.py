#!/usr/bin/env python3
"""Focused Batch 2 security regressions for MERSAD LAB LAN/Host/auth controls."""
import http.cookies
import json
import os
import unittest
import urllib.error
import urllib.request
from types import SimpleNamespace
from unittest import mock

import lab_server


class _HandlerProbe:
    _validate_host_and_origin = lab_server.LabRequestHandler._validate_host_and_origin

    def __init__(self, host, server):
        self.headers = {"Host": host}
        self.server = server
        self.errors = []

    def _json(self, payload, code=200):
        self.errors.append((payload, code))


class Batch2LabLanSecurityTests(unittest.TestCase):
    def test_ipv6_host_with_port_is_parsed_and_accepted(self):
        server = SimpleNamespace(server_address=("::1", 8090), is_lan=False)
        probe = _HandlerProbe("[::1]:8090", server)
        self.assertTrue(probe._validate_host_and_origin())
        self.assertEqual(probe.errors, [])

    def test_mismatched_host_port_is_rejected(self):
        server = SimpleNamespace(server_address=("::1", 8090), is_lan=False)
        probe = _HandlerProbe("[::1]:8091", server)
        self.assertFalse(probe._validate_host_and_origin())
        self.assertEqual(probe.errors[-1][1], 403)

    def test_explicit_lan_host_allowlist_is_honored(self):
        server = SimpleNamespace(server_address=("0.0.0.0", 8090), is_lan=True)
        probe = _HandlerProbe("192.168.50.8:8090", server)
        with mock.patch.dict(os.environ, {"MERSAD_LAB_ALLOWED_HOSTS": "192.168.50.8"}, clear=False):
            self.assertTrue(probe._validate_host_and_origin())

    def test_lan_health_requires_explicit_authentication(self):
        controller = lab_server.LabServerController(
            host="0.0.0.0", port=0, token="batch2-test-token", require_auth=False, allow_lan=True
        )
        controller.start()
        try:
            url = f"http://127.0.0.1:{controller.port}/api/health"
            with self.assertRaises(urllib.error.HTTPError) as denied:
                urllib.request.urlopen(url, timeout=3)
            self.assertEqual(denied.exception.code, 401)
            req = urllib.request.Request(url, headers={"X-Lab-Token": "batch2-test-token"})
            with urllib.request.urlopen(req, timeout=3) as response:
                payload = json.loads(response.read().decode("utf-8"))
            self.assertTrue(payload["ok"])
        finally:
            controller.stop()

    def test_non_loopback_bind_is_rejected_before_server_socket_creation(self):
        with mock.patch.object(lab_server, "LabHTTPServer") as http_server:
            with self.assertRaises(ValueError):
                lab_server.LabServerController(host="0.0.0.0", port=0, allow_lan=False)
            http_server.assert_not_called()

    def test_malformed_cookie_is_contained(self):
        with mock.patch("lab_server.http.cookies.SimpleCookie", side_effect=http.cookies.CookieError("bad cookie")):
            self.assertEqual(lab_server._safe_lab_cookie_token("mersad_lab_k=broken"), "")


if __name__ == "__main__":
    unittest.main(verbosity=2)
