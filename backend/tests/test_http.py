"""Offline checks for HTTPS trust without developer-machine certificate paths."""

import ssl
import unittest
from unittest.mock import patch

from app.http import https_context


class HTTPTrustTests(unittest.TestCase):
    def test_missing_system_roots_use_bundled_roots_without_disabling_verification(
        self,
    ):
        empty = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
        self.assertEqual(empty.get_ca_certs(), [])
        with patch("app.http.ssl.create_default_context", return_value=empty):
            context = https_context()
        self.assertGreater(len(context.get_ca_certs()), 0)
        self.assertEqual(context.verify_mode, ssl.CERT_REQUIRED)
        self.assertTrue(context.check_hostname)

    def test_system_roots_are_preserved_and_missing_bundle_fails_closed(self):
        system = ssl.create_default_context()
        roots = set(system.get_ca_certs(binary_form=True))
        with patch("app.http.ssl.create_default_context", return_value=system):
            self.assertTrue(
                roots <= set(https_context().get_ca_certs(binary_form=True))
            )
        with (
            patch("app.http.certifi.where", return_value="/missing/uarc-ca.pem"),
            self.assertRaises(OSError),
        ):
            https_context()


if __name__ == "__main__":
    unittest.main()
