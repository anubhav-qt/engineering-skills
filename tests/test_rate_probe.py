"""Tests for skills/security/scripts/rate_probe.py.

Run from the repo root: python3 -m unittest discover tests
"""

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from security_app import load, run_main, start_app

rate_probe = load("rate_probe")

LOGIN = '{"email": "a@shop.test", "password": "wrong"}'


class RateProbeTest(unittest.TestCase):
    def serve(self, limit_after=None, limit_answer=None):
        def respond(method, path, headers, body):
            count = len(app.seen)
            if limit_after is not None and count > limit_after:
                return limit_answer
            return 401, [("Content-Type", "application/json")], '{"error": "wrong password"}'

        app = start_app(self, respond)
        return app

    def probe(self, app, *extra):
        return run_main(rate_probe, ["--url", app.url + "login", "--data", LOGIN, "--allow-writes", *extra])

    def test_limit_by_status_is_ok(self):
        app = self.serve(limit_after=5, limit_answer=(429, [], "slow"))
        code, output = self.probe(app)
        self.assertEqual(code, 0, output)
        self.assertIn("limited at request 6 (status 429)", output)
        self.assertEqual(len(app.seen), 6)

    def test_limit_by_text_is_ok(self):
        app = self.serve(limit_after=3, limit_answer=(401, [], '{"error": "Too many attempts"}'))
        code, output = self.probe(app)
        self.assertEqual(code, 0, output)
        self.assertIn("limited at request 4 (the text 'Too many')", output)

    def test_limit_by_retry_after_is_ok(self):
        app = self.serve(limit_after=2, limit_answer=(503, [("Retry-After", "30")], ""))
        code, output = self.probe(app)
        self.assertEqual(code, 0, output)
        self.assertIn("a Retry-After header", output)

    def test_no_limit_is_a_finding(self):
        app = self.serve()
        code, output = self.probe(app, "--count", "12")
        self.assertEqual(code, 1)
        self.assertIn("FINDING      no limit after 12 requests; statuses: 12x 401", output)
        self.assertIn("proof: curl -i -X POST", output)
        self.assertEqual(len(app.seen), 12)
        self.assertEqual(app.seen[0][2].get("Content-Type"), "application/json")

    def test_count_above_hard_cap_cannot_start(self):
        app = self.serve()
        code, output = self.probe(app, "--count", "51")
        self.assertEqual(code, 2)
        self.assertEqual(app.seen, [])

    def test_post_needs_allow_writes(self):
        app = self.serve()
        code, output = run_main(rate_probe, ["--url", app.url + "login", "--data", LOGIN])
        self.assertEqual(code, 2)
        self.assertIn("--allow-writes", output)
        self.assertEqual(app.seen, [])


if __name__ == "__main__":
    unittest.main()
