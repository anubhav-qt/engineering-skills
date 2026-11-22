"""Tests for skills/full-test/scripts/scan_diff.py.

Run from the repo root: python3 -m unittest discover tests
"""

import contextlib
import importlib.util
import io
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

REPO_ROOT = Path(__file__).resolve().parent.parent
SCRIPT = REPO_ROOT / "skills" / "full-test" / "scripts" / "scan_diff.py"

spec = importlib.util.spec_from_file_location("scan_diff", SCRIPT)
scan_diff = importlib.util.module_from_spec(spec)
spec.loader.exec_module(scan_diff)

GIT_ENV = {
    "GIT_CONFIG_GLOBAL": os.devnull,
    "GIT_CONFIG_NOSYSTEM": "1",
    "GIT_AUTHOR_NAME": "tester",
    "GIT_AUTHOR_EMAIL": "tester@localhost",
    "GIT_COMMITTER_NAME": "tester",
    "GIT_COMMITTER_EMAIL": "tester@localhost",
}

# Built from pieces so this test file does not itself look like it leaks keys.
AWS_KEY = "AKIA" + "ABCDEFGHIJKLMNOP"
GITHUB_TOKEN = "ghp_" + "a" * 36


def git(cwd, *args):
    result = subprocess.run(["git", *args], cwd=cwd, capture_output=True, text=True)
    if result.returncode != 0:
        raise AssertionError(f"git {' '.join(args)} failed: {result.stderr}")
    return result.stdout


def write(path, text):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


class ScanTest(unittest.TestCase):
    """A repo with main, and a feature branch checked out on top of it."""

    def setUp(self):
        patcher = mock.patch.dict(os.environ, GIT_ENV)
        patcher.start()
        self.addCleanup(patcher.stop)
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.repo = Path(temp.name).resolve() / "project"
        self.repo.mkdir()
        git(self.repo, "init", "--quiet", "--initial-branch=main")
        write(self.repo / "app.js", "const a = 1;\n// TODO: old note\nconsole.log(a);\n")
        write(self.repo / ".gitignore", "ignored/\n")
        git(self.repo, "add", ".")
        git(self.repo, "commit", "--quiet", "-m", "first")
        git(self.repo, "checkout", "--quiet", "-b", "feature")

    def commit(self, name, text):
        write(self.repo / name, text)
        git(self.repo, "add", name)
        git(self.repo, "commit", "--quiet", "-m", f"add {name}")

    def run_main(self, base="main"):
        output = io.StringIO()
        with contextlib.redirect_stdout(output):
            code = scan_diff.main(["--repo", str(self.repo), "--base", base])
        return code, output.getvalue()

    def assert_finding(self, output, expected):
        self.assertIn(expected, output)


class CleanTest(ScanTest):
    def test_nothing_found(self):
        self.commit("util.js", "export const add = (a, b) => a + b;\n")
        code, output = self.run_main()
        self.assertEqual(code, 0)
        self.assertEqual(output, "nothing found\n")

    def test_old_problems_on_main_are_not_flagged(self):
        self.commit("other.js", "const b = 2;\n")
        code, output = self.run_main()
        self.assertEqual(code, 0)
        self.assertNotIn("app.js", output)

    def test_main_moving_on_does_not_flag_old_lines(self):
        # After the branch was made, main drops its old console.log and TODO.
        git(self.repo, "checkout", "--quiet", "main")
        self.commit("app.js", "const a = 1;\n")
        git(self.repo, "checkout", "--quiet", "feature")
        self.commit("util.js", "export const two = 2;\n")
        code, output = self.run_main()
        self.assertEqual(code, 0, output)

    def test_removed_lines_are_not_flagged(self):
        write(self.repo / "app.js", "const a = 1;\n")
        code, output = self.run_main()
        self.assertEqual(code, 0)

    def test_ignored_files_are_not_scanned(self):
        write(self.repo / "ignored" / "x.js", "console.log(1);\n")
        code, output = self.run_main()
        self.assertEqual(code, 0)

    def test_lowercase_todo_word_is_fine(self):
        self.commit("docs.md", "See docs/todo.md for the list.\n")
        code, output = self.run_main()
        self.assertEqual(code, 0)


