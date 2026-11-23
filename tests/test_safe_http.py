"""Tests for skills/security/scripts/safe_http.py.

Run from the repo root: python3 -m unittest discover tests
"""

import os
import socket
import sys
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent))
from security_app import html_page, load, start_app

safe_http = load("safe_http")


def free_port():
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


class ClientTest(unittest.TestCase):
    def setUp(self):
        def respond(method, path, headers, body):
            if path == "/go":
                return 302, [("Location", "http://8.8.8.8/elsewhere")], ""
            if path == "/boom":
                return 500, [], "broken"
            return html_page("hello")

        self.app = start_app(self, respond)

    def request(self, method, path):
        return safe_http.Request(method, self.app.url + path.lstrip("/"))

    def test_read_is_sent(self):
        answer = safe_http.Client(delay=0).send(self.request("GET", "/"))
        self.assertEqual(answer.status, 200)
        self.assertEqual(answer.text(), "hello")

    def test_error_answers_come_back_as_answers(self):
        answer = safe_http.Client(delay=0).send(self.request("GET", "/boom"))
        self.assertEqual(answer.status, 500)
        self.assertEqual(answer.text(), "broken")

    def test_redirect_is_not_followed(self):
        answer = safe_http.Client(delay=0).send(self.request("GET", "/go"))
        self.assertEqual(answer.status, 302)
        self.assertEqual(answer.header("Location"), "http://8.8.8.8/elsewhere")
        self.assertEqual(len(self.app.seen), 1)

    def test_write_needs_allow_writes(self):
        with self.assertRaises(safe_http.Refused) as caught:
            safe_http.Client(delay=0).send(self.request("POST", "/"))
        self.assertIn("--allow-writes", str(caught.exception))
        self.assertEqual(self.app.seen, [])

    def test_write_with_allow_writes_is_sent_locally(self):
        answer = safe_http.Client(allow_writes=True, delay=0).send(self.request("DELETE", "/"))
        self.assertEqual(answer.status, 200)
        self.assertEqual(self.app.seen[0][0], "DELETE")

    def test_write_to_other_host_is_refused_even_with_allow_writes(self):
        client = safe_http.Client(allowed_hosts=["staging.example.com"], allow_writes=True)
        with self.assertRaises(safe_http.Refused) as caught:
            client.send(safe_http.Request("POST", "https://staging.example.com/api"))
        self.assertIn("read-only", str(caught.exception))

    def test_out_of_scope_is_refused(self):
        with self.assertRaises(safe_http.Refused):
            safe_http.Client().send(safe_http.Request("GET", "http://8.8.8.8/"))

    def test_cap_stops_requests(self):
        client = safe_http.Client(max_requests=2, delay=0)
        client.send(self.request("GET", "/"))
        client.send(self.request("GET", "/"))
        with self.assertRaises(safe_http.Refused) as caught:
            client.send(self.request("GET", "/"))
        self.assertIn("cap of 2", str(caught.exception))
        self.assertEqual(len(self.app.seen), 2)

    def test_closed_port_fails(self):
        url = f"http://127.0.0.1:{free_port()}/"
        with self.assertRaises(safe_http.RequestFailed):
            safe_http.Client(timeout=2).send(safe_http.Request("GET", url))


class HeaderTest(unittest.TestCase):
    def test_env_values_are_read_and_shown_by_name(self):
        with mock.patch.dict(os.environ, {"SEC_A_COOKIE": "sid=real-secret"}):
            real, shown = safe_http.parse_header_lines(["Cookie: env:SEC_A_COOKIE"])
        self.assertEqual(real["Cookie"], "sid=real-secret")
        self.assertEqual(shown["Cookie"], "$SEC_A_COOKIE")

    def test_secret_literals_are_hidden(self):
        real, shown = safe_http.parse_header_lines(["Authorization: Bearer abc123", "Accept: text/html"])
        self.assertEqual(real["Authorization"], "Bearer abc123")
        self.assertEqual(shown["Authorization"], "***")
        self.assertEqual(shown["Accept"], "text/html")

    def test_missing_env_var_stops_the_run(self):
        with mock.patch.dict(os.environ, {}, clear=True):
            with self.assertRaises(safe_http.StartError):
                safe_http.parse_header_lines(["Cookie: env:SEC_MISSING"])

    def test_bad_header_line_stops_the_run(self):
        with self.assertRaises(safe_http.StartError):
            safe_http.parse_header_lines(["no colon here"])

    def test_curl_never_shows_secrets(self):
        with mock.patch.dict(os.environ, {"SEC_A_COOKIE": "sid=real-secret"}):
            real, shown = safe_http.parse_header_lines(["Cookie: env:SEC_A_COOKIE", "X-Api-Key: k-123456"])
        request = safe_http.Request("GET", "http://localhost/x?a=1", real, shown)
        command = request.curl()
        self.assertNotIn("real-secret", command)
        self.assertNotIn("k-123456", command)
        self.assertIn('-H "Cookie: $SEC_A_COOKIE"', command)
        self.assertIn("'X-Api-Key: ***'", command)

    def test_redact_hides_values(self):
        self.assertEqual(safe_http.redact("token abcdef here", ["abcdef"]), "token *** here")


class HelpersTest(unittest.TestCase):
    def test_script_urls_keeps_same_host_only(self):
        page = (
            '<script src="/static/app.js"></script>'
            '<script src="https://cdn.example/lib.js"></script>'
            "<script SRC='chunk.js'></script>"
        )
        urls = safe_http.script_urls(page, "http://localhost:3000/shop/")
        self.assertEqual(urls, ["http://localhost:3000/static/app.js", "http://localhost:3000/shop/chunk.js"])

    def test_find_leaks(self):
        self.assertEqual(safe_http.find_leaks("Traceback (most recent call last):\n  File x"), ["stack trace"])
        node = "Error: boom\n    at Object.handler (/app/server.js:10:5)"
        self.assertIn("stack trace", safe_http.find_leaks(node))
        self.assertIn("SQL error text", safe_http.find_leaks("SQLITE_ERROR: near \"x\": syntax error"))
        self.assertEqual(safe_http.find_leaks("<h1>Not found</h1>"), [])


if __name__ == "__main__":
    unittest.main()
