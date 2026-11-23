"""Tests for skills/security/scripts/audit_deps.py.

Run from the repo root: python3 -m unittest discover tests
"""

import json
import sys
import tempfile
import unittest
import urllib.error
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent))
from security_app import load, run_main

audit_deps = load("audit_deps")

PACKAGE_LOCK_V3 = {
    "name": "shop",
    "lockfileVersion": 3,
    "packages": {
        "": {"name": "shop", "version": "1.0.0"},
        "node_modules/lodash": {"version": "4.17.20"},
        "node_modules/jest": {"version": "29.0.0", "dev": True},
        "node_modules/a/node_modules/@scope/b": {"version": "2.0.0", "devOptional": True},
        "node_modules/local-pkg": {"link": True, "resolved": "../local"},
    },
}

PACKAGE_LOCK_V1 = {
    "lockfileVersion": 1,
    "dependencies": {
        "express": {"version": "4.17.1", "dependencies": {"qs": {"version": "6.7.0"}}},
        "mocha": {"version": "8.0.0", "dev": True},
    },
}

YARN_V1 = '''# yarn lockfile v1

"@babel/core@^7.0.0", "@babel/core@^7.1.0":
  version "7.22.5"
  resolved "https://registry.yarnpkg.com/@babel/core/-/core-7.22.5.tgz"

lodash@^4.17.0:
  version "4.17.20"
'''

YARN_BERRY = '''__metadata:
  version: 6

"lodash@npm:^4.17.0":
  version: 4.17.21
  resolution: "lodash@npm:4.17.21"

"shop@workspace:.":
  version: 0.0.0-use.local
'''

PNPM_V9 = '''lockfileVersion: '9.0'

importers:
  .:
    dependencies:
      lodash:
        specifier: ^4.17.0
        version: 4.17.20

packages:

  lodash@4.17.20:
    resolution: {integrity: sha512-x}

  '@types/node@20.1.0':
    resolution: {integrity: sha512-y}

  react-dom@18.2.0(react@18.2.0):
    resolution: {integrity: sha512-z}
'''

PNPM_V5 = '''lockfileVersion: 5.4

packages:

  /lodash/4.17.20:
    resolution: {integrity: sha512-x}
    dev: false

  /@types/node/20.1.0_peer:
    resolution: {integrity: sha512-y}
'''

REQUIREMENTS = '''# app
Django==3.2.0
requests[socks] == 2.25.0 ; python_version >= "3.6"
flask>=2.0
-r other.txt
'''

POETRY_LOCK = '''[[package]]
name = "django"
version = "3.2.0"
description = "web"

[package.dependencies]
sqlparse = ">=0.2.2"

[[package]]
name = "sqlparse"
version = "0.4.1"

[metadata]
lock-version = "2.0"
'''

GEMFILE_LOCK = '''GEM
  remote: https://rubygems.org/
  specs:
    rack (2.2.3)
    nokogiri (1.13.0-x86_64-linux)
      racc (~> 1.4)

PLATFORMS
  ruby
'''


def rows(reader, text):
    return sorted(reader(text))


class ReaderTest(unittest.TestCase):
    def test_package_lock_v3(self):
        found = rows(audit_deps.read_package_lock, json.dumps(PACKAGE_LOCK_V3))
        self.assertEqual(found, [
            ("npm", "@scope/b", "2.0.0", True),
            ("npm", "jest", "29.0.0", True),
            ("npm", "lodash", "4.17.20", False),
        ])

    def test_package_lock_v1(self):
        found = rows(audit_deps.read_package_lock, json.dumps(PACKAGE_LOCK_V1))
        self.assertEqual(found, [
            ("npm", "express", "4.17.1", False),
            ("npm", "mocha", "8.0.0", True),
            ("npm", "qs", "6.7.0", False),
        ])

    def test_yarn_classic_and_berry(self):
        self.assertEqual(rows(audit_deps.read_yarn_lock, YARN_V1), [
            ("npm", "@babel/core", "7.22.5", None),
            ("npm", "lodash", "4.17.20", None),
        ])
        self.assertEqual(rows(audit_deps.read_yarn_lock, YARN_BERRY), [("npm", "lodash", "4.17.21", None)])

    def test_pnpm_new_and_old(self):
        self.assertEqual(rows(audit_deps.read_pnpm_lock, PNPM_V9), [
            ("npm", "@types/node", "20.1.0", None),
            ("npm", "lodash", "4.17.20", None),
            ("npm", "react-dom", "18.2.0", None),
        ])
        self.assertEqual(rows(audit_deps.read_pnpm_lock, PNPM_V5), [
            ("npm", "@types/node", "20.1.0", None),
            ("npm", "lodash", "4.17.20", None),
        ])

    def test_requirements_pins_only(self):
        self.assertEqual(rows(audit_deps.read_requirements, REQUIREMENTS), [
            ("PyPI", "django", "3.2.0", None),
            ("PyPI", "requests", "2.25.0", None),
        ])

    def test_pipfile_lock(self):
        data = {"default": {"Django": {"version": "==3.2.0"}}, "develop": {"pytest": {"version": "==7.0.0"}}}
        self.assertEqual(rows(audit_deps.read_pipfile_lock, json.dumps(data)), [
            ("PyPI", "django", "3.2.0", False),
            ("PyPI", "pytest", "7.0.0", True),
        ])

    def test_toml_locks(self):
        self.assertEqual(rows(audit_deps.read_python_lock, POETRY_LOCK), [
            ("PyPI", "django", "3.2.0", None),
            ("PyPI", "sqlparse", "0.4.1", None),
        ])
        cargo = '[[package]]\nname = "serde"\nversion = "1.0.0"\ndependencies = [\n "x",\n]\n'
        self.assertEqual(rows(audit_deps.read_cargo_lock, cargo), [("crates.io", "serde", "1.0.0", None)])

    def test_gemfile_lock(self):
        self.assertEqual(rows(audit_deps.read_gemfile_lock, GEMFILE_LOCK), [
            ("RubyGems", "nokogiri", "1.13.0", None),
            ("RubyGems", "rack", "2.2.3", None),
        ])


