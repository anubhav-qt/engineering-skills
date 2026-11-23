"""Checks on the visibility-handling skill's own files.

Run from the repo root: python3 -m unittest discover tests
"""

import re
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from visibility_app import SKILL

UPDATED = re.compile(r"^Updated: \d{4}-\d{2}-\d{2}", re.MULTILINE)
MENTIONED_FILE = re.compile(r"`((?:scripts|assets|references)/[\w.-]+)`|\$\{CLAUDE_SKILL_DIR\}/((?:scripts|assets)/[\w.-]+)")


class SkillFilesTest(unittest.TestCase):
    def test_front_matter(self):
        text = (SKILL / "SKILL.md").read_text()
        self.assertTrue(text.startswith("---\nname: visibility-handling\ndescription: "))
        self.assertLess(len(text.splitlines()), 500)

    def test_every_reference_has_an_updated_date(self):
        references = sorted((SKILL / "references").glob("*.md"))
        self.assertGreater(len(references), 0)
        for reference in references:
            self.assertRegex(reference.read_text(), UPDATED, reference.name)

    def test_every_file_the_skill_names_exists(self):
        names = set()
        for document in [SKILL / "SKILL.md", *(SKILL / "references").glob("*.md")]:
            for match in MENTIONED_FILE.finditer(document.read_text()):
                names.add(match.group(1) or match.group(2))
        self.assertGreater(len(names), 5)
        for name in sorted(names):
            self.assertTrue((SKILL / name).exists(), name)


if __name__ == "__main__":
    unittest.main()
