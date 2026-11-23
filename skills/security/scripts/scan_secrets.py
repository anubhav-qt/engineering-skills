#!/usr/bin/env python3
"""Find secrets in the repo, its git history, built bundles and served JS.

Where it looks:
- every tracked file and every untracked file git does not ignore;
- every line ever added in git history (a removed secret still counts:
  it must be rotated, not just deleted);
- built client folders like dist/ and .next/static, which git ignores;
- with --url, the page and the scripts the running app sends to browsers.

It never calls a provider to check whether a key works, and it never
prints a secret in full.

Exit codes: 0 nothing found, 1 something to look at, 2 could not start.
"""

import argparse
import base64
import json
import re
import subprocess
import sys
from pathlib import Path, PurePosixPath

import safe_http
from safe_http import FINDING, NOT_CHECKED, NOTE

MAX_FILE_BYTES = 5_000_000
SHOWN_CHARS = 4
BUILD_FOLDERS = ("dist", "build", "out", ".next/static", ".output/public", ".svelte-kit/output/client")
SKIP_PARTS = {".git", "node_modules"}
SAFE_ENV_NAMES = {".env.example", ".env.sample", ".env.template", ".env.dist"}
KEY_FILE_ENDINGS = (".pem", ".key", ".p12", ".pfx")
PLACEHOLDER_WORDS = (
    "example", "changeme", "change_me", "your", "xxxx", "placeholder", "dummy",
    "redacted", "<", "${", "{{", "process.env", "os.environ", "getenv",
)

