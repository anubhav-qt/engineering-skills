#!/usr/bin/env python3
"""Lay out the files a project needs after kickoff.

It never overwrites a file. It prints one line per path it looked at:
created, updated (text added to the end), kept, or skipped.
"""

import argparse
import re
import subprocess
import sys
from pathlib import Path

SKILL_DIR = Path(__file__).resolve().parent.parent
ASSETS = SKILL_DIR / "assets"

IMPORT_LINE = "@AGENTS.md"
MERGE_HEADER = "Rules to merge into AGENTS.md:"
PLACEHOLDER = re.compile(r"\{\{(\w+)\}\}")


class Report:
    """Collects what happened to each path, in order."""

    def __init__(self):
        self.lines = []

    def add(self, status, path):
        self.lines.append(f"{status:<8} {path}")

    def text(self):
        return "\n".join(self.lines)


def read_asset(relative_path):
    return (ASSETS / relative_path).read_text(encoding="utf-8")


def render(template, values):
    """Fill {{key}} slots in one pass, so a value is never filled twice."""

    def fill(match):
        key = match.group(1)
        return values[key]

    return PLACEHOLDER.sub(fill, template)


def is_broken_link(path):
    return path.is_symlink() and not path.exists()


def write_if_missing(path, text, label, report):
    if is_broken_link(path):
        report.add("skipped", f"{label} (broken link)")
        return
    if path.exists():
        report.add("kept", label)
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    report.add("created", label)


def read_text_or_none(path):
    """Return the file's text, or None when it is not UTF-8 text."""
    try:
        return path.read_text(encoding="utf-8")
    except UnicodeDecodeError:
        return None


def append_text(path, old_text, text):
    if old_text and not old_text.endswith("\n"):
        text = "\n" + text
    with path.open("a", encoding="utf-8") as file:
        file.write(text)


def ensure_git(target, report):
    try:
        check = subprocess.run(
            ["git", "rev-parse", "--is-inside-work-tree"],
            cwd=target,
            capture_output=True,
            text=True,
        )
    except FileNotFoundError:
        report.add("skipped", "git repo (git is not installed)")
        return
    if check.returncode == 0:
        report.add("kept", "git repo")
        return
    subprocess.run(["git", "init", "-q"], cwd=target, check=True)
    report.add("created", "git repo")


def build_rules(args):
    values = {
        "reply_cap": args.reply_cap,
        "components_dir": args.components_dir,
    }
    parts = [read_asset("rules/core.md")]
    if args.components_dir:
        parts.append(read_asset("rules/ui.md"))
    if args.agents:
        parts.append(read_asset("rules/agents.md"))
    return render("".join(parts), values)


def ensure_agents_md(target, args, report):
    """Create AGENTS.md, or leave an existing one alone.

    An existing AGENTS.md is never edited here, because merging rules needs
    the human's choices. Returns the rules the agent must merge by hand,
    or None when there is nothing to merge.
    """
    path = target / "AGENTS.md"
    rules = build_rules(args)
    if is_broken_link(path):
        report.add("skipped", "AGENTS.md (broken link)")
        return None
    if not path.exists():
        values = {"name": args.name, "summary": args.summary}
        head = render(read_asset("agents-head.md"), values)
        path.write_text(head + rules, encoding="utf-8")
        report.add("created", "AGENTS.md")
        return None
    old_text = read_text_or_none(path)
    if old_text is None:
        report.add("skipped", "AGENTS.md (not UTF-8 text)")
        return None
    if rules in old_text:
        report.add("kept", "AGENTS.md (our rules are already in it)")
        return None
    report.add("kept", "AGENTS.md (merge the rules printed below)")
    return rules


def has_import_line(text):
    for line in text.splitlines():
        if line.strip() == IMPORT_LINE:
            return True
    return False


