#!/usr/bin/env python3
"""Batch 2 AUD-009 regression tests for MERSAD LAB Host/Origin/auth policy."""
import http.client
import socket
import threading
import unittest
from unittest import mock

import http.cookies
import lab_server


class Batch2LabHostSecurityTests(unittest.TestCase):
    def setUp(self):
        self.ctrl = lab_server.LabServerController(
            host="127.0.0.1", port=0, token="batch2-test-token", require_auth=False
        )
        self.ctrl.start()
        self.port = self.ctrl.port

    def tearDown(self):
        self.ctrl.stop()

    def _raw_get(self, host_header, path="/api/health"):
        sock = socket.create_connection(("127.0.0.1", self.port), timeout=3)
        try:
            request = (
                f"GET {path} HTTP/1.1\r\n"
                f"Host: {host_header}\r\n"
                "Connection: close\r\n\r\n"
            ).encode("ascii")
            sock.sendall(request)
            chunks = []
            while True:
                part = sock.recv(4096)
                if not part:
                    break
                chunks.append(part)
            response = b"".join(chunks)
            return int(response.split(b" ", 2)[1]), response
        finally:
            sock.close()

    def test_host_must_match_actual_local_socket_ip_and_port(self):
        status, _ = self._raw_get(f"127.0.0.1:{self.port}")
        self.assertEqual(status, 200)

        status, _ = self._raw_get(f"192.168.1.25:{self.port}")
        self.assertEqual(status, 403)

        status, _ = self._raw_get(f"127.0.0.1:{self.port + 1}")
        self.assertEqual(status, 403)

    def test_missing_host_is_rejected(self):
        sock = socket.create_connection(("127.0.0.1", self.port), timeout=3)
        try:
            sock.sendall(
                b"GET /api/health HTTP/1.1\r\nConnection: close\r\n\r\n"
            )
            raw = b""
            while True:
                part = sock.recv(4096)
                if not part:
                    break
                raw += part
            self.assertIn(b" 403 ", raw.split(b"\r\n", 1)[0])
        finally:
            sock.close()

    def test_lan_mode_requires_authentication_on_health_endpoint(self):
        lan_ctrl = lab_server.LabServerController(
            host="127.0.0.1", port=0, token="batch2-test-token", require_auth=True
        )
        lan_ctrl.start()
        try:
            conn = http.client.HTTPConnection("127.0.0.1", lan_ctrl.port, timeout=3)
            conn.request("GET", "/api/health")
            response = conn.getresponse()
            self.assertEqual(response.status, 401)
            response.read()
            conn.close()

            conn = http.client.HTTPConnection("127.0.0.1", lan_ctrl.port, timeout=3)
            conn.request("GET", "/api/health", headers={"X-Lab-Token": "batch2-test-token"})
            response = conn.getresponse()
            self.assertEqual(response.status, 200)
            response.read()
            conn.close()
        finally:
            lan_ctrl.stop()

    def test_cookie_parser_error_fails_closed_with_401(self):
        with mock.patch.object(
            http.cookies.SimpleCookie,
            "load",
            side_effect=http.cookies.CookieError("malformed cookie"),
        ):
            conn = http.client.HTTPConnection("127.0.0.1", self.port, timeout=3)
            conn.request(
                "GET",
                "/api/cameras",
                headers={"Cookie": "mersad_lab_k=broken"},
            )
            response = conn.getresponse()
            self.assertEqual(response.status, 401)
            response.read()
            conn.close()


    def test_non_loopback_bind_is_rejected_before_socket_creation(self):
        with mock.patch.object(lab_server, "LabHTTPServer") as server_factory:
            with self.assertRaises(ValueError):
                lab_server.LabServerController(host="0.0.0.0", port=0, allow_lan=False)
            server_factory.assert_not_called()

    def test_explicit_lan_bind_forces_authentication(self):
        fake_server = mock.MagicMock()
        fake_server.server_address = ("0.0.0.0", 8090)
        with mock.patch.object(lab_server, "LabHTTPServer", return_value=fake_server) as server_factory:
            controller = lab_server.LabServerController(
                host="0.0.0.0", port=8090, token="batch2-test-token",
                require_auth=False, allow_lan=True,
            )
        self.assertTrue(controller.state.require_auth)
        self.assertIs(controller.httpd, fake_server)
        server_factory.assert_called_once()


if __name__ == "__main__":
    unittest.main(verbosity=2)
