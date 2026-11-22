"""Tests for skills/kickoff/scripts/setup_project.py.

Run from the repo root: python3 -m unittest discover tests
"""

import contextlib
import importlib.util
import io
import os
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest import mock

REPO_ROOT = Path(__file__).resolve().parent.parent
SCRIPT = REPO_ROOT / "skills" / "kickoff" / "scripts" / "setup_project.py"

spec = importlib.util.spec_from_file_location("setup_project", SCRIPT)
setup_project = importlib.util.module_from_spec(spec)
spec.loader.exec_module(setup_project)


def base_args(target, *extra):
    return [
        str(target),
        "--name",
        "Cafe Finder",
        "--summary",
        "Finds quiet cafes to work from.",
        "--reply-cap",
        "5 lines at most.",
        *extra,
    ]


def run_setup(argv):
    """Run the script's main and return its printed report."""
    output = io.StringIO()
    with contextlib.redirect_stdout(output):
        code = setup_project.main(argv)
    if code != 0:
        raise AssertionError(f"main returned {code}")
    return output.getvalue()


def run_bad_args(argv):
    """Run main with bad input and return the error text it printed."""
    errors = io.StringIO()
    with contextlib.redirect_stderr(errors):
        with unittest.TestCase().assertRaises(SystemExit) as caught:
            setup_project.main(argv)
    if caught.exception.code != 2:
        raise AssertionError(f"exit code was {caught.exception.code}")
    return errors.getvalue()


def snapshot(folder):
    """Every file under folder (outside .git) mapped to its bytes."""
    files = {}
    for path in sorted(folder.rglob("*")):
        if ".git" in path.relative_to(folder).parts:
            continue
        if path.is_file():
            files[path.relative_to(folder).as_posix()] = path.read_bytes()
    return files


class TempFolderTest(unittest.TestCase):
    def setUp(self):
        self._temp = tempfile.TemporaryDirectory()
        self.root = Path(self._temp.name).resolve()
        self.project = self.root / "project"

    def tearDown(self):
        self._temp.cleanup()

    def read(self, relative_path):
        return (self.project / relative_path).read_text(encoding="utf-8")


class NewProjectTest(TempFolderTest):
    def test_makes_every_file_in_an_empty_folder(self):
        self.project.mkdir()
        report = run_setup(base_args(self.project))

        self.assertTrue((self.project / ".git").is_dir())
        self.assertEqual(self.read("CLAUDE.md"), "@AGENTS.md\n")
        self.assertTrue((self.project / "docs/todo.md").is_file())
        self.assertTrue((self.project / "docs/adr/template.md").is_file())
        self.assertTrue((self.project / ".claude/skills/.gitkeep").is_file())
        self.assertIn("created  AGENTS.md", report)
        self.assertIn("created  git repo", report)
        self.assertNotIn("Rules to merge", report)

    def test_agents_md_has_name_summary_and_reply_cap(self):
        run_setup(base_args(self.project))
        text = self.read("AGENTS.md")

        self.assertTrue(text.startswith("# Cafe Finder\n\nFinds quiet cafes"))
        self.assertIn("Reply length: 5 lines at most.", text)
        self.assertIn("## Working rules", text)
        self.assertIn(".claude/skills/", text)
        self.assertNotIn("{{", text)

    def test_makes_a_missing_target_folder(self):
        target = self.project / "deep" / "inside"
        run_setup(base_args(target))
        self.assertTrue((target / "AGENTS.md").is_file())

    def test_leaves_out_ui_and_agent_rules_by_default(self):
        run_setup(base_args(self.project))
        text = self.read("AGENTS.md")
        self.assertNotIn("### UI", text)
        self.assertNotIn("### Building agents", text)

    def test_adds_ui_rules_and_components_folder(self):
        run_setup(base_args(self.project, "--components-dir", "src/components/"))
        text = self.read("AGENTS.md")

        self.assertIn("### UI", text)
        self.assertIn("`src/components/`", text)
        self.assertTrue((self.project / "src/components/.gitkeep").is_file())

    def test_adds_agent_rules(self):
        run_setup(base_args(self.project, "--agents"))
        self.assertIn("### Building agents", self.read("AGENTS.md"))

    def test_running_twice_changes_nothing(self):
        argv = base_args(self.project, "--components-dir", "components", "--agents")
        run_setup(argv)
        before = snapshot(self.project)
        report = run_setup(argv)

        self.assertEqual(snapshot(self.project), before)
        self.assertNotIn("created", report)
        self.assertNotIn("updated", report)

    def test_odd_characters_are_written_as_they_are(self):
        name = 'Café "Q" {{summary}} \\1 $HOME'
        run_setup(
            [
                str(self.project),
                "--name",
                name,
                "--summary",
                "Uses {{name}} and \\g<0> safely.",
                "--reply-cap",
                "No limit.",
            ]
        )
        text = self.read("AGENTS.md")
        self.assertTrue(text.startswith(f"# {name}\n"))
        self.assertIn("Uses {{name}} and \\g<0> safely.", text)

    def test_very_long_values_are_kept_whole(self):
        long_summary = "word " * 2000
        run_setup(
            [
                str(self.project),
                "--name",
                "Long",
                "--summary",
                long_summary,
                "--reply-cap",
                "5 lines at most.",
            ]
        )
        self.assertIn(long_summary.strip(), self.read("AGENTS.md"))

    def test_trims_spaces_around_values(self):
        run_setup(
            [
                str(self.project),
                "--name",
                "  Trimmed  ",
                "--summary",
                " One line. ",
                "--reply-cap",
                " 5 lines at most. ",
            ]
        )
        self.assertTrue(self.read("AGENTS.md").startswith("# Trimmed\n\nOne line.\n"))


