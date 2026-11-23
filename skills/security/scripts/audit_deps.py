#!/usr/bin/env python3
"""List known vulnerabilities in the project's locked dependencies.

It reads the lockfiles with the standard library only and asks the OSV
database (api.osv.dev) about each package. Only package names, versions
and ecosystems are sent; the output says so. Run the project's own audit
tool too when it is installed (npm audit, pip-audit, osv-scanner).

Read: package-lock.json, npm-shrinkwrap.json, yarn.lock, pnpm-lock.yaml,
requirements*.txt (pinned lines), Pipfile.lock, poetry.lock, uv.lock,
Cargo.lock, Gemfile.lock.

Exit codes: 0 nothing found, 1 something to look at, 2 could not start.
"""

import argparse
import json
import os
import re
import sys
import urllib.error
import urllib.request
from pathlib import Path

FINDING = "FINDING"
NOTE = "NOTE"
NOT_CHECKED = "NOT CHECKED"

OSV_BATCH_URL = "https://api.osv.dev/v1/querybatch"
OSV_VULN_URL = "https://api.osv.dev/v1/vulns/"
BATCH_SIZE = 1000
MAX_DETAILS = 200
TIMEOUT_SECONDS = 30
MAX_DEPTH = 3
SKIP_FOLDERS = {"node_modules", ".git", ".venv", "venv", "dist", "build", "target", "vendor", ".next"}

NPM = "npm"
PYPI = "PyPI"
CRATES = "crates.io"
GEMS = "RubyGems"


class StartError(Exception):
    """The run cannot start; the message says why."""


class Package:
    def __init__(self, ecosystem, name, version, dev, source):
        self.ecosystem = ecosystem
        self.name = name
        self.version = version
        self.dev = dev
        self.source = source

    def key(self):
        return (self.ecosystem, self.name, self.version)


# Lockfile readers. Each takes the file's text and returns
# (ecosystem, name, version, dev) tuples; dev is None when unknown.


def read_package_lock(text):
    data = json.loads(text)
    rows = []
    packages = data.get("packages")
    if isinstance(packages, dict):
        for path, info in packages.items():
            if not path or info.get("link") or "version" not in info:
                continue
            name = path.rsplit("node_modules/", 1)[-1]
            dev = bool(info.get("dev") or info.get("devOptional"))
            rows.append((NPM, name, info["version"], dev))
        return rows
    read_npm_v1(data.get("dependencies") or {}, rows)
    return rows


def read_npm_v1(dependencies, rows):
    for name, info in dependencies.items():
        if "version" in info:
            rows.append((NPM, name, info["version"], bool(info.get("dev"))))
        read_npm_v1(info.get("dependencies") or {}, rows)


YARN_VERSION = re.compile(r"^\s+version:?\s+\"?([^\"\s]+)\"?\s*$")


def yarn_name(header):
    first = header.rstrip(":").split(",")[0].strip().strip('"')
    at = first.rfind("@")
    if at <= 0:
        return None
    return first[:at]


def read_yarn_lock(text):
    rows = []
    name = None
    for line in text.splitlines():
        if line and not line.startswith((" ", "#")) and line.endswith(":"):
            name = yarn_name(line)
            if name == "__metadata" or "@workspace:" in line:
                name = None
            continue
        match = YARN_VERSION.match(line)
        if match is not None and name is not None:
            rows.append((NPM, name, match.group(1), None))
            name = None
    return rows


PNPM_KEY = re.compile(r"^  ['\"]?(/?[^'\"\s]+?)['\"]?:\s*$")


def pnpm_name_version(key):
    key = key.lstrip("/")
    key = key.split("(", 1)[0]
    if "@" in key[1:]:
        at = key.rfind("@")
        name, version = key[:at], key[at + 1:]
    elif "/" in key:
        name, version = key.rsplit("/", 1)
    else:
        return None
    version = version.split("_", 1)[0]
    if not name or not version or not version[0].isdigit():
        return None
    return name, version


