#!/usr/bin/env python3
"""Batch 1 production-module security regressions for MERSAD LAB."""
import ipaddress
import os
import socket
import ssl
import unittest
from unittest import mock

import lab_server


class DummySocket:
    def __init__(self):
        self.connected_to = None
        self.timeout = None
        self.closed = False

    def settimeout(self, value):
        self.timeout = value

    def connect(self, address):
        self.connected_to = address

    def close(self):
        self.closed = True


class DummyTLSContext:
    def __init__(self, check_hostname=True, verify_mode=ssl.CERT_REQUIRED, error=None):
        self.check_hostname = check_hostname
        self.verify_mode = verify_mode
        self.error = error
        self.wrap_calls = []

    def wrap_socket(self, raw_socket, server_hostname=None):
        self.wrap_calls.append((raw_socket, server_hostname))
        if self.error:
            raise self.error
        return raw_socket


def dns_record(family, address, port=8765):
    sockaddr = (address, port, 0, 0) if family == socket.AF_INET6 else (address, port)
    return (family, socket.SOCK_STREAM, socket.IPPROTO_TCP, "", sockaddr)


class Batch1LabSecurityTests(unittest.TestCase):
    def test_default_local_ai_server_port_8000_is_allowed(self):
        target = lab_server._validate_ai_connect_url("http://127.0.0.1:8000")
        self.assertEqual(target["port"], 8000)
        self.assertEqual(target["pinned_ip"], "127.0.0.1")

    def test_loopback_ipv4_http_is_allowed_without_dns(self):
        with mock.patch("lab_server.socket.getaddrinfo") as getaddrinfo:
            target = lab_server._validate_ai_connect_url("http://127.0.0.1:8765")
        self.assertEqual(target["pinned_ip"], "127.0.0.1")
        getaddrinfo.assert_not_called()

    def test_localhost_https_accepts_only_loopback_ipv4_and_ipv6(self):
        records = [
            dns_record(socket.AF_INET, "127.0.0.1"),
            dns_record(socket.AF_INET6, "::1"),
        ]
        with mock.patch.dict(os.environ, {"MERSAD_LAB_ALLOWED_AI_HOSTS": ""}, clear=False):
            with mock.patch("lab_server.socket.getaddrinfo", return_value=records) as getaddrinfo:
                target = lab_server._validate_ai_connect_url("https://localhost:8765")
        self.assertIn(target["pinned_ip"], {"127.0.0.1", "::1"})
        getaddrinfo.assert_called_once()

    def test_localhost_https_rejects_external_dns(self):
        records = [dns_record(socket.AF_INET, "93.184.216.34")]
        with mock.patch("lab_server.socket.getaddrinfo", return_value=records):
            with self.assertRaises(ValueError):
                lab_server._validate_ai_connect_url("https://localhost:8765")

    def test_localhost_https_rejects_mixed_loopback_and_private_dns(self):
        records = [
            dns_record(socket.AF_INET, "127.0.0.1"),
            dns_record(socket.AF_INET, "10.20.30.40"),
        ]
        with mock.patch("lab_server.socket.getaddrinfo", return_value=records):
            with self.assertRaises(ValueError):
                lab_server._validate_ai_connect_url("https://localhost:8765")

    def test_ipv6_loopback_literal_is_allowed(self):
        target = lab_server._validate_ai_connect_url("https://[::1]:8765")
        self.assertEqual(str(ipaddress.ip_address(target["pinned_ip"])), "::1")

    def test_unlisted_remote_host_is_rejected_before_dns(self):
        with mock.patch.dict(os.environ, {"MERSAD_LAB_ALLOWED_AI_HOSTS": ""}, clear=False):
            with mock.patch("lab_server.socket.getaddrinfo") as getaddrinfo:
                with self.assertRaises(ValueError):
                    lab_server._validate_ai_connect_url("https://evil.example.com:443")
        getaddrinfo.assert_not_called()

    def test_explicit_internal_host_allowlist_accepts_private_ipv4(self):
        records = [dns_record(socket.AF_INET, "10.20.30.40", 8443)]
        env = {
            "MERSAD_LAB_ALLOWED_AI_HOSTS": "ai.internal.local",
            "MERSAD_LAB_ALLOWED_AI_PORTS": "8443",
        }
        with mock.patch.dict(os.environ, env, clear=False):
            with mock.patch("lab_server.socket.getaddrinfo", return_value=records):
                target = lab_server._validate_ai_connect_url("https://ai.internal.local:8443")
        self.assertEqual(target["pinned_ip"], "10.20.30.40")

    def test_explicit_internal_host_allowlist_accepts_unique_local_ipv6(self):
        records = [dns_record(socket.AF_INET6, "fd00::10", 8443)]
        env = {
            "MERSAD_LAB_ALLOWED_AI_HOSTS": "ai6.internal.local",
            "MERSAD_LAB_ALLOWED_AI_PORTS": "8443",
        }
        with mock.patch.dict(os.environ, env, clear=False):
            with mock.patch("lab_server.socket.getaddrinfo", return_value=records):
                target = lab_server._validate_ai_connect_url("https://ai6.internal.local:8443")
        self.assertEqual(str(ipaddress.ip_address(target["pinned_ip"])), "fd00::10")

    def test_allowlisted_remote_rejects_mixed_dns_with_link_local(self):
        records = [
            dns_record(socket.AF_INET, "10.20.30.40", 8443),
            dns_record(socket.AF_INET, "169.254.169.254", 8443),
        ]
        env = {
            "MERSAD_LAB_ALLOWED_AI_HOSTS": "ai.internal.local",
            "MERSAD_LAB_ALLOWED_AI_PORTS": "8443",
        }
        with mock.patch.dict(os.environ, env, clear=False):
            with mock.patch("lab_server.socket.getaddrinfo", return_value=records):
                with self.assertRaises(ValueError):
                    lab_server._validate_ai_connect_url("https://ai.internal.local:8443")

    def test_http_is_not_allowed_for_remote_allowlisted_hosts(self):
        env = {"MERSAD_LAB_ALLOWED_AI_HOSTS": "ai.internal.local"}
        with mock.patch.dict(os.environ, env, clear=False):
            with mock.patch("lab_server.socket.getaddrinfo") as getaddrinfo:
                with self.assertRaises(ValueError):
                    lab_server._validate_ai_connect_url("http://ai.internal.local:8765")
        getaddrinfo.assert_not_called()

    def test_http_connection_uses_only_pinned_numeric_ip(self):
        dummy = DummySocket()
        conn = lab_server._PinnedIPHTTPConnection(
            host="ai.internal.local", port=8443, pinned_ip="10.20.30.40", timeout=1.0
        )
        with mock.patch("lab_server.socket.socket", return_value=dummy):
            conn.connect()
        self.assertEqual(dummy.connected_to, ("10.20.30.40", 8443))
        conn.close()

    def test_https_connection_pins_ip_and_preserves_sni(self):
        dummy = DummySocket()
        context = DummyTLSContext()
        conn = lab_server._PinnedIPHTTPSConnection(
            host="ai.internal.local", port=8443, pinned_ip="10.20.30.40",
            timeout=1.0, context=context,
        )
        with mock.patch("lab_server.socket.socket", return_value=dummy):
            conn.connect()
        self.assertEqual(dummy.connected_to, ("10.20.30.40", 8443))
        self.assertEqual(len(context.wrap_calls), 1)
        self.assertIs(context.wrap_calls[0][0], dummy)
        self.assertEqual(context.wrap_calls[0][1], "ai.internal.local")
        self.assertTrue(context.check_hostname)
        self.assertEqual(context.verify_mode, ssl.CERT_REQUIRED)
        conn.close()

    def test_https_connection_rejects_disabled_hostname_verification(self):
        with self.assertRaises(ValueError):
            lab_server._PinnedIPHTTPSConnection(
                "ai.internal.local", 8443, "10.20.30.40",
                context=DummyTLSContext(check_hostname=False),
            )

    def test_https_connection_rejects_cert_none(self):
        with self.assertRaises(ValueError):
            lab_server._PinnedIPHTTPSConnection(
                "ai.internal.local", 8443, "10.20.30.40",
                context=DummyTLSContext(verify_mode=ssl.CERT_NONE),
            )

    def test_send_pinned_ai_request_rejects_redirect_without_following_it(self):
        class RedirectResponse:
            status = 302

            def read(self, *_args, **_kwargs):
                return b""

        class RecordingConnection:
            instances = []

            def __init__(self, **kwargs):
                self.kwargs = kwargs
                self.requests = []
                self.closed = False
                self.__class__.instances.append(self)

            def request(self, method, path, body=None, headers=None):
                self.requests.append({
                    "method": method, "path": path, "body": body, "headers": dict(headers or {})
                })

            def getresponse(self):
                return RedirectResponse()

            def close(self):
                self.closed = True

        RecordingConnection.instances.clear()
        target = {
            "scheme": "https",
            "host": "ai.internal.local",
            "port": 8443,
            "pinned_ip": "10.20.30.40",
            "path": "/api/cameras/add",
        }
        secret = "mersad-ai-test-secret"
        with mock.patch.object(lab_server, "_PinnedIPHTTPSConnection", RecordingConnection):
            with self.assertRaisesRegex(OSError, "redirects are not permitted"):
                lab_server._send_pinned_ai_request(target, b"{}", secret)

        self.assertEqual(len(RecordingConnection.instances), 1)
        conn = RecordingConnection.instances[0]
        self.assertEqual(len(conn.requests), 1)
        self.assertEqual(conn.requests[0]["headers"].get("X-Mersad-Token"), secret)
        self.assertTrue(conn.closed)
        # A 302 target is never opened and no second request receives the secret.
        self.assertEqual(conn.kwargs["host"], "ai.internal.local")
        self.assertNotIn("attacker.example", repr(conn.requests))

    def test_certificate_error_stops_before_http_request(self):
        dummy = DummySocket()
        context = DummyTLSContext(error=ssl.SSLCertVerificationError("test certificate failure"))
        conn = lab_server._PinnedIPHTTPSConnection(
            "ai.internal.local", 8443, "10.20.30.40",
            context=context,
        )
        with mock.patch("lab_server.socket.socket", return_value=dummy):
            with self.assertRaises(ssl.SSLCertVerificationError):
                conn.connect()
        self.assertTrue(dummy.closed)


if __name__ == "__main__":
    unittest.main(verbosity=2)