class ExistingProjectTest(TempFolderTest):
    def setUp(self):
        super().setUp()
        self.project.mkdir()

    def write(self, relative_path, text):
        path = self.project / relative_path
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")

    def test_existing_agents_md_is_kept_and_rules_are_printed(self):
        self.write("AGENTS.md", "# Old\n\nKeep me.")
        report = run_setup(base_args(self.project))

        self.assertEqual(self.read("AGENTS.md"), "# Old\n\nKeep me.")
        self.assertIn("kept     AGENTS.md (merge the rules printed below)", report)
        merge_part = report.split("Rules to merge into AGENTS.md:\n", 1)[1]
        self.assertIn("## Working rules", merge_part)
        self.assertIn("Reply length: 5 lines at most.", merge_part)
        self.assertNotIn("# Cafe Finder", merge_part)

    def test_printed_rules_follow_the_flags(self):
        self.write("AGENTS.md", "# Old\n")
        report = run_setup(base_args(self.project, "--components-dir", "ui", "--agents"))
        merge_part = report.split("Rules to merge into AGENTS.md:\n", 1)[1]

        self.assertIn("`ui/`", merge_part)
        self.assertIn("### Building agents", merge_part)

    def test_agents_md_with_our_rules_needs_no_merge(self):
        run_setup(base_args(self.project))
        report = run_setup(base_args(self.project))

        self.assertIn("kept     AGENTS.md (our rules are already in it)", report)
        self.assertNotIn("Rules to merge", report)

    def test_changed_reply_cap_asks_for_a_merge(self):
        run_setup(base_args(self.project))
        argv = base_args(self.project)
        argv[6] = "No limit."
        report = run_setup(argv)

        self.assertIn("Rules to merge into AGENTS.md:", report)
        self.assertIn("Reply length: 5 lines at most.", self.read("AGENTS.md"))

    def test_adds_import_line_to_an_existing_claude_md(self):
        self.write("CLAUDE.md", "# Notes\nStay.")
        report = run_setup(base_args(self.project))

        self.assertEqual(self.read("CLAUDE.md"), "# Notes\nStay.\n\n@AGENTS.md\n")
        self.assertIn("updated  CLAUDE.md", report)

    def test_keeps_a_claude_md_that_already_imports(self):
        self.write("CLAUDE.md", "# Notes\n  @AGENTS.md  \n")
        run_setup(base_args(self.project))
        self.assertEqual(self.read("CLAUDE.md"), "# Notes\n  @AGENTS.md  \n")

    def test_claude_md_linked_to_agents_md_does_not_import_itself(self):
        self.write("AGENTS.md", "# Shared\n")
        os.symlink("AGENTS.md", self.project / "CLAUDE.md")
        report = run_setup(base_args(self.project))

        self.assertEqual(self.read("AGENTS.md"), "# Shared\n")
        self.assertIn("kept     CLAUDE.md (it is a link to AGENTS.md)", report)
        self.assertIn("Rules to merge into AGENTS.md:", report)

    def test_dangling_claude_link_to_agents_md_gets_filled(self):
        os.symlink("AGENTS.md", self.project / "CLAUDE.md")
        run_setup(base_args(self.project))

        self.assertTrue((self.project / "CLAUDE.md").is_symlink())
        self.assertNotIn("@AGENTS.md", self.read("AGENTS.md"))

    def test_broken_link_is_skipped_and_nothing_is_written_through_it(self):
        outside = self.root / "outside.md"
        os.symlink(outside, self.project / "CLAUDE.md")
        report = run_setup(base_args(self.project))

        self.assertFalse(outside.exists())
        self.assertIn("skipped  CLAUDE.md (broken link)", report)

    def test_existing_docs_are_kept(self):
        self.write("docs/todo.md", "- [ ] mine\n")
        self.write("docs/adr/template.md", "my template\n")
        run_setup(base_args(self.project))

        self.assertEqual(self.read("docs/todo.md"), "- [ ] mine\n")
        self.assertEqual(self.read("docs/adr/template.md"), "my template\n")

    def test_full_components_folder_gets_no_gitkeep(self):
        self.write("components/Button.tsx", "export {}\n")
        run_setup(base_args(self.project, "--components-dir", "components"))
        self.assertFalse((self.project / "components/.gitkeep").exists())

    def test_file_named_like_the_components_folder_is_skipped(self):
        self.write("components", "not a folder\n")
        report = run_setup(base_args(self.project, "--components-dir", "components"))

        self.assertEqual(self.read("components"), "not a folder\n")
        self.assertIn("skipped  components/", report)

    def test_non_utf8_files_are_skipped(self):
        (self.project / "AGENTS.md").write_bytes(b"\xff\xfe bad")
        (self.project / "CLAUDE.md").write_bytes(b"\xff\xfe bad")
        report = run_setup(base_args(self.project))

        self.assertEqual((self.project / "AGENTS.md").read_bytes(), b"\xff\xfe bad")
        self.assertIn("skipped  AGENTS.md (not UTF-8 text)", report)
        self.assertIn("skipped  CLAUDE.md (not UTF-8 text)", report)

    def test_folder_inside_a_git_repo_gets_no_new_repo(self):
        subprocess.run(["git", "init", "-q"], cwd=self.project, check=True)
        inner = self.project / "packages" / "app"
        report = run_setup(base_args(inner))

        self.assertFalse((inner / ".git").exists())
        self.assertIn("kept     git repo", report)

    def test_missing_git_is_reported_not_fatal(self):
        with mock.patch.object(
            setup_project.subprocess, "run", side_effect=FileNotFoundError
        ):
            report = run_setup(base_args(self.project))

        self.assertIn("skipped  git repo (git is not installed)", report)
        self.assertTrue((self.project / "AGENTS.md").is_file())


