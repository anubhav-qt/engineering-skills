"""Tests for skills/security/scripts/check_access.py.

Run from the repo root: python3 -m unittest discover tests
"""

import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent))
from security_app import load, run_main, start_app

check_access = load("check_access")

COOKIES = {"sid=alice-session": "A", "sid=bob-session": "B"}


def json_answer(status, data):
    return status, [("Content-Type", "application/json")], json.dumps(data)


class ShopApp:
    """A tiny API with one order owned by A. owner_check decides whether it is safe."""

    def __init__(self, owner_check):
        self.owner_check = owner_check
        self.order = {"id": 1, "owner": "A", "title": "alice-order-7f3"}

    def respond(self, method, path, headers, body):
        user = COOKIES.get(headers.get("Cookie", ""))
        if user is None:
            return json_answer(401, {"error": "log in"})
        if path == "/api/me":
            return json_answer(200, {"user": user})
        if path != "/api/orders/1":
            return json_answer(404, {"error": "no route"})
        if self.owner_check and user != self.order["owner"]:
            return json_answer(404, {"error": "not found"})
        if method == "PATCH":
            self.order["title"] = json.loads(body)["title"]
        return json_answer(200, self.order)


class AccessTest(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.folder = Path(temp.name)
        env = mock.patch.dict(os.environ, {"SEC_A_COOKIE": "sid=alice-session"})
        env.start()
        self.addCleanup(env.stop)

    def serve(self, owner_check):
        self.shop = ShopApp(owner_check)
        self.app = start_app(self, self.shop.respond)
        return self.app

    def plan(self, requests):
        plan = {
            "identities": {"A": {"Cookie": "env:SEC_A_COOKIE"}, "B": {"Cookie": "sid=bob-session"}},
            "requests": requests,
        }
        path = self.folder / "plan.json"
        path.write_text(json.dumps(plan))
        return str(path)

    def read_request(self, **extra):
        request = {"name": "A's order", "as": "A", "url": self.app.url + "api/orders/1"}
        request.update(extra)
        return request

    def test_leak_to_other_user_is_a_finding_with_proof(self):
        self.serve(owner_check=False)
        code, output = run_main(check_access, ["--plan", self.plan([self.read_request(marker="alice-order-7f3")])])
        self.assertEqual(code, 1)
        self.assertIn("FINDING      A's order  as B: got the owner's data (marker found, status 200)", output)
        self.assertIn("ok           A's order  as anonymous: blocked (status 401)", output)
        self.assertIn('owner: curl -i -X GET', output)
        self.assertIn('-H "Cookie: $SEC_A_COOKIE"', output)
        self.assertIn("'Cookie: ***'", output)
        self.assertNotIn("alice-session", output)
        self.assertNotIn("bob-session", output)

    def test_safe_app_exits_0(self):
        self.serve(owner_check=True)
        code, output = run_main(check_access, ["--plan", self.plan([self.read_request(marker="alice-order-7f3")])])
        self.assertEqual(code, 0, output)
        self.assertIn("ok           A's order  as B: blocked (status 404)", output)
        self.assertIn("0 finding(s), 0 open, 2 blocked, 0 not checked", output)

    def test_same_answer_without_marker_is_a_finding(self):
        self.serve(owner_check=False)
        code, output = run_main(check_access, ["--plan", self.plan([self.read_request()])])
        self.assertEqual(code, 1)
        self.assertIn("as B: got exactly the owner's answer", output)

    def test_different_answer_without_marker_is_open(self):
        self.serve(owner_check=True)
        me = {"name": "my profile", "as": "A", "url": self.app.url + "api/me"}
        code, output = run_main(check_access, ["--plan", self.plan([me])])
        self.assertEqual(code, 1)
        self.assertIn("OPEN         my profile  as B: status 200 with a different answer", output)

    def test_server_error_for_other_user_is_open_not_blocked(self):
        shop = ShopApp(owner_check=True)

        def respond(method, path, headers, body):
            if headers.get("Cookie") == "sid=bob-session":
                return json_answer(500, {"error": "boom"})
            return shop.respond(method, path, headers, body)

        self.app = start_app(self, respond)
        code, output = run_main(check_access, ["--plan", self.plan([self.read_request(marker="alice-order-7f3")])])
        self.assertEqual(code, 1)
        self.assertIn("OPEN         A's order  as B: server error (status 500); check by hand", output)

    def test_marker_missing_from_owner_answer_is_not_checked(self):
        self.serve(owner_check=True)
        code, output = run_main(check_access, ["--plan", self.plan([self.read_request(marker="typo-marker")])])
        self.assertEqual(code, 2)
        self.assertIn("NOT CHECKED  A's order  the owner's own answer does not hold the marker", output)

    def write_request(self):
        url = self.app.url + "api/orders/1"
        return {
            "name": "rename A's order", "as": "A", "method": "PATCH", "url": url,
            "body": {"title": "sec-was-here"}, "check": {"url": url, "marker": "sec-was-here"},
        }

    def test_write_needs_allow_writes(self):
        self.serve(owner_check=False)
        code, output = run_main(check_access, ["--plan", self.plan([self.write_request()])])
        self.assertEqual(code, 2)
        self.assertIn("pass --allow-writes", output)
        self.assertEqual(self.shop.order["title"], "alice-order-7f3")

    def test_write_that_changes_owner_data_is_a_finding(self):
        self.serve(owner_check=False)
        code, output = run_main(check_access, ["--plan", self.plan([self.write_request()]), "--allow-writes"])
        self.assertEqual(code, 1)
        self.assertIn("FINDING      rename A's order  as B: changed the owner's data (status 200)", output)
        self.assertIn("the other identities were not tried after the first change", output)

    def test_blocked_write_is_ok(self):
        self.serve(owner_check=True)
        code, output = run_main(check_access, ["--plan", self.plan([self.write_request()]), "--allow-writes"])
        self.assertEqual(code, 0, output)
        self.assertEqual(self.shop.order["title"], "alice-order-7f3")

    def test_write_without_check_is_open_when_accepted(self):
        self.serve(owner_check=False)
        request = self.write_request()
        del request["check"]
        code, output = run_main(check_access, ["--plan", self.plan([request]), "--allow-writes"])
        self.assertEqual(code, 1)
        self.assertIn("OPEN         rename A's order  as B: write accepted (status 200)", output)

    def test_marker_already_present_is_not_checked(self):
        self.serve(owner_check=False)
        request = self.write_request()
        request["check"]["marker"] = "alice-order"
        code, output = run_main(check_access, ["--plan", self.plan([request]), "--allow-writes"])
        self.assertIn("the check marker is there before any write", output)


class PlanTest(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.path = Path(temp.name) / "plan.json"

    def start_error(self, plan):
        self.path.write_text(json.dumps(plan))
        code, output = run_main(check_access, ["--plan", str(self.path)])
        self.assertEqual(code, 2)
        return output

    def test_needs_two_identities(self):
        output = self.start_error({"identities": {"A": {}}, "requests": [{"name": "x", "as": "A", "url": "http://localhost/"}]})
        self.assertIn("at least two identities", output)

    def test_unknown_owner(self):
        plan = {"identities": {"A": {}, "B": {}}, "requests": [{"name": "x", "as": "C", "url": "http://localhost/"}]}
        self.assertIn("unknown identity C", self.start_error(plan))

    def test_missing_env_var(self):
        plan = {"identities": {"A": {"Cookie": "env:SEC_NOT_SET_X"}, "B": {}}, "requests": [{"name": "x", "as": "A", "url": "http://localhost/"}]}
        self.assertIn("SEC_NOT_SET_X is not set", self.start_error(plan))

    def test_bad_json(self):
        self.path.write_text("{oops")
        code, output = run_main(check_access, ["--plan", str(self.path)])
        self.assertEqual(code, 2)

    def test_out_of_scope_url_is_not_checked(self):
        plan = {"identities": {"A": {}, "B": {}}, "requests": [{"name": "x", "as": "A", "url": "http://8.8.8.8/"}]}
        self.path.write_text(json.dumps(plan))
        code, output = run_main(check_access, ["--plan", str(self.path)])
        self.assertEqual(code, 2)
        self.assertIn("NOT CHECKED  x", output)


if __name__ == "__main__":
    unittest.main()
