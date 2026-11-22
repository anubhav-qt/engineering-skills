"""Tests for skills/feature-test/scripts/plant_bugs.py.

Run from the repo root: python3 -m unittest discover tests
"""

import contextlib
import importlib.util
import io
import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

REPO_ROOT = Path(__file__).resolve().parent.parent
SCRIPT = REPO_ROOT / "skills" / "feature-test" / "scripts" / "plant_bugs.py"

spec = importlib.util.spec_from_file_location("plant_bugs", SCRIPT)
plant_bugs = importlib.util.module_from_spec(spec)
spec.loader.exec_module(plant_bugs)

CALC = """\
def clamp(value, low, high):
    if value < low:
        return low
    if value > high:
        return high
    return value


def double(number):
    return number * 2
"""

TEST_CALC = """\
import unittest

from calc import clamp


class ClampTest(unittest.TestCase):
    def test_inside(self):
        self.assertEqual(clamp(5, 0, 10), 5)

    def test_below(self):
        self.assertEqual(clamp(-1, 0, 10), 0)

    def test_above(self):
        self.assertEqual(clamp(11, 0, 10), 10)
"""

TEST_COMMAND = f'"{sys.executable}" -m unittest -q'

CAUGHT_BUG = {"file": "calc.py", "find": "value < low", "replace": "value > low", "why": "flip low check"}
SURVIVING_BUG = {"file": "calc.py", "find": "number * 2", "replace": "number * 3", "why": "double is untested"}


class ProjectTest(unittest.TestCase):
    """Each test gets a tiny project with one module and its tests."""

    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.base = Path(temp.name)
        self.project = self.base / "project"
        self.project.mkdir()
        self.calc = self.project / "calc.py"
        self.calc.write_text(CALC, encoding="utf-8")
        (self.project / "test_calc.py").write_text(TEST_CALC, encoding="utf-8")
        self.bugs_file = self.base / "bugs.json"

    def write_bugs(self, bugs):
        self.bugs_file.write_text(json.dumps(bugs), encoding="utf-8")

    def run_main(self, *extra):
        argv = [
            "--bugs",
            str(self.bugs_file),
            "--test",
            TEST_COMMAND,
            "--root",
            str(self.project),
            *extra,
        ]
        output = io.StringIO()
        with contextlib.redirect_stdout(output):
            code = plant_bugs.main(argv)
        return code, output.getvalue()

    def assert_untouched(self):
        self.assertEqual(self.calc.read_text(encoding="utf-8"), CALC)
        self.assertEqual(list(self.project.glob("*.plant-bugs.bak")), [])


