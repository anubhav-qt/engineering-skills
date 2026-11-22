"""Tests for skills/debug/scripts/find_bad_commit.py.

Each test builds a real throwaway git repository with a line of commits,
one of which brings in a bug.

Run from the repo root: python3 -m unittest discover tests
"""

import contextlib
import importlib.util
import io
import os
import subprocess
import sys
import tempfile
import time
import unittest
from pathlib import Path
from unittest import mock

REPO_ROOT = Path(__file__).resolve().parent.parent
SCRIPT = REPO_ROOT / "skills" / "debug" / "scripts" / "find_bad_commit.py"

spec = importlib.util.spec_from_file_location("find_bad_commit", SCRIPT)
find_bad_commit = importlib.util.module_from_spec(spec)
spec.loader.exec_module(find_bad_commit)

PYTHON = f'"{sys.executable}"'

# Keep the tester's own git settings (signing, hooks, names) out of the tests.
GIT_ENV = {
    "GIT_CONFIG_GLOBAL": os.devnull,
    "GIT_CONFIG_NOSYSTEM": "1",
    "GIT_AUTHOR_NAME": "tester",
    "GIT_AUTHOR_EMAIL": "tester@localhost",
    "GIT_COMMITTER_NAME": "tester",
    "GIT_COMMITTER_EMAIL": "tester@localhost",
}

# The test the human would write: kept outside the repo, run in each commit.
CHECK_SCRIPT = """\
import pathlib, sys
calc = pathlib.Path("calc.py")
if not calc.exists():
    sys.exit(125)
sys.exit(1 if "BUG" in calc.read_text() else 0)
"""


def git(cwd, *args):
    result = subprocess.run(["git", *args], cwd=cwd, capture_output=True, text=True)
    if result.returncode != 0:
        raise AssertionError(f"git {' '.join(args)} failed: {result.stderr}")
    return result.stdout.strip()


def write(path, text):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


class BisectTest(unittest.TestCase):
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
        self.check = self.base / "check.py"
        write(self.check, CHECK_SCRIPT)
        self.test = f'{PYTHON} "{self.check}"'

        # Temp folders made by the script go under our own temp folder.
        temp_patcher = mock.patch.object(find_bad_commit.tempfile, "tempdir", str(self.base))
        temp_patcher.start()
        self.addCleanup(temp_patcher.stop)

    def commit(self, message, calc=None):
        if calc is not None:
            write(self.repo / "calc.py", calc)
        write(self.repo / "log.txt", message + "\n")
        git(self.repo, "add", ".")
        git(self.repo, "commit", "--quiet", "-m", message)
        return git(self.repo, "rev-parse", "HEAD")

    def build_history(self, count=12, bug_at=7):
        """Commits 1..count; the bug comes in at bug_at. Returns their hashes."""
        commits = []
        for number in range(1, count + 1):
            if number == bug_at:
                commits.append(self.commit(f"break it at {number}", "VALUE = 1  # BUG\n"))
            elif number == 1:
                commits.append(self.commit("first", "VALUE = 1\n"))
            else:
                commits.append(self.commit(f"change {number}"))
        return commits

    def run_main(self, *argv):
        output = io.StringIO()
        with contextlib.redirect_stdout(output):
            code = find_bad_commit.main(["--repo", str(self.repo), *argv])
        return code, output.getvalue()

    def short(self, commit):
        return git(self.repo, "rev-parse", "--short", commit)

    def assert_left_clean(self):
        self.assertEqual(len(git(self.repo, "worktree", "list").splitlines()), 1)
        self.assertFalse((self.repo / ".git" / "BISECT_LOG").exists())
        self.assertEqual(git(self.repo, "for-each-ref", "refs/bisect"), "")
        leftovers = [path.name for path in self.base.iterdir() if path.name.startswith("debug-bisect-")]
        self.assertEqual(leftovers, [])


