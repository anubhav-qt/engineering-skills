"""Tests for skills/security/scripts/check_headers.py.

Run from the repo root: python3 -m unittest discover tests
"""

import email.message
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from security_app import html_page, load, run_main, start_app

check_headers = load("check_headers")

GOOD_HEADERS = [
    ("Content-Security-Policy", "default-src 'self'; object-src 'none'; base-uri 'self'; frame-ancestors 'none'"),
    ("X-Content-Type-Options", "nosniff"),
    ("Referrer-Policy", "strict-origin-when-cross-origin"),
    ("Set-Cookie", "session=abc; HttpOnly; SameSite=Lax; Path=/"),
]


def headers_of(pairs):
    message = email.message.Message()
    for name, value in pairs:
        message[name] = value
    return message


def texts(results):
    return [text for _, text in results]


class PageTest(unittest.TestCase):
    def serve(self, headers, cors=None):
        def respond(method, path, request_headers, body):
            if method == "TRACE":
                return 405, [], ""
            extra = []
            origin = request_headers.get("Origin")
            if origin is not None and cors is not None:
                extra = cors(origin)
            return html_page("<p>hi</p>", [*headers, *extra])

        return start_app(self, respond)

    def test_good_page_has_nothing_to_report(self):
        app = self.serve(GOOD_HEADERS)
        code, output = run_main(check_headers, [app.url])
        self.assertEqual(code, 0, output)
        self.assertIn("0 finding(s), 0 note(s)", output)
        self.assertIn("HSTS and Secure cookies need HTTPS to check", output)

    def test_bare_page_gets_notes_only(self):
        app = self.serve([])
        code, output = run_main(check_headers, [app.url])
        self.assertEqual(code, 1)
        self.assertIn("no Content-Security-Policy", output)
        self.assertIn("other sites can frame this page", output)
        self.assertIn("no X-Content-Type-Options: nosniff", output)
        self.assertNotIn("FINDING", output)

    def test_cors_trusting_any_origin_with_cookies_is_a_finding(self):
        def reflect(origin):
            return [("Access-Control-Allow-Origin", origin), ("Access-Control-Allow-Credentials", "true")]

        app = self.serve(GOOD_HEADERS, cors=reflect)
        code, output = run_main(check_headers, [app.url])
        self.assertEqual(code, 1)
        self.assertIn("FINDING", output)
        self.assertIn("CORS trusts Origin https://evil.example with cookies", output)
        self.assertIn("CORS trusts Origin null with cookies", output)
        self.assertIn("CORS trusts Origin https://127.0.0.1.evil.example", output)

    def test_cors_echo_without_cookies_is_a_note(self):
        def reflect(origin):
            return [("Access-Control-Allow-Origin", origin)]

        app = self.serve(GOOD_HEADERS, cors=reflect)
        code, output = run_main(check_headers, [app.url])
        self.assertEqual(code, 1)
        self.assertNotIn("FINDING", output)
        self.assertIn("CORS echoes Origin https://evil.example", output)

    def test_cors_star_is_fine(self):
        def star(origin):
            return [("Access-Control-Allow-Origin", "*")]

        app = self.serve(GOOD_HEADERS, cors=star)
        code, output = run_main(check_headers, [app.url])
        self.assertEqual(code, 0, output)

    def test_trace_echo_is_a_note(self):
        def respond(method, path, headers, body):
            if method == "TRACE":
                return 200, [("Content-Type", "message/http")], f"TRACE {path} HTTP/1.1"
            return html_page("hi", GOOD_HEADERS)

        app = start_app(self, respond)
        code, output = run_main(check_headers, [app.url])
        self.assertEqual(code, 1)
        self.assertIn("TRACE is on", output)

    def test_out_of_scope_url_is_not_checked(self):
        code, output = run_main(check_headers, ["http://8.8.8.8/"])
        self.assertEqual(code, 2)
        self.assertIn("NOT CHECKED", output)


