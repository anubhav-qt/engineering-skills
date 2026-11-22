"""Tests for skills/full-test/scripts/pr_copy.py.

Each test builds real throwaway git repositories: a bare "remote", and a
clone with a feature branch, like a human's project folder.

Run from the repo root: python3 -m unittest discover tests
"""

import contextlib
import importlib.util
import io
import os
import shutil
import stat
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

REPO_ROOT = Path(__file__).resolve().parent.parent
SCRIPT = REPO_ROOT / "skills" / "full-test" / "scripts" / "pr_copy.py"

spec = importlib.util.spec_from_file_location("pr_copy", SCRIPT)
pr_copy = importlib.util.module_from_spec(spec)
spec.loader.exec_module(pr_copy)

# Keep the tester's own git settings (signing, hooks, names) out of the tests.
GIT_ENV = {
    "GIT_CONFIG_GLOBAL": os.devnull,
    "GIT_CONFIG_NOSYSTEM": "1",
    "GIT_AUTHOR_NAME": "tester",
    "GIT_AUTHOR_EMAIL": "tester@localhost",
    "GIT_COMMITTER_NAME": "tester",
    "GIT_COMMITTER_EMAIL": "tester@localhost",
}


def git(cwd, *args):
    result = subprocess.run(
        ["git", *args], cwd=cwd, capture_output=True, text=True
    )
    if result.returncode != 0:
        raise AssertionError(f"git {' '.join(args)} failed: {result.stderr}")
    return result.stdout.strip()


def write(path, text):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


class RepoTest(unittest.TestCase):
    """A remote with main, and a clone on a feature branch with one commit."""

    def setUp(self):
        patcher = mock.patch.dict(os.environ, GIT_ENV)
        patcher.start()
        self.addCleanup(patcher.stop)
        # Never ask the real gh about a real PR.
        gh_patcher = mock.patch.object(pr_copy, "target_from_open_pr", return_value=None)
        gh_patcher.start()
        self.addCleanup(gh_patcher.stop)

        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.base = Path(temp.name).resolve()
        self.remote = self.base / "remote.git"
        git(self.base, "init", "--quiet", "--bare", "--initial-branch=main", str(self.remote))

        seed = self.base / "seed"
        git(self.base, "clone", "--quiet", str(self.remote), str(seed))
        git(seed, "checkout", "--quiet", "-b", "main")
        write(seed / "app.py", "VERSION = 1\n")
        write(seed / ".gitignore", ".env\nnode_modules/\n")
        git(seed, "add", ".")
        git(seed, "commit", "--quiet", "-m", "first")
        git(seed, "push", "--quiet", "origin", "main")
        self.seed = seed

        self.repo = self.base / "project"
        git(self.base, "clone", "--quiet", str(self.remote), str(self.repo))
        git(self.repo, "checkout", "--quiet", "-b", "feature")
        write(self.repo / "feature.py", "FEATURE = True\n")
        git(self.repo, "add", ".")
        git(self.repo, "commit", "--quiet", "-m", "feature")

    def push_to_main(self, name, text):
        """Someone else lands a change on main after the feature branched."""
        write(self.seed / name, text)
        git(self.seed, "add", ".")
        git(self.seed, "commit", "--quiet", "-m", f"change {name}")
        git(self.seed, "push", "--quiet", "origin", "main")

    def run_main(self, *argv):
        output = io.StringIO()
        with contextlib.redirect_stdout(output):
            code = pr_copy.main(list(argv))
        return code, output.getvalue()

    def setup_copy(self, *extra):
        code, output = self.run_main("setup", "--repo", str(self.repo), *extra)
        self.assertEqual(code, 0, output)
        folder = Path(self.value(output, "folder"))
        self.addCleanup(self.cleanup_quietly, folder)
        return folder, output

    def cleanup_quietly(self, folder):
        if folder.exists():
            self.run_main("cleanup", str(folder))

    def value(self, output, key):
        for line in output.splitlines():
            if line.startswith(key + " "):
                return line[len(key):].strip().split("  ")[0]
        raise AssertionError(f"no {key} line in: {output}")

    def worktree_count(self):
        listing = git(self.repo, "worktree", "list", "--porcelain")
        return listing.count("worktree ")

    def snapshot(self):
        """What the human sees in their own folder."""
        return (
            git(self.repo, "rev-parse", "HEAD"),
            git(self.repo, "branch", "--show-current"),
            git(self.repo, "status", "--porcelain", "--ignored"),
        )


