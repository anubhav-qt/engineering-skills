#!/usr/bin/env python3
"""List temporary debug lines that are still in the code.

While debugging, tag every temporary line (a print, a log, a timer) with
the marker DEBUG-TEMP in a comment on the same line:

    print("total", total)  # DEBUG-TEMP
    console.log(order);  // DEBUG-TEMP

This lists every such line not yet committed: changed tracked files and
new files git does not ignore. Remove them all before you finish.

Exit codes: 0 none left, 1 some left, 2 could not start.
"""

import argparse
import re
import subprocess
import sys
from pathlib import Path

MARKER = "DEBUG-TEMP"
HUNK_PATTERN = re.compile(r"^@@ -\d+(?:,\d+)? \+(\d+)(?:,\d+)? @@")
# The C escapes git uses in quoted file names.
ESCAPES = {
    b"a": b"\a", b"b": b"\b", b"f": b"\f", b"n": b"\n",
    b"r": b"\r", b"t": b"\t", b"v": b"\v",
}


class StartError(Exception):
    """The run cannot start; the message says why."""


def git(args, cwd):
    result = subprocess.run(
        ["git", "-c", "core.quotePath=false", *args],
        cwd=cwd,
        stdin=subprocess.DEVNULL,
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


def diff_base(repo):
    """HEAD, or the empty tree when the repo has no commit yet."""
    result = subprocess.run(
        ["git", "rev-parse", "--verify", "--quiet", "HEAD"],
        cwd=repo,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    if result.returncode == 0:
        return "HEAD"
    return git(["hash-object", "-t", "tree", "/dev/null"], repo).strip()


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


def strip_path(raw):
    # git ends the name with a tab when it holds a space.
    path = unquote(raw.rstrip("\t"))
    if path.startswith("b/"):
        path = path[2:]
    return path


def unquote(name):
    """git puts a name in quotes, with C escapes like \\" and \\t, when it
    holds a quote, a backslash or a control character."""
    quoted = len(name) >= 2 and name.startswith('"') and name.endswith('"')
    if not quoted:
        return name
    raw = name[1:-1].encode("utf-8")
    result = bytearray()
    index = 0
    while index < len(raw):
        byte = raw[index:index + 1]
        if byte != b"\\":
            result += byte
            index += 1
            continue
        code = raw[index + 1:index + 2]
        if code.isdigit():
            # Three octal digits stand for one byte.
            result.append(int(raw[index + 1:index + 4], 8))
            index += 4
        else:
            result += ESCAPES.get(code, code)
            index += 2
    return result.decode("utf-8", errors="replace")


def read_text(full_path):
    try:
        return full_path.read_bytes().decode("utf-8")
    except (OSError, UnicodeDecodeError):
        return None


def find_marked(repo):
    found = []
    diff_text = git(
        ["diff", "--no-color", "--no-ext-diff", "-U0", "--no-renames",
         "--src-prefix=a/", "--dst-prefix=b/", diff_base(repo)],
        repo,
    )
    for path, number, text in added_lines(diff_text):
        if MARKER in text:
            found.append((path, number, text.strip()))

    untracked = git(["ls-files", "--others", "--exclude-standard", "-z"], repo)
    for path in untracked.split("\0"):
        if not path:
            continue
        text = read_text(repo / path)
        if text is None:
            continue
        for number, line in enumerate(text.splitlines(), start=1):
            if MARKER in line:
                found.append((path, number, line.strip()))
    return found


def parse_args(argv):
    parser = argparse.ArgumentParser(
        description=f"List temporary debug lines tagged {MARKER} that are still in the code."
    )
    parser.add_argument("--repo", default=".", help="the human's project folder")
    return parser.parse_args(argv)


def main(argv=None):
    args = parse_args(argv)
    try:
        repo = find_repo_root(args.repo)
        found = find_marked(repo)
    except StartError as error:
        print(f"cannot start: {error}")
        return 2

    if not found:
        print(f"none left: no {MARKER} lines")
        return 0
    for path, number, text in found:
        print(f"{path}:{number}  {text}")
    print(f"{len(found)} {MARKER} line(s) left; remove them")
    return 1


if __name__ == "__main__":
    sys.exit(main())
