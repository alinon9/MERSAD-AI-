#!/usr/bin/env python3
"""Batch 2 AUD-010 regressions: Telegram API transport allowlist and redirect safety."""
import os
import unittest
from unittest import mock

import notify


class TelegramApiTransportSecurityTests(unittest.TestCase):
    def test_default_api_is_official_https_origin(self):
        with mock.patch.dict(os.environ, {"TELEGRAM_API": ""}, clear=False):
            self.assertEqual(notify._telegram_api_base(), "https://api.telegram.org")

    def test_remote_http_api_is_rejected(self):
        env = {"TELEGRAM_API": "http://api.telegram.org"}
        with mock.patch.dict(os.environ, env, clear=False):
            with self.assertRaisesRegex(RuntimeError, "must use https"):
                notify._telegram_api_base()

    def test_untrusted_https_host_is_rejected(self):
        env = {"TELEGRAM_API": "https://telegram-proxy.example.com"}
        with mock.patch.dict(os.environ, env, clear=False):
            with self.assertRaisesRegex(RuntimeError, "must use https"):
                notify._telegram_api_base()

    def test_loopback_http_requires_explicit_test_switch(self):
        env = {
            "TELEGRAM_API": "http://127.0.0.1:8780",
            "MERSAD_TELEGRAM_ALLOW_LOCAL_API": "0",
        }
        with mock.patch.dict(os.environ, env, clear=False):
            with self.assertRaisesRegex(RuntimeError, "test-only"):
                notify._telegram_api_base()

    def test_explicit_loopback_test_api_is_allowed(self):
        env = {
            "TELEGRAM_API": "http://127.0.0.1:8780",
            "MERSAD_TELEGRAM_ALLOW_LOCAL_API": "1",
        }
        with mock.patch.dict(os.environ, env, clear=False):
            self.assertEqual(notify._telegram_api_base(), "http://127.0.0.1:8780")

    def test_lan_private_http_is_not_allowed_even_in_test_mode(self):
        env = {
            "TELEGRAM_API": "http://192.168.1.20:8780",
            "MERSAD_TELEGRAM_ALLOW_LOCAL_API": "1",
        }
        with mock.patch.dict(os.environ, env, clear=False):
            with self.assertRaisesRegex(RuntimeError, "test-only"):
                notify._telegram_api_base()

    def test_redirect_handler_never_returns_redirect_request(self):
        handler = notify._NoRedirectHandler()
        redirected = handler.redirect_request(
            None, None, 302, "Found", {"Location": "https://attacker.example/"},
            "https://attacker.example/",
        )
        self.assertIsNone(redirected)

    def test_api_method_path_is_validated_before_network(self):
        env = {
            "TELEGRAM_TOKEN": "test-token",
            "TELEGRAM_API": "https://api.telegram.org",
        }
        with mock.patch.dict(os.environ, env, clear=False):
            with mock.patch.object(notify.urllib.request, "build_opener") as build_opener:
                with self.assertRaisesRegex(RuntimeError, "Invalid Telegram API method"):
                    notify._call("../sendMessage", fields={"chat_id": "1"})
                build_opener.assert_not_called()


if __name__ == "__main__":
    unittest.main(verbosity=2)