class SetupTest(RepoTest):
    def test_pr_is_merged_onto_the_latest_target(self):
        self.push_to_main("later.py", "LATER = 1\n")
        folder, output = self.setup_copy("--target", "main")
        pr = folder / "pr"
        base = folder / "base"
        self.assertTrue((pr / "feature.py").is_file())
        self.assertTrue((pr / "later.py").is_file())
        self.assertTrue((base / "later.py").is_file())
        self.assertFalse((base / "feature.py").exists())
        self.assertIn("target   origin/main", output)
        self.assertIn("pending  none", output)

    def test_human_folder_is_untouched(self):
        self.push_to_main("later.py", "LATER = 1\n")
        write(self.repo / "app.py", "VERSION = 2\n")
        write(self.repo / "notes.txt", "draft\n")
        before = self.snapshot()
        folder, output = self.setup_copy("--target", "main")
        self.assertEqual(self.snapshot(), before)
        self.run_main("cleanup", str(folder))
        self.assertEqual(self.snapshot(), before)

    def test_uncommitted_changes_come_along(self):
        write(self.repo / "app.py", "VERSION = 2\n")
        git(self.repo, "add", "app.py")
        write(self.repo / "feature.py", "FEATURE = False\n")
        write(self.repo / "src" / "new.py", "NEW = 1\n")
        folder, output = self.setup_copy("--target", "main")
        pr = folder / "pr"
        self.assertEqual((pr / "app.py").read_text(), "VERSION = 2\n")
        self.assertEqual((pr / "feature.py").read_text(), "FEATURE = False\n")
        self.assertEqual((pr / "src" / "new.py").read_text(), "NEW = 1\n")
        self.assertIn("pending  3 uncommitted file(s)", output)
        self.assertIn("           app.py", output)
        self.assertIn("           src/new.py", output)

    def test_deleted_file_is_deleted_in_the_copy(self):
        (self.repo / "feature.py").unlink()
        folder, output = self.setup_copy("--target", "main")
        self.assertFalse((folder / "pr" / "feature.py").exists())
        self.assertIn("           feature.py", output)

    def test_ignored_files_stay_out(self):
        write(self.repo / ".env", "SECRET=1\n")
        write(self.repo / "node_modules" / "lib.js", "x\n")
        folder, output = self.setup_copy("--target", "main")
        self.assertFalse((folder / "pr" / ".env").exists())
        self.assertFalse((folder / "pr" / "node_modules").exists())
        self.assertIn("pending  none", output)

    def test_binary_and_odd_named_files_come_along(self):
        data = bytes(range(256))
        (self.repo / "logo.bin").write_bytes(data)
        git(self.repo, "add", "logo.bin")
        git(self.repo, "commit", "--quiet", "-m", "logo")
        (self.repo / "logo.bin").write_bytes(data[::-1])
        write(self.repo / "naïve name ✓.txt", "hi\n")
        folder, output = self.setup_copy("--target", "main")
        pr = folder / "pr"
        self.assertEqual((pr / "logo.bin").read_bytes(), data[::-1])
        self.assertEqual((pr / "naïve name ✓.txt").read_text(), "hi\n")

    def test_executable_bit_is_kept(self):
        script = self.repo / "run.sh"
        write(script, "#!/bin/sh\n")
        script.chmod(0o755)
        folder, output = self.setup_copy("--target", "main")
        mode = (folder / "pr" / "run.sh").stat().st_mode
        self.assertTrue(mode & stat.S_IXUSR)

    def test_human_signing_and_hooks_do_not_block_the_merge(self):
        self.push_to_main("later.py", "LATER = 1\n")
        git(self.repo, "config", "commit.gpgsign", "true")
        git(self.repo, "config", "gpg.program", "false")
        hook = self.repo / ".git" / "hooks" / "pre-merge-commit"
        write(hook, "#!/bin/sh\nexit 1\n")
        hook.chmod(0o755)
        folder, output = self.setup_copy("--target", "main")
        self.assertTrue((folder / "pr" / "later.py").is_file())

    def test_target_already_merged(self):
        folder, output = self.setup_copy("--target", "main")
        self.assertTrue((folder / "pr" / "feature.py").is_file())

    def test_chosen_folder(self):
        chosen = self.base / "copies"
        folder, output = self.setup_copy("--target", "main", "--dir", str(chosen))
        self.assertEqual(folder, chosen)
        self.assertTrue((chosen / "pr" / "feature.py").is_file())

    def test_runs_from_a_subfolder(self):
        sub = self.repo / "src"
        sub.mkdir()
        code, output = self.run_main("setup", "--repo", str(sub), "--target", "main")
        self.assertEqual(code, 0, output)
        folder = Path(self.value(output, "folder"))
        self.addCleanup(self.cleanup_quietly, folder)
        self.assertTrue((folder / "pr" / "feature.py").is_file())


