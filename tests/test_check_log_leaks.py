"""Tests for skills/logger/scripts/check_log_leaks.py.

Run from the repo root: python3 -m unittest discover tests
"""

import base64
import contextlib
import importlib.util
import io
import sys
import tempfile
import unittest
import urllib.parse
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
SCRIPT = REPO_ROOT / "skills" / "logger" / "scripts" / "check_log_leaks.py"

spec = importlib.util.spec_from_file_location("check_log_leaks", SCRIPT)
check_log_leaks = importlib.util.module_from_spec(spec)
spec.loader.exec_module(check_log_leaks)

PASSWORD = check_log_leaks.CANARIES["LOG_CANARY_PASSWORD"]
EMAIL = check_log_leaks.CANARIES["LOG_CANARY_EMAIL"]
PYTHON = sys.executable


def python_command(code):
    """A shell command that runs this Python code."""
    return f'"{PYTHON}" -c "{code}"'


class FindLeaksTest(unittest.TestCase):
    def found(self, text):
        leaks = check_log_leaks.find_leaks([("out", text)])
        return [(leak.name, leak.form) for leak in leaks]

    def test_clean_text(self):
        self.assertEqual(self.found('{"event":"user.login","user_id":7}\n'), [])

    def test_plain_value(self):
        self.assertEqual(self.found(f"login pw={PASSWORD}"), [("LOG_CANARY_PASSWORD", "as is")])

    def test_url_encoded_email(self):
        quoted = urllib.parse.quote(EMAIL, safe="")
        self.assertIn("%40", quoted)
        self.assertEqual(self.found(f"GET /reset?email={quoted}"), [("LOG_CANARY_EMAIL", "URL-encoded")])

    def test_base64_alone_and_inside_basic_auth(self):
        alone = base64.b64encode(PASSWORD.encode()).decode()
        self.assertEqual(self.found(f"blob={alone}"), [("LOG_CANARY_PASSWORD", "base64")])
        for user in ["a", "ab", "abc", "user"]:
            with self.subTest(user=user):
                header = base64.b64encode(f"{user}:{PASSWORD}x".encode()).decode()
                self.assertEqual(self.found(f"Authorization: Basic {header}"),
                                 [("LOG_CANARY_PASSWORD", "base64")])

    def test_masked_values_are_not_leaks(self):
        self.assertEqual(self.found("card=************4242 email=l***@example.com"), [])

    def test_line_numbers_and_one_report_per_canary_per_line(self):
        quoted = urllib.parse.quote(EMAIL, safe="")
        text = f"ok\n{EMAIL} {quoted}\nok\n"
        leaks = check_log_leaks.find_leaks([("app.log", text)])
        self.assertEqual(len(leaks), 1)
        self.assertEqual((leaks[0].source, leaks[0].number), ("app.log", 2))

    def test_canaries_have_no_spaces(self):
        for value in check_log_leaks.CANARIES.values():
            self.assertEqual(urllib.parse.quote(value, safe=""), urllib.parse.quote_plus(value))

    def test_needles_are_long_enough_to_be_unique(self):
        for value in check_log_leaks.CANARIES.values():
            for _, needle in check_log_leaks.encoded_forms(value):
                self.assertGreaterEqual(len(needle), 12)


