"""Tests for skills/visibility-handling/scripts/check_site.py.

Run from the repo root: python3 -m unittest discover tests
"""

import email.message
import sys
import unittest
from pathlib import Path
from xml.etree import ElementTree

sys.path.insert(0, str(Path(__file__).resolve().parent))
from visibility_app import html, load, page, redirect, run_main, start_app, text

check_site = load("check_site")
crawl_http = load("crawl_http")

HOME_HEAD = (
    '<title>Shop</title><link rel="icon" href="/icon.png">'
    '<script type="application/ld+json">{"@type": "WebSite", "name": "Shop", "url": "/"}</script>'
)
ROBOTS_OK = "User-agent: *\nDisallow: /admin\n"


def sitemap(urls, extra=""):
    entries = ""
    for url in urls:
        entries += f"<url><loc>{url}</loc>{extra}</url>"
    return f'<?xml version="1.0"?><urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">{entries}</urlset>'


def xml(body):
    return text(body, content_type="application/xml")


class RobotsRulesTest(unittest.TestCase):
    def rules(self, robots, token):
        groups, _ = check_site.parse_robots(robots)
        return check_site.rules_for(groups, token)

    def test_no_rules_allow_everything(self):
        self.assertTrue(check_site.is_allowed([], "/"))
        self.assertTrue(check_site.is_allowed(self.rules("User-agent: *\nDisallow:\n", "googlebot"), "/x"))

    def test_disallow_all(self):
        rules = self.rules("User-agent: *\nDisallow: /\n", "googlebot")
        self.assertFalse(check_site.is_allowed(rules, "/"))
        self.assertFalse(check_site.is_allowed(rules, "/page"))

    def test_longest_match_wins_and_allow_wins_a_tie(self):
        rules = self.rules("User-agent: *\nDisallow: /shop\nAllow: /shop/mugs\nAllow: /x\nDisallow: /x\n", "googlebot")
        self.assertFalse(check_site.is_allowed(rules, "/shop/cart"))
        self.assertTrue(check_site.is_allowed(rules, "/shop/mugs/blue"))
        self.assertTrue(check_site.is_allowed(rules, "/x"))

    def test_rule_order_does_not_matter(self):
        rules = self.rules("User-agent: *\nAllow: /shop\nDisallow: /shop/cart\nDisallow: /y\nAllow: /y\n", "googlebot")
        self.assertTrue(check_site.is_allowed(rules, "/shop/mugs"))
        self.assertFalse(check_site.is_allowed(rules, "/shop/cart/1"))
        self.assertTrue(check_site.is_allowed(rules, "/y"))

    def test_wildcards(self):
        rules = self.rules("User-agent: *\nDisallow: /*.pdf$\nDisallow: /private*/\n", "googlebot")
        self.assertFalse(check_site.is_allowed(rules, "/files/a.pdf"))
        self.assertTrue(check_site.is_allowed(rules, "/files/a.pdf?x=1"))
        self.assertFalse(check_site.is_allowed(rules, "/private-area/x"))
        self.assertTrue(check_site.is_allowed(rules, "/public/x"))

    def test_own_group_replaces_star_group(self):
        robots = "User-agent: *\nDisallow: /\n\nUser-agent: Googlebot\nDisallow: /admin\n"
        self.assertTrue(check_site.is_allowed(self.rules(robots, "googlebot"), "/"))
        self.assertFalse(check_site.is_allowed(self.rules(robots, "GPTBot"), "/"))

    def test_agents_listed_together_share_a_group(self):
        robots = "User-agent: GPTBot\nUser-agent: ClaudeBot\nDisallow: /\n"
        self.assertFalse(check_site.is_allowed(self.rules(robots, "ClaudeBot"), "/"))
        self.assertTrue(check_site.is_allowed(self.rules(robots, "googlebot"), "/"))

    def test_groups_for_the_same_agent_merge(self):
        robots = "User-agent: googlebot\nDisallow: /a\n\nUser-agent: googlebot\nDisallow: /b\n"
        rules = self.rules(robots, "googlebot")
        self.assertFalse(check_site.is_allowed(rules, "/a"))
        self.assertFalse(check_site.is_allowed(rules, "/b"))

    def test_comments_sitemaps_and_rules_before_any_agent(self):
        robots = "Disallow: /\n# a comment\nSitemap: https://shop.test/sitemap.xml\nUser-agent: * # all\nDisallow: /tmp # temp\n"
        groups, sitemaps = check_site.parse_robots(robots)
        self.assertEqual(sitemaps, ["https://shop.test/sitemap.xml"])
        rules = check_site.rules_for(groups, "googlebot")
        self.assertEqual(rules, [(False, "/tmp")])