def read_pnpm_lock(text):
    rows = []
    in_packages = False
    for line in text.splitlines():
        if not line.startswith(" ") and line.strip():
            in_packages = line.rstrip() == "packages:"
            continue
        if not in_packages:
            continue
        match = PNPM_KEY.match(line)
        if match is None:
            continue
        found = pnpm_name_version(match.group(1))
        if found is not None:
            rows.append((NPM, found[0], found[1], None))
    return rows


REQUIREMENT = re.compile(r"^([A-Za-z0-9][A-Za-z0-9._-]*)(\[[^\]]*\])?\s*==\s*([^\s;#,]+)")


def read_requirements(text):
    rows = []
    for line in text.splitlines():
        match = REQUIREMENT.match(line.strip())
        if match is not None:
            rows.append((PYPI, match.group(1).lower(), match.group(3), None))
    return rows


def read_pipfile_lock(text):
    data = json.loads(text)
    rows = []
    for section, dev in (("default", False), ("develop", True)):
        for name, info in (data.get(section) or {}).items():
            version = str(info.get("version", ""))
            if version.startswith("=="):
                rows.append((PYPI, name.lower(), version[2:], dev))
    return rows


TOML_FIELD = re.compile(r"^(name|version)\s*=\s*\"([^\"]+)\"")


def read_toml_packages(text, ecosystem):
    """poetry.lock, uv.lock and Cargo.lock: [[package]] blocks with name and version."""
    rows = []
    fields = None
    for line in text.splitlines() + ["[[package]]"]:
        if line.strip() == "[[package]]" or line.startswith("["):
            if fields and "name" in fields and "version" in fields:
                rows.append((ecosystem, fields["name"], fields["version"], None))
            fields = {} if line.strip() == "[[package]]" else None
            continue
        if fields is None:
            continue
        match = TOML_FIELD.match(line)
        if match is not None and match.group(1) not in fields:
            fields[match.group(1)] = match.group(2)
    return rows


def read_python_lock(text):
    return read_toml_packages(text, PYPI)


def read_cargo_lock(text):
    return read_toml_packages(text, CRATES)


GEM_SPEC = re.compile(r"^    ([A-Za-z0-9_.-]+) \(([^)\s]+)\)$")


def read_gemfile_lock(text):
    rows = []
    for line in text.splitlines():
        match = GEM_SPEC.match(line)
        if match is not None:
            version = match.group(2).split("-", 1)[0]
            rows.append((GEMS, match.group(1), version, None))
    return rows


def reader_for(name):
    if name in ("package-lock.json", "npm-shrinkwrap.json"):
        return read_package_lock
    if name == "yarn.lock":
        return read_yarn_lock
    if name == "pnpm-lock.yaml":
        return read_pnpm_lock
    if name.startswith("requirements") and name.endswith(".txt"):
        return read_requirements
    if name == "Pipfile.lock":
        return read_pipfile_lock
    if name in ("poetry.lock", "uv.lock"):
        return read_python_lock
    if name == "Cargo.lock":
        return read_cargo_lock
    if name == "Gemfile.lock":
        return read_gemfile_lock
    return None


def find_lockfiles(root):
    found = []
    for folder, subfolders, files in os.walk(root):
        depth = len(Path(folder).relative_to(root).parts)
        subfolders[:] = sorted(
            name for name in subfolders if name not in SKIP_FOLDERS and depth < MAX_DEPTH
        )
        for name in sorted(files):
            if reader_for(name) is not None:
                found.append(Path(folder) / name)
    return found


def read_packages(root, lockfiles):
    packages = {}
    problems = []
    for path in lockfiles:
        relative = str(path.relative_to(root))
        try:
            rows = reader_for(path.name)(path.read_text(encoding="utf-8"))
        except (OSError, ValueError, UnicodeDecodeError) as error:
            problems.append(f"{relative}: could not read it ({error})")
            continue
        if not rows:
            problems.append(f"{relative}: no pinned packages found in it")
        for ecosystem, name, version, dev in rows:
            package = Package(ecosystem, name, version, dev, relative)
            if package.key() not in packages:
                packages[package.key()] = package
    return list(packages.values()), problems


# OSV. Tests replace these two functions.