class MainTest(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.root = Path(temp.name).resolve()

    def run_main(self, *argv):
        output = io.StringIO()
        with contextlib.redirect_stdout(output):
            code = check_log_leaks.main(["--root", str(self.root), *argv])
        return code, output.getvalue()

    def test_print_canaries(self):
        output = io.StringIO()
        with contextlib.redirect_stdout(output):
            code = check_log_leaks.main(["--print-canaries"])
        self.assertEqual(code, 0)
        self.assertIn(f"LOG_CANARY_PASSWORD={PASSWORD}", output.getvalue())

    def test_clean_run(self):
        command = python_command("print('event=user.login user_id=7')")
        code, output = self.run_main("--command", command, "--expect", "user.login")
        self.assertEqual(code, 0)
        self.assertIn("clean: no fake secret in 1 source(s)", output)

    def test_leak_from_environment_in_stderr(self):
        code_text = "import os,sys; sys.stderr.write('pw=' + os.environ['LOG_CANARY_PASSWORD'])"
        code, output = self.run_main("--command", python_command(code_text), "--expect", "pw=")
        self.assertEqual(code, 1)
        self.assertIn("LEAK: 1 line(s) hold a fake secret", output)
        self.assertIn("LOG_CANARY_PASSWORD (as is) in command output line 1:", output)

    def test_leak_in_log_file_counts_only_new_lines(self):
        log = self.root / "logs" / "app.log"
        log.parent.mkdir()
        log.write_text(f"old line with {PASSWORD}\n", encoding="utf-8")
        code_text = "open('logs/app.log','a').write('event=user.login\\n')"
        code, output = self.run_main(
            "--command", python_command(code_text), "--expect", "user.login",
            "--log-file", "logs/app.log",
        )
        self.assertEqual(code, 0, output)
        self.assertIn("clean: no fake secret in 2 source(s)", output)

    def test_leak_written_to_log_file(self):
        code_text = (
            "import os; open('app.log','w').write('event=user.login email='"
            " + os.environ['LOG_CANARY_EMAIL'])"
        )
        code, output = self.run_main(
            "--command", python_command(code_text), "--expect", "user.login",
            "--log-file", "app.log",
        )
        self.assertEqual(code, 1)
        self.assertIn("LOG_CANARY_EMAIL (as is) in", output)
        self.assertIn("app.log line 1", output)

    def test_rotated_log_file_is_read_whole(self):
        log = self.root / "app.log"
        log.write_text("x" * 500, encoding="utf-8")
        code_text = f"open('app.log','w').write('event=user.login {PASSWORD}')"
        code, output = self.run_main(
            "--command", python_command(code_text), "--expect", "user.login",
            "--log-file", str(log),
        )
        self.assertEqual(code, 1)

    def test_leak_wins_over_failed_command(self):
        code_text = f"import sys; print('{PASSWORD}'); sys.exit(3)"
        code, output = self.run_main("--command", python_command(code_text), "--expect", "x")
        self.assertEqual(code, 1)

    def test_failed_command_proves_nothing(self):
        code_text = "import sys; print('event=user.login'); sys.exit(3)"
        code, output = self.run_main("--command", python_command(code_text), "--expect", "user.login")
        self.assertEqual(code, 2)
        self.assertIn("proves nothing: the command failed (exit 3)", output)
        self.assertIn("last lines of its output:\n      event=user.login\n", output)

    def test_failure_shows_only_the_last_lines(self):
        code_text = "import sys; [print(f'line {n}') for n in range(30)]; sys.exit(1)"
        code, output = self.run_main("--command", python_command(code_text), "--expect", "x")
        self.assertEqual(code, 2)
        self.assertIn("line 29", output)
        self.assertIn("line 20", output)
        self.assertNotIn("line 19", output)

    def test_silent_failure_shows_no_output_header(self):
        code, output = self.run_main("--command", python_command("import sys; sys.exit(4)"), "--expect", "x")
        self.assertEqual(code, 2)
        self.assertNotIn("last lines", output)

    def test_missing_expect_text_proves_nothing(self):
        code, output = self.run_main("--command", python_command("print('hi')"), "--expect", "user.login")
        self.assertEqual(code, 2)
        self.assertIn("proves nothing: 'user.login' never showed up", output)

    def test_hang_proves_nothing(self):
        code_text = "import time; print('waiting for db', flush=True); time.sleep(30)"
        code, output = self.run_main(
            "--command", python_command(code_text), "--expect", "x", "--timeout", "0.5"
        )
        self.assertEqual(code, 2)
        self.assertIn("proves nothing: the command hung past 0.5s", output)
        self.assertIn("      waiting for db", output)

    def test_missing_root(self):
        output = io.StringIO()
        with contextlib.redirect_stdout(output):
            code = check_log_leaks.main(
                ["--root", str(self.root / "nope"), "--command", "true", "--expect", "x"]
            )
        self.assertEqual(code, 2)
        self.assertIn("cannot start: the folder does not exist", output.getvalue())

    def test_bad_arguments(self):
        cases = [
            [],
            ["--command", "true"],
            ["--command", "  ", "--expect", "x"],
            ["--command", "true", "--expect", ""],
            ["--command", "true", "--expect", "x", "--timeout", "0"],
        ]
        for argv in cases:
            with self.subTest(argv=argv):
                with contextlib.redirect_stderr(io.StringIO()):
                    with self.assertRaises(SystemExit) as caught:
                        check_log_leaks.main(argv)
                self.assertEqual(caught.exception.code, 2)

    def test_long_lines_are_shortened(self):
        line = "a" * 500
        self.assertEqual(len(check_log_leaks.shorten(line)), check_log_leaks.SHOWN_LINE_LENGTH + 3)


if __name__ == "__main__":
    unittest.main()