# (level, kind, pattern). The whole match is the secret.
KEY_RULES = [
    (FINDING, "AWS access key", re.compile(r"\b(?:AKIA|ASIA)[0-9A-Z]{16}\b")),
    (FINDING, "private key", re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----")),
    (FINDING, "GitHub token", re.compile(r"\bgh[pousr]_[A-Za-z0-9]{36,}|\bgithub_pat_[A-Za-z0-9_]{20,}")),
    (FINDING, "sk- API key (OpenAI, Anthropic or similar)", re.compile(r"\bsk-[A-Za-z0-9_-]{20,}")),
    (FINDING, "Stripe secret key", re.compile(r"\b[sr]k_live_[A-Za-z0-9]{16,}")),
    (FINDING, "Slack token", re.compile(r"\bxox[abprs]-[A-Za-z0-9-]{10,}")),
    (FINDING, "SendGrid key", re.compile(r"\bSG\.[A-Za-z0-9_-]{22}\.[A-Za-z0-9_-]{43}")),
    (
        NOTE,
        "Google API key (public if it is a Firebase web key; check its limits)",
        re.compile(r"\bAIza[0-9A-Za-z_-]{35}"),
    ),
]
JWT_PATTERN = re.compile(r"\beyJ[A-Za-z0-9_-]{10,}\.eyJ[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}")
KEYWORD_PATTERN = re.compile(
    r"(?i)\b([a-z0-9_]*(?:api[_-]?key|secret|passw(?:or)?d|token|private[_-]?key)[a-z0-9_]*)"
    r"[\"']?\s*[:=]\s*[\"']([^\"'\s]{8,})[\"']"
)
PUBLIC_ENV_PATTERN = re.compile(
    r"\b(?:NEXT_PUBLIC_|VITE_|REACT_APP_|EXPO_PUBLIC_)[A-Z0-9_]*(?:SECRET|PRIVATE|SERVICE_ROLE|PASSWORD)[A-Z0-9_]*"
)


class Finding:
    def __init__(self, level, place, kind, shown, secret):
        self.level = level
        self.place = place
        self.kind = kind
        self.shown = shown
        self.secret = secret

    def describe(self):
        if self.shown:
            return f"{self.level:<11}  {self.place}  {self.kind}: {self.shown}"
        return f"{self.level:<11}  {self.place}  {self.kind}"


def hide(secret):
    return secret[:SHOWN_CHARS] + "***"


def is_placeholder(value):
    lowered = value.lower()
    for word in PLACEHOLDER_WORDS:
        if word in lowered:
            return True
    # One repeated character, like "xxxxxxxx" or "********".
    return len(set(value)) <= 2


def jwt_role(token):
    payload = token.split(".")[1]
    padded = payload + "=" * (-len(payload) % 4)
    try:
        claims = json.loads(base64.urlsafe_b64decode(padded))
    except (ValueError, UnicodeDecodeError):
        return None
    if not isinstance(claims, dict):
        return None
    return claims.get("role")


def check_line(place, line):
    findings = []
    for level, kind, pattern in KEY_RULES:
        for match in pattern.finditer(line):
            secret = match.group(0)
            findings.append(Finding(level, place, kind, hide(secret), secret))

    for match in JWT_PATTERN.finditer(line):
        token = match.group(0)
        if jwt_role(token) == "service_role":
            kind = "Supabase service_role key (full database access, never public)"
            findings.append(Finding(FINDING, place, kind, hide(token), token))

    for match in KEYWORD_PATTERN.finditer(line):
        name, value = match.group(1), match.group(2)
        if is_placeholder(value):
            continue
        already_found = False
        for finding in findings:
            if value in finding.secret or finding.secret in value:
                already_found = True
        if not already_found:
            findings.append(Finding(FINDING, place, f"secret-looking value in {name}", hide(value), value))

    for match in PUBLIC_ENV_PATTERN.finditer(line):
        name = match.group(0)
        kind = "secret-named env var goes to the browser (public prefix)"
        findings.append(Finding(FINDING, place, kind, name, name))
    return findings


def check_text(place, text):
    findings = []
    for number, line in enumerate(text.splitlines(), start=1):
        findings.extend(check_line(f"{place}:{number}", line))
    return findings


def git(args, repo):
    result = subprocess.run(
        ["git", "-c", "core.quotePath=false", *args],
        cwd=repo,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    if result.returncode != 0:
        message = result.stderr.decode("utf-8", errors="replace").strip()
        raise safe_http.StartError(f"git {' '.join(args)} failed: {message}")
    return result.stdout.decode("utf-8", errors="replace")


def read_text(path):
    try:
        if path.stat().st_size > MAX_FILE_BYTES:
            return None
        data = path.read_bytes()
    except OSError:
        return None
    if b"\0" in data:
        return None
    return data.decode("utf-8", errors="replace")


def file_reason(path):
    name = PurePosixPath(path).name
    if name == ".env":
        return "env file"
    if name.startswith(".env.") and name not in SAFE_ENV_NAMES:
        return "env file"
    if name.endswith(KEY_FILE_ENDINGS) or name.startswith(("id_rsa", "id_ed25519")):
        return "key file"
    return None


def scan_tree(repo):
    findings = []
    tracked = git(["ls-files", "-z"], repo).split("\0")
    untracked = git(["ls-files", "-z", "--others", "--exclude-standard"], repo).split("\0")
    for path in tracked:
        if not path:
            continue
        reason = file_reason(path)
        if reason is not None:
            findings.append(Finding(FINDING, path, f"{reason} committed to git", "", path))
        findings.extend(scan_file(repo, path))
    for path in untracked:
        if not path:
            continue
        reason = file_reason(path)
        if reason is not None:
            findings.append(Finding(NOTE, path, f"{reason} not in .gitignore", "", path))
        findings.extend(scan_file(repo, path))
    return findings


def scan_file(repo, path):
    full = repo / path
    if full.is_symlink() or not full.is_file():
        return []
    text = read_text(full)
    if text is None:
        return []
    return check_text(path, text)


def scan_build_folders(repo):
    findings = []
    for folder in BUILD_FOLDERS:
        root = repo / folder
        if not root.is_dir():
            continue
        for full in sorted(root.rglob("*")):
            if full.is_symlink() or not full.is_file():
                continue
            if SKIP_PARTS.intersection(full.relative_to(repo).parts):
                continue
            text = read_text(full)
            if text is not None:
                findings.extend(check_text(str(full.relative_to(repo)), text))
    return findings


def history_lines(repo):
    """Yield (commit, path, line) for every line ever added, oldest last."""
    command = [
        "git", "-c", "core.quotePath=false", "log", "-p", "--all", "--no-color",
        "--no-ext-diff", "-U0", "--format=commit %H",
    ]
    process = subprocess.Popen(command, cwd=repo, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL)
    commit = ""
    path = ""
    try:
        for raw in process.stdout:
            line = raw.decode("utf-8", errors="replace").rstrip("\n")
            if line.startswith("commit "):
                commit = line[len("commit "):][:10]
            elif line.startswith("+++ "):
                path = line[len("+++ "):]
                if path.startswith("b/"):
                    path = path[2:]
            elif line.startswith("+"):
                yield commit, path, line[1:]
    finally:
        process.stdout.close()
        process.wait()


def scan_history(repo, known_secrets):
    findings = []
    seen = set(known_secrets)
    for commit, path, line in history_lines(repo):
        for finding in check_line(f"{path} (commit {commit})", line):
            if finding.secret in seen:
                continue
            seen.add(finding.secret)
            finding.kind = finding.kind + ", in git history (rotate it even if removed)"
            findings.append(finding)
    return findings


def scan_url(client, url):
    findings = []
    try:
        page = client.send(safe_http.Request("GET", url))
    except (safe_http.Refused, safe_http.RequestFailed) as error:
        return [Finding(NOT_CHECKED, url, str(error), "", "")]
    findings.extend(check_text(url, page.text()))
    for script_url in safe_http.script_urls(page.text(), url):
        try:
            script = client.send(safe_http.Request("GET", script_url))
        except (safe_http.Refused, safe_http.RequestFailed) as error:
            findings.append(Finding(NOT_CHECKED, script_url, str(error), "", ""))
            continue
        if script.status == 200:
            findings.extend(check_text(script_url, script.text()))
    return findings


def parse_args(argv):
    parser = argparse.ArgumentParser(description="Find secrets in the repo, history, bundles and served JS.")
    parser.add_argument("--repo", default=".", help="the project folder")
    parser.add_argument("--url", action="append", default=[], help="a page of the running app to scan")
    parser.add_argument("--no-history", action="store_true", help="skip git history")
    safe_http.add_target_args(parser, writes=False)
    return parser.parse_args(argv)


def run(args):
    repo = Path(args.repo).resolve()
    if not repo.is_dir():
        raise safe_http.StartError(f"the folder does not exist: {args.repo}")
    repo = Path(git(["rev-parse", "--show-toplevel"], repo).strip())

    findings = scan_tree(repo)
    findings.extend(scan_build_folders(repo))
    if not args.no_history:
        known = [finding.secret for finding in findings]
        findings.extend(scan_history(repo, known))
    client = safe_http.client_from_args(args)
    for url in args.url:
        findings.extend(scan_url(client, url))
    return without_repeats(findings)


def without_repeats(findings):
    # A build folder that git tracks is scanned twice; show each once.
    seen = set()
    unique = []
    for finding in findings:
        key = (finding.place, finding.kind, finding.secret)
        if key in seen:
            continue
        seen.add(key)
        unique.append(finding)
    return unique


def main(argv=None):
    args = parse_args(argv)
    try:
        findings = run(args)
    except safe_http.StartError as error:
        print(f"cannot start: {error}")
        return 2

    counts = {FINDING: 0, NOTE: 0, NOT_CHECKED: 0}
    for finding in findings:
        counts[finding.level] += 1
        print(finding.describe())
    print(f"{counts[FINDING]} finding(s), {counts[NOTE]} note(s), {counts[NOT_CHECKED]} not checked")
    if counts[FINDING] or counts[NOTE]:
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