def ensure_claude_md(target, report):
    path = target / "CLAUDE.md"
    agents_path = target / "AGENTS.md"
    if is_broken_link(path):
        report.add("skipped", "CLAUDE.md (broken link)")
        return
    if not path.exists():
        path.write_text(IMPORT_LINE + "\n", encoding="utf-8")
        report.add("created", "CLAUDE.md")
        return
    if agents_path.exists() and path.samefile(agents_path):
        report.add("kept", "CLAUDE.md (it is a link to AGENTS.md)")
        return
    old_text = read_text_or_none(path)
    if old_text is None:
        report.add("skipped", "CLAUDE.md (not UTF-8 text)")
        return
    if has_import_line(old_text):
        report.add("kept", "CLAUDE.md")
        return
    append_text(path, old_text, "\n" + IMPORT_LINE + "\n")
    report.add("updated", "CLAUDE.md (import line added)")


def ensure_folder(target, relative_path, report):
    """Make a folder git can track. An empty one gets a .gitkeep file."""
    folder = target / relative_path
    if folder.exists() and not folder.is_dir():
        report.add("skipped", relative_path + "/ (a file has that name)")
        return
    if folder.is_dir() and any(folder.iterdir()):
        report.add("kept", relative_path + "/")
        return
    folder.mkdir(parents=True, exist_ok=True)
    (folder / ".gitkeep").touch()
    report.add("created", relative_path + "/")


def ensure_docs(target, report):
    write_if_missing(
        target / "docs" / "todo.md",
        read_asset("todo.md"),
        "docs/todo.md",
        report,
    )
    write_if_missing(
        target / "docs" / "adr" / "template.md",
        read_asset("adr-template.md"),
        "docs/adr/template.md",
        report,
    )


def clean_one_line(parser, flag, value):
    value = value.strip()
    if not value:
        parser.error(f"{flag} must not be empty")
    if "\n" in value or "\r" in value:
        parser.error(f"{flag} must be one line")
    return value


def clean_components_dir(parser, value):
    value = clean_one_line(parser, "--components-dir", value)
    path = Path(value)
    if not path.parts:
        parser.error("--components-dir must name a folder")
    if path.is_absolute():
        parser.error("--components-dir must be a path inside the project")
    if ".." in path.parts:
        parser.error("--components-dir must not go above the project")
    return path.as_posix()


def parse_args(argv):
    parser = argparse.ArgumentParser(
        description="Lay out the files a project needs after kickoff."
    )
    parser.add_argument("target", help="the project folder")
    parser.add_argument("--name", required=True, help="project name")
    parser.add_argument("--summary", required=True, help="what it is, in one line")
    parser.add_argument(
        "--reply-cap",
        required=True,
        help='how long replies may be, as a sentence, like "5 lines at most."',
    )
    parser.add_argument(
        "--components-dir",
        help="folder for UI components, relative to the project; leave out if there is no UI",
    )
    parser.add_argument(
        "--agents",
        action="store_true",
        help="the project builds its own AI agents",
    )
    args = parser.parse_args(argv)

    args.name = clean_one_line(parser, "--name", args.name)
    args.summary = clean_one_line(parser, "--summary", args.summary)
    args.reply_cap = clean_one_line(parser, "--reply-cap", args.reply_cap)
    if args.components_dir is not None:
        args.components_dir = clean_components_dir(parser, args.components_dir)

    target = Path(args.target)
    if target.exists() and not target.is_dir():
        parser.error(f"{args.target} is a file, not a folder")
    args.target = target
    return args


def main(argv):
    args = parse_args(argv)
    target = args.target
    target.mkdir(parents=True, exist_ok=True)

    report = Report()
    ensure_git(target, report)
    rules_to_merge = ensure_agents_md(target, args, report)
    ensure_claude_md(target, report)
    ensure_docs(target, report)
    ensure_folder(target, ".claude/skills", report)
    if args.components_dir:
        ensure_folder(target, args.components_dir, report)

    print(report.text())
    if rules_to_merge is not None:
        print()
        print(MERGE_HEADER)
        print(rules_to_merge, end="")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
