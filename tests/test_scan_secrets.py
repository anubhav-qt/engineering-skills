"""Tests for skills/security/scripts/scan_secrets.py.

Run from the repo root: python3 -m unittest discover tests
"""

import base64
import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent))
from security_app import html_page, load, not_found, run_main, start_app

scan_secrets = load("scan_secrets")

GIT_ENV = {
    "GIT_CONFIG_GLOBAL": os.devnull,
    "GIT_CONFIG_NOSYSTEM": "1",
    "GIT_AUTHOR_NAME": "tester",
    "GIT_AUTHOR_EMAIL": "tester@localhost",
    "GIT_COMMITTER_NAME": "tester",
    "GIT_COMMITTER_EMAIL": "tester@localhost",
}

# Built from pieces so this test file does not itself look like it leaks keys.
AWS_KEY = "AKIA" + "QWERTYUIOPASDFGH"
STRIPE_KEY = "sk_" + "live_" + "a1b2c3d4e5f6g7h8i9j0"


def fake_jwt(claims):
    def part(data):
        raw = json.dumps(data).encode("utf-8")
        return base64.urlsafe_b64encode(raw).decode("ascii").rstrip("=")

    return part({"alg": "HS256", "typ": "JWT"}) + "." + part(claims) + "." + "s1gnatureSIGNATUREsig"


def git(cwd, *args):
    result = subprocess.run(["git", *args], cwd=cwd, capture_output=True, text=True)
    if result.returncode != 0:
        raise AssertionError(f"git {' '.join(args)} failed: {result.stderr}")
    return result.stdout


def write(path, text):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