class PlantTest(ProjectTest):
    def test_caught_bug(self):
        self.write_bugs([CAUGHT_BUG])
        code, output = self.run_main()
        self.assertEqual(code, 0)
        self.assertIn("caught    calc.py: flip low check", output)
        self.assertIn("1 of 1 bugs caught", output)
        self.assert_untouched()

    def test_surviving_bug(self):
        self.write_bugs([SURVIVING_BUG])
        code, output = self.run_main()
        self.assertEqual(code, 1)
        self.assertIn("SURVIVED  calc.py: double is untested", output)
        self.assertIn("0 of 1 bugs caught", output)
        self.assert_untouched()

    def test_bugs_run_in_order_on_the_original_file(self):
        self.write_bugs([CAUGHT_BUG, SURVIVING_BUG, CAUGHT_BUG])
        code, output = self.run_main()
        self.assertEqual(code, 1)
        lines = output.splitlines()
        self.assertTrue(lines[0].startswith("caught"))
        self.assertTrue(lines[1].startswith("SURVIVED"))
        self.assertTrue(lines[2].startswith("caught"))
        self.assertIn("2 of 3 bugs caught", output)
        self.assert_untouched()

    def test_bug_without_why_shows_file_only(self):
        self.write_bugs([{"file": "calc.py", "find": "value < low", "replace": "value > low"}])
        code, output = self.run_main()
        self.assertEqual(code, 0)
        self.assertIn("caught    calc.py\n", output)

    def test_blank_why_shows_file_only(self):
        self.write_bugs([dict(CAUGHT_BUG, why="   ")])
        code, output = self.run_main()
        self.assertEqual(code, 0)
        self.assertIn("caught    calc.py\n", output)

    def test_why_is_trimmed(self):
        self.write_bugs([dict(CAUGHT_BUG, why="  flip low check \n")])
        code, output = self.run_main()
        self.assertIn("caught    calc.py: flip low check\n", output)

    def test_interrupt_stops_running_tests(self):
        started = []
        real_popen = subprocess.Popen

        def spy(*args, **kwargs):
            process = real_popen(*args, **kwargs)
            started.append(process)
            return process

        with mock.patch.object(plant_bugs.subprocess, "Popen", side_effect=spy):
            with mock.patch.object(
                real_popen, "communicate", side_effect=KeyboardInterrupt
            ):
                with self.assertRaises(KeyboardInterrupt):
                    plant_bugs.run_tests("sleep 30", self.project, 60)
        process = started[0]
        self.addCleanup(process.kill)
        self.assertIsNotNone(process.poll())
        self.assertTrue(process.stdout.closed)

    def test_find_text_missing(self):
        self.write_bugs([{"file": "calc.py", "find": "no such text", "replace": "x"}])
        code, output = self.run_main()
        self.assertEqual(code, 1)
        self.assertIn("unusable  calc.py (find text matches 0 times, it must match once)", output)
        self.assert_untouched()

    def test_find_text_matches_twice(self):
        self.write_bugs([{"file": "calc.py", "find": "return ", "replace": "return -"}])
        code, output = self.run_main()
        self.assertEqual(code, 1)
        self.assertIn("matches 4 times", output)
        self.assert_untouched()

    def test_file_not_utf8(self):
        binary = self.project / "data.bin"
        binary.write_bytes(b"\xff\xfe\x00bad")
        self.write_bugs([{"file": "data.bin", "find": "bad", "replace": "good"}])
        code, output = self.run_main()
        self.assertEqual(code, 1)
        self.assertIn("unusable  data.bin (file is not UTF-8 text)", output)
        self.assertEqual(binary.read_bytes(), b"\xff\xfe\x00bad")

    def test_stuck_tests_count_as_caught(self):
        endless = {
            "file": "calc.py",
            "find": "    return value\n",
            "replace": "    while True:\n        pass\n",
            "why": "endless loop",
        }
        self.write_bugs([endless])
        code, output = self.run_main("--timeout", "3")
        self.assertEqual(code, 0)
        self.assertIn("caught    calc.py: endless loop (tests timed out after 3s)", output)
        self.assert_untouched()

    def test_windows_line_endings_are_kept(self):
        crlf = CALC.replace("\n", "\r\n").encode("utf-8")
        self.calc.write_bytes(crlf)
        self.write_bugs([CAUGHT_BUG])
        code, _ = self.run_main()
        self.assertEqual(code, 0)
        self.assertEqual(self.calc.read_bytes(), crlf)

    def test_file_is_restored_when_interrupted(self):
        self.write_bugs([CAUGHT_BUG])
        clean = plant_bugs.TestRun(True, False, 0.1, "")
        with mock.patch.object(
            plant_bugs, "run_tests", side_effect=[clean, KeyboardInterrupt]
        ):
            with self.assertRaises(KeyboardInterrupt):
                self.run_main()
        self.assert_untouched()

    def test_default_timeout_has_a_floor(self):
        self.assertEqual(self.timeout_after_clean_run(seconds=1), 60)

    def test_default_timeout_grows_with_slow_tests(self):
        self.assertEqual(self.timeout_after_clean_run(seconds=12), 120)

    def timeout_after_clean_run(self, seconds):
        self.write_bugs([CAUGHT_BUG])
        clean = plant_bugs.TestRun(True, False, seconds, "")
        with mock.patch.object(plant_bugs, "run_tests", return_value=clean):
            with mock.patch.object(
                plant_bugs, "plant_and_test", return_value=("caught", "")
            ) as planted:
                self.run_main()
        return planted.call_args[0][3]


