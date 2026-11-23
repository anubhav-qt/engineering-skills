#!/usr/bin/env python3
"""Prove that fake secrets never reach the logs.

Step 1: print the fake values (canaries) a test or journey should use:

    check_log_leaks.py --print-canaries

Write a test or journey that sends them through the code under test (a
login with the fake password, a request with the fake token). It can
also read them from the environment: this script sets LOG_CANARY_* when
it runs the command.

Step 2: run that command and search everything it logged:

    check_log_leaks.py --command "pytest tests/test_login.py" \\
      --expect "user.login" [--log-file logs/app.log ...]

It searches stdout, stderr and what the run added to each log file for
every canary: as is, URL-encoded and base64-encoded.

--expect is text a real log line from the run must hold (an event name).
It proves the logs were captured; without it, an empty capture would
pass and prove nothing.

Exit codes: 0 no canary leaked, 1 a canary leaked, 2 the check proves
nothing (could not start, the command failed or hung, or --expect was
not seen).
"""

# logger: cli (its prints are its report)

import argparse
import base64
import os
import signal
import subprocess
import sys
import urllib.parse
from pathlib import Path

DEFAULT_TIMEOUT_SECONDS = 600
SHOWN_LINE_LENGTH = 200
SHOWN_FAILURE_LINES = 10

# Fixed and unusual, so a match can only come from the test.
# The card is a well known fake test number that passes the Luhn check.
CANARIES = {
    "LOG_CANARY_PASSWORD": "lc-Passw0rd-7Hq2",
    "LOG_CANARY_TOKEN": "lc-tok-9f3K1xQ8vB",
    "LOG_CANARY_API_KEY": "lc-key-Z4m8T2wR",
    "LOG_CANARY_EMAIL": "lc.canary.8d2@example.com",
    "LOG_CANARY_CARD": "4242424242424242",
}


class StartError(Exception):
    """The run cannot start; the message says why."""


class Leak:
    def __init__(self, name, form, source, number, line):
        self.name = name
        self.form = form
        self.source = source
        self.number = number
        self.line = line


class Run:
    def __init__(self, exit_code, timed_out, output):
        self.exit_code = exit_code
        self.timed_out = timed_out
        self.output = output


# ---------- the forms a canary can take ----------

def encoded_forms(value):
    """Return [(form name, text)] for one canary value."""
    forms = [("as is", value)]
    # The canaries hold no spaces, so quote and quote_plus agree.
    quoted = urllib.parse.quote(value, safe="")
    if quoted != value:
        forms.append(("URL-encoded", quoted))
    for needle in base64_needles(value):
        forms.append(("base64", needle))
    return forms


def base64_needles(value):
    """The middle of the value's base64 text, for each of the 3 ways it
    can line up inside a longer encoded string (like "user:password" in
    a Basic auth header). The first and last 4 characters mix with what
    comes before and after, so they are cut off."""
    needles = []
    raw = value.encode("utf-8")
    for offset in range(3):
        encoded = base64.b64encode(b"\0" * offset + raw).decode("ascii")
        start = 0
        if offset > 0:
            start = 4
        needles.append(encoded[start:len(encoded) - 4])
    return needles


def find_leaks(sources):
    """sources: [(name, text)]. Return every canary found in them."""
    leaks = []
    for source, text in sources:
        lines = text.splitlines()
        for number, line in enumerate(lines, start=1):
            for name, value in CANARIES.items():
                for form, needle in encoded_forms(value):
                    if needle in line:
                        leaks.append(Leak(name, form, source, number, line))
                        break
    return leaks


# ---------- running the command ----------

def run_command(command, root, timeout, env):
    """Run the command in its own process group, so a timeout kills it all."""
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
    text = output.decode("utf-8", errors="replace")
    return Run(process.returncode, timed_out, text)


def kill_process_group(process):
    if hasattr(os, "killpg"):
        try:
            os.killpg(process.pid, signal.SIGKILL)
        except ProcessLookupError:
            pass
    else:
        process.kill()


def file_size(path):
    try:
        return path.stat().st_size
    except FileNotFoundError:
        return 0