class FindTest(BisectTest):
    def test_finds_the_commit_that_broke_it(self):
        commits = self.build_history()
        code, output = self.run_main("--good", commits[0], "--test", self.test)
        self.assertEqual(code, 0, output)
        self.assertIn(f"first bad commit: {self.short(commits[6])} break it at 7", output)
        self.assert_left_clean()

    def test_bug_in_the_commit_right_after_good(self):
        commits = self.build_history(count=6, bug_at=2)
        code, output = self.run_main("--good", commits[0], "--test", self.test)
        self.assertEqual(code, 0, output)
        self.assertIn("break it at 2", output)

    def test_bug_in_the_last_commit(self):
        commits = self.build_history(count=6, bug_at=6)
        code, output = self.run_main("--good", commits[0], "--test", self.test)
        self.assertEqual(code, 0, output)
        self.assertIn("break it at 6", output)

    def test_shows_the_files_the_commit_changed(self):
        commits = self.build_history()
        code, output = self.run_main("--good", commits[0], "--test", self.test)
        self.assertIn("    calc.py", output)

    def test_lists_each_commit_tested(self):
        commits = self.build_history()
        code, output = self.run_main("--good", commits[0], "--test", self.test)
        tested = [line for line in output.splitlines() if " good: " in line or " bad: " in line]
        self.assertGreaterEqual(len(tested), 2)
        self.assertLessEqual(len(tested), 5)

    def test_bad_other_than_head(self):
        commits = self.build_history(count=12, bug_at=4)
        code, output = self.run_main("--good", commits[0], "--bad", commits[7], "--test", self.test)
        self.assertEqual(code, 0, output)
        self.assertIn("break it at 4", output)

    def test_good_given_as_a_tag(self):
        commits = self.build_history()
        git(self.repo, "tag", "v1", commits[0])
        code, output = self.run_main("--good", "v1", "--test", self.test)
        self.assertEqual(code, 0, output)
        self.assertIn("break it at 7", output)

    def test_killed_by_a_signal_counts_as_bad_and_does_not_stop_bisect(self):
        commits = self.build_history()
        crash = self.base / "crash.py"
        write(crash, CHECK_SCRIPT.replace(
            'sys.exit(1 if "BUG" in calc.read_text() else 0)',
            'import os, signal\n'
            'if "BUG" in calc.read_text():\n'
            '    os.kill(os.getpid(), signal.SIGKILL)\n',
        ))
        code, output = self.run_main("--good", commits[0], "--test", f'{PYTHON} "{crash}"')
        self.assertEqual(code, 0, output)
        self.assertIn("break it at 7", output)

    def test_timeout_counts_as_bad(self):
        commits = self.build_history(count=6, bug_at=4)
        hang = self.base / "hang.py"
        write(hang, CHECK_SCRIPT.replace(
            'sys.exit(1 if "BUG" in calc.read_text() else 0)',
            'import time\n'
            'if "BUG" in calc.read_text():\n'
            '    time.sleep(30)\n',
        ))
        started = time.monotonic()
        code, output = self.run_main(
            "--good", commits[0], "--test", f'{PYTHON} "{hang}"', "--timeout", "1"
        )
        self.assertEqual(code, 0, output)
        self.assertIn("break it at 4", output)
        self.assertIn("timed out", output)
        self.assertLess(time.monotonic() - started, 25)


class HumanFolderTest(BisectTest):
    def test_uncommitted_work_and_branch_are_untouched(self):
        commits = self.build_history()
        write(self.repo / "calc.py", "VALUE = 2  # my edit\n")
        write(self.repo / "notes.txt", "mine\n")
        code, output = self.run_main("--good", commits[0], "--test", self.test)
        self.assertEqual(code, 0, output)
        self.assertEqual((self.repo / "calc.py").read_text(), "VALUE = 2  # my edit\n")
        self.assertEqual((self.repo / "notes.txt").read_text(), "mine\n")
        self.assertEqual(git(self.repo, "rev-parse", "--abbrev-ref", "HEAD"), "main")
        self.assertEqual(git(self.repo, "rev-parse", "HEAD"), commits[-1])
        self.assert_left_clean()

    def test_runs_from_a_subfolder(self):
        commits = self.build_history()
        (self.repo / "sub").mkdir()
        output = io.StringIO()
        with contextlib.redirect_stdout(output):
            code = find_bad_commit.main(
                ["--repo", str(self.repo / "sub"), "--good", commits[0], "--test", self.test]
            )
        self.assertEqual(code, 0, output.getvalue())

    def test_cleaned_up_after_an_early_stop(self):
        commits = self.build_history()
        code, output = self.run_main("--good", commits[0], "--test", f"{PYTHON} -c 'pass'")
        self.assertEqual(code, 2)
        self.assert_left_clean()

    def test_a_step_that_cannot_run_is_caught_first(self):
        commits = self.build_history()
        broken = [sys.executable, "-c", "import sys; print('step crashed'); sys.exit(7)"]
        with mock.patch.object(find_bad_commit, "step_command", return_value=broken):
            code, output = self.run_main("--good", commits[0], "--test", self.test)
        self.assertEqual(code, 2)
        self.assertIn("the bisect step itself failed", output)
        self.assertIn("step crashed", output)
        self.assertNotIn("first bad commit", output)
        self.assert_left_clean()

    def test_project_files_cannot_shadow_the_script(self):
        commits = self.build_history()
        write(self.repo / "tempfile.py", "raise SystemExit(1)\n")
        write(self.repo / "subprocess.py", "raise SystemExit(1)\n")
        git(self.repo, "add", ".")
        git(self.repo, "commit", "--quiet", "-m", "files named like Python modules")
        code, output = self.run_main("--good", commits[0], "--test", self.test)
        self.assertEqual(code, 0, output)
        self.assertIn("break it at 7", output)

    def test_pythonpath_cannot_shadow_the_script(self):
        # A human's PYTHONPATH often points at their own project.
        commits = self.build_history()
        shadow = self.base / "shadow"
        write(shadow / "subprocess.py", "raise SystemExit(1)\n")
        with mock.patch.dict(os.environ, {"PYTHONPATH": str(shadow)}):
            code, output = self.run_main("--good", commits[0], "--test", self.test)
        self.assertEqual(code, 0, output)
        self.assertIn("break it at 7", output)

    def test_step_that_cannot_test_stops_bisect(self):
        # Exit 128 makes git bisect run stop instead of calling it bad.
        outside = self.base / "not-a-repo"
        outside.mkdir()
        saved = os.getcwd()
        os.chdir(outside)
        self.addCleanup(os.chdir, saved)
        output = io.StringIO()
        with contextlib.redirect_stdout(output):
            code = find_bad_commit.main(["--step", "--test", "true"])
        self.assertEqual(code, 128)
        self.assertIn("cannot test this commit", output.getvalue())

    def test_cleaned_up_after_ctrl_c(self):
        commits = self.build_history()
        with mock.patch.object(find_bad_commit, "run_bisect", side_effect=KeyboardInterrupt):
            with self.assertRaises(KeyboardInterrupt):
                self.run_main("--good", commits[0], "--test", self.test)
        self.assert_left_clean()