class TargetTest(RepoTest):
    def test_open_pr_base_wins(self):
        git(self.seed, "push", "--quiet", "origin", "main:dev")
        with mock.patch.object(pr_copy, "target_from_open_pr", return_value="dev"):
            folder, output = self.setup_copy()
        self.assertIn("target   origin/dev", output)

    def test_remote_default_branch_is_used(self):
        folder, output = self.setup_copy()
        self.assertIn("target   origin/main", output)

    def test_non_main_default_branch(self):
        git(self.seed, "push", "--quiet", "origin", "main:dev")
        git(self.repo, "fetch", "--quiet")
        git(self.repo, "remote", "set-head", "origin", "dev")
        folder, output = self.setup_copy()
        self.assertIn("target   origin/dev", output)

    def test_no_way_to_tell(self):
        git(self.repo, "remote", "set-head", "origin", "--delete")
        code, output = self.run_main("setup", "--repo", str(self.repo))
        self.assertEqual(code, 2)
        self.assertIn("Pass --target", output)

    def test_unknown_branch(self):
        code, output = self.run_main("setup", "--repo", str(self.repo), "--target", "nope")
        self.assertEqual(code, 2)
        self.assertIn("branch nope was not found", output)
        self.assertEqual(self.worktree_count(), 1)

    def test_fetch_failure_uses_what_is_here(self):
        git(self.repo, "remote", "set-url", "origin", str(self.base / "gone.git"))
        folder, output = self.setup_copy("--target", "main")
        self.assertIn("could not fetch origin/main", output)
        self.assertIn("target   origin/main", output)

    def test_no_fetch_skips_the_remote(self):
        self.push_to_main("later.py", "LATER = 1\n")
        folder, output = self.setup_copy("--target", "main", "--no-fetch")
        self.assertFalse((folder / "pr" / "later.py").exists())

    def test_local_branch_when_there_is_no_remote(self):
        git(self.repo, "branch", "--quiet", "dev", "main")
        git(self.repo, "remote", "remove", "origin")
        folder, output = self.setup_copy("--target", "dev")
        self.assertIn("target   dev", output)
        self.assertIn("using the local branch dev", output)


class GhTest(unittest.TestCase):
    """target_from_open_pr on its own, with gh faked."""

    def test_no_gh(self):
        with mock.patch.object(pr_copy.shutil, "which", return_value=None):
            self.assertIsNone(pr_copy.target_from_open_pr(Path(".")))

    def fake_gh(self, returncode, stdout):
        result = subprocess.CompletedProcess([], returncode, stdout=stdout)
        return mock.patch.object(pr_copy.subprocess, "run", return_value=result)

    def test_gh_gives_the_base(self):
        with mock.patch.object(pr_copy.shutil, "which", return_value="/bin/gh"):
            with self.fake_gh(0, b"dev\n"):
                self.assertEqual(pr_copy.target_from_open_pr(Path(".")), "dev")

    def test_gh_finds_no_pr(self):
        with mock.patch.object(pr_copy.shutil, "which", return_value="/bin/gh"):
            with self.fake_gh(1, b"no pull requests found\n"):
                self.assertIsNone(pr_copy.target_from_open_pr(Path(".")))

    def test_gh_prints_nothing(self):
        with mock.patch.object(pr_copy.shutil, "which", return_value="/bin/gh"):
            with self.fake_gh(0, b"\n"):
                self.assertIsNone(pr_copy.target_from_open_pr(Path(".")))

    def test_gh_hangs(self):
        timeout = subprocess.TimeoutExpired("gh", 30)
        with mock.patch.object(pr_copy.shutil, "which", return_value="/bin/gh"):
            with mock.patch.object(pr_copy.subprocess, "run", side_effect=timeout):
                self.assertIsNone(pr_copy.target_from_open_pr(Path(".")))