class RepoTest(unittest.TestCase):
    def setUp(self):
        patcher = mock.patch.dict(os.environ, GIT_ENV)
        patcher.start()
        self.addCleanup(patcher.stop)
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.repo = Path(temp.name).resolve() / "shop"
        self.repo.mkdir()
        git(self.repo, "init", "--quiet", "--initial-branch=main")
        write(self.repo / ".gitignore", "dist/\n.env.local\n")
        write(self.repo / "app.js", "const greeting = 'hi';\n")
        self.commit("first")

    def commit(self, message):
        git(self.repo, "add", "-A")
        git(self.repo, "commit", "--quiet", "-m", message)

    def scan(self, *extra):
        return run_main(scan_secrets, ["--repo", str(self.repo), *extra])

    def test_clean_repo_exits_0(self):
        code, output = self.scan()
        self.assertEqual(code, 0, output)
        self.assertIn("0 finding(s), 0 note(s)", output)

    def test_key_in_a_file_is_found_and_hidden(self):
        write(self.repo / "config.js", f"const aws = '{AWS_KEY}';\n")
        code, output = self.scan()
        self.assertEqual(code, 1)
        self.assertIn("FINDING      config.js:1  AWS access key: AKIA***", output)
        self.assertNotIn(AWS_KEY, output)

    def test_removed_secret_is_still_found_in_history(self):
        write(self.repo / "pay.js", f"const stripe = '{STRIPE_KEY}';\n")
        self.commit("add payments")
        write(self.repo / "pay.js", "const stripe = process.env.STRIPE_KEY;\n")
        self.commit("move key to env")
        code, output = self.scan()
        self.assertEqual(code, 1)
        self.assertIn("Stripe secret key, in git history (rotate it even if removed)", output)
        self.assertIn("pay.js (commit ", output)
        self.assertNotIn(STRIPE_KEY, output)

        code, output = self.scan("--no-history")
        self.assertEqual(code, 0, output)

    def test_secret_in_tree_is_not_repeated_from_history(self):
        write(self.repo / "config.js", f"const aws = '{AWS_KEY}';\n")
        self.commit("add config")
        code, output = self.scan()
        self.assertEqual(output.count("AWS access key"), 1, output)

    def test_committed_env_file_is_a_finding(self):
        write(self.repo / ".env", "PORT=3000\n")
        self.commit("add env")
        code, output = self.scan()
        self.assertEqual(code, 1)
        self.assertIn("FINDING      .env  env file committed to git", output)

    def test_unignored_env_file_is_a_note(self):
        write(self.repo / ".env.production", "PORT=3000\n")
        write(self.repo / ".env.local", "PORT=3000\n")
        write(self.repo / ".env.example", "PORT=\n")
        code, output = self.scan()
        self.assertEqual(code, 1)
        self.assertIn("NOTE         .env.production  env file not in .gitignore", output)
        self.assertNotIn(".env.local", output)
        self.assertNotIn(".env.example", output)

    def test_placeholders_are_skipped(self):
        write(self.repo / "README.md", 'api_key = "your-api-key-here"\npassword: "********"\n')
        write(self.repo / "settings.py", 'SECRET_KEY = "${SECRET_KEY}"\n')
        code, output = self.scan()
        self.assertEqual(code, 0, output)

    def test_keyword_value_is_found(self):
        write(self.repo / "settings.py", 'DB_PASSWORD = "hunter2-prod-9876"\n')
        code, output = self.scan()
        self.assertEqual(code, 1)
        self.assertIn("secret-looking value in DB_PASSWORD: hunt***", output)
        self.assertNotIn("hunter2-prod-9876", output)

    def test_ignored_bundle_with_service_role_key_is_found(self):
        service = fake_jwt({"iss": "supabase", "role": "service_role"})
        anon = fake_jwt({"iss": "supabase", "role": "anon"})
        write(self.repo / "dist" / "assets" / "index.js", f'createClient(u, "{anon}");createClient(u, "{service}")\n')
        code, output = self.scan()
        self.assertEqual(code, 1)
        self.assertIn("dist/assets/index.js:1  Supabase service_role key", output)
        self.assertEqual(output.count("Supabase"), 1, output)

    def test_secret_named_public_env_var_is_found(self):
        write(self.repo / "lib" / "pay.ts", "const k = process.env.NEXT_PUBLIC_STRIPE_SECRET_KEY;\n")
        code, output = self.scan()
        self.assertEqual(code, 1)
        self.assertIn("NEXT_PUBLIC_STRIPE_SECRET_KEY", output)
        self.assertIn("secret-named env var goes to the browser", output)

    def test_served_scripts_are_scanned(self):
        def respond(method, path, headers, body):
            if path == "/":
                return html_page('<script src="/static/main.js"></script>')
            if path == "/static/main.js":
                return 200, [("Content-Type", "application/javascript")], f'var k="{AWS_KEY}";'
            return not_found()

        app = start_app(self, respond)
        code, output = self.scan("--url", app.url)
        self.assertEqual(code, 1)
        self.assertIn(f"{app.url}static/main.js:1  AWS access key", output)

    def test_out_of_scope_url_is_not_checked(self):
        code, output = self.scan("--url", "http://8.8.8.8/")
        self.assertIn("NOT CHECKED", output)

    def test_missing_folder_cannot_start(self):
        code, output = run_main(scan_secrets, ["--repo", str(self.repo / "nope")])
        self.assertEqual(code, 2)
        self.assertIn("cannot start", output)


class LineTest(unittest.TestCase):
    def kinds(self, line):
        return [finding.kind for finding in scan_secrets.check_line("x", line)]

    def test_private_key_header(self):
        self.assertEqual(self.kinds("-----BEGIN RSA PRIVATE KEY-----"), ["private key"])

    def test_google_key_is_only_a_note(self):
        key = "AIza" + "B" * 35
        findings = scan_secrets.check_line("x", f'apiKey: "{key}"')
        self.assertEqual(len(findings), 1)
        self.assertEqual(findings[0].level, scan_secrets.NOTE)

    def test_known_key_is_not_reported_twice_by_keyword_rule(self):
        self.assertEqual(self.kinds(f'api_key = "{AWS_KEY}"'), ["AWS access key"])


if __name__ == "__main__":
    unittest.main()