LODASH_VULN = {
    "id": "GHSA-35jh-r3h4-6jhm",
    "summary": "Command Injection in lodash",
    "aliases": ["CVE-2021-23337"],
    "database_specific": {"severity": "HIGH"},
    "affected": [{
        "package": {"name": "lodash", "ecosystem": "npm"},
        "ranges": [{"type": "SEMVER", "events": [{"introduced": "0"}, {"fixed": "4.17.21"}]}],
    }],
}


def fake_post(url, payload):
    results = []
    for query in payload["queries"]:
        if query["package"]["name"] in ("lodash", "jest"):
            results.append({"vulns": [{"id": "GHSA-35jh-r3h4-6jhm"}]})
        else:
            results.append({})
    return {"results": results}


class MainTest(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.root = Path(temp.name)

    def run_audit(self, post=fake_post, get=None):
        if get is None:
            get = mock.Mock(return_value=LODASH_VULN)
        with mock.patch.object(audit_deps, "osv_post", side_effect=post):
            with mock.patch.object(audit_deps, "osv_get", get):
                return run_main(audit_deps, ["--repo", str(self.root)])

    def test_vulnerable_package_is_a_finding_and_dev_is_a_note(self):
        (self.root / "package-lock.json").write_text(json.dumps(PACKAGE_LOCK_V3))
        get = mock.Mock(return_value=LODASH_VULN)
        code, output = self.run_audit(get=get)
        self.assertEqual(code, 1)
        self.assertIn("Asked api.osv.dev about 3 packages (names and versions only).", output)
        self.assertIn(
            "FINDING      npm lodash 4.17.20 (package-lock.json)  GHSA-35jh-r3h4-6jhm (CVE-2021-23337) high: "
            "Command Injection in lodash. fixed in 4.17.21",
            output,
        )
        self.assertIn("NOTE         npm jest 29.0.0", output)
        self.assertIn(", dev only", output)
        # Details are fetched once per vulnerability, not once per package.
        self.assertEqual(get.call_count, 1)

    def test_no_vulnerabilities_exits_0(self):
        (self.root / "requirements.txt").write_text("django==4.2.0\n")
        code, output = self.run_audit()
        self.assertEqual(code, 0, output)

    def test_lockfiles_in_skipped_folders_are_ignored(self):
        nested = self.root / "node_modules" / "x"
        nested.mkdir(parents=True)
        (nested / "package-lock.json").write_text(json.dumps(PACKAGE_LOCK_V3))
        app = self.root / "web"
        app.mkdir()
        (app / "requirements-dev.txt").write_text("django==4.2.0\n")
        found = audit_deps.find_lockfiles(self.root)
        self.assertEqual(found, [app / "requirements-dev.txt"])

    def test_no_lockfile_cannot_start(self):
        code, output = self.run_audit()
        self.assertEqual(code, 2)
        self.assertIn("no lockfile found", output)

    def test_unreadable_lockfile_is_not_checked(self):
        (self.root / "package-lock.json").write_text("{not json")
        (self.root / "requirements.txt").write_text("django==4.2.0\n")
        code, output = self.run_audit()
        self.assertIn("NOT CHECKED  package-lock.json: could not read it", output)

    def test_osv_failure_cannot_start(self):
        (self.root / "requirements.txt").write_text("django==4.2.0\n")
        failing = mock.Mock(side_effect=urllib.error.URLError("offline"))
        code, output = self.run_audit(post=failing)
        self.assertEqual(code, 2)
        self.assertIn("the OSV lookup failed", output)


if __name__ == "__main__":
    unittest.main()
