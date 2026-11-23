"""Tests for skills/visibility-handling/scripts/submit_indexnow.py.

Run from the repo root: python3 -m unittest discover tests
"""

import json
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from visibility_app import load, not_found, run_main, start_app, text

submit = load("submit_indexnow")

KEY = "a1b2c3d4e5f6a7b8"


def temp_dir(test):
    folder = tempfile.TemporaryDirectory()
    test.addCleanup(folder.cleanup)
    return Path(folder.name)


class KeyTest(unittest.TestCase):
    def test_key_format(self):
        self.assertTrue(submit.is_valid_key("abcd-123"))
        self.assertTrue(submit.is_valid_key("A" * 128))
        self.assertFalse(submit.is_valid_key("abc-123"))
        self.assertFalse(submit.is_valid_key("A" * 129))
        self.assertFalse(submit.is_valid_key("abcd_1234"))
        self.assertFalse(submit.is_valid_key("abcd 1234"))
        self.assertFalse(submit.is_valid_key("abcd1234\n"))
        self.assertFalse(submit.is_valid_key(""))

    def test_makes_a_key_file_holding_only_the_key(self):
        folder = temp_dir(self)
        key, made = submit.make_key(folder)
        self.assertTrue(made)
        self.assertTrue(submit.is_valid_key(key))
        self.assertEqual((folder / f"{key}.txt").read_bytes(), key.encode("utf-8"))

    def test_reuses_the_key_already_there(self):
        folder = temp_dir(self)
        first, _ = submit.make_key(folder)
        second, made = submit.make_key(folder)
        self.assertEqual(first, second)
        self.assertFalse(made)
        self.assertEqual(len(list(folder.glob("*.txt"))), 1)

    def test_other_text_files_are_not_keys(self):
        folder = temp_dir(self)
        (folder / "robots.txt").write_text("User-agent: *\n")
        (folder / "abcdefgh.txt").write_text("abcdefgh\n")
        (folder / "notes_1234.txt").write_text("notes_1234")
        self.assertIsNone(submit.find_key(folder))
        key, made = submit.make_key(folder)
        self.assertTrue(made)
        self.assertNotIn(key, ("abcdefgh", "robots"))

    def test_missing_folder_is_refused(self):
        missing = temp_dir(self) / "public"
        code, output = run_main(submit, ["key", str(missing)])
        self.assertEqual(code, 2)
        self.assertIn("not a folder", output)
        self.assertFalse(missing.exists())

    def test_key_command_prints_the_key(self):
        folder = temp_dir(self)
        code, output = run_main(submit, ["key", str(folder)])
        self.assertEqual(code, 0)
        key = submit.find_key(folder)
        self.assertIn(f"made key {key}", output)
        code, output = run_main(submit, ["key", str(folder)])
        self.assertEqual(code, 0)
        self.assertIn(f"key {key} already exists", output)


class UrlsTest(unittest.TestCase):
    def test_site_of_one_host(self):
        site = submit.site_of(["https://Example.com/a", "https://example.com/b?x=1"])
        self.assertEqual(site, ("https", "example.com", "example.com"))

    def test_mixed_hosts_are_refused(self):
        with self.assertRaises(submit.SubmitError):
            submit.site_of(["https://example.com/a", "https://www.example.com/b"])
        with self.assertRaises(submit.SubmitError):
            submit.site_of(["https://example.com/a", "https://example.com:8443/b"])

    def test_not_full_urls_are_refused(self):
        for bad in (["/a"], ["ftp://example.com/a"], ["https:///a"], []):
            with self.assertRaises(submit.SubmitError):
                submit.site_of(bad)

    def test_unique_keeps_order(self):
        self.assertEqual(submit.unique(["b", "a", "b", "c", "a"]), ["b", "a", "c"])


