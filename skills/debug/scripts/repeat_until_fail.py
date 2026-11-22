#!/usr/bin/env python3
"""Run a command again and again until it fails, to catch a bug that
only shows up sometimes.

It stops at the first failure and prints what that run printed. If every
run passes, the bug did not show up. After a fix, run it again with more
runs to show the bug is really gone.

A run fails when the command exits with a code other than 0, or runs
longer than the timeout (a hang is a failure too). CI=true is set, so
test runners do not wait in watch mode.

Exit codes: 0 every run passed, 1 a run failed, 2 could not start.
"""

import argparse
import os
import signal
import subprocess
import sys
import time
from pathlib import Path

DEFAULT_TIMES = 50
DEFAULT_TIMEOUT_SECONDS = 600
OUTPUT_TAIL_LINES = 40


class Run:
    def __init__(self, exit_code, timed_out, seconds, output):
        self.exit_code = exit_code
        self.timed_out = timed_out
        self.seconds = seconds
        self.output = output

    @property
    def passed(self):
        return self.exit_code == 0 and not self.timed_out


def run_once(command, root, timeout, env):
    """Run the command in its own process group, so a timeout kills it all."""
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
        # Ctrl+C or any crash: stop the command so it does not outlive us.
        kill_process_group(process)
        process.wait()
        process.stdout.close()
        raise
    seconds = time.monotonic() - started
    text = output.decode("utf-8", errors="replace")
    return Run(process.returncode, timed_out, seconds, text)


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


def describe_failure(number, times, run, timeout):
    if run.timed_out:
        ending = f"timed out after {timeout:g}s"
    else:
        ending = f"exit {run.exit_code}, {run.seconds:.1f}s"
    return f"FAIL on run {number} of {times} ({ending})"


def write_log(log_path, command, number, run):
    header = f"$ {command}\n== run {number} ==\n"
    log_path.parent.mkdir(parents=True, exist_ok=True)
    log_path.write_text(header + run.output, encoding="utf-8")


def parse_args(argv):
    parser = argparse.ArgumentParser(
        description="Run a command again and again until it fails."
    )
    parser.add_argument("--command", required=True, help="the shell command that shows the bug")
    parser.add_argument(
        "--times", type=int, default=DEFAULT_TIMES, help=f"most runs to try (default {DEFAULT_TIMES})"
    )
    parser.add_argument(
        "--timeout",
        type=float,
        default=DEFAULT_TIMEOUT_SECONDS,
        help=f"seconds one run may take before it counts as failed (default {DEFAULT_TIMEOUT_SECONDS})",
    )
    parser.add_argument("--root", default=".", help="the folder to run the command in")
    parser.add_argument("--log", help="file to save the failing run's full output in")
    args = parser.parse_args(argv)
    if args.times < 1:
        parser.error("--times must be 1 or more")
    if args.timeout <= 0:
        parser.error("--timeout must be above 0")
    if args.command.strip() == "":
        parser.error("--command must not be empty")
    return args


def main(argv=None):
    args = parse_args(argv)
    root = Path(args.root).resolve()
    if not root.is_dir():
        print(f"cannot start: the folder does not exist: {args.root}")
        return 2

    env = os.environ.copy()
    env["CI"] = "true"

    total_seconds = 0.0
    for number in range(1, args.times + 1):
        run = run_once(args.command, root, args.timeout, env)
        total_seconds += run.seconds
        if run.passed:
            continue
        print(describe_failure(number, args.times, run, args.timeout))
        for line in tail(run.output, OUTPUT_TAIL_LINES):
            print(f"    {line}")
        if args.log:
            log_path = Path(args.log).resolve()
            write_log(log_path, args.command, number, run)
            print(f"Full output: {log_path}")
        return 1

    average = total_seconds / args.times
    print(f"pass: all {args.times} runs passed ({average:.1f}s each on average)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
