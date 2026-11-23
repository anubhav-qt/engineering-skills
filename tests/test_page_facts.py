"""Tests for skills/visibility-handling/scripts/page_facts.py.

Run from the repo root: python3 -m unittest discover tests
"""

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from visibility_app import load

page_facts = load("page_facts")

PAGE = """<!doctype html>
<html lang="en-GB">
<head>
  <title>  Mugs
     for tea </title>
  <meta name="Description" content=" Hand made. ">
  <meta property="og:image" content="/card.png">
  <meta name="robots" content="NoIndex, nofollow">
  <link rel="Canonical" href="https://shop.test/mugs">
  <link rel="alternate" hreflang="de" href="https://shop.test/de/mugs">
  <link rel="alternate" type="application/rss+xml" href="/feed">
  <link rel="shortcut icon" href="/icon.png">
  <script type="application/ld+json">{"@context": "https://schema.org", "@graph": [
    {"@type": "WebSite", "name": "Shop"}, {"@type": ["Product", "Thing"]}]}</script>
  <script type="application/ld+json">{broken</script>
  <style>.hidden { color: red }</style>
</head>
<body>
  <svg><title>icon title</title></svg>
  <h1>Big <span>mugs</span></h1>
  <img src="a.png" alt="">
  <img src="b.png">
  <a href="/cups">Cups</a>
  <script>var words = "not text";</script>
  <p>Hello &amp; welcome.<br>Second line.</p>
</body>
</html>"""


class PageFactsTest(unittest.TestCase):
    def setUp(self):
        self.facts = page_facts.parse(PAGE)

    def test_lang_and_title(self):
        self.assertEqual(self.facts.lang, "en-GB")
        self.assertEqual(self.facts.title(), "Mugs for tea")
        self.assertEqual(self.facts.titles, ["Mugs for tea"])

    def test_meta_names_are_case_insensitive(self):
        self.assertEqual(self.facts.meta("description"), "Hand made.")
        self.assertEqual(self.facts.meta("og:image"), "/card.png")
        self.assertIsNone(self.facts.meta("keywords"))

    def test_robots_directives(self):
        self.assertEqual(self.facts.robots_directives(), {"noindex", "nofollow"})

    def test_links(self):
        self.assertEqual(self.facts.canonicals(), ["https://shop.test/mugs"])
        self.assertEqual(self.facts.hreflangs(), [("de", "https://shop.test/de/mugs")])
        self.assertTrue(self.facts.has_icon())

    def test_h1_images_and_anchors(self):
        self.assertEqual(self.facts.h1s, ["Big mugs"])
        self.assertEqual([image.get("alt") for image in self.facts.images], ["", None])
        self.assertEqual(self.facts.internal_links("https://shop.test/mugs"), ["https://shop.test/cups"])

    def test_jsonld_types_and_errors(self):
        types, errors = self.facts.jsonld_types()
        self.assertEqual(types, ["WebSite", "Product", "Thing"])
        self.assertEqual(len(errors), 1)
        names = [item.get("name") for item in self.facts.jsonld_items()]
        self.assertIn("Shop", names)

    def test_text_leaves_out_head_scripts_styles_and_svg(self):
        text = self.facts.text()
        self.assertIn("Hello & welcome.", text)
        self.assertIn("Big mugs", text)
        self.assertNotIn("not text", text)
        self.assertNotIn("color", text)
        self.assertNotIn("icon title", text)
        self.assertNotIn("Mugs for tea", text)
        self.assertEqual(self.facts.script_count, 3)

    def test_empty_page(self):
        facts = page_facts.parse("")
        self.assertIsNone(facts.lang)
        self.assertIsNone(facts.title())
        self.assertEqual(facts.text_length(), 0)

    def test_unclosed_title_still_counts(self):
        facts = page_facts.parse("<html><title>Half open")
        self.assertEqual(facts.title(), "Half open")

    def test_two_titles(self):
        facts = page_facts.parse("<title>A</title><title>B</title>")
        self.assertEqual(facts.titles, ["A", "B"])


if __name__ == "__main__":
    unittest.main()
