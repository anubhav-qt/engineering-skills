#!/usr/bin/env python3
"""List the log calls a change adds, and flag the noisy or risky ones.

It reads every line the change adds: changed tracked files, plus new
files git does not ignore. With --base it also counts the commits made
since the branch left that ref. Test files are skipped.

Each added log call is listed with its level. These are flagged:

- print: a bare print or console call in shipped code. Use the logger.
- built-message: the message is built from values (f-string, template
  string, + or % or format). Keep the message constant; put the values
  in fields.
- secret-name: a name like password, token or cookie inside the call.
  Never log it; log an id or a yes/no instead.

A line that really must stay (a field that only holds a token count)
gets the comment marker `logger: keep`. It is still listed, but not
flagged. A command-line tool, whose prints are its real output, gets the
comment `logger: cli` once anywhere in the file; its prints are then
skipped. Comment lines are skipped, and so are words inside message
text: "token refreshed" is a message, not a token.

Only Python, JavaScript, TypeScript and Go files are read; others are
named as not scanned.

Exit codes: 0 nothing flagged, 1 something flagged, 2 could not start.
"""

# logger: cli (its prints are its report)

import argparse
import re
import subprocess
import sys
from pathlib import Path

KEEP_MARKER = "logger: keep"
CLI_MARKER = "logger: cli"

LANGUAGES = {
    ".py": "python",
    ".js": "js",
    ".jsx": "js",
    ".mjs": "js",
    ".cjs": "js",
    ".ts": "js",
    ".tsx": "js",
    ".go": "go",
}

LEVELS = (
    "trace|debug|info|warn|warning|error|exception|critical|fatal"
)

# A logger is a name like log, logger, logging, slog, app_log, appLogger
# or req.log. "catalog.info(" must not count, so the suffix is matched
# only after "_" or as a capitalized "Log" / "Logger".
LOGGER_NAME = (
    r"(?:[A-Za-z_$][\w$]*\.)*"
    r"(?:log|logger|logging|slog|[\w$]*_log|[\w$]*_logger|[\w$]*Log|[\w$]*Logger)"
)
LOG_CALL = re.compile(
    r"(?<![\w$.])" + LOGGER_NAME + r"\.(?P<level>(?i:" + LEVELS + r"))\s*\("
)

PRINT_CALLS = {
    "python": re.compile(r"(?<![\w.])print\s*\("),
    "js": re.compile(r"(?<![\w$.])console\.(?:log|debug|info|warn|error|trace|dir|table)\s*\("),
    "go": re.compile(r"(?<![\w.])(?:fmt\.Print(?:f|ln)?|println|print)\s*\("),
}

BUILT_MESSAGE = {
    "python": [
        re.compile(r"""(?<![\w"'])[rRbB]?[fF][rR]?["']"""),
        re.compile(r"""["']\s*(?:\+|%)\s*[\w(]"""),
        re.compile(r"""[\w)\]]\s*\+\s*["']"""),
        re.compile(r"""["']\s*\.format\s*\("""),
    ],
    "js": [
        re.compile(r"`[^`]*\$\{"),
        re.compile(r"""["'`]\s*\+\s*[\w(]"""),
        re.compile(r"""[\w)\]]\s*\+\s*["'`]"""),
    ],
    "go": [
        re.compile(r"\bfmt\.Sprint(?:f|ln)?\s*\("),
        re.compile(r"""["`]\s*\+\s*[\w(]"""),
        re.compile(r"""[\w)\]]\s*\+\s*["`]"""),
    ],
}

SECRET_WORDS = {
    "password", "passwd", "pwd", "passphrase", "secret", "token",
    "apikey", "authorization", "cookie", "cookies", "cvv", "ssn",
}
SECRET_PAIRS = {
    ("api", "key"), ("session", "id"), ("private", "key"),
    ("card", "number"), ("access", "key"),
}
# "token_count" or "secret_name" says something about a secret, not the
# secret itself.
HARMLESS_NEXT = {
    "count", "counts", "usage", "limit", "limits", "length", "len",
    "total", "type", "expiry", "expires", "expired", "ttl", "name",
    "set", "present", "valid", "used",
}

COMMENT_STARTS = {
    "python": ("#",),
    "js": ("//", "/*", "*"),
    "go": ("//", "/*", "*"),
}