class ConflictTest(RepoTest):
    def assert_conflict(self, file_name, step):
        chosen = self.base / "copies"
        code, output = self.run_main(
            "setup", "--repo", str(self.repo), "--target", "main", "--dir", str(chosen)
        )
        self.assertEqual(code, 1, output)
        self.assertIn(f"conflict while {step}", output)
        self.assertIn(f"  {file_name}", output)
        self.assertEqual(self.worktree_count(), 1)
        self.assertFalse(chosen.exists())

    def test_pr_does_not_merge(self):
        self.push_to_main("feature.py", "FEATURE = 'theirs'\n")
        self.assert_conflict("feature.py", "merging origin/main into the PR")

    def test_uncommitted_change_does_not_fit(self):
        self.push_to_main("app.py", "VERSION = 'theirs'\n")
        write(self.repo / "app.py", "VERSION = 'mine'\n")
        self.assert_conflict("app.py", "adding the uncommitted changes")

    def test_new_file_clashes_with_target(self):
        self.push_to_main("shared.py", "THEIRS = 1\n")
        write(self.repo / "shared.py", "MINE = 1\n")
        self.assert_conflict("shared.py", "adding the uncommitted new files")


class RefreshTest(RepoTest):
    def test_refresh_brings_new_edits_and_drops_old_ones(self):
        write(self.repo / "draft.txt", "one\n")
        folder, output = self.setup_copy("--target", "main")
        pr = folder / "pr"
        write(pr / "node_modules" / "lib.js", "installed\n")
        write(pr / "stray.txt", "made in the copy\n")

        (self.repo / "draft.txt").unlink()
        write(self.repo / "app.py", "VERSION = 3\n")
        code, output = self.run_main("refresh", str(folder))
        self.assertEqual(code, 0, output)
        self.assertEqual((pr / "app.py").read_text(), "VERSION = 3\n")
        self.assertFalse((pr / "draft.txt").exists())
        self.assertFalse((pr / "stray.txt").exists())
        self.assertTrue((pr / "node_modules" / "lib.js").is_file())
        self.assertTrue((pr / "feature.py").is_file())
        self.assertIn("pending  1 uncommitted file(s)", output)

    def test_refresh_keeps_the_merge(self):
        self.push_to_main("later.py", "LATER = 1\n")
        folder, output = self.setup_copy("--target", "main")
        self.run_main("refresh", str(folder))
        self.assertTrue((folder / "pr" / "later.py").is_file())

    def test_refresh_sees_new_commits_only_as_pending(self):
        folder, output = self.setup_copy("--target", "main")
        write(self.repo / "fix.py", "FIXED = 1\n")
        git(self.repo, "add", "fix.py")
        code, output = self.run_main("refresh", str(folder))
        self.assertTrue((folder / "pr" / "fix.py").is_file())

    def test_refresh_picks_up_new_commits(self):
        self.push_to_main("later.py", "LATER = 1\n")
        folder, output = self.setup_copy("--target", "main")
        write(self.repo / "fix.py", "FIXED = 1\n")
        git(self.repo, "add", "fix.py")
        git(self.repo, "commit", "--quiet", "-m", "fix")
        code, output = self.run_main("refresh", str(folder))
        self.assertEqual(code, 0, output)
        pr = folder / "pr"
        self.assertTrue((pr / "fix.py").is_file())
        self.assertTrue((pr / "later.py").is_file())
        self.assertIn("pending  none", output)
        # A second refresh with no new commits keeps everything.
        code, output = self.run_main("refresh", str(folder))
        self.assertEqual(code, 0, output)
        self.assertTrue((pr / "fix.py").is_file())
        self.assertTrue((pr / "later.py").is_file())

    def test_refresh_reports_a_new_conflict(self):
        self.push_to_main("app.py", "VERSION = 'theirs'\n")
        folder, output = self.setup_copy("--target", "main")
        write(self.repo / "app.py", "VERSION = 'mine'\n")
        git(self.repo, "commit", "--quiet", "-am", "mine")
        code, output = self.run_main("refresh", str(folder))
        self.assertEqual(code, 1, output)
        self.assertIn("conflict while merging origin/main into the PR", output)
        self.assertIn("  app.py", output)
        # Once the human resolves it, refresh works again.
        git(self.repo, "reset", "--quiet", "--hard", "HEAD~1")
        code, output = self.run_main("refresh", str(folder))
        self.assertEqual(code, 0, output)
        self.assertEqual((folder / "pr" / "app.py").read_text(), "VERSION = 'theirs'\n")

    def test_refresh_a_folder_that_is_not_ours(self):
        stranger = self.base / "stranger"
        write(stranger / "keep.txt", "mine\n")
        code, output = self.run_main("refresh", str(stranger))
        self.assertEqual(code, 2)
        self.assertIn("not a full-test folder", output)