class SkipTest(BisectTest):
    def test_untestable_commits_are_skipped(self):
        commits = []
        commits.append(self.commit("first", "VALUE = 1\n"))
        for number in range(2, 6):
            commits.append(self.commit(f"change {number}"))
        git(self.repo, "rm", "--quiet", "calc.py")
        commits.append(self.commit("calc removed for a while"))
        commits.append(self.commit("still no calc"))
        commits.append(self.commit("calc back", "VALUE = 1\n"))
        commits.append(self.commit("break it", "VALUE = 1  # BUG\n"))
        commits.append(self.commit("after"))
        code, output = self.run_main("--good", commits[0], "--test", self.test)
        self.assertEqual(code, 0, output)
        self.assertIn("break it", output.split("first bad commit:")[1])

    def test_too_many_skipped_lists_the_candidates(self):
        commits = []
        commits.append(self.commit("first", "VALUE = 1\n"))
        git(self.repo, "rm", "--quiet", "calc.py")
        commits.append(self.commit("gone a"))
        commits.append(self.commit("gone b"))
        commits.append(self.commit("back broken", "VALUE = 1  # BUG\n"))
        commits.append(self.commit("after"))
        code, output = self.run_main("--good", commits[0], "--test", self.test)
        self.assertEqual(code, 1, output)
        self.assertIn("could not narrow it to one commit", output)
        self.assertIn("back broken", output)
        self.assert_left_clean()

    def test_setup_runs_before_the_test(self):
        commits = self.build_history()
        needs_setup = self.base / "needs_setup.py"
        write(needs_setup, "import pathlib, sys\n"
                           "sys.exit(0 if pathlib.Path('built.txt').exists() else 2)\n")
        test = f'{PYTHON} "{needs_setup}" && {self.test}'
        setup = f"{PYTHON} -c \"open('built.txt', 'w').write('ok')\""
        code, output = self.run_main("--good", commits[0], "--test", test, "--setup", setup)
        self.assertEqual(code, 0, output)
        self.assertIn("break it at 7", output)

    def test_failed_setup_skips_the_commit(self):
        commits = self.build_history(count=12, bug_at=9)
        # Setup fails on commits that say "change 5" or "change 6".
        setup = (
            f'{PYTHON} -c "import pathlib, sys; '
            "text = pathlib.Path('log.txt').read_text(); "
            "sys.exit(1 if text.strip() in ('change 5', 'change 6') else 0)\""
        )
        code, output = self.run_main("--good", commits[0], "--test", self.test, "--setup", setup)
        self.assertEqual(code, 0, output)
        self.assertIn("break it at 9", output)

    def test_setup_failing_at_bad_stops(self):
        commits = self.build_history()
        code, output = self.run_main(
            "--good", commits[0], "--test", self.test, "--setup", f"{PYTHON} -c 'import sys; sys.exit(1)'"
        )
        self.assertEqual(code, 2)
        self.assertIn("cannot test HEAD (", output)
        self.assertIn("setup failed", output)
        self.assert_left_clean()


