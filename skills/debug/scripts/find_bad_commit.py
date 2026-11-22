#!/usr/bin/env python3
"""Find the commit that broke something, with git bisect.

It works in a throwaway copy of the repo, so the human's folder, branch
and uncommitted changes are never touched. First it checks that the test
really fails on the bad commit and passes on the good one, then lets
git bisect test the commits in between. The copy is always removed.

The test is a shell command run inside the copy at each commit. Exit 0
means good, 125 means this commit cannot be tested (skip it), anything
else, a crash or a timeout means bad. Keep the test outside the repo
(an absolute path), since old commits do not have files you just wrote.

--setup runs before the test at each commit (like an install or build).
If it fails, that commit is skipped, not called bad.

Exit codes: 0 found the commit, 1 could not narrow it to one commit
(too many were skipped), 2 could not start.
"""

import argparse
import os
import re
import shutil
import signal
import subprocess
import sys
import tempfile
import time
from pathlib import Path

DEFAULT_TIMEOUT_SECONDS = 600
GOOD = 0
SKIP = 125
BAD = 1
STEP_PREFIX = "step "
FOUND_PATTERN = re.compile(r"^([0-9a-f]{40}) is the first bad commit", re.MULTILINE)
SKIPPED_ONLY_TEXT = "only 'skip'ped commits left"


class StartError(Exception):
    """The run cannot start; the message says why."""


def git(args, cwd, check=True):
    result = subprocess.run(
        ["git", *args],
        cwd=cwd,
        stdin=subprocess.DEVNULL,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
    )
    text = result.stdout.decode("utf-8", errors="replace")
    if check and result.returncode != 0:
        raise StartError(f"git {' '.join(args)} failed: {text.strip()}")
    return result.returncode, text


def git_text(args, cwd):
    return git(args, cwd)[1].strip()


def run_shell(command, cwd, timeout):
    """Run a command in its own process group. Returns its exit code, or
    None if it ran past the timeout."""
    process = subprocess.Popen(
        command,
        shell=True,
        cwd=cwd,
        stdin=subprocess.DEVNULL,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        start_new_session=True,
    )
    try:
        return process.wait(timeout=timeout)
    except subprocess.TimeoutExpired:
        kill_process_group(process)
        process.wait()
        return None
    except BaseException:
        kill_process_group(process)
        process.wait()
        raise


def kill_process_group(process):
    if hasattr(os, "killpg"):
        try:
            os.killpg(process.pid, signal.SIGKILL)
        except ProcessLookupError:
            pass
    else:
        process.kill()


def judge(test, setup, cwd, timeout):
    """Test the commit checked out in cwd. Returns GOOD, SKIP or BAD and why."""
    if setup:
        code = run_shell(setup, cwd, timeout)
        if code is None:
            return SKIP, "setup timed out"
        if code != 0:
            return SKIP, f"setup failed (exit {code})"
    started = time.monotonic()
    code = run_shell(test, cwd, timeout)
    seconds = time.monotonic() - started
    if code is None:
        return BAD, f"test timed out after {timeout:g}s"
    if code == 0:
        return GOOD, f"test passed, {seconds:.1f}s"
    if code == SKIP:
        return SKIP, "test asked to skip (exit 125)"
    return BAD, f"test failed (exit {code}), {seconds:.1f}s"


def verdict_word(verdict):
    if verdict == GOOD:
        return "good"
    if verdict == SKIP:
        return "skip"
    return "bad"


def step(args):
    """Called by git bisect run, inside the copy, once per commit."""
    cwd = Path.cwd()
    verdict, reason = judge(args.test, args.setup, cwd, args.timeout)
    commit = git_text(["rev-parse", "--short", "HEAD"], cwd)
    print(f"{STEP_PREFIX}{commit}  {verdict_word(verdict)}: {reason}", flush=True)
    return verdict


def find_repo_root(path):
    folder = Path(path).resolve()
    if not folder.is_dir():
        raise StartError(f"the folder does not exist: {path}")
    code, text = git(["rev-parse", "--show-toplevel"], folder, check=False)
    if code != 0:
        raise StartError(f"not inside a git repository: {path}")
    return Path(text.strip())


def resolve_commit(repo, ref):
    code, text = git(["rev-parse", "--verify", "--quiet", f"{ref}^{{commit}}"], repo, check=False)
    if code != 0:
        raise StartError(f"no commit named {ref}")
    return text.strip()


def check_order(repo, good, bad, good_ref, bad_ref):
    if good == bad:
        raise StartError(f"{good_ref} and {bad_ref} are the same commit")
    code, _ = git(["merge-base", "--is-ancestor", good, bad], repo, check=False)
    if code != 0:
        raise StartError(f"{good_ref} is not an older commit of {bad_ref}")