class CspTest(unittest.TestCase):
    def csp(self, policy):
        return texts(check_headers.check_csp(headers_of([("Content-Security-Policy", policy)])))

    def test_unsafe_inline_is_noted(self):
        found = self.csp("script-src 'self' 'unsafe-inline'; object-src 'none'; base-uri 'none'")
        self.assertEqual(found, ["CSP allows inline scripts ('unsafe-inline')"])

    def test_unsafe_inline_with_nonce_is_ignored(self):
        found = self.csp("script-src 'self' 'unsafe-inline' 'nonce-abc'; object-src 'none'; base-uri 'none'")
        self.assertEqual(found, [])

    def test_wide_sources_and_eval_are_noted(self):
        found = self.csp("default-src * 'unsafe-eval'; base-uri 'none'")
        self.assertIn("CSP allows eval ('unsafe-eval')", found)
        self.assertIn("CSP lets scripts load from anywhere (*)", found)
        self.assertIn("CSP object-src is not 'none'", found)

    def test_default_src_none_covers_objects(self):
        self.assertEqual(self.csp("default-src 'none'; base-uri 'none'"), [])

    def test_report_only_blocks_nothing(self):
        headers = headers_of([("Content-Security-Policy-Report-Only", "default-src 'self'")])
        self.assertEqual(texts(check_headers.check_csp(headers)), ["CSP is report-only, so it blocks nothing"])

    def test_first_directive_wins(self):
        found = self.csp("script-src 'self'; script-src *; object-src 'none'; base-uri 'none'")
        self.assertEqual(found, [])


class OtherHeaderTest(unittest.TestCase):
    def test_hsts(self):
        short = headers_of([("Strict-Transport-Security", "max-age=3600")])
        good = headers_of([("Strict-Transport-Security", "max-age=63072000; includeSubDomains")])
        self.assertEqual(texts(check_headers.check_hsts(short, https=True)), ["Strict-Transport-Security max-age is under one year"])
        self.assertEqual(check_headers.check_hsts(good, https=True), [])
        self.assertEqual(texts(check_headers.check_hsts(headers_of([]), https=True)), ["no Strict-Transport-Security"])

    def test_server_version_is_noted_but_plain_name_is_not(self):
        with_version = headers_of([("Server", "nginx/1.25.3"), ("X-Powered-By", "Express")])
        found = texts(check_headers.check_leak_headers(with_version))
        self.assertIn("Server header shows a version: nginx/1.25.3", found)
        self.assertIn("X-Powered-By header shows the software: Express", found)
        self.assertEqual(check_headers.check_leak_headers(headers_of([("Server", "nginx")])), [])

    def test_framing_guards(self):
        self.assertEqual(check_headers.check_framing(headers_of([("X-Frame-Options", "deny")])), [])
        csp = headers_of([("Content-Security-Policy", "frame-ancestors 'self'")])
        self.assertEqual(check_headers.check_framing(csp), [])
        loose = headers_of([("X-Frame-Options", "ALLOW-FROM https://x")])
        self.assertEqual(len(check_headers.check_framing(loose)), 1)

    def test_weak_referrer_policy(self):
        weak = headers_of([("Referrer-Policy", "unsafe-url"), ("X-Content-Type-Options", "nosniff")])
        self.assertEqual(texts(check_headers.check_simple_headers(weak)), ["Referrer-Policy unsafe-url sends full URLs to other sites"])


class CookieTest(unittest.TestCase):
    def test_session_cookie_without_httponly(self):
        found = texts(check_headers.check_cookies(["connect.sid=x; Path=/"], https=False))
        self.assertEqual(found, ["cookie connect.sid is readable by page scripts (no HttpOnly)"])

    def test_plain_cookie_may_skip_httponly(self):
        self.assertEqual(check_headers.check_cookies(["theme=dark; Path=/"], https=False), [])

    def test_secure_is_checked_on_https_only(self):
        line = "auth_token=x; HttpOnly"
        self.assertEqual(check_headers.check_cookies([line], https=False), [])
        found = texts(check_headers.check_cookies([line], https=True))
        self.assertEqual(found, ["cookie auth_token can travel over plain HTTP (no Secure)"])

    def test_samesite_none_needs_secure(self):
        found = texts(check_headers.check_cookies(["pref=1; SameSite=None"], https=False))
        self.assertEqual(found, ["cookie pref has SameSite=None without Secure, so browsers drop it"])


if __name__ == "__main__":
    unittest.main()
