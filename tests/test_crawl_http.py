"""Tests for skills/visibility-handling/scripts/crawl_http.py.

Run from the repo root: python3 -m unittest discover tests
"""

import contextlib
import io
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from visibility_app import html, load, redirect, serve_site

crawl_http = load("crawl_http")


class ScopeTest(unittest.TestCase):
    def test_local_host_is_allowed(self):
        client = crawl_http.Client()
        client.check("http://127.0.0.1:9/")
        client.check("http://localhost:9/")

    def test_other_host_is_refused_without_allow_host(self):
        client = crawl_http.Client()
        with self.assertRaises(crawl_http.Refused) as caught:
            client.check("https://example.com/")
        self.assertIn("--allow-host example.com", str(caught.exception))

    def test_allow_host_lets_that_host_through(self):
        client = crawl_http.Client(allowed_hosts=["Example.com."])
        client.check("https://example.com/")

    def test_only_http_and_https(self):
        client = crawl_http.Client()
        with self.assertRaises(crawl_http.Refused):
            client.check("file:///etc/passwd")
        with self.assertRaises(crawl_http.Refused):
            client.check("http:///nohost")

    def test_cap_stops_requests(self):
        app = serve_site(self, {"/": html("ok")})
        client = crawl_http.Client(max_requests=2)
        client.get(app.url)
        client.get(app.url)
        with self.assertRaises(crawl_http.Refused) as caught:
            client.get(app.url)
        self.assertIn("cap of 2", str(caught.exception))
        self.assertEqual(len(app.seen), 2)

    def test_only_get_is_sent(self):
        app = serve_site(self, {"/": html("ok")})
        crawl_http.Client().get(app.url)
        self.assertEqual(app.seen[0][0], "GET")


class FollowTest(unittest.TestCase):
    def test_walks_redirects_and_records_each_hop(self):
        app = serve_site(self, {
            "/a": redirect("/b", 301),
            "/b": redirect("/c", 302),
            "/c": html("done"),
        })
        followed = crawl_http.follow(crawl_http.Client(), app.url + "a")
        self.assertEqual(followed.problem, "")
        self.assertEqual(followed.hops, [(301, app.url + "a"), (302, app.url + "b")])
        self.assertEqual(followed.response.url, app.url + "c")
        self.assertEqual(followed.response.status, 200)

    def test_loop_is_a_problem(self):
        app = serve_site(self, {"/a": redirect("/b"), "/b": redirect("/a")})
        followed = crawl_http.follow(crawl_http.Client(), app.url + "a")
        self.assertIn("redirect loop", followed.problem)
        self.assertIsNone(followed.response)

    def test_too_many_hops_is_a_problem(self):
        files = {}
        for number in range(10):
            files[f"/{number}"] = redirect(f"/{number + 1}")
        app = serve_site(self, files)
        followed = crawl_http.follow(crawl_http.Client(), app.url + "0")
        self.assertIn("more than 5 redirects", followed.problem)

    def test_redirect_to_another_host_is_refused(self):
        app = serve_site(self, {"/": redirect("https://example.com/")})
        with self.assertRaises(crawl_http.Refused):
            crawl_http.follow(crawl_http.Client(), app.url)


class HelpersTest(unittest.TestCase):
    def test_normalize_url(self):
        self.assertEqual(crawl_http.normalize_url("HTTP://Shop.Test#top"), "http://shop.test/")
        self.assertEqual(crawl_http.normalize_url("https://a.test/x?y=1#z"), "https://a.test/x?y=1")

    def test_print_results_exit_codes(self):
        cases = [
            ([], 0),
            ([(crawl_http.NOTE, "u", "t"), (crawl_http.INFO, "u", "t")], 0),
            ([(crawl_http.NOT_CHECKED, "u", "t")], 0),
            ([(crawl_http.MINOR, "u", "t")], 1),
            ([(crawl_http.BLOCKER, "u", "t")], 1),
        ]
        for results, expected in cases:
            with contextlib.redirect_stdout(io.StringIO()) as output:
                code = crawl_http.print_results(results)
            self.assertEqual(code, expected, results)
            self.assertIn("blocker(s)", output.getvalue())

    def test_summary_counts(self):
        results = [(crawl_http.BLOCKER, "u", "a"), (crawl_http.MAJOR, "u", "b"), (crawl_http.MAJOR, "u", "c")]
        with contextlib.redirect_stdout(io.StringIO()) as output:
            crawl_http.print_results(results)
        self.assertIn("1 blocker(s), 2 major, 0 minor, 0 note(s), 0 not checked", output.getvalue())


if __name__ == "__main__":
    unittest.main()
