"""Tests for skills/debug/scripts/check_debug_prints.py.

Run from the repo root: python3 -m unittest discover tests
"""

import contextlib
import importlib.util
import io
import os
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest import mock

REPO_ROOT = Path(__file__).resolve().parent.parent
SCRIPT = REPO_ROOT / "skills" / "debug" / "scripts" / "check_debug_prints.py"

spec = importlib.util.spec_from_file_location("check_debug_prints", SCRIPT)
check_debug_prints = importlib.util.module_from_spec(spec)
spec.loader.exec_module(check_debug_prints)

GIT_ENV = {
    "GIT_CONFIG_GLOBAL": os.devnull,
    "GIT_CONFIG_NOSYSTEM": "1",
    "GIT_AUTHOR_NAME": "tester",
    "GIT_AUTHOR_EMAIL": "tester@localhost",
    "GIT_COMMITTER_NAME": "tester",
    "GIT_COMMITTER_EMAIL": "tester@localhost",
}

# Built in two parts so this test file never holds the marker itself.
MARKER = "DEBUG-" + "TEMP"


def git(cwd, *args):
    result = subprocess.run(["git", *args], cwd=cwd, capture_output=True, text=True)
    if result.returncode != 0:
        raise AssertionError(f"git {' '.join(args)} failed: {result.stderr}")
    return result.stdout.strip()


def write(path, text):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


class CheckTest(unittest.TestCase):
    def setUp(self):
        patcher = mock.patch.dict(os.environ, GIT_ENV)
        patcher.start()
        self.addCleanup(patcher.stop)
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.base = Path(temp.name).resolve()
        self.repo = self.base / "project"
        self.repo.mkdir()
        git(self.repo, "init", "--quiet", "--initial-branch=main")
        write(self.repo / ".gitignore", "build/\n")
        write(self.repo / "app.py", "def total(items):\n    return sum(items)\n")
        git(self.repo, "add", ".")
        git(self.repo, "commit", "--quiet", "-m", "first")

    def run_main(self, *argv):
        output = io.StringIO()
        with contextlib.redirect_stdout(output):
            code = check_debug_prints.main(["--repo", str(self.repo), *argv])
        return code, output.getvalue()


class FoundTest(CheckTest):
    def test_marked_line_in_a_changed_file(self):
        write(self.repo / "app.py",
              "def total(items):\n"
              f"    print('items', items)  # {MARKER}\n"
              "    return sum(items)\n")
        code, output = self.run_main()
        self.assertEqual(code, 1)
        self.assertIn(f"app.py:2  print('items', items)  # {MARKER}", output)
        self.assertIn(f"1 {MARKER} line(s) left; remove them", output)

    def test_marked_line_in_a_new_file(self):
        write(self.repo / "src" / "debug_helper.js", "let a = 1;\n" f"console.log(a); // {MARKER}\n")
        code, output = self.run_main()
        self.assertEqual(code, 1)
        self.assertIn("src/debug_helper.js:2", output)

    def test_staged_lines_count_too(self):
        write(self.repo / "app.py", f"x = 1  # {MARKER}\n")
        git(self.repo, "add", "app.py")
        code, output = self.run_main()
        self.assertEqual(code, 1)
        self.assertIn("app.py:1", output)

    def test_every_marked_line_is_listed(self):
        write(self.repo / "app.py",
              f"a = 1  # {MARKER}\n"
              "b = 2\n"
              f"c = 3  # {MARKER}\n")
        write(self.repo / "new.py", f"d = 4  # {MARKER}\n")
        code, output = self.run_main()
        self.assertIn("app.py:1", output)
        self.assertIn("app.py:3", output)
        self.assertIn("new.py:1", output)
        self.assertIn(f"3 {MARKER} line(s) left", output)

    def test_line_numbers_after_earlier_changes(self):
        lines = [f"line{number} = {number}\n" for number in range(1, 21)]
        write(self.repo / "long.py", "".join(lines))
        git(self.repo, "add", ".")
        git(self.repo, "commit", "--quiet", "-m", "long")
        lines[2] = "line3 = 'changed'\n"
        lines.insert(15, f"print(line15)  # {MARKER}\n")
        write(self.repo / "long.py", "".join(lines))
        code, output = self.run_main()
        self.assertIn("long.py:16", output)

    def test_file_name_with_spaces(self):
        write(self.repo / "my file.py", "x = 1\n")
        git(self.repo, "add", ".")
        git(self.repo, "commit", "--quiet", "-m", "spaces")
        write(self.repo / "my file.py", f"x = 1\nprint(x)  # {MARKER}\n")
        code, output = self.run_main()
        self.assertIn("my file.py:2", output)

    def test_non_ascii_file_name(self):
        write(self.repo / "café.py", "x = 1\n")
        git(self.repo, "add", ".")
        git(self.repo, "commit", "--quiet", "-m", "accent")
        write(self.repo / "café.py", f"print(x)  # {MARKER}\n")
        code, output = self.run_main()
        self.assertIn("café.py:1", output)

    def test_added_line_starting_with_plus_plus(self):
        write(self.repo / "count.c", "int i = 0;\n")
        git(self.repo, "add", ".")
        git(self.repo, "commit", "--quiet", "-m", "c")
        write(self.repo / "count.c", f"int i = 0;\n++i; // {MARKER}\n")
        code, output = self.run_main()
        self.assertIn("count.c:2", output)

    def test_added_line_starting_with_plus_plus_space(self):
        # In the diff this line reads "+++ i", like a file name header.
        write(self.repo / "count.c", "int i = 0;\n")
        git(self.repo, "add", ".")
        git(self.repo, "commit", "--quiet", "-m", "c")
        write(self.repo / "count.c", f"int i = 0;\n++ i; // {MARKER}\n")
        code, output = self.run_main()
        self.assertEqual(code, 1)
        self.assertIn(f"count.c:2  ++ i; // {MARKER}", output)

    def test_file_names_git_puts_in_quotes(self):
        # git writes the last name with an octal escape: \001.
        names = ['say "hi".py', "back\\slash.py", "tab\there.py", "ctrl\x01here.py"]
        for name in names:
            write(self.repo / name, "x = 1\n")
        git(self.repo, "add", ".")
        git(self.repo, "commit", "--quiet", "-m", "odd names")
        for name in names:
            write(self.repo / name, f"x = 1\nprint(x)  # {MARKER}\n")
        code, output = self.run_main()
        for name in names:
            self.assertIn(f"{name}:2", output)

    def test_repo_with_no_commit_yet(self):
        fresh = self.base / "fresh"
        fresh.mkdir()
        git(fresh, "init", "--quiet")
        write(fresh / "a.py", f"print(1)  # {MARKER}\n")
        write(fresh / "b.py", f"print(2)  # {MARKER}\n")
        git(fresh, "add", "a.py")
        output = io.StringIO()
        with contextlib.redirect_stdout(output):
            code = check_debug_prints.main(["--repo", str(fresh)])
        self.assertEqual(code, 1)
        self.assertIn("a.py:1", output.getvalue())
        self.assertIn("b.py:1", output.getvalue())

    def test_from_a_subfolder(self):
        (self.repo / "sub").mkdir()
        write(self.repo / "app.py", f"x = 1  # {MARKER}\n")
        output = io.StringIO()
        with contextlib.redirect_stdout(output):
            code = check_debug_prints.main(["--repo", str(self.repo / "sub")])
        self.assertEqual(code, 1)
        self.assertIn("app.py:1", output.getvalue())


