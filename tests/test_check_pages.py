"""Tests for skills/visibility-handling/scripts/check_pages.py.

Run from the repo root: python3 -m unittest discover tests
"""

import json
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from visibility_app import good_body, good_head, html, load, page, redirect, run_main, start_app, text

check_pages = load("check_pages")

PNG = text("png bytes", content_type="image/png")


class CheckPagesTest(unittest.TestCase):
    def site(self, pages):
        """pages: path -> function(base url) returning a response tuple."""
        holder = {}
        files = {"/card.png": PNG}

        def respond(method, path, headers, body):
            if path in pages:
                return pages[path](holder["url"])
            if path in files:
                return files[path]
            return 404, [("Content-Type", "text/plain")], "not found"


        app = start_app(self, respond)
        holder["url"] = app.url
        return app

    def good_page(self, path="/", title="Plain shop", description="Hand made mugs.", head_extra="", body=None, lang="en"):
        def build(url):
            if body is None:
                content = good_body()
            else:
                content = body
            return html(page(good_head(url, path, title, description) + head_extra, content, lang))

        return build

    def run_pages(self, app, paths, extra=()):
        urls = [app.url.rstrip("/") + path for path in paths]
        return run_main(check_pages, [*urls, *extra])

    def test_clean_page_has_nothing_to_fix(self):
        app = self.site({"/": self.good_page()})
        code, output = self.run_pages(app, ["/"])
        self.assertEqual(code, 0, output)
        self.assertIn("0 blocker(s), 0 major, 0 minor, 0 note(s), 0 not checked", output)

    def test_meta_noindex_is_a_blocker(self):
        app = self.site({"/": self.good_page(head_extra='<meta name="robots" content="noindex">')})
        code, output = self.run_pages(app, ["/"])
        self.assertEqual(code, 1)
        self.assertIn("BLOCKER", output)
        self.assertIn("meta robots says noindex", output)

    def test_googlebot_none_is_a_blocker(self):
        app = self.site({"/": self.good_page(head_extra='<meta name="googlebot" content="none">')})
        code, output = self.run_pages(app, ["/"])
        self.assertIn("meta robots says none", output)

    def test_header_noindex_is_a_blocker(self):
        def build(url):
            status, headers, body = self.good_page()(url)
            return status, [*headers, ("X-Robots-Tag", "noarchive, noindex")], body

        app = self.site({"/": build})
        code, output = self.run_pages(app, ["/"])
        self.assertIn("X-Robots-Tag header says noindex", output)

    def test_header_noindex_for_another_crawler_is_ignored(self):
        def build(url):
            status, headers, body = self.good_page()(url)
            return status, [*headers, ("X-Robots-Tag", "otherbot: noindex"), ("X-Robots-Tag", "max-snippet: 20")], body

        app = self.site({"/": build})
        code, output = self.run_pages(app, ["/"])
        self.assertEqual(code, 0, output)

    def test_header_noindex_for_googlebot_counts(self):
        def build(url):
            status, headers, body = self.good_page()(url)
            return status, [*headers, ("X-Robots-Tag", "googlebot: noindex")], body

        app = self.site({"/": build})
        code, output = self.run_pages(app, ["/"])
        self.assertIn("X-Robots-Tag header says noindex", output)

    def test_missing_page_is_a_blocker(self):
        app = self.site({})
        code, output = self.run_pages(app, ["/gone"])
        self.assertEqual(code, 1)
        self.assertIn("answers 404", output)

    def test_one_redirect_is_a_note_and_the_final_page_is_checked(self):
        app = self.site({"/old": lambda url: redirect("/new"), "/new": self.good_page(path="/new")})
        code, output = self.run_pages(app, ["/old"])
        self.assertEqual(code, 0, output)
        self.assertIn("redirects (301) to", output)

    def test_redirect_chain_is_minor(self):
        app = self.site({
            "/a": lambda url: redirect("/b"),
            "/b": lambda url: redirect("/c"),
            "/c": self.good_page(path="/c"),
        })
        code, output = self.run_pages(app, ["/a"])
        self.assertIn("2 redirects in a row", output)

    def test_redirect_loop_is_a_blocker(self):
        app = self.site({"/a": lambda url: redirect("/b"), "/b": lambda url: redirect("/a")})
        code, output = self.run_pages(app, ["/a"])
        self.assertIn("BLOCKER", output)
        self.assertIn("redirect loop", output)

    def test_missing_title_description_lang_h1_viewport(self):
        app = self.site({"/": lambda url: html(page("", "<p>hi</p>", lang=None))})
        code, output = self.run_pages(app, ["/"])
        self.assertIn("no title", output)
        self.assertIn("no meta description", output)
        self.assertIn("no lang on <html>", output)
        self.assertIn("no H1", output)
        self.assertIn("no viewport meta", output)
        self.assertIn("no canonical link", output)
        self.assertIn("link previews miss og:title, og:description, og:image", output)

    def test_meta_keywords_is_a_note(self):
        app = self.site({"/": self.good_page(head_extra='<meta name="keywords" content="mugs">')})
        code, output = self.run_pages(app, ["/"])
        self.assertEqual(code, 0)
        self.assertIn("meta keywords is ignored", output)

    def test_two_canonicals_are_major(self):
        app = self.site({"/": self.good_page(head_extra='<link rel="canonical" href="/other">')})
        code, output = self.run_pages(app, ["/"])
        self.assertIn("2 canonical links", output)

    def test_canonical_to_home_page_from_a_deep_page_is_major(self):
        def build(url):
            head = good_head(url, "/").replace("<title>", "<title>Pricing ")
            return html(page(head, good_body()))

        app = self.site({"/pricing": build})
        code, output = self.run_pages(app, ["/pricing"])
        self.assertIn("canonical points at the home page", output)

    def test_canonical_to_a_404_is_major(self):
        app = self.site({"/a": self.good_page(path="/missing")})
        code, output = self.run_pages(app, ["/a"])
        self.assertIn("which answers 404", output)

    def test_canonical_to_another_live_page_is_a_note(self):
        app = self.site({"/a": self.good_page(path="/b"), "/b": self.good_page(path="/b")})
        code, output = self.run_pages(app, ["/a"])
        self.assertEqual(code, 0, output)
        self.assertIn("this page itself will not be indexed", output)

    def test_relative_canonical_is_minor(self):
        def build(url):
            head = good_head(url, "/").replace(f'href="{url.rstrip("/")}/"', 'href="/"')
            return html(page(head, good_body()))

        app = self.site({"/": build})
        code, output = self.run_pages(app, ["/"])
        self.assertIn("canonical is relative", output)

    def test_og_image_that_is_missing(self):
        def build(url):
            head = good_head(url, "/").replace("card.png", "gone.png")
            return html(page(head, good_body()))

        app = self.site({"/": build})
        code, output = self.run_pages(app, ["/"])
        self.assertIn("gone.png answers 404", output)

    def test_no_twitter_card_is_a_note(self):
        def build(url):
            head = good_head(url, "/").replace('<meta name="twitter:card" content="summary_large_image">', "")
            return html(page(head, good_body()))

        app = self.site({"/": build})
        code, output = self.run_pages(app, ["/"])
        self.assertEqual(code, 0)
        self.assertIn("no twitter:card", output)

    def test_images_without_alt_and_weak_alt(self):
        body = good_body() + '<img src="/a.png"><img src="/b.png" alt="IMG_2041.jpg"><img src="/c.png" alt="">'
        app = self.site({"/": self.good_page(body=body)})
        code, output = self.run_pages(app, ["/"])
        self.assertIn("1 image(s) with no alt (WCAG 1.1.1): /a.png", output)
        self.assertIn("alt that says nothing", output)
        self.assertNotIn("/c.png", output)

    def test_jsonld_that_does_not_parse_and_faq(self):
        extra = (
            '<script type="application/ld+json">{"@type": "FAQPage",}</script>'
            '<script type="application/ld+json">{"@type": "FAQPage"}</script>'
        )
        app = self.site({"/": self.good_page(head_extra=extra)})
        code, output = self.run_pages(app, ["/"])
        self.assertIn("JSON-LD does not parse", output)
        self.assertIn("FAQ rich results stopped showing", output)

    def test_hreflang_bad_codes(self):
        cases = {"en-UK": "use GB", "es-419": "number regions", "english": "not a language", "en_GB": "not a language"}
        for code, words in cases.items():
            self.assertIn(words, check_pages.hreflang_problem(code), code)
        for code in ("en", "en-GB", "zh-Hant", "zh-Hant-TW", "x-default", "DE-de"):
            self.assertEqual(check_pages.hreflang_problem(code), "", code)

    def test_hreflang_with_return_links_is_clean(self):
        def build(path):
            def make(url):
                alternates = (
                    f'<link rel="alternate" hreflang="en" href="{url}en">'
                    f'<link rel="alternate" hreflang="de" href="{url}de">'
                    f'<link rel="alternate" hreflang="x-default" href="{url}en">'
                )
                return html(page(good_head(url, path, title=path) + alternates, good_body()))

            return make

        app = self.site({"/en": build("/en"), "/de": build("/de")})
        code, output = self.run_pages(app, ["/en"])
        self.assertEqual(code, 0, output)

    def test_hreflang_without_return_link_is_major(self):
        def english(url):
            alternates = (
                f'<link rel="alternate" hreflang="en" href="{url}en">'
                f'<link rel="alternate" hreflang="de" href="{url}de">'
            )
            return html(page(good_head(url, "/en") + alternates, good_body()))

        app = self.site({"/en": english, "/de": self.good_page(path="/de", title="Deutsch")})
        code, output = self.run_pages(app, ["/en"])
        self.assertIn("/de does not link back", output)

    def test_hreflang_set_without_itself_is_minor(self):
        def english(url):
            alternate = f'<link rel="alternate" hreflang="de" href="{url}de">'
            return html(page(good_head(url, "/en") + alternate, good_body()))

        def german(url):
            alternate = f'<link rel="alternate" hreflang="en" href="{url}en">'
            return html(page(good_head(url, "/de", title="Deutsch") + alternate, good_body()))

        app = self.site({"/en": english, "/de": german})
        code, output = self.run_pages(app, ["/en"])
        self.assertIn("does not list this page itself", output)
        self.assertNotIn("does not link back", output)

    def test_empty_shell_is_major(self):
        def shell(url):
            return html(page(good_head(url, "/"), '<div id="root"></div><script src="/app.js"></script>'))

        app = self.site({"/": shell})
        code, output = self.run_pages(app, ["/"])
        self.assertIn("see an empty page", output)

    def test_short_page_without_scripts_is_not_a_shell(self):
        app = self.site({"/": self.good_page(body="<main><h1>Hi</h1></main>")})
        code, output = self.run_pages(app, ["/"])
        self.assertNotIn("empty page", output)

    def test_same_title_on_two_pages(self):
        app = self.site({"/a": self.good_page(path="/a", description="A"), "/b": self.good_page(path="/b", description="B")})
        code, output = self.run_pages(app, ["/a", "/b"])
        self.assertIn("same title 'Plain shop' on 2 pages", output)
        self.assertNotIn("same description", output)

    def test_two_urls_for_one_page_are_not_duplicates(self):
        app = self.site({"/old": lambda url: redirect("/"), "/": self.good_page()})
        code, output = self.run_pages(app, ["/", "/old"])
        self.assertNotIn("same title", output)

    def test_out_of_scope_url_cannot_start(self):
        code, output = run_main(check_pages, ["https://example.com/"])
        self.assertEqual(code, 2)
        self.assertIn("--allow-host example.com", output)


