"""Tests for skills/visibility-handling/assets (a11y_probe.js, page_fields.js, run_axe.js).

The probe and the field reader run in installed Chrome, headless, on
local fixture pages; the tests skip when Chrome is not found. Headless
Chrome gives the page window focus on some runs and not on others, so
the focus test checks whichever of the two paths the run took.

Run from the repo root: python3 -m unittest discover tests
"""

import html
import json
import re
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from visibility_app import ASSETS

CHROME_PLACES = [
    "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
    "/Applications/Chromium.app/Contents/MacOS/Chromium",
]
CHROME_NAMES = ["google-chrome", "google-chrome-stable", "chromium", "chromium-browser"]
OUTPUT = re.compile(r'<pre id="probe-out">(.*?)</pre>', re.DOTALL)


def find_chrome():
    for place in CHROME_PLACES:
        if Path(place).exists():
            return place
    for name in CHROME_NAMES:
        found = shutil.which(name)
        if found:
            return found
    return None


CHROME = find_chrome()


def run_asset(asset, head, body, lang="en"):
    """Run an asset on a fixture page in headless Chrome and return its result."""
    source = (ASSETS / asset).read_text()
    # The asset runs through eval, the same REPL rule javascript_tool uses:
    # the value of its last expression is the result.
    code = json.dumps(source).replace("</", "<\\/")
    runner = (
        "<script>"
        f"Promise.resolve(eval({code}))"
        ".then((result) => JSON.stringify(result), (error) => 'ERROR ' + error)"
        ".then((text) => { const out = document.createElement('pre'); out.id = 'probe-out';"
        " out.textContent = text; document.body.appendChild(out); });"
        "</script>"
    )
    lang_attribute = ""
    if lang is not None:
        lang_attribute = f' lang="{lang}"'
    page = f"<!doctype html><html{lang_attribute}><head>{head}</head><body>{body}{runner}</body></html>"
    with tempfile.TemporaryDirectory() as folder:
        path = Path(folder) / "page.html"
        path.write_text(page)
        completed = subprocess.run(
            [CHROME, "--headless", "--disable-gpu", "--virtual-time-budget=5000", "--dump-dom", path.as_uri()],
            capture_output=True,
            text=True,
            timeout=60,
        )
    match = OUTPUT.search(completed.stdout)
    if match is None:
        raise AssertionError(f"no output from {asset}: {completed.stderr[-500:]}")
    text = html.unescape(match.group(1))
    if text.startswith("ERROR"):
        raise AssertionError(f"{asset} failed: {text}")
    return json.loads(text)


BAD_HEAD = """
<title>Bad</title>
<style>
  .pulse { animation: pulse 1s infinite; }
  @keyframes pulse { from { opacity: 1; } to { opacity: 0.5; } }
  .tiny { width: 16px; height: 16px; padding: 0; border: 0; }
  .card { cursor: pointer; }
</style>
"""

BAD_BODY = """
<img src="missing.png">
<img src="also.png" alt="IMG_2041.jpg">
<div onclick="buy()">Buy now</div>
<div class="card"><span>Open card</span></div>
<button></button>
<input placeholder="Email" name="email">
<input type="text" name="phone" aria-label="Phone">
<a href="/x" tabindex="1">Skip</a>
<button class="tiny" aria-label="Close">x</button>
<h1>Shop</h1>
<h3>Deals</h3>
<label>Password <input type="password" onpaste="return false" autocomplete="current-password"></label>
<span class="pulse">new</span>
<video autoplay src="a.mp4"></video>
"""

GOOD_HEAD = """
<title>Good</title>
<style>
  .pulse { animation: pulse 1s infinite; }
  @keyframes pulse { from { opacity: 1; } to { opacity: 0.5; } }
  @media (prefers-reduced-motion: reduce) { .pulse { animation: none; } }
  button, input, a { min-height: 44px; min-width: 44px; display: inline-block; }
</style>
"""

GOOD_BODY = """
<header><a href="/">Home</a></header>
<main>
  <h1>Shop</h1>
  <h2>Deals</h2>
  <img src="missing.png" alt="A blue mug on a table">
  <img src="line.png" alt="">
  <p>Read the <a href="/terms">terms</a> before you buy.</p>
  <label for="mail">Email</label>
  <input id="mail" type="email" name="email" autocomplete="email">
  <button type="button">Buy now</button>
  <span class="pulse">new</span>
  <video autoplay muted controls src="a.mp4"></video>
</main>
"""


