#!/usr/bin/env python3
"""List things in the PR's diff that a reviewer would flag.

It reads every line the PR adds (committed, uncommitted and new files)
and lists debug leftovers, conflict markers, focused or skipped tests,
notes like TODO, possible secrets, and files that should not be
committed. A finding is something to look at, not always a mistake.

Exit codes: 0 nothing found, 1 something to look at, 2 could not start.
"""

import argparse
import re
import subprocess
import sys
from pathlib import Path, PurePosixPath

LARGE_FILE_BYTES = 1_000_000
SHOWN_TEXT_CHARS = 120
SECRET_KIND = "possible secret"
SAFE_ENV_NAMES = {".env.example", ".env.sample", ".env.template", ".env.dist"}
KEY_FILE_ENDINGS = (".pem", ".key", ".p12", ".pfx")
HUNK_PATTERN = re.compile(r"^@@ -\d+(?:,\d+)? \+(\d+)(?:,\d+)? @@")

LINE_CHECKS = [
    ("conflict marker", re.compile(r"^(<{7}|>{7})( |$)")),
    (
        "debug leftover",
        re.compile(
            r"\bconsole\.(log|debug|trace)\("
            r"|^\s*debugger\s*;?\s*$"
            r"|\bbreakpoint\(\)"
            r"|\bi?pdb\.set_trace\("
            r"|^\s*import i?pdb\b"
            r"|\bbinding\.pry\b"
            r"|\bdbg!\("
        ),
    ),
    ("note left in", re.compile(r"\b(TODO|FIXME|XXX|HACK)\b")),
    (
        "focused or skipped test",
        re.compile(
            r"\b(describe|it|test|context)\.(only|skip)\("
            r"|\b(fit|fdescribe|xit|xdescribe|xtest)\("
            r"|@pytest\.mark\.skip"
            r"|@unittest\.skip"
            r"|\bt\.Skip(Now)?\("
        ),
    ),
    (
        SECRET_KIND,
        re.compile(
            r"AKIA[0-9A-Z]{16}"
            r"|-----BEGIN [A-Z ]*PRIVATE KEY-----"
            r"|\bgh[pousr]_[A-Za-z0-9]{36,}"
            r"|\bgithub_pat_[A-Za-z0-9_]{20,}"
            r"|\bsk-[A-Za-z0-9_-]{20,}"
            r"|\bxox[abprs]-[A-Za-z0-9-]{10,}"
            r"|\bAIza[0-9A-Za-z_-]{35}"
        ),
    ),
    (
        SECRET_KIND,
        re.compile(
            r"(?i)\b(api[_-]?key|secret|passw(or)?d|token)\b\s*[:=]\s*['\"][^'\"\s]{8,}['\"]"
        ),
    ),
]


class StartError(Exception):
    """The run cannot start; the message says why."""


class Finding:
    def __init__(self, path, line, kind, text):
        self.path = path
        self.line = line
        self.kind = kind
        self.text = text

    def describe(self):
        place = self.path
        if self.line is not None:
            place = f"{self.path}:{self.line}"
        if self.text:
            return f"{place}  {self.kind}: {self.text}"
        return f"{place}  {self.kind}"


