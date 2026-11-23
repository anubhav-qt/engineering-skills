"""Tests for skills/security/scripts/probe_paths.py.

Run from the repo root: python3 -m unittest discover tests
"""

import json
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from security_app import html_page, load, not_found, run_main, start_app

probe_paths = load("probe_paths")

INDEX = '<html><script src="/assets/app.js"></script><script src="https://cdn.example/x.js"></script></html>'


class ProbePathsTest(unittest.TestCase):
    def serve(self, files):
        """files: path -> (content type, body). Anything else is a 404."""

        def respond(method, path, headers, body):
            if path in files:
                content_type, content = files[path]
                return 200, [("Content-Type", content_type)], content
            return not_found()

        return start_app(self, respond)

    def test_clean_app_has_nothing_to_report(self):
        app = self.serve({"/": ("text/html", "<p>shop</p>")})
        code, output = run_main(probe_paths, [app.url])
        self.assertEqual(code, 0, output)
        self.assertIn("0 finding(s), 0 note(s), 0 not checked", output)

    def test_catch_all_app_does_not_fool_it(self):
        def respond(method, path, headers, body):
            return html_page("<html><div id=root></div></html>")

        app = start_app(self, respond)
        code, output = run_main(probe_paths, [app.url])
        self.assertEqual(code, 0, output)

    def test_env_and_git_files_are_findings(self):
        app = self.serve({
            "/": ("text/html", "<p>shop</p>"),
            "/.env": ("text/plain", "# config\nDATABASE_URL=postgres://x\nSECRET_KEY=abc\n"),
            "/.git/HEAD": ("text/plain", "ref: refs/heads/main\n"),
        })
        code, output = run_main(probe_paths, [app.url])
        self.assertEqual(code, 1)
        self.assertIn(f"FINDING      {app.url}.env  env file served", output)
        self.assertIn(f"FINDING      {app.url}.git/HEAD  git folder served", output)

    def test_api_description_is_a_note(self):
        app = self.serve({
            "/": ("text/html", "<p>shop</p>"),
            "/openapi.json": ("application/json", '{"openapi": "3.0.0"}'),
        })
        code, output = run_main(probe_paths, [app.url])
        self.assertEqual(code, 1)
        self.assertIn("NOTE", output)
        self.assertIn("API description served", output)

    def test_source_map_with_source_code_is_a_finding(self):
        source_map = {"version": 3, "sources": ["src/app.ts"], "mappings": "AAAA", "sourcesContent": ["const k = 1"]}
        app = self.serve({
            "/": ("text/html", INDEX),
            "/assets/app.js": ("application/javascript", "console.log(1)\n//# sourceMappingURL=app.js.map"),
            "/assets/app.js.map": ("application/json", json.dumps(source_map)),
        })
        code, output = run_main(probe_paths, [app.url])
        self.assertEqual(code, 1)
        self.assertIn("source map served with the full source code", output)
        self.assertNotIn("cdn.example", output)

    def test_source_map_without_content_is_a_note(self):
        source_map = {"version": 3, "sources": ["src/app.ts"], "mappings": "AAAA"}
        app = self.serve({
            "/": ("text/html", INDEX),
            "/assets/app.js": ("application/javascript", "console.log(1)"),
            "/assets/app.js.map": ("application/json", json.dumps(source_map)),
        })
        code, output = run_main(probe_paths, [app.url])
        self.assertEqual(code, 1)
        self.assertIn("NOTE", output)
        self.assertIn("source map served (file names only)", output)

    def test_error_page_with_stack_trace_is_a_finding(self):
        def respond(method, path, headers, body):
            if path.startswith("/sec-missing-"):
                trace = "Error: no route\n    at Router.handle (/Users/dev/shop/node_modules/express/router.js:10:5)"
                return 500, [("Content-Type", "text/html")], trace
            return not_found()

        app = start_app(self, respond)
        code, output = run_main(probe_paths, [app.url])
        self.assertEqual(code, 1)
        self.assertIn("error page shows a stack trace", output)
        self.assertIn("error page shows a server file path", output)

    def test_out_of_scope_base_does_not_start(self):
        code, output = run_main(probe_paths, ["http://8.8.8.8"])
        self.assertEqual(code, 2)
        self.assertIn("cannot start", output)


class SourceMapUrlTest(unittest.TestCase):
    def test_comment_is_followed_relative_to_the_script(self):
        url = probe_paths.source_map_url("http://h/a/app.js", "x\n//# sourceMappingURL=maps/app.map")
        self.assertEqual(url, "http://h/a/maps/app.map")

    def test_default_is_dot_map(self):
        self.assertEqual(probe_paths.source_map_url("http://h/app.js", "x"), "http://h/app.js.map")

    def test_inline_map_has_no_url(self):
        self.assertIsNone(probe_paths.source_map_url("http://h/app.js", "//# sourceMappingURL=data:application/json;base64,e30="))


if __name__ == "__main__":
    unittest.main()