class RenderedTest(unittest.TestCase):
    def setUp(self):
        self.folder = tempfile.TemporaryDirectory()
        self.addCleanup(self.folder.cleanup)

    def write(self, data):
        path = Path(self.folder.name) / "rendered.json"
        path.write_text(json.dumps(data))
        return str(path)

    def shell_site(self, head="<title>Shop</title>"):
        def respond(method, path, headers, body):
            return html(page(head, '<div id="root"></div><script src="/app.js"></script>'))

        return start_app(self, respond)

    def rendered(self, url, **fields):
        entry = {"url": url, "title": "Shop", "canonicals": [], "robots": [], "h1Count": 0, "textLength": 0}
        entry.update(fields)
        return entry

    def test_text_and_h1_only_after_javascript(self):
        app = self.shell_site()
        path = self.write([self.rendered(app.url, h1Count=1, textLength=900)])
        code, output = run_main(check_pages, [app.url, "--rendered", path])
        self.assertIn("most text appears only after JavaScript (raw 0, rendered 900", output)
        self.assertIn("the H1 only exists after JavaScript", output)
        self.assertNotIn("Confirm with --rendered", output)

    def test_short_page_built_only_by_javascript(self):
        app = self.shell_site()
        path = self.write([self.rendered(app.url, h1Count=1, textLength=150)])
        code, output = run_main(check_pages, [app.url, "--rendered", path])
        self.assertIn("most text appears only after JavaScript (raw 0, rendered 150", output)

    def test_raw_text_that_holds_most_of_the_page_is_fine(self):
        words = "Hand-made mugs, fired in small batches. " * 8

        def respond(method, path, headers, body):
            return html(page("<title>Shop</title>", f"<h1>Shop</h1><p>{words}</p><script src='/app.js'></script>"))

        app = start_app(self, respond)
        raw_length = len(f"Shop {words}".strip())
        path = self.write([self.rendered(app.url, h1Count=1, textLength=raw_length + 150)])
        code, output = run_main(check_pages, [app.url, "--rendered", path])
        self.assertNotIn("only after JavaScript", output)

    def test_title_only_after_javascript(self):
        app = self.shell_site(head="")
        path = self.write([self.rendered(app.url, title="Shop")])
        code, output = run_main(check_pages, [app.url, "--rendered", path])
        self.assertIn("title only exists after JavaScript ('Shop')", output)

    def test_javascript_changes_title_and_canonical(self):
        app = self.shell_site(head='<title>Shop</title><link rel="canonical" href="https://shop.test/">')
        path = self.write([self.rendered(app.url, title="Mugs", canonicals=["https://shop.test/mugs"])])
        code, output = run_main(check_pages, [app.url, "--rendered", path])
        self.assertIn("JavaScript changes the title from 'Shop' to 'Mugs'", output)
        self.assertIn("JavaScript changes the canonical", output)

    def test_javascript_adds_noindex(self):
        app = self.shell_site()
        path = self.write([self.rendered(app.url, robots=["noindex, follow"])])
        code, output = run_main(check_pages, [app.url, "--rendered", path])
        self.assertIn("BLOCKER", output)
        self.assertIn("JavaScript adds noindex", output)

    def test_javascript_removes_noindex(self):
        app = self.shell_site(head='<title>Shop</title><meta name="robots" content="noindex">')
        path = self.write([self.rendered(app.url)])
        code, output = run_main(check_pages, [app.url, "--rendered", path])
        self.assertIn("Google may skip rendering a noindex page", output)

    def test_same_render_adds_nothing(self):
        app = self.shell_site()
        path = self.write(self.rendered(app.url + "#top"))
        code, output = run_main(check_pages, [app.url, "--rendered", path])
        self.assertNotIn("JavaScript", output)

    def test_page_missing_from_rendered_file(self):
        app = self.shell_site()
        path = self.write([self.rendered("http://127.0.0.1:1/other")])
        code, output = run_main(check_pages, [app.url, "--rendered", path])
        self.assertIn("no entry for this page in the --rendered file", output)
        self.assertIn("Confirm with --rendered", output)

    def test_bad_rendered_file_cannot_start(self):
        bad_json = Path(self.folder.name) / "bad.json"
        bad_json.write_text("{nope")
        no_url = self.write([{"title": "x"}])
        for path in (str(bad_json), no_url, str(Path(self.folder.name) / "missing.json")):
            code, output = run_main(check_pages, ["http://127.0.0.1:1/", "--rendered", path])
            self.assertEqual(code, 2, path)
            self.assertIn("cannot start", output)


if __name__ == "__main__":
    unittest.main()
