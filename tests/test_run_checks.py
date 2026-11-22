"""Tests for skills/full-test/scripts/run_checks.py.

Run from the repo root: python3 -m unittest discover tests
"""

import contextlib
import importlib.util
import io
import json
import os
import shutil
import subprocess
import sys
import tempfile
import time
import unittest
from pathlib import Path
from unittest import mock

REPO_ROOT = Path(__file__).resolve().parent.parent
SCRIPT = REPO_ROOT / "skills" / "full-test" / "scripts" / "run_checks.py"

spec = importlib.util.spec_from_file_location("run_checks", SCRIPT)
run_checks = importlib.util.module_from_spec(spec)
spec.loader.exec_module(run_checks)

PYTHON = f'"{sys.executable}"'
PASS = f'{PYTHON} -c "print(\'all good\')"'
FAIL = f'{PYTHON} -c "import sys; print(\'lint broke\'); sys.exit(3)"'


class ChecksTest(unittest.TestCase):
    """Each test gets a project folder, a checks file and a log folder."""

    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.base = Path(temp.name)
        self.project = self.base / "project"
        self.project.mkdir()
        self.checks_file = self.base / "checks.json"
        self.log_dir = self.base / "logs"

    def write_checks(self, checks):
        self.checks_file.write_text(json.dumps(checks), encoding="utf-8")

    def run_main(self, *extra):
        argv = [
            "--checks",
            str(self.checks_file),
            "--root",
            str(self.project),
            "--log-dir",
            str(self.log_dir),
            *extra,
        ]
        output = io.StringIO()
        with contextlib.redirect_stdout(output):
            code = run_checks.main(argv)
        return code, output.getvalue()

    def log(self, name):
        return (self.log_dir / f"{name}.log").read_text(encoding="utf-8")