# A string literal on one line, with its prefix (f, r, b ...) if any.
STRING_LITERAL = re.compile(
    r"""(?P<prefix>\b[rRbBfFuU]{1,2})?(?P<quote>["'`])(?P<body>(?:\\.|(?!(?P=quote)).)*)(?P=quote)"""
)
INTERPOLATION = re.compile(r"\{([^{}]*)\}")
# Capital runs first, so "APIKey" splits into "API" and "Key".
WORD_PATTERN = re.compile(r"[A-Z]+(?![a-z])|[A-Z]?[a-z]+")
IDENTIFIER_PATTERN = re.compile(r"[A-Za-z_$][\w$]*")
HUNK_PATTERN = re.compile(r"^@@ -\d+(?:,\d+)? \+(\d+)(?:,\d+)? @@")
# The C escapes git uses in quoted file names.
ESCAPES = {
    b"a": b"\a", b"b": b"\b", b"f": b"\f", b"n": b"\n",
    b"r": b"\r", b"t": b"\t", b"v": b"\v",
}

TEST_FOLDERS = {"test", "tests", "__tests__", "spec", "specs", "testdata"}
TEST_NAME_PATTERNS = [
    re.compile(r"^test_.*\.py$"),
    re.compile(r"^.*_test\.(?:py|go)$"),
    re.compile(r"^conftest\.py$"),
    re.compile(r"^.*\.(?:test|spec)\.[cm]?[jt]sx?$"),
]


class StartError(Exception):
    """The run cannot start; the message says why."""


class LogCall:
    def __init__(self, path, number, level, text):
        self.path = path
        self.number = number
        self.level = level
        self.text = text


class Finding:
    def __init__(self, path, number, kind, advice, text):
        self.path = path
        self.number = number
        self.kind = kind
        self.advice = advice
        self.text = text


# ---------- git ----------

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


