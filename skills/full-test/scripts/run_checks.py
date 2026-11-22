#!/usr/bin/env python3
"""Run the PR's checks in order and record what each one printed.

The checks file is a JSON list of {"name", "command", "timeout"} objects,
in the order to run them. Every check runs, even after one fails, so one
run shows every problem. Each check's full output goes to a log file.

CI=true is set for every check, as CI does, so test runners do not sit
in watch mode waiting for a key press.

Exit codes: 0 every check passed, 1 a check failed or was flaky, 2 the
run could not start.
"""

import argparse
import json
import os
import re
import signal
import subprocess
import sys
import tempfile
import time
from pathlib import Path

DEFAULT_TIMEOUT_SECONDS = 1800
OUTPUT_TAIL_LINES = 20
NAME_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_-]*$")


class StartError(Exception):
    """The run cannot start; the message says why."""


class CommandRun:
    def __init__(self, passed, timed_out, exit_code, seconds, output):
        self.passed = passed
        self.timed_out = timed_out
        self.exit_code = exit_code
        self.seconds = seconds
        self.output = output


def run_command(command, root, timeout, env):
    """Run one command in its own process group, so a timeout kills it all."""
    started = time.monotonic()
    process = subprocess.Popen(
        command,
        shell=True,
        cwd=root,
        env=env,
        stdin=subprocess.DEVNULL,
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
        # Ctrl+C or any crash: stop the check so it does not outlive us.
        kill_process_group(process)
        process.wait()
        process.stdout.close()
        raise
    seconds = time.monotonic() - started
    passed = process.returncode == 0 and not timed_out
    text = output.decode("utf-8", errors="replace")
    return CommandRun(passed, timed_out, process.returncode, seconds, text)


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
    return lines[-count:]


def load_checks(checks_path):
    """Read the checks file and check every entry before anything runs."""
    try:
        raw = checks_path.read_text(encoding="utf-8")
    except OSError as error:
        raise StartError(f"cannot read the checks file: {error}")
    try:
        entries = json.loads(raw)
    except json.JSONDecodeError as error:
        raise StartError(f"the checks file is not valid JSON: {error}")
    if not isinstance(entries, list) or not entries:
        raise StartError("the checks file must be a JSON list with at least one check")

    checks = []
    seen = set()
    for number, entry in enumerate(entries, start=1):
        check = check_entry(entry, number)
        if check["name"] in seen:
            raise StartError(f'check {number} reuses the name "{check["name"]}"')
        seen.add(check["name"])
        checks.append(check)
    return checks


def check_entry(entry, number):
    if not isinstance(entry, dict):
        raise StartError(f"check {number} must be an object")
    name = entry.get("name")
    if not isinstance(name, str) or not NAME_PATTERN.match(name):
        raise StartError(
            f"check {number} needs a \"name\" of letters, digits, - or _ (like \"type-check\")"
        )
    command = entry.get("command")
    if not isinstance(command, str) or command.strip() == "":
        raise StartError(f'check {number} needs a "command" as text')
    timeout = entry.get("timeout", DEFAULT_TIMEOUT_SECONDS)
    if isinstance(timeout, bool) or not isinstance(timeout, (int, float)) or timeout <= 0:
        raise StartError(f'check {number} has a "timeout" that is not a number of seconds above 0')
    return {"name": name, "command": command, "timeout": float(timeout)}


def pick_checks(checks, only):
    if not only:
        return checks
    known = {check["name"] for check in checks}
    for name in only:
        if name not in known:
            raise StartError(f'no check named "{name}" in the checks file')
    return [check for check in checks if check["name"] in only]


def make_log_dir(requested):
    if requested is None:
        return Path(tempfile.mkdtemp(prefix="full-test-logs-")).resolve()
    folder = Path(requested).resolve()
    folder.mkdir(parents=True, exist_ok=True)
    return folder


def status_of(runs):
    passes = sum(1 for run in runs if run.passed)
    if passes == len(runs):
        return "pass"
    if passes == 0:
        return "FAIL"
    return "FLAKY"


def write_log(log_path, check, runs):
    parts = [f"$ {check['command']}\n"]
    for number, run in enumerate(runs, start=1):
        if run.timed_out:
            ending = f"timed out after {check['timeout']:.0f}s"
        else:
            ending = f"exit {run.exit_code}"
        parts.append(f"\n== run {number} of {len(runs)}: {ending}, {run.seconds:.1f}s ==\n")
        parts.append(run.output)
    log_path.write_text("".join(parts), encoding="utf-8")


def describe_line(status, check, runs, width):
    seconds = sum(run.seconds for run in runs) / len(runs)
    line = f"{status:<6} {check['name']:<{width}} {seconds:>7.1f}s  {check['command']}"
    if len(runs) > 1:
        passes = sum(1 for run in runs if run.passed)
        line = f"{line}  ({passes} of {len(runs)} passed)"
    if any(run.timed_out for run in runs):
        line = f"{line}  (timed out after {check['timeout']:.0f}s)"
    return line


def last_failure(runs):
    for run in reversed(runs):
        if not run.passed:
            return run
    return None


def run_check(check, root, repeat, env, log_dir, width):
    runs = []
    for _ in range(repeat):
        runs.append(run_command(check["command"], root, check["timeout"], env))
    status = status_of(runs)
    write_log(log_dir / f"{check['name']}.log", check, runs)
    print(describe_line(status, check, runs, width), flush=True)
    failed_run = last_failure(runs)
    if failed_run is not None:
        for line in tail(failed_run.output, OUTPUT_TAIL_LINES):
            print(f"    {line}")
    return status


def parse_args(argv):
    parser = argparse.ArgumentParser(
        description="Run the PR's checks in order and record what each one printed."
    )
    parser.add_argument(
        "--checks",
        required=True,
        help='JSON file: a list of {"name", "command", "timeout"} objects, in order',
    )
    parser.add_argument("--root", required=True, help="the folder to run the checks in")
    parser.add_argument(
        "--only",
        action="append",
        default=[],
        help="run only this check (repeat the flag for more than one)",
    )
    parser.add_argument(
        "--repeat",
        type=int,
        default=1,
        help="run each check this many times on the same code, to tell flaky from broken",
    )
    parser.add_argument("--log-dir", help="where to write each check's full output")
    args = parser.parse_args(argv)
    if args.repeat < 1:
        parser.error("--repeat must be 1 or more")
    return args


def main(argv=None):
    args = parse_args(argv)
    root = Path(args.root).resolve()
    if not root.is_dir():
        print(f"cannot start: the folder does not exist: {args.root}")
        return 2
    try:
        checks = pick_checks(load_checks(Path(args.checks)), args.only)
    except StartError as error:
        print(f"cannot start: {error}")
        return 2

    log_dir = make_log_dir(args.log_dir)
    env = os.environ.copy()
    env["CI"] = "true"
    width = max(len(check["name"]) for check in checks)

    passed = 0
    for check in checks:
        status = run_check(check, root, args.repeat, env, log_dir, width)
        if status == "pass":
            passed += 1

    print(f"{passed} of {len(checks)} checks passed. Full output: {log_dir}")
    if passed == len(checks):
        return 0
    return 1


if __name__ == "__main__":
    sys.exit(main())