def osv_post(url, payload):
    data = json.dumps(payload).encode("utf-8")
    request = urllib.request.Request(url, data=data, headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(request, timeout=TIMEOUT_SECONDS) as answer:
        return json.loads(answer.read())


def osv_get(url):
    with urllib.request.urlopen(url, timeout=TIMEOUT_SECONDS) as answer:
        return json.loads(answer.read())


def query_ids(packages):
    """Return a list of vuln id lists, one per package, in the same order."""
    results = []
    for start in range(0, len(packages), BATCH_SIZE):
        chunk = packages[start:start + BATCH_SIZE]
        queries = []
        for package in chunk:
            queries.append({
                "package": {"name": package.name, "ecosystem": package.ecosystem},
                "version": package.version,
            })
        answer = osv_post(OSV_BATCH_URL, {"queries": queries})
        for result in answer.get("results", []):
            ids = []
            for vuln in result.get("vulns") or []:
                ids.append(vuln["id"])
            results.append(ids)
    return results


def severity_of(details):
    specific = details.get("database_specific") or {}
    severity = specific.get("severity")
    if isinstance(severity, str) and severity:
        return severity.lower()
    return "severity not given"


def fixed_versions(details, package):
    fixed = []
    for affected in details.get("affected") or []:
        info = affected.get("package") or {}
        if info.get("name", "").lower() != package.name.lower():
            continue
        for version_range in affected.get("ranges") or []:
            for event in version_range.get("events") or []:
                if "fixed" in event and event["fixed"] not in fixed:
                    fixed.append(event["fixed"])
    return fixed


def describe(package, vuln_id, details):
    aliases = [alias for alias in details.get("aliases") or [] if alias.startswith("CVE-")]
    name = vuln_id
    if aliases:
        name = f"{vuln_id} ({aliases[0]})"
    summary = details.get("summary") or "no summary"
    fixed = fixed_versions(details, package)
    if fixed:
        fix = "fixed in " + ", ".join(fixed)
    else:
        fix = "no fixed version yet"
    where = f"{package.ecosystem} {package.name} {package.version} ({package.source})"
    dev = ""
    if package.dev:
        dev = ", dev only"
    return f"{where}  {name} {severity_of(details)}{dev}: {summary}. {fix}"


def audit(packages):
    """Return (level, text) lines for every known vulnerability."""
    results = []
    details_cache = {}
    for package, ids in zip(packages, query_ids(packages)):
        for vuln_id in ids:
            if vuln_id not in details_cache:
                if len(details_cache) >= MAX_DETAILS:
                    results.append((NOT_CHECKED, f"{package.name}: {vuln_id} (detail cap reached)"))
                    continue
                details_cache[vuln_id] = osv_get(OSV_VULN_URL + vuln_id)
            level = FINDING
            if package.dev:
                level = NOTE
            results.append((level, describe(package, vuln_id, details_cache[vuln_id])))
    return results


def parse_args(argv):
    parser = argparse.ArgumentParser(description="List known vulnerabilities in locked dependencies.")
    parser.add_argument("--repo", default=".", help="the project folder")
    return parser.parse_args(argv)


def main(argv=None):
    args = parse_args(argv)
    root = Path(args.repo).resolve()
    if not root.is_dir():
        print(f"cannot start: the folder does not exist: {args.repo}")
        return 2
    lockfiles = find_lockfiles(root)
    if not lockfiles:
        print("NOT CHECKED  no lockfile found; dependencies are not pinned or use a format not read here")
        return 2

    packages, problems = read_packages(root, lockfiles)
    for problem in problems:
        print(f"{NOT_CHECKED:<11}  {problem}")
    if not packages:
        return 2

    print(f"Asked api.osv.dev about {len(packages)} packages (names and versions only).")
    try:
        results = audit(packages)
    except (urllib.error.URLError, OSError, ValueError, KeyError) as error:
        print(f"cannot start: the OSV lookup failed ({error})")
        return 2

    counts = {FINDING: 0, NOTE: 0, NOT_CHECKED: 0}
    for level, text in results:
        counts[level] += 1
        print(f"{level:<11}  {text}")
    print(f"{counts[FINDING]} finding(s), {counts[NOTE]} note(s), {counts[NOT_CHECKED]} not checked")
    if counts[FINDING] or counts[NOTE]:
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