class Endpoint:
    """A local app that serves the key file and plays the IndexNow endpoint."""

    def __init__(self, test, key_status=200, key_body=KEY, answer=200):
        self.posts = []
        self.order = []

        def respond(method, path, headers, body):
            self.order.append((method, path))
            if method == "POST" and path == "/indexnow":
                self.posts.append((headers, body))
                if answer in (301, 302):
                    return answer, [("Location", "/elsewhere")], ""
                return answer, [("Content-Type", "text/plain")], ""
            if method == "GET" and path == f"/{KEY}.txt":
                return text(key_body, status=key_status)
            return not_found()

        self.app = start_app(test, respond)
        old_endpoint = submit.ENDPOINT
        submit.ENDPOINT = self.app.url + "indexnow"
        test.addCleanup(setattr, submit, "ENDPOINT", old_endpoint)

    def url(self, path):
        return self.app.url + path


def send_args(endpoint, *paths):
    urls = []
    for path in paths:
        urls.append(endpoint.url(path))
    return ["send", *urls, "--key", KEY, "--allow-host", "127.0.0.1"]


class SendTest(unittest.TestCase):
    def test_sends_the_urls_after_the_key_check(self):
        endpoint = Endpoint(self)
        code, output = run_main(submit, send_args(endpoint, "a", "b"))
        self.assertEqual(code, 0, output)
        self.assertIn("200  2 URL(s)", output)
        self.assertEqual(endpoint.order[0], ("GET", f"/{KEY}.txt"))
        self.assertEqual(endpoint.order[1], ("POST", "/indexnow"))
        headers, body = endpoint.posts[0]
        self.assertTrue(headers["Content-Type"].startswith("application/json"))
        self.assertEqual(
            json.loads(body),
            {
                "host": "127.0.0.1",
                "key": KEY,
                "keyLocation": endpoint.url(f"{KEY}.txt"),
                "urlList": [endpoint.url("a"), endpoint.url("b")],
            },
        )

    def test_accepted_is_a_success(self):
        endpoint = Endpoint(self, answer=202)
        code, output = run_main(submit, send_args(endpoint, "a"))
        self.assertEqual(code, 0)
        self.assertIn("key check is still pending", output)

    def test_each_error_code_is_explained(self):
        expected = {
            400: "format is wrong",
            403: "key is not valid",
            422: "not on the key's host",
            429: "wait 10 minutes or more",
            500: "Unexpected answer",
        }
        for status, words in expected.items():
            with self.subTest(status=status):
                endpoint = Endpoint(self, answer=status)
                code, output = run_main(submit, send_args(endpoint, "a"))
                self.assertEqual(code, 1)
                self.assertIn(f"{status}  1 URL(s)", output)
                self.assertIn(words, output)
                self.assertEqual(len(endpoint.posts), 1)

    def test_a_redirect_from_the_endpoint_is_not_followed(self):
        endpoint = Endpoint(self, answer=301)
        code, output = run_main(submit, send_args(endpoint, "a"))
        self.assertEqual(code, 1)
        self.assertIn("Unexpected answer", output)
        self.assertEqual(len(endpoint.posts), 1)
        self.assertNotIn(("GET", "/elsewhere"), endpoint.order)
        self.assertNotIn(("POST", "/elsewhere"), endpoint.order)

    def test_duplicates_are_sent_once(self):
        endpoint = Endpoint(self)
        run_main(submit, send_args(endpoint, "a", "b", "a"))
        _, body = endpoint.posts[0]
        self.assertEqual(json.loads(body)["urlList"], [endpoint.url("a"), endpoint.url("b")])

    def test_url_file(self):
        endpoint = Endpoint(self)
        url_file = temp_dir(self) / "urls.txt"
        url_file.write_text(f"\n{endpoint.url('c')}\n  {endpoint.url('d')}  \n\n")
        code, output = run_main(submit, [*send_args(endpoint, "a"), "--url-file", str(url_file)])
        self.assertEqual(code, 0, output)
        _, body = endpoint.posts[0]
        self.assertEqual(json.loads(body)["urlList"], [endpoint.url(p) for p in ("a", "c", "d")])

    def test_missing_url_file_sends_nothing(self):
        endpoint = Endpoint(self)
        missing = temp_dir(self) / "nope.txt"
        code, output = run_main(submit, [*send_args(endpoint, "a"), "--url-file", str(missing)])
        self.assertEqual(code, 2)
        self.assertIn("cannot read", output)
        self.assertEqual(endpoint.order, [])


