"""Tests for skills/debug/scripts/repeat_until_fail.py.

Run from the repo root: python3 -m unittest discover tests
"""

import contextlib
import importlib.util
import io
import os
import sys
import tempfile
import time
import unittest
from pathlib import Path
from unittest import mock

REPO_ROOT = Path(__file__).resolve().parent.parent
SCRIPT = REPO_ROOT / "skills" / "debug" / "scripts" / "repeat_until_fail.py"

spec = importlib.util.spec_from_file_location("repeat_until_fail", SCRIPT)
repeat_until_fail = importlib.util.module_from_spec(spec)
spec.loader.exec_module(repeat_until_fail)

PYTHON = f'"{sys.executable}"'


def python_command(code):
    return f'{PYTHON} -c "{code}"'


class RepeatTest(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.base = Path(temp.name).resolve()
        self.project = self.base / "project"
        self.project.mkdir()
        self.counter = self.base / "count.txt"

    def run_main(self, *argv):
        output = io.StringIO()
        with contextlib.redirect_stdout(output):
            code = repeat_until_fail.main(list(argv))
        return code, output.getvalue()

    def fail_on_run(self, failing_run):
        """A command that counts its runs in a file and fails on one of them."""
        script = self.base / "flaky.py"
        script.write_text(
            "import pathlib, sys\n"
            f"path = pathlib.Path({str(self.counter)!r})\n"
            "count = int(path.read_text()) + 1 if path.exists() else 1\n"
            "path.write_text(str(count))\n"
            "print('run', count)\n"
            f"sys.exit(4 if count == {failing_run} else 0)\n",
            encoding="utf-8",
        )
        return f'{PYTHON} "{script}"'

    def runs_made(self):
        return int(self.counter.read_text())


class PassTest(RepeatTest):
    def test_every_run_passes(self):
        command = self.fail_on_run(0)
        code, output = self.run_main("--command", command, "--times", "5", "--root", str(self.project))
        self.assertEqual(code, 0)
        self.assertEqual(self.runs_made(), 5)
        self.assertIn("pass: all 5 runs passed", output)

    def test_one_run(self):
        command = self.fail_on_run(0)
        code, output = self.run_main("--command", command, "--times", "1")
        self.assertEqual(code, 0)
        self.assertEqual(self.runs_made(), 1)
        self.assertIn("all 1 runs passed", output)

    def test_default_is_fifty_runs(self):
        command = self.fail_on_run(0)
        code, output = self.run_main("--command", command)
        self.assertEqual(code, 0)
        self.assertEqual(self.runs_made(), 50)


class FailTest(RepeatTest):
    def test_stops_at_the_first_failure(self):
        command = self.fail_on_run(3)
        code, output = self.run_main("--command", command, "--times", "10")
        self.assertEqual(code, 1)
        self.assertEqual(self.runs_made(), 3)
        self.assertIn("FAIL on run 3 of 10 (exit 4,", output)

    def test_prints_what_the_failing_run_printed(self):
        command = self.fail_on_run(2)
        code, output = self.run_main("--command", command, "--times", "5")
        self.assertIn("    run 2", output)
        self.assertNotIn("    run 1", output)

    def test_fails_on_the_first_run(self):
        command = python_command("import sys; sys.exit(1)")
        code, output = self.run_main("--command", command, "--times", "5")
        self.assertEqual(code, 1)
        self.assertIn("FAIL on run 1 of 5", output)

    def test_shows_only_the_last_lines(self):
        command = python_command("import sys; [print('line', n) for n in range(100)]; sys.exit(1)")
        code, output = self.run_main("--command", command, "--times", "1")
        self.assertIn("    line 99", output)
        self.assertIn("    line 60", output)
        self.assertNotIn("    line 59", output)

    def test_stderr_is_shown_too(self):
        command = python_command("import sys; sys.stderr.write('boom on stderr'); sys.exit(1)")
        code, output = self.run_main("--command", command, "--times", "1")
        self.assertIn("boom on stderr", output)

    def test_log_holds_the_full_output(self):
        command = python_command("import sys; [print('line', n) for n in range(100)]; sys.exit(1)")
        log = self.base / "logs" / "fail.log"
        code, output = self.run_main("--command", command, "--times", "1", "--log", str(log))
        text = log.read_text(encoding="utf-8")
        self.assertIn("line 0\n", text)
        self.assertIn("line 99", text)
        self.assertIn("== run 1 ==", text)
        self.assertIn(f"Full output: {log}", output)

    def test_no_log_file_without_the_option(self):
        command = python_command("import sys; sys.exit(1)")
        code, output = self.run_main("--command", command, "--times", "1", "--root", str(self.project))
        self.assertEqual(list(self.project.iterdir()), [])
        self.assertEqual([path.name for path in self.base.iterdir()], ["project"])
        self.assertNotIn("Full output", output)

    def test_no_log_when_every_run_passes(self):
        command = self.fail_on_run(0)
        log = self.base / "pass.log"
        self.run_main("--command", command, "--times", "2", "--log", str(log))
        self.assertFalse(log.exists())


class TimeoutTest(RepeatTest):
    def test_a_hang_counts_as_a_failure(self):
        command = python_command("import time; time.sleep(30)")
        started = time.monotonic()
        code, output = self.run_main("--command", command, "--times", "3", "--timeout", "0.5")
        self.assertEqual(code, 1)
        self.assertLess(time.monotonic() - started, 10)
        self.assertIn("FAIL on run 1 of 3 (timed out after 0.5s)", output)

    def test_timeout_kills_child_processes(self):
        marker = self.base / "child-alive.txt"
        child = (
            "import time, pathlib; time.sleep(2); "
            f"pathlib.Path({str(marker)!r}).write_text('alive')"
        )
        script = self.base / "parent.py"
        script.write_text(
            "import subprocess, sys, time\n"
            f"subprocess.Popen([sys.executable, '-c', {child!r}])\n"
            "time.sleep(30)\n",
            encoding="utf-8",
        )
        code, output = self.run_main("--command", f'{PYTHON} "{script}"', "--times", "1", "--timeout", "0.5")
        self.assertEqual(code, 1)
        time.sleep(3)
        self.assertFalse(marker.exists())

    def test_leftover_child_holding_output_still_times_out(self):
        script = self.base / "parent.py"
        script.write_text(
            "import subprocess, sys\n"
            "subprocess.Popen([sys.executable, '-c', 'import time; time.sleep(30)'])\n",
            encoding="utf-8",
        )
        started = time.monotonic()
        code, output = self.run_main("--command", f'{PYTHON} "{script}"', "--times", "1", "--timeout", "1")
        self.assertLess(time.monotonic() - started, 10)
        self.assertEqual(code, 1)
        self.assertIn("timed out", output)


    def test_ctrl_c_stops_the_command_and_closes_its_output(self):
        started = []
        real_popen = repeat_until_fail.subprocess.Popen

        def spy(*args, **kwargs):
            process = real_popen(*args, **kwargs)
            started.append(process)
            return process

        command = python_command("import time; time.sleep(30)")
        with mock.patch.object(repeat_until_fail.subprocess, "Popen", side_effect=spy):
            with mock.patch.object(real_popen, "communicate", side_effect=KeyboardInterrupt):
                with self.assertRaises(KeyboardInterrupt):
                    self.run_main("--command", command, "--times", "1")
        process = started[0]
        self.assertIsNotNone(process.poll())
        self.assertTrue(process.stdout.closed)


class EnvironmentTest(RepeatTest):
    def test_runs_in_the_root_folder(self):
        command = python_command("import os, sys; sys.exit(0 if os.path.exists('here.txt') else 1)")
        (self.project / "here.txt").write_text("x", encoding="utf-8")
        code, output = self.run_main("--command", command, "--times", "1", "--root", str(self.project))
        self.assertEqual(code, 0)

    def test_ci_is_set(self):
        command = python_command("import os, sys; sys.exit(0 if os.environ.get('CI') == 'true' else 1)")
        with mock.patch.dict(os.environ, {"CI": "false"}):
            code, output = self.run_main("--command", command, "--times", "1")
        self.assertEqual(code, 0)

    def test_stdin_is_closed(self):
        command = python_command("import sys; sys.exit(0 if sys.stdin.read() == '' else 1)")
        read_end, write_end = os.pipe()
        self.addCleanup(os.close, write_end)
        saved = os.dup(0)
        os.dup2(read_end, 0)
        os.close(read_end)
        try:
            started = time.monotonic()
            code, output = self.run_main("--command", command, "--times", "1", "--timeout", "5")
        finally:
            os.dup2(saved, 0)
            os.close(saved)
        self.assertEqual(code, 0)
        self.assertLess(time.monotonic() - started, 4)

    def test_shell_features_work(self):
        command = python_command("print('a')") + " && " + python_command("import sys; sys.exit(2)")
        code, output = self.run_main("--command", command, "--times", "1")
        self.assertEqual(code, 1)
        self.assertIn("exit 2", output)


class StartTest(RepeatTest):
    def test_missing_root(self):
        code, output = self.run_main("--command", "true", "--root", str(self.base / "nope"))
        self.assertEqual(code, 2)
        self.assertIn("the folder does not exist", output)

    def test_root_is_a_file(self):
        file = self.base / "file.txt"
        file.write_text("x", encoding="utf-8")
        code, output = self.run_main("--command", "true", "--root", str(file))
        self.assertEqual(code, 2)
        self.assertIn("the folder does not exist", output)

    def check_usage_error(self, *argv):
        with contextlib.redirect_stderr(io.StringIO()):
            with self.assertRaises(SystemExit) as caught:
                repeat_until_fail.main(list(argv))
        self.assertEqual(caught.exception.code, 2)

    def test_zero_times(self):
        self.check_usage_error("--command", "true", "--times", "0")

    def test_negative_timeout(self):
        self.check_usage_error("--command", "true", "--timeout", "-1")

    def test_zero_timeout(self):
        self.check_usage_error("--command", "true", "--timeout", "0")

    def test_empty_command(self):
        self.check_usage_error("--command", "  ")

    def test_command_is_required(self):
        self.check_usage_error("--times", "3")


if __name__ == "__main__":
    unittest.main()