class RunTest(ChecksTest):
    def test_all_pass(self):
        self.write_checks([{"name": "lint", "command": PASS}, {"name": "tests", "command": PASS}])
        code, output = self.run_main()
        self.assertEqual(code, 0)
        lines = output.splitlines()
        self.assertTrue(lines[0].startswith("pass   lint "))
        self.assertTrue(lines[1].startswith("pass   tests"))
        self.assertIn("2 of 2 checks passed", output)

    def test_every_check_runs_after_a_failure(self):
        self.write_checks([
            {"name": "lint", "command": FAIL},
            {"name": "tests", "command": PASS},
        ])
        code, output = self.run_main()
        self.assertEqual(code, 1)
        self.assertIn("FAIL   lint", output)
        self.assertIn("pass   tests", output)
        self.assertIn("1 of 2 checks passed", output)

    def test_failure_shows_output_tail(self):
        self.write_checks([{"name": "lint", "command": FAIL}])
        code, output = self.run_main()
        self.assertEqual(code, 1)
        self.assertIn("    lint broke", output)

    def test_pass_hides_output(self):
        self.write_checks([{"name": "lint", "command": PASS}])
        code, output = self.run_main()
        self.assertNotIn("    all good", output)

    def test_only_the_last_lines_are_shown(self):
        command = f'{PYTHON} -c "import sys; [print(n) for n in range(100)]; sys.exit(1)"'
        self.write_checks([{"name": "tests", "command": command}])
        code, output = self.run_main()
        self.assertIn("    99", output)
        self.assertIn("    80", output)
        self.assertNotIn("    79\n", output)

    def test_log_holds_full_output_and_exit_code(self):
        self.write_checks([{"name": "lint", "command": FAIL}])
        self.run_main()
        log = self.log("lint")
        self.assertIn(f"$ {FAIL}", log)
        self.assertIn("run 1 of 1: exit 3", log)
        self.assertIn("lint broke", log)

    def test_log_holds_what_the_check_printed(self):
        command = f'{PYTHON} -c "print(6 * 7)"'
        self.write_checks([{"name": "math", "command": command}])
        self.run_main()
        self.assertIn("42", self.log("math"))

    def test_leftover_child_holding_output_counts_as_timeout(self):
        # The shell exits 0 at once, but a child keeps the output open.
        child = "import subprocess, sys; subprocess.Popen([sys.executable, '-c', 'import time; time.sleep(30)'])"
        command = f'{PYTHON} -c "{child}"'
        self.write_checks([{"name": "child", "command": command, "timeout": 1}])
        started = time.monotonic()
        code, output = self.run_main()
        self.assertLess(time.monotonic() - started, 15)
        self.assertEqual(code, 1)
        self.assertIn("FAIL   child", output)

    def test_runs_in_the_root_folder(self):
        (self.project / "marker.txt").write_text("here", encoding="utf-8")
        command = f'{PYTHON} -c "open(\'marker.txt\')"'
        self.write_checks([{"name": "where", "command": command}])
        code, output = self.run_main()
        self.assertEqual(code, 0)

    def test_ci_is_set(self):
        command = f'{PYTHON} -c "import os, sys; sys.exit(os.environ.get(\'CI\') != \'true\')"'
        self.write_checks([{"name": "ci", "command": command}])
        code, output = self.run_main()
        self.assertEqual(code, 0)

    def test_stdin_is_closed_so_prompts_do_not_hang(self):
        # Give this process an input that stays open and never sends
        # anything, so a check that inherits it would wait forever.
        command = f'{PYTHON} -c "input()"'
        self.write_checks([{"name": "prompt", "command": command, "timeout": 5}])
        read_end, write_end = os.pipe()
        saved_stdin = os.dup(0)
        os.dup2(read_end, 0)
        try:
            code, output = self.run_main()
        finally:
            os.dup2(saved_stdin, 0)
            os.close(saved_stdin)
            os.close(read_end)
            os.close(write_end)
        self.assertEqual(code, 1)
        self.assertNotIn("timed out", output)

    def test_stuck_check_times_out(self):
        command = f'{PYTHON} -c "import time; time.sleep(30)"'
        self.write_checks([{"name": "stuck", "command": command, "timeout": 1}])
        started = time.monotonic()
        code, output = self.run_main()
        self.assertLess(time.monotonic() - started, 15)
        self.assertEqual(code, 1)
        self.assertIn("FAIL   stuck", output)
        self.assertIn("timed out after 1s", output)
        self.assertIn("timed out after 1s", self.log("stuck"))

    def test_interrupt_stops_the_check(self):
        self.write_checks([{"name": "tests", "command": PASS}])
        started = []
        real_popen = subprocess.Popen

        def spy(*args, **kwargs):
            process = real_popen(*args, **kwargs)
            started.append(process)
            return process

        with mock.patch.object(run_checks.subprocess, "Popen", side_effect=spy):
            with mock.patch.object(real_popen, "communicate", side_effect=KeyboardInterrupt):
                with mock.patch.object(run_checks, "kill_process_group") as kill:
                    with self.assertRaises(KeyboardInterrupt):
                        self.run_main()
        kill.assert_called_once()
        self.assertTrue(started[0].stdout.closed)

    def test_odd_output_bytes_do_not_crash(self):
        command = f'{PYTHON} -c "import sys; sys.stdout.buffer.write(bytes([255, 254])); sys.exit(1)"'
        self.write_checks([{"name": "odd", "command": command}])
        code, output = self.run_main()
        self.assertEqual(code, 1)
        self.assertIn("FAIL   odd", output)

    def test_default_log_dir_is_made(self):
        self.write_checks([{"name": "lint", "command": PASS}])
        argv = ["--checks", str(self.checks_file), "--root", str(self.project)]
        output = io.StringIO()
        with contextlib.redirect_stdout(output):
            code = run_checks.main(argv)
        self.assertEqual(code, 0)
        log_dir = Path(output.getvalue().split("Full output: ")[1].strip())
        self.addCleanup(shutil.rmtree, log_dir)
        self.assertTrue((log_dir / "lint.log").is_file())


class OnlyTest(ChecksTest):
    def test_only_runs_the_named_checks_in_file_order(self):
        self.write_checks([
            {"name": "install", "command": PASS},
            {"name": "lint", "command": FAIL},
            {"name": "tests", "command": PASS},
        ])
        code, output = self.run_main("--only", "tests", "--only", "install")
        self.assertEqual(code, 0)
        lines = output.splitlines()
        self.assertTrue(lines[0].startswith("pass   install"))
        self.assertTrue(lines[1].startswith("pass   tests"))
        self.assertNotIn("lint", output)
        self.assertIn("2 of 2 checks passed", output)

    def test_unknown_name(self):
        self.write_checks([{"name": "lint", "command": PASS}])
        code, output = self.run_main("--only", "lnt")
        self.assertEqual(code, 2)
        self.assertIn('no check named "lnt"', output)


class RepeatTest(ChecksTest):
    def flaky_command(self):
        counter = self.base / "count.txt"
        script = (
            "import pathlib, sys; "
            f"p = pathlib.Path({str(counter)!r}); "
            "n = int(p.read_text()) if p.exists() else 0; "
            "p.write_text(str(n + 1)); "
            "sys.exit(n % 2)"
        )
        return f'{PYTHON} -c "{script}"'

    def test_mixed_results_are_flaky(self):
        self.write_checks([{"name": "tests", "command": self.flaky_command()}])
        code, output = self.run_main("--repeat", "4")
        self.assertEqual(code, 1)
        self.assertIn("FLAKY  tests", output)
        self.assertIn("(2 of 4 passed)", output)
        self.assertIn("run 4 of 4", self.log("tests"))

    def test_steady_pass(self):
        self.write_checks([{"name": "tests", "command": PASS}])
        code, output = self.run_main("--repeat", "3")
        self.assertEqual(code, 0)
        self.assertIn("(3 of 3 passed)", output)

    def test_steady_fail(self):
        self.write_checks([{"name": "tests", "command": FAIL}])
        code, output = self.run_main("--repeat", "3")
        self.assertEqual(code, 1)
        self.assertIn("FAIL   tests", output)
        self.assertIn("(0 of 3 passed)", output)

    def test_single_run_shows_no_count(self):
        self.write_checks([{"name": "tests", "command": PASS}])
        code, output = self.run_main()
        self.assertNotIn("passed)", output)