class NothingSentTest(unittest.TestCase):
    def assert_not_sent(self, endpoint, args, words):
        code, output = run_main(submit, args)
        self.assertEqual(code, 2, output)
        self.assertIn("STOPPED", output)
        self.assertIn(words, output)
        self.assertEqual(endpoint.posts, [])

    def test_needs_allow_host(self):
        endpoint = Endpoint(self)
        args = ["send", endpoint.url("a"), "--key", KEY]
        self.assert_not_sent(endpoint, args, "--allow-host 127.0.0.1")
        self.assertEqual(endpoint.order, [])

    def test_allow_host_for_another_host_is_not_enough(self):
        endpoint = Endpoint(self)
        args = ["send", endpoint.url("a"), "--key", KEY, "--allow-host", "example.com"]
        self.assert_not_sent(endpoint, args, "needs the human's yes")
        self.assertEqual(endpoint.order, [])

    def test_key_file_missing(self):
        endpoint = Endpoint(self, key_status=404)
        self.assert_not_sent(endpoint, send_args(endpoint, "a"), "answered 404")

    def test_key_file_with_a_newline(self):
        endpoint = Endpoint(self, key_body=KEY + "\n")
        self.assert_not_sent(endpoint, send_args(endpoint, "a"), "newline")

    def test_key_file_with_another_key(self):
        endpoint = Endpoint(self, key_body="ffffffffffffffff")
        self.assert_not_sent(endpoint, send_args(endpoint, "a"), "does not hold the key")

    def test_key_file_holding_more_than_the_key(self):
        endpoint = Endpoint(self, key_body=KEY + KEY)
        self.assert_not_sent(endpoint, send_args(endpoint, "a"), "does not hold the key")

    def test_bad_key(self):
        endpoint = Endpoint(self)
        args = ["send", endpoint.url("a"), "--key", "short", "--allow-host", "127.0.0.1"]
        self.assert_not_sent(endpoint, args, "8 to 128")
        self.assertEqual(endpoint.order, [])

    def test_urls_on_two_hosts(self):
        endpoint = Endpoint(self)
        args = ["send", endpoint.url("a"), "https://example.com/b", "--key", KEY, "--allow-host", "127.0.0.1"]
        self.assert_not_sent(endpoint, args, "every URL must be on")
        self.assertEqual(endpoint.order, [])

    def test_no_urls(self):
        endpoint = Endpoint(self)
        self.assert_not_sent(endpoint, send_args(endpoint), "no URLs")

    def test_at_most_ten_thousand_urls(self):
        endpoint = Endpoint(self)
        paths = []
        for number in range(submit.MAX_URLS + 1):
            paths.append(f"p{number}")
        self.assert_not_sent(endpoint, send_args(endpoint, *paths), "more than 10000")
        self.assertEqual(endpoint.order, [])

    def test_exactly_ten_thousand_urls_are_sent(self):
        endpoint = Endpoint(self)
        paths = []
        for number in range(submit.MAX_URLS):
            paths.append(f"p{number}")
        code, output = run_main(submit, send_args(endpoint, *paths))
        self.assertEqual(code, 0, output)
        _, body = endpoint.posts[0]
        self.assertEqual(len(json.loads(body)["urlList"]), submit.MAX_URLS)


class CheckKeyTest(unittest.TestCase):
    def test_good_key_file(self):
        endpoint = Endpoint(self)
        code, output = run_main(submit, ["check-key", endpoint.url(""), "--key", KEY, "--allow-host", "127.0.0.1"])
        self.assertEqual(code, 0, output)
        self.assertIn("answers 200 with the key", output)
        self.assertEqual(endpoint.posts, [])

    def test_bad_key_file(self):
        endpoint = Endpoint(self, key_status=404)
        code, output = run_main(submit, ["check-key", endpoint.url(""), "--key", KEY, "--allow-host", "127.0.0.1"])
        self.assertEqual(code, 2)
        self.assertIn("deploy it first", output)

    def test_redirected_key_file_is_not_followed(self):
        endpoint = Endpoint(self, key_status=301)
        code, output = run_main(submit, ["check-key", endpoint.url(""), "--key", KEY, "--allow-host", "127.0.0.1"])
        self.assertEqual(code, 2)
        self.assertIn("answered 301", output)


if __name__ == "__main__":
    unittest.main()