def has_head(repo):
    result = subprocess.run(
        ["git", "rev-parse", "--verify", "--quiet", "HEAD"],
        cwd=repo,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    return result.returncode == 0


def diff_base(repo, base):
    """Where the change starts: the fork point from --base, else HEAD,
    else the empty tree when the repo has no commit yet."""
    if base is not None:
        return git(["merge-base", base, "HEAD"], repo).strip()
    if has_head(repo):
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


def changed_lines(repo, base):
    """Yield (path, line number, text) for every line the change adds."""
    diff_text = git(
        ["diff", "--no-color", "--no-ext-diff", "-U0", "--no-renames",
         "--src-prefix=a/", "--dst-prefix=b/", diff_base(repo, base)],
        repo,
    )
    yield from added_lines(diff_text)

    untracked = git(["ls-files", "--others", "--exclude-standard", "-z"], repo)
    for path in untracked.split("\0"):
        if not path:
            continue
        text = read_text(repo / path)
        if text is None:
            continue
        for number, line in enumerate(text.splitlines(), start=1):
            yield path, number, line


# ---------- rules ----------

def language_of(path):
    return LANGUAGES.get(Path(path).suffix.lower())


def is_test_file(path):
    parts = Path(path).parts
    for folder in parts[:-1]:
        if folder.lower() in TEST_FOLDERS:
            return True
    name = parts[-1]
    for pattern in TEST_NAME_PATTERNS:
        if pattern.match(name):
            return True
    return False


def words_of(identifier):
    """Split snake_case, camelCase and kebab-case names into lowercase words."""
    words = []
    for part in re.split(r"[_\-$]+", identifier):
        for word in WORD_PATTERN.findall(part):
            words.append(word.lower())
    return words


def secret_name(text):
    """The first name in the text that looks like it holds a secret."""
    for identifier in IDENTIFIER_PATTERN.findall(text):
        words = words_of(identifier)
        if names_a_secret(words):
            return identifier
    return None


def names_a_secret(words):
    for index, word in enumerate(words):
        following = None
        if index + 1 < len(words):
            following = words[index + 1]
        if following in HARMLESS_NEXT:
            continue
        if word in SECRET_WORDS:
            return True
        if (word, following) in SECRET_PAIRS:
            # The pair "api key" is harmless only if the word after it is.
            after = None
            if index + 2 < len(words):
                after = words[index + 2]
            if after not in HARMLESS_NEXT:
                return True
    return False


def call_arguments(text, match):
    """The rest of the line after the call's opening parenthesis."""
    return text[match.end():]


def code_only(arguments):
    """The arguments with message text taken out of every string, so
    "token refreshed" is not read as a token. Kept: what is inside
    {...} or ${...} (a value goes there), and strings used as keys
    ({"password": ...}), since a key names the value next to it."""
    parts = []
    position = 0
    for match in STRING_LITERAL.finditer(arguments):
        parts.append(arguments[position:match.start()])
        position = match.end()
        rest = arguments[position:]
        if rest.lstrip().startswith(":") and match.group("quote") != "`":
            parts.append(match.group("body"))
            continue
        prefix = match.group("prefix") or ""
        interpolated = "f" in prefix.lower() or match.group("quote") == "`"
        if interpolated:
            for inside in INTERPOLATION.findall(match.group("body")):
                parts.append(" " + inside + " ")
    parts.append(arguments[position:])
    return "".join(parts)


def is_built_message(language, arguments):
    for pattern in BUILT_MESSAGE[language]:
        if pattern.search(arguments):
            return True
    return False


def check_line(path, number, text, language, cli=False):
    """Return (log calls, findings) for one added line. cli: the file is
    a command-line tool, so its prints are its real output."""
    calls = []
    findings = []
    stripped = text.strip()
    kept = KEEP_MARKER in text
    if stripped.startswith(COMMENT_STARTS[language]):
        return calls, findings

    print_match = PRINT_CALLS[language].search(text)
    if print_match is not None and cli:
        return calls, findings
    if print_match is not None:
        calls.append(LogCall(path, number, "print", stripped))
        if not kept:
            findings.append(Finding(
                path, number, "print",
                f"use the project's logger, or mark `{KEEP_MARKER}` if it is real output",
                stripped,
            ))
        arguments = call_arguments(text, print_match)
    else:
        log_match = LOG_CALL.search(text)
        if log_match is None:
            return calls, findings
        calls.append(LogCall(path, number, log_match.group("level").lower(), stripped))
        arguments = call_arguments(text, log_match)
        if not kept and is_built_message(language, arguments):
            findings.append(Finding(
                path, number, "built-message",
                "keep the message constant; put the values in fields",
                stripped,
            ))

    if not kept:
        name = secret_name(code_only(arguments))
        if name is not None:
            findings.append(Finding(
                path, number, "secret-name",
                f"'{name}' looks secret; log an id or a yes/no instead",
                stripped,
            ))
    return calls, findings


def is_cli_file(full_path):
    text = read_text(full_path)
    if text is None:
        return False
    return CLI_MARKER in text


def scan(repo, base):
    calls = []
    findings = []
    not_scanned = set()
    cli_files = {}
    for path, number, text in changed_lines(repo, base):
        language = language_of(path)
        if language is None:
            not_scanned.add(path)
            continue
        if is_test_file(path):
            continue
        if path not in cli_files:
            cli_files[path] = is_cli_file(repo / path)
        line_calls, line_findings = check_line(path, number, text, language, cli_files[path])
        calls.extend(line_calls)
        findings.extend(line_findings)
    return calls, findings, sorted(not_scanned)


# ---------- report ----------

def report(calls, findings, not_scanned):
    if calls:
        print(f"log calls added ({len(calls)}):")
        for call in calls:
            print(f"  {call.path}:{call.number}  {call.level}  {call.text}")
    else:
        print("log calls added: none")

    if not_scanned:
        print(f"not scanned (no rules for these files): {', '.join(not_scanned)}")

    if not findings:
        print("nothing flagged")
        return
    print(f"flagged ({len(findings)}):")
    for finding in findings:
        print(f"  {finding.path}:{finding.number}  {finding.kind}: {finding.advice}")
        print(f"      {finding.text}")


def parse_args(argv):
    parser = argparse.ArgumentParser(
        description="List the log calls a change adds, and flag the noisy or risky ones."
    )
    parser.add_argument("--repo", default=".", help="the human's project folder")
    parser.add_argument(
        "--base",
        help="also count commits since the branch left this ref (for example main)",
    )
    return parser.parse_args(argv)


def main(argv=None):
    args = parse_args(argv)
    try:
        repo = find_repo_root(args.repo)
        calls, findings, not_scanned = scan(repo, args.base)
    except StartError as error:
        print(f"cannot start: {error}")
        return 2

    report(calls, findings, not_scanned)
    if findings:
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