class NotFoundTest(CheckTest):
    def test_clean_tree(self):
        code, output = self.run_main()
        self.assertEqual(code, 0)
        self.assertIn(f"none left: no {MARKER} lines", output)

    def test_changes_without_the_marker(self):
        write(self.repo / "app.py", "def total(items):\n    print(items)\n")
        write(self.repo / "new.py", "x = 1\n")
        code, output = self.run_main()
        self.assertEqual(code, 0)

    def test_committed_marker_is_not_listed(self):
        # Lines already in HEAD were not added by this debugging session.
        write(self.repo / "app.py", f"x = 1  # {MARKER}\n")
        git(self.repo, "add", ".")
        git(self.repo, "commit", "--quiet", "-m", "old")
        code, output = self.run_main()
        self.assertEqual(code, 0)

    def test_removed_marker_line_is_not_listed(self):
        write(self.repo / "app.py", f"x = 1  # {MARKER}\ny = 2\n")
        git(self.repo, "add", ".")
        git(self.repo, "commit", "--quiet", "-m", "old")
        write(self.repo / "app.py", "y = 2\n")
        code, output = self.run_main()
        self.assertEqual(code, 0)

    def test_ignored_files_are_skipped(self):
        write(self.repo / "build" / "out.js", f"console.log(1); // {MARKER}\n")
        code, output = self.run_main()
        self.assertEqual(code, 0)

    def test_binary_new_file_is_skipped(self):
        (self.repo / "image.bin").write_bytes(b"\xff\xfe\x00" + MARKER.encode() + b"\x80")
        code, output = self.run_main()
        self.assertEqual(code, 0)

    def test_lowercase_is_not_the_marker(self):
        write(self.repo / "app.py", "x = 1  # debug-temp\n")
        code, output = self.run_main()
        self.assertEqual(code, 0)


class StartTest(CheckTest):
    def test_not_a_repo(self):
        plain = self.base / "plain"
        plain.mkdir()
        output = io.StringIO()
        with contextlib.redirect_stdout(output):
            code = check_debug_prints.main(["--repo", str(plain)])
        self.assertEqual(code, 2)
        self.assertIn("cannot start", output.getvalue())

    def test_missing_folder(self):
        output = io.StringIO()
        with contextlib.redirect_stdout(output):
            code = check_debug_prints.main(["--repo", str(self.base / "nope")])
        self.assertEqual(code, 2)
        self.assertIn("the folder does not exist", output.getvalue())


if __name__ == "__main__":
    unittest.main()
