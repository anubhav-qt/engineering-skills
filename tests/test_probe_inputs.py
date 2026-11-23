"""Tests for skills/security/scripts/probe_inputs.py.

Run from the repo root: python3 -m unittest discover tests
"""

import html
import re
import sys
import time
import unittest
import urllib.request
from pathlib import Path
from unittest import mock
from urllib.parse import parse_qs, urlsplit

sys.path.insert(0, str(Path(__file__).resolve().parent))
from security_app import html_page, load, run_main, start_app

probe_inputs = load("probe_inputs")

FAKE_PASSWD = "root:x:0:0:root:/root:/bin/bash\n"


def query_value(path):
    values = parse_qs(urlsplit(path).query).get("q")
    if not values:
        return ""
    return values[0]


def safe_search(value):
    return html_page(f"<h1>Results for {html.escape(value)}</h1><ul><li>apple</li></ul>")


class ProbeTest(unittest.TestCase):
    def serve(self, search):
        def respond(method, path, headers, body):
            return search(query_value(path))

        app = start_app(self, respond)
        return app.url + "search?q=FUZZ"

    def probe(self, url, *extra):
        return run_main(probe_inputs, ["--url", url, *extra])

    def test_safe_search_finds_nothing(self):
        code, output = self.probe(self.serve(safe_search))
        self.assertEqual(code, 0, output)
        self.assertIn("0 finding(s), 0 note(s), 0 open", output)

    def test_reflected_html_is_xss(self):
        def search(value):
            return html_page(f"<h1>Results for {value}</h1>")

        code, output = self.probe(self.serve(search), "--only", "xss")
        self.assertEqual(code, 1)
        self.assertIn("FINDING      xss: the input comes back as raw HTML", output)
        self.assertIn("proof: curl -i -X GET", output)

    def test_reflection_in_json_is_only_a_note(self):
        def search(value):
            return 200, [("Content-Type", "application/json")], '{"q": "%s"}' % value

        code, output = self.probe(self.serve(search), "--only", "xss")
        self.assertEqual(code, 1)
        self.assertIn("NOTE         xss: the input comes back unescaped in a application/json answer", output)

    def test_template_math_is_ssti(self):
        def search(value):
            shown = re.sub(r"\{\{(\d+)\*(\d+)\}\}", lambda m: str(int(m.group(1)) * int(m.group(2))), value)
            return html_page(f"<h1>{html.escape(shown)}</h1>")

        code, output = self.probe(self.serve(search), "--only", "ssti")
        self.assertEqual(code, 1)
        self.assertIn("FINDING      ssti: the template ran {{1337*7331}}", output)

    def test_quote_breaking_sql_is_found(self):
        def search(value):
            if value.count("'") % 2 == 1:
                return 500, [("Content-Type", "text/plain")], 'SQLITE_ERROR: unrecognized token: "\'"'
            return safe_search(value)

        code, output = self.probe(self.serve(search), "--only", "sql")
        self.assertEqual(code, 1)
        self.assertIn("FINDING      sql: a single quote gives SQL error text", output)
        self.assertIn("FINDING      leak: a bad input shows a SQL error text", output)

    def test_quote_giving_bare_server_error_is_open(self):
        def search(value):
            if value.count("'") % 2 == 1:
                return 500, [("Content-Type", "text/plain")], "Internal Server Error"
            return safe_search(value)

        code, output = self.probe(self.serve(search), "--only", "sql")
        self.assertEqual(code, 1)
        self.assertIn("OPEN         sql: a single quote gives a server error", output)

    def test_boolean_sql_is_found(self):
        def search(value):
            if value.endswith("'1'='2"):
                return html_page(f"<h1>Results for {html.escape(value)}</h1><ul></ul>")
            return safe_search(value)

        code, output = self.probe(self.serve(search), "--only", "sql")
        self.assertEqual(code, 1)
        self.assertIn("FINDING      sql: a true condition (' AND '1'='1) keeps the page", output)

    def test_changing_page_skips_boolean(self):
        def search(value):
            return html_page(f"<p>{time.monotonic()}</p>")

        code, output = self.probe(self.serve(search), "--only", "sql")
        self.assertIn("the page changes on every load", output)

    def test_path_traversal_is_found(self):
        def search(value):
            if "etc/passwd" in value and value.startswith("../"):
                return 200, [("Content-Type", "text/plain")], FAKE_PASSWD
            return safe_search(value)

        code, output = self.probe(self.serve(search), "--only", "path")
        self.assertEqual(code, 1)
        self.assertIn("FINDING      path: the answer holds /etc/passwd", output)

    def test_slow_command_is_found(self):
        def search(value):
            if "sleep 3" in value:
                time.sleep(0.4)
            return safe_search(value)

        with mock.patch.object(probe_inputs, "SLOW_MARGIN_SECONDS", 0.3):
            code, output = self.probe(self.serve(search), "--only", "cmd")
        self.assertEqual(code, 1)
        self.assertIn("FINDING      cmd: ';sleep 3;' made the answer 3s slower three times out of three", output)

    def test_one_slow_answer_is_only_open(self):
        calls = []

        def search(value):
            if "sleep 3" in value:
                calls.append(value)
                if len(calls) == 1:
                    time.sleep(0.4)
            return safe_search(value)

        with mock.patch.object(probe_inputs, "SLOW_MARGIN_SECONDS", 0.3):
            code, output = self.probe(self.serve(search), "--only", "cmd")
        self.assertIn("OPEN         cmd: ';sleep 3;' was slow only 1 of 3 times", output)

    def test_server_fetching_the_input_is_ssrf(self):
        def search(value):
            if value.startswith("http://127.0.0.1:"):
                try:
                    urllib.request.urlopen(value, timeout=2).close()
                except OSError:
                    pass
            return safe_search(value)

        code, output = self.probe(self.serve(search), "--only", "ssrf")
        self.assertEqual(code, 1)
        self.assertIn("FINDING      ssrf: the server fetched a URL taken from the input", output)

    def test_redirect_to_input_is_open_redirect(self):
        def search(value):
            if value.startswith(("http", "//")):
                return 302, [("Location", value)], ""
            return safe_search(value)

        code, output = self.probe(self.serve(search), "--only", "redirect")
        self.assertEqual(code, 1)
        self.assertIn("FINDING      redirect: the answer redirects to evil.example", output)

    def test_post_body_needs_allow_writes(self):
        def respond(method, path, headers, body):
            return safe_search(body.decode("utf-8"))

        app = start_app(self, respond)
        code, output = self.probe(app.url + "notes", "--method", "POST", "--data", '{"title": "FUZZ"}')
        self.assertEqual(code, 2)
        self.assertIn("--allow-writes", output)
        self.assertEqual(app.seen, [])

    def test_json_body_is_escaped_and_sent(self):
        bodies = []

        def respond(method, path, headers, body):
            bodies.append((headers.get("Content-Type"), body.decode("utf-8")))
            return safe_search("ok")

        app = start_app(self, respond)
        code, output = self.probe(
            app.url + "notes", "--method", "POST", "--data", '{"title": "FUZZ"}', "--allow-writes", "--only", "xss"
        )
        self.assertEqual(code, 0, output)
        self.assertEqual(bodies[0], ("application/json", '{"title": "sec1"}'))
        self.assertIn('\\"\'>', bodies[-1][1])

    def test_missing_slot_cannot_start(self):
        code, output = self.probe("http://localhost:1/search?q=x")
        self.assertEqual(code, 2)
        self.assertIn("put FUZZ in --url or --data", output)

    def test_unknown_check_cannot_start(self):
        code, output = self.probe("http://localhost:1/?q=FUZZ", "--only", "xss,nope")
        self.assertEqual(code, 2)

    def test_out_of_scope_cannot_start(self):
        code, output = self.probe("http://8.8.8.8/?q=FUZZ")
        self.assertEqual(code, 2)


class SsrfScopeTest(unittest.TestCase):
    def test_ssrf_is_skipped_when_app_is_not_on_this_machine(self):
        prober = mock.Mock()
        results = probe_inputs.check_ssrf(prober, probe_inputs.scope.ALLOWED)
        self.assertEqual(len(results), 1)
        self.assertEqual(results[0].level, probe_inputs.NOT_CHECKED)
        prober.send.assert_not_called()


class HelperTest(unittest.TestCase):
    def test_without_value_removes_echoed_forms(self):
        value = "a' AND '1'='1"
        page = f"<h1>{html.escape(value)}</h1><p>{value}</p>"
        self.assertEqual(probe_inputs.without_value(page, value), "<h1></h1><p></p>")

    def test_form_body_is_url_encoded(self):
        self.assertEqual(probe_inputs.encode_for_body("q=FUZZ", "a b&c"), "a+b%26c")


if __name__ == "__main__":
    unittest.main()