class SitemapLimitTest(unittest.TestCase):
    def results_for(self, count):
        urls = []
        for number in range(count):
            urls.append(f"https://shop.test/p{number}")
        root = ElementTree.fromstring(sitemap(urls))
        results, listed = check_site.check_urlset("https://shop.test/sitemap.xml", root, "shop.test")
        self.assertEqual(len(listed), count)
        return results

    def test_fifty_thousand_urls_is_fine(self):
        self.assertEqual(self.results_for(50_000), [])

    def test_one_more_is_major(self):
        results = self.results_for(50_001)
        self.assertEqual(len(results), 1)
        self.assertEqual(results[0][0], crawl_http.MAJOR)
        self.assertIn("50001 URLs; one sitemap holds at most 50,000", results[0][2])


class CheckSiteTest(unittest.TestCase):
    def site(self, files, catch_all=None):
        """files: path -> response tuple, or a function(base url) returning one."""
        holder = {}

        def respond(method, path, headers, body):
            answer = files.get(path)
            if answer is None and catch_all is not None:
                answer = catch_all
            if answer is None:
                return 404, [("Content-Type", "text/plain")], "not found"
            if callable(answer):
                return answer(holder["url"])
            return answer

        app = start_app(self, respond)
        holder["url"] = app.url
        return app

    def good_files(self, robots=ROBOTS_OK, pages=("/",)):
        files = {"/robots.txt": text(robots)}
        for path in pages:
            files[path] = html(page(HOME_HEAD, "<h1>Shop</h1>"))

        def build_sitemap(url):
            urls = []
            for path in pages:
                urls.append(url.rstrip("/") + path)
            return xml(sitemap(urls))

        files["/sitemap.xml"] = build_sitemap
        return files

    def test_clean_site_has_nothing_to_fix(self):
        app = self.site(self.good_files())
        code, output = run_main(check_site, [app.url])
        self.assertEqual(code, 0, output)
        self.assertIn("0 blocker(s), 0 major, 0 minor, 0 note(s), 1 not checked", output)
        self.assertIn("https and one host", output)

    def test_robots_blocking_all_is_a_blocker(self):
        app = self.site(self.good_files(robots="User-agent: *\nDisallow: /\n"))
        code, output = run_main(check_site, [app.url])
        self.assertEqual(code, 1)
        self.assertIn("BLOCKER", output)
        self.assertIn("blocks Googlebot from the whole site", output)

    def test_robots_blocking_a_key_path(self):
        app = self.site(self.good_files(robots="User-agent: *\nDisallow: /pricing\n"))
        code, output = run_main(check_site, [app.url, "--path", "/pricing", "--path", "/about"])
        self.assertIn("blocks Googlebot from /pricing", output)
        self.assertNotIn("/about", output)

    def test_ai_crawlers_are_listed_as_info(self):
        robots = "User-agent: GPTBot\nDisallow: /\n\nUser-agent: *\nAllow: /\n"
        app = self.site(self.good_files(robots=robots))
        code, output = run_main(check_site, [app.url])
        self.assertEqual(code, 0, output)
        self.assertIn("GPTBot (OpenAI, model training): blocked", output)
        self.assertIn("OAI-SearchBot (OpenAI, ChatGPT search results): allowed", output)
        self.assertIn("INFO", output)

    def test_robots_server_error_is_major(self):
        files = self.good_files()
        files["/robots.txt"] = text("oops", status=503)
        app = self.site(files)
        code, output = run_main(check_site, [app.url])
        self.assertIn("answers 503; Google stops crawling", output)

    def test_no_robots_is_a_note(self):
        files = self.good_files()
        del files["/robots.txt"]
        app = self.site(files)
        code, output = run_main(check_site, [app.url])
        self.assertEqual(code, 0, output)
        self.assertIn("no robots.txt", output)

    def test_robots_that_is_html_is_minor(self):
        files = self.good_files()
        files["/robots.txt"] = html("<!doctype html><html><body>app</body></html>")
        app = self.site(files)
        code, output = run_main(check_site, [app.url])
        self.assertIn("answers with an HTML page", output)

    def test_huge_robots_is_major(self):
        files = self.good_files(robots=ROBOTS_OK + "# x\n" * 140_000)
        app = self.site(files)
        code, output = run_main(check_site, [app.url])
        self.assertIn("larger than 500 KiB", output)

    def test_sitemap_from_robots_line(self):
        files = self.good_files()
        files["/robots.txt"] = lambda url: text(ROBOTS_OK + f"Sitemap: {url}maps/main.xml\n")
        files["/maps/main.xml"] = files.pop("/sitemap.xml")
        app = self.site(files)
        code, output = run_main(check_site, [app.url])
        self.assertEqual(code, 0, output)

    def test_live_sitemap_line_is_read_locally_with_map_host(self):
        files = self.good_files()
        files["/robots.txt"] = text(ROBOTS_OK + "Sitemap: https://shop.test/sitemap.xml\n")
        files["/sitemap.xml"] = xml(sitemap(["https://shop.test/"]))
        app = self.site(files)
        code, output = run_main(check_site, [app.url])
        self.assertIn("shop.test is not this machine", output)
        code, output = run_main(check_site, [app.url, "--map-host", "shop.test"])
        self.assertEqual(code, 0, output)
        self.assertIn("0 blocker(s), 0 major, 0 minor, 0 note(s), 1 not checked", output)

    def test_no_sitemap_is_minor(self):
        files = self.good_files()
        del files["/sitemap.xml"]
        app = self.site(files)
        code, output = run_main(check_site, [app.url])
        self.assertIn("sitemap answers 404", output)
        self.assertIn("no sitemap found", output)

    def test_sitemap_with_ignored_tags_and_bad_urls(self):
        files = self.good_files()
        files["/sitemap.xml"] = lambda url: xml(sitemap(
            [url, "/relative", "https://other.example/x"],
            extra="<priority>0.8</priority><changefreq>daily</changefreq><lastmod>2026-11-23</lastmod>",
        ))
        app = self.site(files)
        code, output = run_main(check_site, [app.url])
        self.assertIn("1 URL(s) not absolute: /relative", output)
        self.assertIn("1 URL(s) on another host: https://other.example/x", output)
        self.assertIn("changefreq and priority are ignored by Google", output)
        self.assertIn("every lastmod is the same", output)
        self.assertNotIn("other.example/x  ", output)

    def test_sitemap_listing_bad_pages(self):
        files = self.good_files()
        files["/sitemap.xml"] = lambda url: xml(sitemap([url, url + "gone", url + "moved", url + "hidden", url + "copy"]))
        files["/moved"] = redirect("/")
        files["/hidden"] = html(page('<meta name="robots" content="noindex">', "x"))
        files["/copy"] = lambda url: html(page(f'<link rel="canonical" href="{url}">', "x"))
        app = self.site(files)
        code, output = run_main(check_site, [app.url])
        self.assertIn("gone  listed in", output)
        self.assertIn("but answers 404", output)
        self.assertIn("but answers 301", output)
        self.assertIn("but says noindex", output)
        self.assertIn("but its canonical is", output)

    def test_sample_limits_the_listed_urls_fetched(self):
        files = self.good_files()
        files["/sitemap.xml"] = lambda url: xml(sitemap([url, url + "gone"]))
        app = self.site(files)
        code, output = run_main(check_site, [app.url, "--sample", "1"])
        self.assertNotIn("gone  listed in", output)

    def test_sitemap_that_is_html_or_broken_or_unsafe(self):
        cases = {
            "answers with an HTML page": html("<!doctype html><html><body>app</body></html>"),
            "not valid XML": xml("<urlset><url>"),
            "DOCTYPE or ENTITY": xml('<?xml version="1.0"?><!DOCTYPE x [<!ENTITY a "b">]><urlset/>'),
            "not a sitemap (root tag": xml("<feed/>"),
        }
        for words, answer in cases.items():
            files = self.good_files()
            files["/sitemap.xml"] = answer
            app = self.site(files)
            code, output = run_main(check_site, [app.url])
            self.assertIn(words, output)
            self.assertEqual(code, 1, words)

    def test_sitemap_index_reads_children(self):
        files = self.good_files()
        files["/sitemap.xml"] = lambda url: xml(
            '<?xml version="1.0"?><sitemapindex xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">'
            f"<sitemap><loc>{url}pages.xml</loc></sitemap></sitemapindex>"
        )
        files["/pages.xml"] = lambda url: xml(sitemap([url + "gone"]))
        app = self.site(files)
        code, output = run_main(check_site, [app.url])
        self.assertIn("gone  listed in", output)
        self.assertNotIn("no sitemap found", output)

    def test_soft_404_is_major(self):
        app = self.site(self.good_files(), catch_all=html(page("<title>App</title>", '<div id="root"></div>')))
        code, output = run_main(check_site, [app.url])
        self.assertIn("MAJOR", output)
        self.assertIn("a missing page answers 200 (soft 404)", output)

    def test_soft_404_with_noindex_is_a_note(self):
        catch_all = html(page('<meta name="robots" content="noindex">', "Not found"))
        app = self.site(self.good_files(), catch_all=catch_all)
        code, output = run_main(check_site, [app.url])
        self.assertIn("answers 200 with noindex", output)
        self.assertNotIn("(soft 404)", output)

    def test_soft_404_with_noindex_on_every_page_is_major(self):
        shell = html(page('<meta name="robots" content="noindex"><title>App</title>', '<div id="root"></div>'))
        files = self.good_files()
        files["/"] = shell
        app = self.site(files, catch_all=shell)
        code, output = run_main(check_site, [app.url])
        self.assertIn("a missing page answers 200 (soft 404); the home page says noindex too", output)
        self.assertNotIn("Google's accepted fix", output)

    def test_home_without_favicon_or_site_name(self):
        files = self.good_files()
        files["/"] = html(page("<title>Shop</title>", "<h1>Shop</h1>"))
        app = self.site(files)
        code, output = run_main(check_site, [app.url])
        self.assertIn("no favicon", output)
        self.assertIn("no WebSite JSON-LD", output)

    def test_favicon_file_counts(self):
        files = self.good_files()
        files["/"] = html(page("<title>Shop</title>", "<h1>Shop</h1>"))
        files["/favicon.ico"] = text("icon", content_type="image/x-icon")
        app = self.site(files)
        code, output = run_main(check_site, [app.url])
        self.assertNotIn("no favicon", output)

    def test_home_that_fails_is_a_blocker(self):
        files = self.good_files()
        files["/"] = text("down", status=500)
        app = self.site(files)
        code, output = run_main(check_site, [app.url])
        self.assertIn("the home page does not answer 200", output)

    def test_llms_txt_shape(self):
        files = self.good_files()
        files["/llms.txt"] = text("Shop\n\n- [Docs](/docs)\n")
        app = self.site(files)
        code, output = run_main(check_site, [app.url])
        self.assertIn("llms.txt must start with an H1", output)
        files["/llms.txt"] = text("\n# Shop\n> Mugs.\n")
        app = self.site(files)
        code, output = run_main(check_site, [app.url])
        self.assertEqual(code, 0, output)
        self.assertIn("llms.txt is present (optional", output)

    def test_crawl_finds_broken_links_and_pages_missing_from_sitemap(self):
        files = self.good_files()
        files["/"] = html(page(HOME_HEAD, '<a href="/a">A</a><a href="/gone">x</a><a href="/old">o</a><a href="https://other.example/">e</a>'))
        files["/a"] = html(page("<title>A</title>", '<a href="/">home</a><a href="#top">top</a>'))
        files["/old"] = redirect("/a")
        app = self.site(files)
        code, output = run_main(check_site, [app.url, "--crawl", "10"])
        self.assertIn("broken internal link (404), linked from", output)
        self.assertIn("1 internal link(s) redirect", output)
        self.assertIn("1 crawled page(s) not in the sitemap", output)
        self.assertNotIn("other.example", output)

    def test_crawl_stops_at_the_limit(self):
        files = self.good_files()
        files["/"] = html(page(HOME_HEAD, '<a href="/a">A</a><a href="/b">B</a>'))
        app = self.site(files)
        code, output = run_main(check_site, [app.url, "--crawl", "1"])
        self.assertIn("crawl stopped at 1 pages", output)

    def test_out_of_scope_cannot_start(self):
        code, output = run_main(check_site, ["https://example.com/"])
        self.assertEqual(code, 2)