def git(args, cwd):
    result = subprocess.run(
        ["git", "-c", "core.quotePath=false", *args],
        cwd=cwd,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    if result.returncode != 0:
        message = result.stderr.decode("utf-8", errors="replace").strip()
        raise StartError(f"git {' '.join(args)} failed: {message}")
    return result.stdout.decode("utf-8", errors="replace")


def find_repo_root(path):
    folder = Path(path).resolve()
    if not folder.is_dir():
        raise StartError(f"the folder does not exist: {path}")
    return Path(git(["rev-parse", "--show-toplevel"], folder).strip())


def merge_base(repo, base):
    return git(["merge-base", base, "HEAD"], repo).strip()


def shown_text(kind, line, match):
    text = line.strip()
    if kind == SECRET_KIND:
        # Never print a secret in full; keep enough to find it.
        secret = match.group(0)
        text = text.replace(secret, secret[:4] + "***")
    if len(text) > SHOWN_TEXT_CHARS:
        text = text[:SHOWN_TEXT_CHARS] + "..."
    return text


def check_line(path, number, line):
    findings = []
    for kind, pattern in LINE_CHECKS:
        match = pattern.search(line)
        if match is not None:
            findings.append(Finding(path, number, kind, shown_text(kind, line, match)))
    return findings


def strip_path(raw):
    # git ends the name with a tab when it holds a space.
    path = raw.rstrip("\t")
    if path.startswith('"') and path.endswith('"'):
        path = path[1:-1]
    if path.startswith("b/"):
        path = path[2:]
    return path


def added_lines(diff_text):
    """Yield (path, line number, text) for every line the diff adds."""
    path = None
    number = 0
    # Header lines come between "diff --git" and the first "@@". An added
    # line can start with "++" too, so "+++ " means a file name only here.
    in_header = False
    for line in diff_text.splitlines():
        if line.startswith("diff --git "):
            path = None
            in_header = True
        elif in_header and line.startswith("+++ "):
            # A deleted file's name is /dev/null; it adds no lines anyway.
            path = strip_path(line[4:])
        elif line.startswith("@@"):
            in_header = False
            match = HUNK_PATTERN.match(line)
            if match is not None:
                number = int(match.group(1))
        elif in_header:
            continue
        elif line.startswith("+") and path is not None:
            yield path, number, line[1:]
            number += 1


def bad_file_reason(path):
    pure = PurePosixPath(path)
    name = pure.name
    parts = pure.parts
    if name == ".env":
        return "env file, may hold secrets"
    if name.startswith(".env.") and name not in SAFE_ENV_NAMES:
        return "env file, may hold secrets"
    if name.endswith(KEY_FILE_ENDINGS) or name.startswith(("id_rsa", "id_ed25519")):
        return "key file, may hold secrets"
    if "node_modules" in parts or "__pycache__" in parts:
        return "generated file"
    if name.endswith(".pyc") or name == ".DS_Store":
        return "generated file"
    return None


def check_new_file(repo, path):
    findings = []
    reason = bad_file_reason(path)
    if reason is not None:
        findings.append(Finding(path, None, reason, ""))
    full_path = repo / path
    if full_path.is_file() and not full_path.is_symlink():
        size = full_path.stat().st_size
        if size > LARGE_FILE_BYTES:
            megabytes = size / 1_000_000
            findings.append(Finding(path, None, f"large file ({megabytes:.1f} MB)", ""))
    return findings


def read_text(full_path):
    try:
        return full_path.read_bytes().decode("utf-8")
    except (OSError, UnicodeDecodeError):
        return None


def scan(repo, base):
    start = merge_base(repo, base)
    findings = []

    diff_text = git(
        ["diff", "--no-color", "--no-ext-diff", "-U0", "-M",
         "--src-prefix=a/", "--dst-prefix=b/", start],
        repo,
    )
    for path, number, text in added_lines(diff_text):
        findings.extend(check_line(path, number, text))

    new_tracked = git(["diff", "--name-only", "--diff-filter=A", "-z", start], repo)
    for path in new_tracked.split("\0"):
        if path:
            findings.extend(check_new_file(repo, path))

    untracked = git(["ls-files", "--others", "--exclude-standard", "-z"], repo)
    for path in untracked.split("\0"):
        if not path:
            continue
        findings.extend(check_new_file(repo, path))
        text = read_text(repo / path)
        if text is None:
            continue
        for number, line in enumerate(text.splitlines(), start=1):
            findings.extend(check_line(path, number, line))

    return findings


def parse_args(argv):
    parser = argparse.ArgumentParser(
        description="List things in the PR's diff that a reviewer would flag."
    )
    parser.add_argument(
        "--base",
        required=True,
        help="the branch the PR merges into, like origin/main",
    )
    parser.add_argument("--repo", default=".", help="the human's project folder")
    return parser.parse_args(argv)


def main(argv=None):
    args = parse_args(argv)
    try:
        repo = find_repo_root(args.repo)
        findings = scan(repo, args.base)
    except StartError as error:
        print(f"cannot start: {error}")
        return 2

    for finding in findings:
        print(finding.describe())
    if not findings:
        print("nothing found")
        return 0
    print(f"{len(findings)} thing(s) to look at")
    return 1


if __name__ == "__main__":
    sys.exit(main())