class StartTest(ProjectTest):
    """Every problem found before planting stops the run with code 2."""

    def assert_cannot_start(self, expected, *extra):
        code, output = self.run_main(*extra)
        self.assertEqual(code, 2)
        self.assertIn("cannot start:", output)
        self.assertIn(expected, output)
        self.assert_untouched()

    def test_tests_fail_before_planting(self):
        (self.project / "test_calc.py").write_text(
            TEST_CALC.replace("clamp(5, 0, 10), 5", "clamp(5, 0, 10), 6"),
            encoding="utf-8",
        )
        self.write_bugs([CAUGHT_BUG])
        self.assert_cannot_start("fail before any bug is planted")

    def test_failing_output_is_shown(self):
        (self.project / "test_calc.py").write_text(
            TEST_CALC.replace("clamp(5, 0, 10), 5", "clamp(5, 0, 10), 6"),
            encoding="utf-8",
        )
        self.write_bugs([CAUGHT_BUG])
        self.assert_cannot_start("FAILED (failures=1)")

    def test_leftover_backup(self):
        (self.project / "calc.py.plant-bugs.bak").write_text(CALC, encoding="utf-8")
        self.write_bugs([CAUGHT_BUG])
        code, output = self.run_main()
        self.assertEqual(code, 2)
        self.assertIn("an earlier run did not finish", output)
        self.assertEqual(self.calc.read_text(encoding="utf-8"), CALC)

    def test_missing_bugs_file(self):
        self.assert_cannot_start("cannot read the bugs file")

    def test_bugs_file_not_json(self):
        self.bugs_file.write_text("[{", encoding="utf-8")
        self.assert_cannot_start("not valid JSON")

    def test_bugs_file_empty_list(self):
        self.write_bugs([])
        self.assert_cannot_start("at least one bug")

    def test_bugs_file_not_a_list(self):
        self.write_bugs(CAUGHT_BUG)
        self.assert_cannot_start("at least one bug")

    def test_entry_not_an_object(self):
        self.write_bugs(["calc.py"])
        self.assert_cannot_start("bug 1 must be an object")

    def test_entry_missing_key(self):
        self.write_bugs([CAUGHT_BUG, {"file": "calc.py", "find": "x"}])
        self.assert_cannot_start('bug 2 needs "replace" as text')

    def test_entry_key_not_text(self):
        self.write_bugs([{"file": "calc.py", "find": 1, "replace": "x"}])
        self.assert_cannot_start('bug 1 needs "find" as text')

    def test_why_not_text(self):
        self.write_bugs([dict(CAUGHT_BUG, why=3)])
        self.assert_cannot_start('"why" that is not text')

    def test_empty_find(self):
        self.write_bugs([{"file": "calc.py", "find": "", "replace": "x"}])
        self.assert_cannot_start('empty "find"')

    def test_replace_same_as_find(self):
        self.write_bugs([{"file": "calc.py", "find": "low", "replace": "low"}])
        self.assert_cannot_start("changes nothing")

    def test_file_outside_project(self):
        outside = self.base / "outside.py"
        outside.write_text("x = 1\n", encoding="utf-8")
        self.write_bugs([{"file": "../outside.py", "find": "1", "replace": "2"}])
        self.assert_cannot_start("points outside the project")
        self.assertEqual(outside.read_text(encoding="utf-8"), "x = 1\n")

    def test_link_to_file_outside_project(self):
        outside = self.base / "outside.py"
        outside.write_text("x = 1\n", encoding="utf-8")
        os.symlink(outside, self.project / "linked.py")
        self.write_bugs([{"file": "linked.py", "find": "1", "replace": "2"}])
        self.assert_cannot_start("points outside the project")

    def test_file_missing(self):
        self.write_bugs([{"file": "gone.py", "find": "a", "replace": "b"}])
        self.assert_cannot_start("file that does not exist: gone.py")

    def test_folder_instead_of_file(self):
        (self.project / "pkg").mkdir()
        self.write_bugs([{"file": "pkg", "find": "a", "replace": "b"}])
        self.assert_cannot_start("file that does not exist: pkg")

    def test_bad_entry_stops_before_any_run(self):
        self.write_bugs([CAUGHT_BUG, {"file": "gone.py", "find": "a", "replace": "b"}])
        with mock.patch.object(plant_bugs, "run_tests") as runner:
            self.assert_cannot_start("bug 2")
        runner.assert_not_called()

    def test_missing_project_folder(self):
        self.write_bugs([CAUGHT_BUG])
        argv = ["--bugs", str(self.bugs_file), "--test", TEST_COMMAND, "--root", str(self.base / "nope")]
        output = io.StringIO()
        with contextlib.redirect_stdout(output):
            code = plant_bugs.main(argv)
        self.assertEqual(code, 2)
        self.assertIn("project folder does not exist", output.getvalue())


class ArgumentTest(unittest.TestCase):
    def assert_rejected(self, argv, expected):
        errors = io.StringIO()
        with contextlib.redirect_stderr(errors):
            with self.assertRaises(SystemExit) as stop:
                plant_bugs.parse_args(argv)
        self.assertEqual(stop.exception.code, 2)
        self.assertIn(expected, errors.getvalue())

    def test_empty_test_command(self):
        self.assert_rejected(["--bugs", "b.json", "--test", "  "], "--test must not be empty")

    def test_zero_timeout(self):
        self.assert_rejected(["--bugs", "b.json", "--test", "t", "--timeout", "0"], "more than 0")

    def test_missing_bugs(self):
        self.assert_rejected(["--test", "t"], "--bugs")


class CommandLineTest(ProjectTest):
    def test_runs_as_a_script(self):
        self.write_bugs([CAUGHT_BUG, SURVIVING_BUG])
        result = subprocess.run(
            [
                sys.executable,
                str(SCRIPT),
                "--bugs",
                str(self.bugs_file),
                "--test",
                TEST_COMMAND,
                "--root",
                str(self.project),
            ],
            capture_output=True,
            text=True,
        )
        self.assertEqual(result.returncode, 1)
        self.assertIn("SURVIVED  calc.py: double is untested", result.stdout)
        self.assertIn("1 of 2 bugs caught", result.stdout)
        self.assert_untouched()


if __name__ == "__main__":
    unittest.main()