class BadInputTest(TempFolderTest):
    def assert_rejected(self, argv, message):
        error = run_bad_args(argv)
        self.assertIn(message, error)
        self.assertFalse(self.project.exists())

    def test_empty_name(self):
        argv = base_args(self.project)
        argv[2] = "   "
        self.assert_rejected(argv, "--name must not be empty")

    def test_summary_with_a_new_line(self):
        argv = base_args(self.project)
        argv[4] = "line one\nline two"
        self.assert_rejected(argv, "--summary must be one line")

    def test_reply_cap_with_a_carriage_return(self):
        argv = base_args(self.project)
        argv[6] = "5 lines\rmore"
        self.assert_rejected(argv, "--reply-cap must be one line")

    def test_missing_reply_cap(self):
        argv = base_args(self.project)[:5]
        self.assert_rejected(argv, "--reply-cap")

    def test_components_dir_outside_the_project(self):
        argv = base_args(self.project, "--components-dir", "../ui")
        self.assert_rejected(argv, "must not go above the project")

    def test_components_dir_absolute(self):
        argv = base_args(self.project, "--components-dir", "/tmp/ui")
        self.assert_rejected(argv, "must be a path inside the project")

    def test_components_dir_dot(self):
        argv = base_args(self.project, "--components-dir", ".")
        self.assert_rejected(argv, "must name a folder")

    def test_target_is_a_file(self):
        self.root.joinpath("file.txt").write_text("x", encoding="utf-8")
        error = run_bad_args(base_args(self.root / "file.txt"))
        self.assertIn("is a file, not a folder", error)


class CommandLineTest(TempFolderTest):
    def test_script_runs_from_the_command_line(self):
        result = subprocess.run(
            ["python3", str(SCRIPT), *base_args(self.project)],
            capture_output=True,
            text=True,
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("created  AGENTS.md", result.stdout)


if __name__ == "__main__":
    unittest.main()