class StartTest(BisectTest):
    def test_test_passes_on_bad(self):
        commits = self.build_history()
        code, output = self.run_main("--good", commits[0], "--test", f"{PYTHON} -c 'pass'")
        self.assertEqual(code, 2)
        self.assertIn("the test passes on HEAD", output)
        self.assertIn("does not show the bug", output)

    def test_test_fails_on_good(self):
        commits = self.build_history()
        code, output = self.run_main(
            "--good", commits[0], "--test", f"{PYTHON} -c 'import sys; sys.exit(1)'"
        )
        self.assertEqual(code, 2)
        self.assertIn(f"the test fails on {commits[0]} too", output)
        self.assert_left_clean()

    def test_good_cannot_be_tested(self):
        commits = [self.commit("no calc yet")]
        commits.append(self.commit("broken", "VALUE = 1  # BUG\n"))
        code, output = self.run_main("--good", commits[0], "--test", self.test)
        self.assertEqual(code, 2)
        self.assertIn(f"cannot test {commits[0]}", output)

    def test_good_after_bad(self):
        commits = self.build_history()
        code, output = self.run_main("--good", "HEAD", "--bad", commits[0], "--test", self.test)
        self.assertEqual(code, 2)
        self.assertIn("is not an older commit of", output)

    def test_good_on_another_branch(self):
        commits = self.build_history()
        git(self.repo, "checkout", "--quiet", "-b", "side", commits[2])
        side = self.commit("side work")
        git(self.repo, "checkout", "--quiet", "main")
        code, output = self.run_main("--good", side, "--test", self.test)
        self.assertEqual(code, 2)
        self.assertIn("is not an older commit of HEAD", output)

    def test_same_commit(self):
        commits = self.build_history()
        code, output = self.run_main("--good", "HEAD", "--test", self.test)
        self.assertEqual(code, 2)
        self.assertIn("are the same commit", output)

    def test_unknown_ref(self):
        self.build_history()
        code, output = self.run_main("--good", "no-such-ref", "--test", self.test)
        self.assertEqual(code, 2)
        self.assertIn("no commit named no-such-ref", output)
        self.assert_left_clean()

    def test_not_a_repo(self):
        plain = self.base / "plain"
        plain.mkdir()
        output = io.StringIO()
        with contextlib.redirect_stdout(output):
            code = find_bad_commit.main(["--repo", str(plain), "--good", "HEAD~1", "--test", "true"])
        self.assertEqual(code, 2)
        self.assertIn("not inside a git repository", output.getvalue())

    def test_missing_folder(self):
        output = io.StringIO()
        with contextlib.redirect_stdout(output):
            code = find_bad_commit.main(["--repo", str(self.base / "nope"), "--good", "a", "--test", "true"])
        self.assertEqual(code, 2)
        self.assertIn("the folder does not exist", output.getvalue())

    def check_usage_error(self, *argv):
        with contextlib.redirect_stderr(io.StringIO()):
            with self.assertRaises(SystemExit) as caught:
                find_bad_commit.main(list(argv))
        self.assertEqual(caught.exception.code, 2)

    def test_good_is_required(self):
        self.check_usage_error("--test", "true")

    def test_test_is_required(self):
        self.check_usage_error("--good", "HEAD~1")

    def test_empty_test(self):
        self.check_usage_error("--good", "HEAD~1", "--test", " ")

    def test_zero_timeout(self):
        self.check_usage_error("--good", "HEAD~1", "--test", "true", "--timeout", "0")


class JudgeTest(BisectTest):
    def judge(self, test, setup=None, timeout=10):
        return find_bad_commit.judge(test, setup, self.base, timeout)

    def test_exit_zero_is_good(self):
        self.assertEqual(self.judge("true")[0], find_bad_commit.GOOD)

    def test_exit_one_is_bad(self):
        self.assertEqual(self.judge("exit 1")[0], find_bad_commit.BAD)

    def test_exit_125_is_skip(self):
        self.assertEqual(self.judge("exit 125")[0], find_bad_commit.SKIP)

    def test_exit_above_127_is_bad(self):
        # git bisect run would stop on these; the step turns them into bad.
        self.assertEqual(self.judge("exit 200")[0], find_bad_commit.BAD)

    def test_failed_setup_is_skip_and_test_does_not_run(self):
        marker = self.base / "ran.txt"
        verdict, reason = self.judge(f"touch '{marker}'", setup="exit 3")
        self.assertEqual(verdict, find_bad_commit.SKIP)
        self.assertIn("setup failed (exit 3)", reason)
        self.assertFalse(marker.exists())

    def test_setup_timeout_is_skip(self):
        verdict, reason = self.judge("true", setup="sleep 30", timeout=0.5)
        self.assertEqual(verdict, find_bad_commit.SKIP)
        self.assertIn("setup timed out", reason)

    def test_stdin_is_closed(self):
        verdict, reason = self.judge(f"{PYTHON} -c \"import sys; sys.exit(0 if sys.stdin.read() == '' else 1)\"")
        self.assertEqual(verdict, find_bad_commit.GOOD)


if __name__ == "__main__":
    unittest.main()
