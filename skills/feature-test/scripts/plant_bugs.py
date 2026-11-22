#!/usr/bin/env python3
"""Plant bugs one at a time and check that the tests catch each one.

Each bug is a plain text edit: find one exact piece of text in one file
and replace it. The script runs the tests once with no bug, then once per
bug, and always puts the file back the way it was.

Exit codes: 0 every bug was caught, 1 a bug survived or could not be
planted, 2 the run could not start.
"""

import argparse
import json
import os
import signal
import subprocess
import sys
import time
from pathlib import Path

BACKUP_SUFFIX = ".plant-bugs.bak"
MIN_TIMEOUT_SECONDS = 60
TIMEOUT_FACTOR = 10
OUTPUT_TAIL_LINES = 20


class StartError(Exception):
    """The run cannot start; the message says why."""


class TestRun:
    def __init__(self, passed, timed_out, seconds, output):
        self.passed = passed
        self.timed_out = timed_out
        self.seconds = seconds
        self.output = output


def run_tests(command, root, timeout):
    """Run the test command in its own process group, so a timeout kills it all."""
    started = time.monotonic()
    process = subprocess.Popen(
        command,
        shell=True,
        cwd=root,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        start_new_session=True,
    )
    try:
        output, _ = process.communicate(timeout=timeout)
        timed_out = False
    except subprocess.TimeoutExpired:
        kill_process_group(process)
        output, _ = process.communicate()
        timed_out = True
    except BaseException:
        # Ctrl+C or any crash: stop the tests so they do not outlive us.
        kill_process_group(process)
        process.wait()
        process.stdout.close()
        raise
    seconds = time.monotonic() - started
    passed = process.returncode == 0
    text = output.decode("utf-8", errors="replace")
    return TestRun(passed, timed_out, seconds, text)


def kill_process_group(process):
    if hasattr(os, "killpg"):
        try:
            os.killpg(process.pid, signal.SIGKILL)
        except ProcessLookupError:
            pass
    else:
        process.kill()


def tail(text, count):
    lines = text.rstrip("\n").splitlines()
    return "\n".join(lines[-count:])


def load_bugs(bugs_path, root):
    """Read the bugs file and check every entry before anything is touched."""
    try:
        raw = bugs_path.read_text(encoding="utf-8")
    except OSError as error:
        raise StartError(f"cannot read the bugs file: {error}")
    try:
        entries = json.loads(raw)
    except json.JSONDecodeError as error:
        raise StartError(f"the bugs file is not valid JSON: {error}")
    if not isinstance(entries, list) or not entries:
        raise StartError("the bugs file must be a JSON list with at least one bug")

    bugs = []
    for number, entry in enumerate(entries, start=1):
        bugs.append(check_entry(entry, number, root))
    return bugs


def check_entry(entry, number, root):
    if not isinstance(entry, dict):
        raise StartError(f"bug {number} must be an object")
    for key in ("file", "find", "replace"):
        value = entry.get(key)
        if not isinstance(value, str):
            raise StartError(f'bug {number} needs "{key}" as text')
    why = entry.get("why", "")
    if not isinstance(why, str):
        raise StartError(f'bug {number} has a "why" that is not text')
    if entry["find"] == "":
        raise StartError(f'bug {number} has an empty "find"')
    if entry["find"] == entry["replace"]:
        raise StartError(f'bug {number} has "replace" equal to "find", so it changes nothing')

    path = (root / entry["file"]).resolve()
    if not is_inside(path, root):
        raise StartError(f'bug {number} points outside the project: {entry["file"]}')
    if not path.is_file():
        raise StartError(f'bug {number} points to a file that does not exist: {entry["file"]}')

    return {
        "file": entry["file"],
        "path": path,
        "find": entry["find"],
        "replace": entry["replace"],
        "why": why.strip(),
    }


def is_inside(path, root):
    try:
        path.relative_to(root)
    except ValueError:
        return False
    return True


def backup_path(path):
    return path.with_name(path.name + BACKUP_SUFFIX)


def check_no_leftovers(bugs):
    """A backup left behind means an earlier run was killed mid-bug."""
    for bug in bugs:
        leftover = backup_path(bug["path"])
        if leftover.exists():
            raise StartError(
                f"an earlier run did not finish. Check {bug['file']}, "
                f"restore it from {leftover.name} if it holds a planted bug, "
                f"then delete {leftover.name}"
            )


def plant_and_test(bug, command, root, timeout):
    """Plant one bug, run the tests, put the file back. Returns (status, note)."""
    path = bug["path"]
    original = path.read_bytes()
    try:
        text = original.decode("utf-8")
    except UnicodeDecodeError:
        return "unusable", "file is not UTF-8 text"

    matches = text.count(bug["find"])
    if matches != 1:
        return "unusable", f"find text matches {matches} times, it must match once"

    planted = text.replace(bug["find"], bug["replace"]).encode("utf-8")
    backup = backup_path(path)
    backup.write_bytes(original)
    try:
        path.write_bytes(planted)
        result = run_tests(command, root, timeout)
    finally:
        path.write_bytes(original)
        backup.unlink()

    if result.timed_out:
        return "caught", f"tests timed out after {timeout:.0f}s"
    if result.passed:
        return "SURVIVED", ""
    return "caught", ""


def describe(bug):
    if bug["why"]:
        return f"{bug['file']}: {bug['why']}"
    return bug["file"]


def parse_args(argv):
    parser = argparse.ArgumentParser(
        description="Plant bugs one at a time and check that the tests catch each one."
    )
    parser.add_argument(
        "--bugs",
        required=True,
        help='JSON file: a list of {"file", "find", "replace", "why"} objects',
    )
    parser.add_argument(
        "--test",
        required=True,
        help='the command that runs the tests, like "python3 -m unittest"',
    )
    parser.add_argument(
        "--root",
        default=".",
        help="the project folder; files in the bugs list are relative to it",
    )
    parser.add_argument(
        "--timeout",
        type=float,
        help="seconds before a test run counts as stuck "
        f"(default: {TIMEOUT_FACTOR} times the clean run, at least {MIN_TIMEOUT_SECONDS})",
    )
    args = parser.parse_args(argv)
    if args.test.strip() == "":
        parser.error("--test must not be empty")
    if args.timeout is not None and args.timeout <= 0:
        parser.error("--timeout must be more than 0")
    return args


def main(argv=None):
    args = parse_args(argv)
    root = Path(args.root).resolve()
    if not root.is_dir():
        print(f"cannot start: the project folder does not exist: {args.root}")
        return 2

    try:
        bugs = load_bugs(Path(args.bugs), root)
        check_no_leftovers(bugs)
    except StartError as error:
        print(f"cannot start: {error}")
        return 2

    clean = run_tests(args.test, root, args.timeout)
    if not clean.passed:
        print("cannot start: the tests fail before any bug is planted. Fix them first.")
        print(tail(clean.output, OUTPUT_TAIL_LINES))
        return 2

    timeout = args.timeout
    if timeout is None:
        timeout = max(MIN_TIMEOUT_SECONDS, clean.seconds * TIMEOUT_FACTOR)

    failures = 0
    for bug in bugs:
        status, note = plant_and_test(bug, args.test, root, timeout)
        line = f"{status:<9} {describe(bug)}"
        if note:
            line = f"{line} ({note})"
        print(line, flush=True)
        if status != "caught":
            failures += 1

    caught = len(bugs) - failures
    print(f"{caught} of {len(bugs)} bugs caught")
    if failures:
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