class CleanupTest(RepoTest):
    def test_cleanup_removes_everything(self):
        folder, output = self.setup_copy("--target", "main")
        write(folder / "pr" / "node_modules" / "lib.js", "installed\n")
        # The skill keeps its checks file and logs in the folder too.
        write(folder / "checks.json", "[]\n")
        write(folder / "logs" / "lint.log", "ok\n")
        self.assertEqual(self.worktree_count(), 3)
        code, output = self.run_main("cleanup", str(folder))
        self.assertEqual(code, 0)
        self.assertFalse(folder.exists())
        self.assertEqual(self.worktree_count(), 1)
        self.assertIn(f"removed  {folder}", output)

    def test_cleanup_after_a_copy_was_deleted_by_hand(self):
        folder, output = self.setup_copy("--target", "main")
        shutil.rmtree(folder / "pr")
        code, output = self.run_main("cleanup", str(folder))
        self.assertEqual(code, 0)
        self.assertFalse(folder.exists())
        self.assertEqual(self.worktree_count(), 1)

    def test_cleanup_twice(self):
        folder, output = self.setup_copy("--target", "main")
        self.run_main("cleanup", str(folder))
        code, output = self.run_main("cleanup", str(folder))
        self.assertEqual(code, 2)
        self.assertIn("not a full-test folder", output)

    def test_cleanup_refuses_a_stranger_folder(self):
        stranger = self.base / "stranger"
        write(stranger / "keep.txt", "mine\n")
        code, output = self.run_main("cleanup", str(stranger))
        self.assertEqual(code, 2)
        self.assertTrue((stranger / "keep.txt").is_file())


class StartTest(RepoTest):
    def test_not_a_repo(self):
        plain = self.base / "plain"
        plain.mkdir()
        code, output = self.run_main("setup", "--repo", str(plain), "--target", "main")
        self.assertEqual(code, 2)
        self.assertIn("not inside a git repository", output)

    def test_missing_folder(self):
        code, output = self.run_main("setup", "--repo", str(self.base / "nope"), "--target", "main")
        self.assertEqual(code, 2)
        self.assertIn("the folder does not exist", output)

    def test_no_commits(self):
        empty = self.base / "empty"
        git(self.base, "init", "--quiet", str(empty))
        code, output = self.run_main("setup", "--repo", str(empty), "--target", "main")
        self.assertEqual(code, 2)
        self.assertIn("no commits yet", output)

    def test_chosen_folder_not_empty(self):
        chosen = self.base / "busy"
        write(chosen / "keep.txt", "mine\n")
        code, output = self.run_main(
            "setup", "--repo", str(self.repo), "--target", "main", "--dir", str(chosen)
        )
        self.assertEqual(code, 2)
        self.assertIn("the folder is not empty", output)
        self.assertTrue((chosen / "keep.txt").is_file())

    def test_no_command(self):
        with contextlib.redirect_stderr(io.StringIO()):
            with self.assertRaises(SystemExit) as raised:
                pr_copy.parse_args([])
        self.assertEqual(raised.exception.code, 2)


class CommandLineTest(RepoTest):
    def test_runs_as_a_script(self):
        result = subprocess.run(
            [sys.executable, str(SCRIPT), "setup", "--repo", str(self.repo), "--target", "main"],
            capture_output=True,
            text=True,
        )
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        folder = Path(self.value(result.stdout, "folder"))
        self.addCleanup(self.cleanup_quietly, folder)
        self.assertTrue((folder / "pr" / "feature.py").is_file())


if __name__ == "__main__":
    unittest.main()