@unittest.skipIf(CHROME is None, "Chrome is not installed")
class ProbeTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.bad = run_asset("a11y_probe.js", BAD_HEAD, BAD_BODY, lang=None)
        cls.good = run_asset("a11y_probe.js", GOOD_HEAD, GOOD_BODY)

    def rules(self, result):
        found = {}
        for finding in result["findings"]:
            found[finding["rule"]] = finding
        return found

    def test_bad_page_findings(self):
        found = self.rules(self.bad)
        expected = {
            "no-lang": 1,
            "img-no-alt": 1,
            "img-file-name-alt": 1,
            "fake-control": 2,
            "control-no-name": 1,
            "placeholder-only-label": 1,
            "positive-tabindex": 1,
            "heading-skip": 1,
            "no-main": 1,
            "no-autocomplete": 2,
            "paste-blocked": 1,
            "autoplay-sound": 1,
            "no-reduced-motion": 1,
        }
        for rule, count in expected.items():
            self.assertIn(rule, found, rule)
            self.assertEqual(found[rule]["count"], count, (rule, found[rule]))

    def test_examples_name_the_element(self):
        found = self.rules(self.bad)
        self.assertEqual(found["fake-control"]["examples"], ['div "Buy now"', 'div.card "Open card"'])
        self.assertEqual(found["heading-skip"]["wcag"], "1.3.1")

    def test_small_target_skips_links_in_a_sentence(self):
        bad = self.rules(self.bad)
        self.assertIn("small-target", bad)
        self.assertIn('button.tiny "x"', bad["small-target"]["examples"])
        self.assertNotIn("small-target", self.rules(self.good))

    def test_good_page_has_no_findings(self):
        self.assertEqual(self.good["findings"], [], self.good["findings"])

    def test_focus_style_is_judged_only_with_window_focus(self):
        result = run_asset(
            "a11y_probe.js",
            "<title>t</title><style>.plain:focus { outline: none; }</style>",
            '<main><h1>x</h1><button class="plain">Plain</button></main>',
        )
        found = self.rules(result)
        not_checked = " ".join(result["notChecked"])
        if "focus-not-visible: the page window has no focus" in not_checked:
            self.assertNotIn("focus-not-visible", found)
        else:
            self.assertIn("focus-not-visible", found)
            self.assertEqual(found["focus-not-visible"]["examples"], ['button.plain "Plain"'])

    def test_hidden_parent_hides_its_small_buttons(self):
        result = run_asset(
            "a11y_probe.js",
            "<title>t</title><style>.tiny { width: 16px; height: 16px; padding: 0; border: 0; }</style>",
            '<main><h1>x</h1><div style="display:none"><button class="tiny" aria-label="Close">x</button></div></main>',
        )
        self.assertNotIn("small-target", self.rules(result))

    def test_focus_without_a_visible_ring_mode_is_not_judged(self):
        # Stands in for a focused window after a mouse click: focus lands,
        # but no control matches :focus-visible.
        stub = (
            "<script>const real = Element.prototype.matches;"
            "Element.prototype.matches = function (s) {"
            " if (s === ':focus') { return document.activeElement === this; }"
            " if (s === ':focus-visible') { return false; }"
            " return real.call(this, s); };"
            "</script>"
        )
        result = run_asset(
            "a11y_probe.js",
            "<title>t</title><style>.plain:focus { outline: none; }</style>" + stub,
            '<main><h1>x</h1><button class="plain">Plain</button></main>',
        )
        self.assertNotIn("focus-not-visible", self.rules(result))
        not_checked = " ".join(result["notChecked"])
        self.assertIn("1 control(s) skipped, the browser hides focus rings after a mouse click", not_checked)

    def test_headings_and_vitals(self):
        self.assertEqual(self.good["headings"], ["h1 Shop", "h2 Deals"])
        self.assertIn("INP needs real users", self.good["vitals"]["note"])
        self.assertIsNotNone(self.good["vitals"]["cls"])

    def test_page_is_left_as_it_was(self):
        result = run_asset(
            "a11y_probe.js",
            "<title>t</title>",
            '<main><h1>x</h1><input id="keep" aria-label="Keep"></main>'
            "<script>document.getElementById('keep').focus();</script>",
        )
        self.assertEqual(result["findings"], [])


@unittest.skipIf(CHROME is None, "Chrome is not installed")
class PageFieldsTest(unittest.TestCase):
    def test_reads_rendered_fields(self):
        head = (
            "<title> Shop </title>"
            '<link rel="Canonical" href="https://shop.test/">'
            '<meta name="robots" content="index, follow">'
        )
        body = (
            "<div id=root></div><script>"
            "document.getElementById('root').innerHTML = '<h1>Mugs</h1><p>Plain words.</p>';"
            "document.title = 'Mugs  shop';"
            "const meta = document.createElement('meta'); meta.name = 'googlebot'; meta.content = 'noindex';"
            "document.head.appendChild(meta);"
            "</script>"
        )
        result = run_asset("page_fields.js", head, body)
        self.assertTrue(result["url"].startswith("file://"))
        self.assertEqual(result["title"], "Mugs shop")
        self.assertEqual(result["canonicals"], ["https://shop.test/"])
        self.assertEqual(result["robots"], ["index, follow", "noindex"])
        self.assertEqual(result["h1Count"], 1)
        self.assertEqual(result["lang"], "en")
        self.assertGreater(result["textLength"], 10)

    def test_waits_for_a_late_app_to_draw(self):
        body = (
            "<div id=root></div><script>"
            "setTimeout(() => { document.getElementById('root').innerHTML = '<h1>Mugs</h1>'; }, 800);"
            "</script>"
        )
        result = run_asset("page_fields.js", "<title>Shop</title>", body)
        self.assertEqual(result["h1Count"], 1)


NODE = shutil.which("node")


@unittest.skipIf(NODE is None, "Node is not installed")
class SyntaxTest(unittest.TestCase):
    def test_every_asset_parses(self):
        for asset in sorted(ASSETS.glob("*.js")):
            completed = subprocess.run([NODE, "--check", str(asset)], capture_output=True, text=True)
            self.assertEqual(completed.returncode, 0, f"{asset.name}: {completed.stderr}")

    def test_axe_is_pinned_and_uses_wcag_22_aa(self):
        source = (ASSETS / "run_axe.js").read_text()
        self.assertIn('const VERSION = "4.14.1";', source)
        self.assertIn("axe-core@${VERSION}", source)
        for tag in ("wcag2a", "wcag2aa", "wcag21a", "wcag21aa", "wcag22aa"):
            self.assertIn(f'"{tag}"', source)
        self.assertIn("blocked: true", source)


if __name__ == "__main__":
    unittest.main()