class LineTest(ScanTest):
    def assert_one(self, text, expected, name="feature.js"):
        self.commit(name, text)
        code, output = self.run_main()
        self.assertEqual(code, 1, output)
        self.assertIn(expected, output)
        self.assertIn("1 thing(s) to look at", output)

    def test_console_log(self):
        self.assert_one("const x = 1;\nconsole.log(x);\n", "feature.js:2  debug leftover: console.log(x);")

    def test_debugger(self):
        self.assert_one("  debugger;\n", "feature.js:1  debug leftover")

    def test_word_debugger_in_prose_is_fine(self):
        self.commit("notes.md", "Open the debugger panel to see it.\n")
        code, output = self.run_main()
        self.assertEqual(code, 0)

    def test_python_breakpoint(self):
        self.assert_one("def f():\n    breakpoint()\n", "feature.py:2  debug leftover", "feature.py")

    def test_pdb(self):
        self.assert_one("import pdb\n", "feature.py:1  debug leftover", "feature.py")

    def test_conflict_marker(self):
        self.assert_one("a\n<<<<<<< HEAD\n", "feature.js:2  conflict marker")

    def test_todo(self):
        self.assert_one("// FIXME: later\n", "feature.js:1  note left in")

    def test_focused_test(self):
        self.assert_one("it.only('works', () => {});\n", "feature.js:1  focused or skipped test")

    def test_skipped_python_test(self):
        self.assert_one("@unittest.skip('later')\n", "feature.py:1  focused or skipped test", "feature.py")

    def test_aws_key_is_masked(self):
        self.commit("config.js", f"const key = '{AWS_KEY}';\n")
        code, output = self.run_main()
        self.assertEqual(code, 1)
        self.assertIn("config.js:1  possible secret: const key = 'AKIA***';", output)
        self.assertNotIn(AWS_KEY, output)

    def test_github_token_is_masked(self):
        self.commit("deploy.sh", f"TOKEN={GITHUB_TOKEN}\n")
        code, output = self.run_main()
        self.assertEqual(code, 1)
        self.assertIn("possible secret", output)
        self.assertNotIn(GITHUB_TOKEN, output)

    def test_password_in_quotes(self):
        self.commit("settings.py", 'password = "hunter2hunter2"\n')
        code, output = self.run_main()
        self.assertEqual(code, 1)
        self.assertIn("settings.py:1  possible secret", output)
        self.assertNotIn("hunter2hunter2", output)

    def test_password_read_from_env_is_fine(self):
        self.commit("settings.py", 'password = os.environ["DB_PASSWORD"]\n')
        code, output = self.run_main()
        self.assertEqual(code, 0)

    def test_empty_or_spaced_values_are_fine(self):
        self.commit("settings.py", 'password = ""\ntoken = "see the docs"\n')
        code, output = self.run_main()
        self.assertEqual(code, 0, output)

    def test_private_key_header(self):
        self.assert_one("-----BEGIN RSA PRIVATE KEY-----\n", "possible secret", "notes.txt")

    def test_line_numbers_follow_each_hunk(self):
        lines = [f"line {n}\n" for n in range(1, 41)]
        self.commit("long.js", "".join(lines))
        lines[4] = "console.log(5);\n"
        lines[29] = "console.log(30);\n"
        write(self.repo / "long.js", "".join(lines))
        code, output = self.run_main()
        self.assertIn("long.js:5  debug leftover", output)
        self.assertIn("long.js:30  debug leftover", output)
        self.assertIn("2 thing(s) to look at", output)

    def test_added_line_starting_with_plus_plus(self):
        self.commit("math.c", "int x = 0;\n")
        write(self.repo / "math.c", "int x = 0;\n++ x; // TODO bump\n")
        code, output = self.run_main()
        self.assertIn("math.c:2  note left in", output)

    def test_long_line_is_cut(self):
        self.commit("feature.js", "console.log('" + "x" * 300 + "');\n")
        code, output = self.run_main()
        line = [l for l in output.splitlines() if "debug leftover" in l][0]
        self.assertTrue(line.endswith("..."))
        self.assertLess(len(line), 200)

    def test_one_line_can_have_two_findings(self):
        self.commit("feature.js", "console.log(x); // TODO remove\n")
        code, output = self.run_main()
        self.assertIn("debug leftover", output)
        self.assertIn("note left in", output)
        self.assertIn("2 thing(s) to look at", output)

    def test_renamed_file_only_flags_new_lines(self):
        git(self.repo, "mv", "app.js", "main.js")
        git(self.repo, "commit", "--quiet", "-m", "rename")
        code, output = self.run_main()
        self.assertEqual(code, 0, output)

    def test_odd_file_name(self):
        self.assert_one("console.log(1);\n", "naïve ✓.js:1  debug leftover", "naïve ✓.js")