def run_step(copy, args):
    """Test the commit checked out in the copy exactly as git bisect run
    will, so a step that cannot run is caught before bisecting."""
    result = subprocess.run(
        step_command(args),
        cwd=copy,
        stdin=subprocess.DEVNULL,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
    )
    text = result.stdout.decode("utf-8", errors="replace").strip()
    if result.returncode not in (GOOD, SKIP, BAD):
        raise StartError(f"the bisect step itself failed:\n{text}")
    reason = text
    if reason.startswith(STEP_PREFIX):
        reason = reason[len(STEP_PREFIX):]
    return result.returncode, reason


def check_ends(copy, args, good, bad):
    """The test must fail on bad and pass on good, or bisect means nothing."""
    git(["checkout", "--quiet", "--detach", bad], copy)
    verdict, reason = run_step(copy, args)
    if verdict == GOOD:
        raise StartError(f"the test passes on {args.bad} ({reason}), so it does not show the bug")
    if verdict == SKIP:
        raise StartError(f"cannot test {args.bad} ({reason})")

    git(["checkout", "--quiet", "--detach", good], copy)
    verdict, reason = run_step(copy, args)
    if verdict == BAD:
        raise StartError(
            f"the test fails on {args.good} too ({reason}); pick an older good commit"
        )
    if verdict == SKIP:
        raise StartError(f"cannot test {args.good} ({reason})")


def step_command(args):
    # -I keeps the project's own files and PYTHON* settings out of the step.
    command = [sys.executable, "-I", str(Path(__file__).resolve()), "--step",
               "--test", args.test, "--timeout", str(args.timeout)]
    if args.setup:
        command.extend(["--setup", args.setup])
    return command


def print_commit(copy, commit):
    summary = git_text(["show", "--no-patch", "--format=%h %s (%an, %ad)", "--date=short", commit], copy)
    files = git_text(["show", "--format=", "--stat", commit], copy)
    print(f"first bad commit: {summary}")
    for line in files.splitlines():
        print(f"    {line}")


def run_bisect(copy, args, good, bad):
    git(["bisect", "start", bad, good], copy)
    _, text = git(["bisect", "run", *step_command(args)], copy, check=False)
    for line in text.splitlines():
        if line.startswith(STEP_PREFIX):
            print(line[len(STEP_PREFIX):])

    found = FOUND_PATTERN.search(text)
    if found is not None:
        print_commit(copy, found.group(1))
        return 0
    if SKIPPED_ONLY_TEXT in text:
        print("could not narrow it to one commit; the first bad one is among these:")
        for line in text.splitlines():
            if re.match(r"^[0-9a-f]{40}$", line.strip()):
                print(f"    {git_text(['show', '--no-patch', '--format=%h %s', line.strip()], copy)}")
        return 1
    raise StartError(f"git bisect run stopped early:\n{text.strip()}")


def remove_copy(repo, folder, copy):
    if copy.exists():
        git(["bisect", "reset"], copy, check=False)
    # Removing the folder and pruning removes the worktree too.
    shutil.rmtree(folder, ignore_errors=True)
    git(["worktree", "prune"], repo, check=False)


def find(args):
    repo = find_repo_root(args.repo)
    good = resolve_commit(repo, args.good)
    bad = resolve_commit(repo, args.bad)
    check_order(repo, good, bad, args.good, args.bad)

    folder = Path(tempfile.mkdtemp(prefix="debug-bisect-")).resolve()
    copy = folder / "copy"
    try:
        git(["worktree", "add", "--quiet", "--detach", str(copy), bad], repo)
        check_ends(copy, args, good, bad)
        return run_bisect(copy, args, good, bad)
    finally:
        remove_copy(repo, folder, copy)


def parse_args(argv):
    parser = argparse.ArgumentParser(description="Find the commit that broke something.")
    parser.add_argument("--repo", default=".", help="the human's project folder")
    parser.add_argument("--good", help="a commit where the test passes")
    parser.add_argument("--bad", default="HEAD", help="a commit where the test fails (default HEAD)")
    parser.add_argument("--test", required=True, help="shell command: exit 0 good, 125 skip, else bad")
    parser.add_argument("--setup", help="shell command run before the test at each commit")
    parser.add_argument(
        "--timeout",
        type=float,
        default=DEFAULT_TIMEOUT_SECONDS,
        help=f"seconds the setup or test may take at one commit (default {DEFAULT_TIMEOUT_SECONDS})",
    )
    # Used only by git bisect run, to test one commit.
    parser.add_argument("--step", action="store_true", help=argparse.SUPPRESS)
    args = parser.parse_args(argv)
    if args.timeout <= 0:
        parser.error("--timeout must be above 0")
    if args.test.strip() == "":
        parser.error("--test must not be empty")
    if not args.step and not args.good:
        parser.error("--good is required")
    return args


def main(argv=None):
    args = parse_args(argv)
    try:
        if args.step:
            return step(args)
        return find(args)
    except StartError as error:
        if args.step:
            # git bisect run stops on exit codes above 127.
            print(f"{STEP_PREFIX}cannot test this commit: {error}", flush=True)
            return 128
        print(f"cannot start: {error}")
        return 2


if __name__ == "__main__":
    sys.exit(main())