class StartTest(ChecksTest):
    def assert_cannot_start(self, checks, message):
        if checks is not None:
            self.write_checks(checks)
        code, output = self.run_main()
        self.assertEqual(code, 2)
        self.assertIn("cannot start", output)
        self.assertIn(message, output)
        self.assertFalse(self.log_dir.exists())

    def test_missing_checks_file(self):
        self.assert_cannot_start(None, "cannot read the checks file")

    def test_not_json(self):
        self.checks_file.write_text("[{", encoding="utf-8")
        self.assert_cannot_start(None, "not valid JSON")

    def test_empty_list(self):
        self.assert_cannot_start([], "at least one check")

    def test_not_a_list(self):
        self.assert_cannot_start({"name": "lint"}, "at least one check")

    def test_entry_not_an_object(self):
        self.assert_cannot_start(["npm test"], "check 1 must be an object")

    def test_missing_name(self):
        self.assert_cannot_start([{"command": PASS}], 'check 1 needs a "name"')

    def test_name_with_a_slash(self):
        self.assert_cannot_start([{"name": "../lint", "command": PASS}], 'check 1 needs a "name"')

    def test_name_with_a_space(self):
        self.assert_cannot_start([{"name": "type check", "command": PASS}], 'check 1 needs a "name"')

    def test_name_too_odd(self):
        self.assert_cannot_start([{"name": "-lint", "command": PASS}], 'check 1 needs a "name"')

    def test_missing_command(self):
        self.assert_cannot_start([{"name": "lint"}], 'check 1 needs a "command"')

    def test_blank_command(self):
        self.assert_cannot_start([{"name": "lint", "command": "   "}], 'check 1 needs a "command"')

    def test_duplicate_name(self):
        checks = [{"name": "lint", "command": PASS}, {"name": "lint", "command": PASS}]
        self.assert_cannot_start(checks, 'check 2 reuses the name "lint"')

    def test_zero_timeout(self):
        self.assert_cannot_start([{"name": "lint", "command": PASS, "timeout": 0}], '"timeout"')

    def test_text_timeout(self):
        self.assert_cannot_start([{"name": "lint", "command": PASS, "timeout": "60"}], '"timeout"')

    def test_true_timeout(self):
        self.assert_cannot_start([{"name": "lint", "command": PASS, "timeout": True}], '"timeout"')

    def test_bad_entry_stops_before_any_run(self):
        marker = self.base / "ran.txt"
        command = f'{PYTHON} -c "open({str(marker)!r}, \'w\')"'
        self.assert_cannot_start(
            [{"name": "first", "command": command}, {"name": "second"}],
            'check 2 needs a "command"',
        )
        self.assertFalse(marker.exists())

    def test_missing_root(self):
        self.write_checks([{"name": "lint", "command": PASS}])
        argv = ["--checks", str(self.checks_file), "--root", str(self.base / "nope")]
        output = io.StringIO()
        with contextlib.redirect_stdout(output):
            code = run_checks.main(argv)
        self.assertEqual(code, 2)
        self.assertIn("the folder does not exist", output.getvalue())


class ArgumentTest(unittest.TestCase):
    def assert_usage_error(self, argv):
        with contextlib.redirect_stderr(io.StringIO()):
            with self.assertRaises(SystemExit) as raised:
                run_checks.parse_args(argv)
        self.assertEqual(raised.exception.code, 2)

    def test_zero_repeat(self):
        self.assert_usage_error(["--checks", "c.json", "--root", ".", "--repeat", "0"])

    def test_missing_root(self):
        self.assert_usage_error(["--checks", "c.json"])

    def test_missing_checks(self):
        self.assert_usage_error(["--root", "."])


class CommandLineTest(ChecksTest):
    def test_runs_as_a_script(self):
        self.write_checks([{"name": "lint", "command": FAIL}])
        result = subprocess.run(
            [sys.executable, str(SCRIPT), "--checks", str(self.checks_file),
             "--root", str(self.project), "--log-dir", str(self.log_dir)],
            capture_output=True,
            text=True,
        )
        self.assertEqual(result.returncode, 1)
        self.assertIn("FAIL   lint", result.stdout)


if __name__ == "__main__":
    unittest.main()