def read_new_part(path, size_before):
    """What the run added to a log file. If the file shrank (it was
    rotated or rewritten), read all of it."""
    try:
        data = path.read_bytes()
    except FileNotFoundError:
        return ""
    if len(data) >= size_before:
        data = data[size_before:]
    return data.decode("utf-8", errors="replace")


# ---------- report ----------

def shorten(line):
    line = line.strip()
    if len(line) <= SHOWN_LINE_LENGTH:
        return line
    return line[:SHOWN_LINE_LENGTH] + "..."


def print_last_lines(output):
    """Show the end of the command's output, where the error usually is."""
    lines = output.splitlines()[-SHOWN_FAILURE_LINES:]
    if not lines:
        return
    print("last lines of its output:")
    for line in lines:
        print(f"      {shorten(line)}")


def print_canaries():
    print("Use these fake values in the test or journey, or read them from")
    print("the environment (the run sets them):")
    for name, value in CANARIES.items():
        print(f"{name}={value}")


def parse_args(argv):
    parser = argparse.ArgumentParser(
        description="Prove that fake secrets never reach the logs."
    )
    parser.add_argument(
        "--print-canaries", action="store_true", help="print the fake values and stop"
    )
    parser.add_argument("--command", help="the test or journey that uses the fake values")
    parser.add_argument(
        "--expect", help="text a real log line from the run must hold, such as an event name"
    )
    parser.add_argument(
        "--log-file", action="append", default=[], help="a log file the app writes (repeat for more)"
    )
    parser.add_argument("--root", default=".", help="the folder to run the command in")
    parser.add_argument(
        "--timeout",
        type=float,
        default=DEFAULT_TIMEOUT_SECONDS,
        help=f"seconds the command may take (default {DEFAULT_TIMEOUT_SECONDS})",
    )
    args = parser.parse_args(argv)
    if args.print_canaries:
        return args
    if args.command is None or args.command.strip() == "":
        parser.error("--command is required and must not be empty")
    if args.expect is None or args.expect.strip() == "":
        parser.error("--expect is required and must not be empty")
    if args.timeout <= 0:
        parser.error("--timeout must be above 0")
    return args


def check(args):
    root = Path(args.root).resolve()
    if not root.is_dir():
        raise StartError(f"the folder does not exist: {args.root}")

    log_files = []
    for raw in args.log_file:
        path = Path(raw)
        if not path.is_absolute():
            path = root / path
        log_files.append(path)
    sizes_before = [file_size(path) for path in log_files]

    env = os.environ.copy()
    env["CI"] = "true"
    env.update(CANARIES)
    run = run_command(args.command, root, args.timeout, env)

    sources = [("command output", run.output)]
    for path, size_before in zip(log_files, sizes_before):
        sources.append((str(path), read_new_part(path, size_before)))
    return run, sources


def main(argv=None):
    args = parse_args(argv)
    if args.print_canaries:
        print_canaries()
        return 0

    try:
        run, sources = check(args)
    except StartError as error:
        print(f"cannot start: {error}")
        return 2

    leaks = find_leaks(sources)
    if leaks:
        print(f"LEAK: {len(leaks)} line(s) hold a fake secret")
        for leak in leaks:
            print(f"  {leak.name} ({leak.form}) in {leak.source} line {leak.number}:")
            print(f"      {shorten(leak.line)}")
        return 1

    if run.timed_out:
        print(f"proves nothing: the command hung past {args.timeout:g}s")
        print_last_lines(run.output)
        return 2
    if run.exit_code != 0:
        print(f"proves nothing: the command failed (exit {run.exit_code}); fix it first")
        print_last_lines(run.output)
        return 2

    seen = False
    for _, text in sources:
        if args.expect in text:
            seen = True
    if not seen:
        print(f"proves nothing: '{args.expect}' never showed up, so the logs were not captured")
        return 2

    names = ", ".join(sorted(CANARIES))
    print(f"clean: no fake secret in {len(sources)} source(s) ({names})")
    return 0


if __name__ == "__main__":
    sys.exit(main())