def headers(pairs):
    message = email.message.Message()
    for name, value in pairs:
        message[name] = value
    return message


class FakeClient:
    """Answers by URL from a dict, to test the deployed-site checks offline."""

    def __init__(self, answers, refused=()):
        self.answers = answers
        self.refused = refused
        self.asked = []

    def check(self, url):
        if crawl_http.host_of(url) in self.refused:
            raise crawl_http.Refused("not allowed")

    def get(self, url):
        self.check(url)
        self.asked.append(url)
        answer = self.answers.get(url)
        if answer is None:
            raise crawl_http.RequestFailed("connection refused")
        status, pairs = answer
        return crawl_http.Response(url, status, headers(pairs), b"")


class DeployedChecksTest(unittest.TestCase):
    def test_http_moves_to_https_for_good(self):
        client = FakeClient({"http://shop.test/": (301, [("Location", "https://shop.test/")])})
        self.assertEqual(check_site.check_https(client, "https://shop.test/"), [])

    def test_http_with_a_temporary_redirect_is_minor(self):
        client = FakeClient({"http://shop.test/": (302, [("Location", "https://shop.test/")])})
        [result] = check_site.check_https(client, "https://shop.test/")
        self.assertEqual(result[0], crawl_http.MINOR)

    def test_http_that_serves_pages_is_major(self):
        client = FakeClient({"http://shop.test/": (200, [])})
        [result] = check_site.check_https(client, "https://shop.test/")
        self.assertEqual(result[0], crawl_http.MAJOR)

    def test_site_on_http_is_major(self):
        [result] = check_site.check_https(FakeClient({}), "http://shop.test/")
        self.assertIn("served over http", result[2])

    def test_nothing_on_http_is_a_note(self):
        [result] = check_site.check_https(FakeClient({}), "https://shop.test/")
        self.assertEqual(result[0], crawl_http.NOTE)

    def test_both_hosts_serving_is_major(self):
        client = FakeClient({"https://www.shop.test/": (200, [])})
        [result] = check_site.check_one_host(client, "https://shop.test/")
        self.assertEqual(result[0], crawl_http.MAJOR)
        self.assertIn("pick one", result[2])

    def test_other_host_redirecting_is_fine(self):
        client = FakeClient({"https://shop.test/": (301, [("Location", "https://www.shop.test/")])})
        self.assertEqual(check_site.check_one_host(client, "https://www.shop.test/"), [])

    def test_other_host_not_allowed_is_not_checked(self):
        client = FakeClient({}, refused=("www.shop.test",))
        [result] = check_site.check_one_host(client, "https://shop.test/", resolves=lambda host: True)
        self.assertEqual(result[0], crawl_http.NOT_CHECKED)
        self.assertIn("--allow-host www.shop.test", result[2])
        self.assertEqual(client.asked, [])


if __name__ == "__main__":
    unittest.main()

    def test_other_host_with_no_dns_has_nothing_to_redirect(self):
        client = FakeClient({}, refused=("www.shop.test",))
        [result] = check_site.check_one_host(client, "https://shop.test/", resolves=lambda host: False)
        self.assertEqual(result[0], crawl_http.NOTE)
        self.assertIn("www.shop.test has no DNS record; nothing to redirect", result[2])
        self.assertEqual(client.asked, [])


class MapHostTest(unittest.TestCase):
    def test_a_live_url_is_read_from_the_base(self):
        hosts = check_site.HostMap("Shop.test", "http://localhost:4173/")
        self.assertEqual(hosts.local("https://shop.test/books?x=1#top"), "http://localhost:4173/books?x=1")
        self.assertEqual(hosts.local("https://shop.test"), "http://localhost:4173/")
        self.assertEqual(hosts.local("https://other.test/a"), "https://other.test/a")

    def test_no_map_keeps_every_url(self):
        self.assertEqual(check_site.NO_MAP.local("https://shop.test/a"), "https://shop.test/a")