class PendingTest(ScanTest):
    def test_uncommitted_edit_is_scanned(self):
        write(self.repo / "app.js", "const a = 1;\n// TODO: old note\nconsole.log(a);\ndebugger;\n")
        code, output = self.run_main()
        self.assertIn("app.js:4  debug leftover", output)
        self.assertIn("1 thing(s) to look at", output)

    def test_untracked_file_is_scanned(self):
        write(self.repo / "draft.js", "ok\nconsole.log('draft');\n")
        code, output = self.run_main()
        self.assertIn("draft.js:2  debug leftover", output)

    def test_untracked_binary_file_is_skipped(self):
        (self.repo / "blob.bin").write_bytes(bytes([255, 0, 254]))
        code, output = self.run_main()
        self.assertEqual(code, 0)


class FileTest(ScanTest):
    def test_env_file(self):
        self.commit(".env", "A=1\n")
        code, output = self.run_main()
        self.assertIn(".env  env file, may hold secrets", output)

    def test_env_local_file(self):
        write(self.repo / ".env.local", "A=1\n")
        code, output = self.run_main()
        self.assertIn(".env.local  env file, may hold secrets", output)

    def test_env_example_is_fine(self):
        self.commit(".env.example", "A=\n")
        code, output = self.run_main()
        self.assertEqual(code, 0)

    def test_key_file(self):
        self.commit("certs/server.pem", "x\n")
        code, output = self.run_main()
        self.assertIn("certs/server.pem  key file, may hold secrets", output)

    def test_ssh_key(self):
        write(self.repo / "id_ed25519", "x\n")
        code, output = self.run_main()
        self.assertIn("id_ed25519  key file", output)

    def test_generated_files(self):
        self.commit("node_modules/lib/index.js", "x\n")
        write(self.repo / "src" / "__pycache__" / "a.pyc", "x\n")
        write(self.repo / "__pycache__" / "cache.bin", "x\n")
        write(self.repo / ".DS_Store", "x\n")
        code, output = self.run_main()
        self.assertIn("node_modules/lib/index.js  generated file", output)
        self.assertIn("src/__pycache__/a.pyc  generated file", output)
        self.assertIn("__pycache__/cache.bin  generated file", output)
        self.assertIn(".DS_Store  generated file", output)

    def test_large_file(self):
        (self.repo / "video.mp4").write_bytes(b"0" * 1_500_000)
        code, output = self.run_main()
        self.assertIn("video.mp4  large file (1.5 MB)", output)

    def test_file_just_under_the_limit(self):
        (self.repo / "data.bin").write_bytes(b"\0" * 1_000_000)
        code, output = self.run_main()
        self.assertEqual(code, 0)

    def test_changed_old_file_is_not_a_new_file(self):
        git(self.repo, "checkout", "--quiet", "main")
        self.commit(".env.production", "A=1\n")
        git(self.repo, "checkout", "--quiet", "feature")
        git(self.repo, "merge", "--quiet", "main")
        write(self.repo / ".env.production", "A=2\n")
        code, output = self.run_main()
        self.assertNotIn("env file", output)


class StartTest(ScanTest):
    def test_unknown_base(self):
        code, output = self.run_main("nope")
        self.assertEqual(code, 2)
        self.assertIn("cannot start", output)

    def test_not_a_repo(self):
        plain = self.repo.parent / "plain"
        plain.mkdir()
        output = io.StringIO()
        with contextlib.redirect_stdout(output):
            code = scan_diff.main(["--repo", str(plain), "--base", "main"])
        self.assertEqual(code, 2)

    def test_missing_folder(self):
        output = io.StringIO()
        with contextlib.redirect_stdout(output):
            code = scan_diff.main(["--repo", str(self.repo / "nope"), "--base", "main"])
        self.assertEqual(code, 2)
        self.assertIn("the folder does not exist", output.getvalue())

    def test_base_is_required(self):
        with contextlib.redirect_stderr(io.StringIO()):
            with self.assertRaises(SystemExit) as raised:
                scan_diff.parse_args([])
        self.assertEqual(raised.exception.code, 2)


class CommandLineTest(ScanTest):
    def test_runs_as_a_script(self):
        self.commit("feature.js", "console.log(1);\n")
        result = subprocess.run(
            [sys.executable, str(SCRIPT), "--repo", str(self.repo), "--base", "main"],
            capture_output=True,
            text=True,
        )
        self.assertEqual(result.returncode, 1)
        self.assertIn("feature.js:1  debug leftover", result.stdout)


if __name__ == "__main__":
    unittest.main()
