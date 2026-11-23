"""Tests for skills/security/scripts/scope.py.

Run from the repo root: python3 -m unittest discover tests
"""

import socket
import sys
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent))
from security_app import load, run_main

scope = load("scope")


def resolves_to(*addresses):
    infos = []
    for address in addresses:
        infos.append((socket.AF_INET, socket.SOCK_STREAM, 6, "", (address, 0)))
    return mock.patch.object(scope.socket, "getaddrinfo", return_value=infos)


class CheckTest(unittest.TestCase):
    def test_localhost_names_and_addresses_are_local(self):
        for url in ("http://localhost:3000/", "http://127.0.0.1/", "http://[::1]:8080/x", "https://LOCALHOST./"):
            with self.subTest(url=url):
                self.assertEqual(scope.check(url), scope.LOCAL)

    def test_name_pointing_here_is_local(self):
        with resolves_to("127.0.0.1"):
            self.assertEqual(scope.check("http://shop.test/"), scope.LOCAL)

    def test_public_address_is_refused(self):
        with self.assertRaises(scope.OutOfScope) as caught:
            scope.check("http://8.8.8.8/")
        self.assertIn("--allow-host 8.8.8.8", str(caught.exception))

    def test_name_pointing_away_is_refused(self):
        with resolves_to("93.184.216.34"):
            with self.assertRaises(scope.OutOfScope):
                scope.check("https://app.example.com/")

    def test_name_pointing_both_here_and_away_is_refused(self):
        with resolves_to("127.0.0.1", "93.184.216.34"):
            with self.assertRaises(scope.OutOfScope):
                scope.check("https://tricky.example/")

    def test_private_network_address_is_refused(self):
        with self.assertRaises(scope.OutOfScope):
            scope.check("http://192.168.1.1/")

    def test_allowed_host_passes_without_lookup(self):
        with mock.patch.object(scope.socket, "getaddrinfo", side_effect=AssertionError("no lookup")):
            kind = scope.check("https://Staging.Example.com/login", ["staging.example.com."])
        self.assertEqual(kind, scope.ALLOWED)

    def test_allowed_host_does_not_cover_other_hosts(self):
        with resolves_to("93.184.216.34"):
            with self.assertRaises(scope.OutOfScope):
                scope.check("https://prod.example.com/", ["staging.example.com"])

    def test_other_schemes_are_refused(self):
        for url in ("ftp://localhost/", "file:///etc/passwd", "localhost:3000"):
            with self.subTest(url=url):
                with self.assertRaises(scope.OutOfScope):
                    scope.check(url)

    def test_unresolvable_name_is_refused(self):
        error = socket.gaierror(8, "nodename nor servname provided")
        with mock.patch.object(scope.socket, "getaddrinfo", side_effect=error):
            with self.assertRaises(scope.OutOfScope) as caught:
                scope.check("http://nowhere.invalid/")
        self.assertIn("does not resolve", str(caught.exception))


class MainTest(unittest.TestCase):
    def test_all_allowed_exits_0(self):
        code, output = run_main(scope, ["http://localhost:1/", "http://127.0.0.1:2/"])
        self.assertEqual(code, 0)
        self.assertEqual(output.count("allowed"), 2)

    def test_some_refused_exits_1(self):
        code, output = run_main(scope, ["http://localhost/", "http://8.8.8.8/"])
        self.assertEqual(code, 1)
        self.assertIn("refused  http://8.8.8.8/", output)


if __name__ == "__main__":
    unittest.main()
