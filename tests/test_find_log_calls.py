"""Tests for skills/logger/scripts/find_log_calls.py.

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
SCRIPT = REPO_ROOT / "skills" / "logger" / "scripts" / "find_log_calls.py"

spec = importlib.util.spec_from_file_location("find_log_calls", SCRIPT)
find_log_calls = importlib.util.module_from_spec(spec)
spec.loader.exec_module(find_log_calls)

GIT_ENV = {
    "GIT_CONFIG_GLOBAL": os.devnull,
    "GIT_CONFIG_NOSYSTEM": "1",
    "GIT_AUTHOR_NAME": "tester",
    "GIT_AUTHOR_EMAIL": "tester@localhost",
    "GIT_COMMITTER_NAME": "tester",
    "GIT_COMMITTER_EMAIL": "tester@localhost",
}


def git(cwd, *args):
    result = subprocess.run(["git", *args], cwd=cwd, capture_output=True, text=True)
    if result.returncode != 0:
        raise AssertionError(f"git {' '.join(args)} failed: {result.stderr}")
    return result.stdout.strip()


def write(path, text):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def kinds(path, line, language):
    """The finding kinds for one line."""
    _, findings = find_log_calls.check_line(path, 1, line, language)
    return [finding.kind for finding in findings]


def levels(line, language):
    calls, _ = find_log_calls.check_line("app.x", 1, line, language)
    return [call.level for call in calls]


class PythonLineTest(unittest.TestCase):
    def test_constant_message_with_fields_is_clean(self):
        line = 'logger.info("order.paid", extra={"order_id": order.id, "cents": total})'
        self.assertEqual(kinds("app.py", line, "python"), [])
        self.assertEqual(levels(line, "python"), ["info"])

    def test_lazy_percent_arguments_are_clean(self):
        line = 'log.warning("retrying %s after %d ms", name, delay)'
        self.assertEqual(kinds("app.py", line, "python"), [])

    def test_f_string_message_is_built(self):
        line = '    logger.error(f"payment failed for {order.id}")'
        self.assertEqual(kinds("app.py", line, "python"), ["built-message"])

    def test_concatenated_message_is_built(self):
        self.assertEqual(kinds("app.py", 'logger.info("user " + name)', "python"), ["built-message"])
        self.assertEqual(kinds("app.py", 'logger.info(name + " joined")', "python"), ["built-message"])

    def test_percent_operator_and_format_are_built(self):
        self.assertEqual(kinds("app.py", 'logging.info("n=%s" % n)', "python"), ["built-message"])
        self.assertEqual(kinds("app.py", 'logging.info("n={}".format(n))', "python"), ["built-message"])

    def test_key_named_f_is_not_an_f_string(self):
        line = 'logger.info("done", extra={"f": 1})'
        self.assertEqual(kinds("app.py", line, "python"), [])

    def test_bare_print_is_flagged(self):
        self.assertEqual(kinds("app.py", 'print("saved", item)', "python"), ["print"])
        self.assertEqual(levels('print("saved", item)', "python"), ["print"])

    def test_method_named_print_is_not_a_print(self):
        self.assertEqual(kinds("app.py", "report.print(x)", "python"), [])
        self.assertEqual(kinds("app.py", "pprint(x)", "python"), [])

    def test_keep_marker_lists_but_does_not_flag(self):
        line = 'print(f"{count} files")  # logger: keep'
        self.assertEqual(kinds("cli.py", line, "python"), [])
        self.assertEqual(levels(line, "python"), ["print"])

    def test_secret_name_in_fields_is_flagged(self):
        line = 'logger.info("login", extra={"user": u, "password": pw})'
        self.assertEqual(kinds("app.py", line, "python"), ["secret-name"])

    def test_secret_in_built_message_gives_both(self):
        line = 'logger.debug(f"token={access_token}")'
        self.assertEqual(kinds("app.py", line, "python"), ["built-message", "secret-name"])

    def test_secret_word_only_in_constant_message_is_fine(self):
        line = 'logger.info("token refreshed", extra={"user_id": uid})'
        self.assertEqual(kinds("app.py", line, "python"), [])

    def test_harmless_secret_words(self):
        line = 'logger.info("llm.call", extra={"token_count": n, "password_set": True})'
        self.assertEqual(kinds("app.py", line, "python"), [])

    def test_pairs_and_camel_case(self):
        self.assertEqual(kinds("a.py", 'log.info("x", extra={"api_key": k})', "python"), ["secret-name"])
        self.assertEqual(kinds("a.py", 'log.info("x", extra={"sessionId": s})', "python"), ["secret-name"])
        self.assertEqual(kinds("a.py", 'log.info("x", extra={"APIKey": k})', "python"), ["secret-name"])
        self.assertEqual(kinds("a.py", 'log.info("x", extra={"api_key_count": k})', "python"), [])

    def test_not_a_logger(self):
        self.assertEqual(levels("catalog.info(item)", "python"), [])
        self.assertEqual(levels("dialog.error(x)", "python"), [])
        self.assertEqual(levels("x = 1", "python"), [])

    def test_logger_names(self):
        self.assertEqual(levels('self.logger.exception("boom")', "python"), ["exception"])
        self.assertEqual(levels('app_log.critical("down")', "python"), ["critical"])
        self.assertEqual(levels('logging.info("up")', "python"), ["info"])


class JavaScriptLineTest(unittest.TestCase):
    def test_structured_pino_call_is_clean(self):
        line = "logger.info({ orderId, cents }, 'order.paid');"
        self.assertEqual(kinds("app.ts", line, "js"), [])
        self.assertEqual(levels(line, "js"), ["info"])

    def test_template_literal_is_built(self):
        line = "req.log.error(`failed for ${orderId}`);"
        self.assertEqual(kinds("app.js", line, "js"), ["built-message"])

    def test_plain_template_literal_is_clean(self):
        self.assertEqual(kinds("app.js", "logger.info(`server.started`);", "js"), [])

    def test_concatenation_is_built(self):
        self.assertEqual(kinds("app.js", "logger.warn('slow ' + ms);", "js"), ["built-message"])

    def test_console_is_flagged(self):
        for name in ["log", "debug", "info", "warn", "error", "trace", "dir", "table"]:
            with self.subTest(name=name):
                self.assertEqual(kinds("app.jsx", f"console.{name}(x);", "js"), ["print"])

    def test_camel_case_logger(self):
        self.assertEqual(levels("this.appLogger.fatal(err);", "js"), ["fatal"])

    def test_secret_in_console(self):
        self.assertEqual(kinds("a.js", "console.log(user.password);", "js"), ["print", "secret-name"])

    def test_cookie_and_authorization(self):
        self.assertEqual(kinds("a.js", "logger.info({ cookie: req.headers.cookie }, 'req');", "js"), ["secret-name"])
        self.assertEqual(kinds("a.js", "logger.info({ h: req.headers.authorization }, 'req');", "js"), ["secret-name"])


class GoLineTest(unittest.TestCase):
    def test_slog_with_fields_is_clean(self):
        line = 'slog.Info("order.paid", "order_id", id, "cents", total)'
        self.assertEqual(kinds("main.go", line, "go"), [])
        self.assertEqual(levels(line, "go"), ["info"])

    def test_sprintf_message_is_built(self):
        line = 'logger.Error(fmt.Sprintf("failed %d", id))'
        self.assertEqual(kinds("main.go", line, "go"), ["built-message"])

    def test_fmt_print_is_flagged(self):
        for call in ['fmt.Println("x")', 'fmt.Printf("%d", x)', 'fmt.Print(x)', 'println(x)']:
            with self.subTest(call=call):
                self.assertEqual(kinds("main.go", call, "go"), ["print"])

    def test_fprintf_is_real_output(self):
        self.assertEqual(kinds("main.go", 'fmt.Fprintf(w, "ok")', "go"), [])


class CommentAndCliLineTest(unittest.TestCase):
    def test_comment_lines_are_skipped(self):
        cases = [
            ('    # print(f"debug {token}")', "python"),
            ("  // console.log(`token ${token}`)", "js"),
            ("   * console.log(password)", "js"),
            ("\t// fmt.Println(token)", "go"),
        ]
        for line, language in cases:
            with self.subTest(line=line):
                calls, findings = find_log_calls.check_line("app.x", 1, line, language)
                self.assertEqual((calls, findings), ([], []))

    def test_cli_prints_are_real_output(self):
        line = 'print(f"wrote {count} files")'
        calls, findings = find_log_calls.check_line("tool.py", 1, line, "python", cli=True)
        self.assertEqual((calls, findings), ([], []))

    def test_cli_files_still_check_log_calls(self):
        line = 'log.info(f"wrote {count} files")'
        _, findings = find_log_calls.check_line("tool.py", 1, line, "python", cli=True)
        self.assertEqual([finding.kind for finding in findings], ["built-message"])


class TestFileTest(unittest.TestCase):
    def test_test_files(self):
        for path in [
            "tests/test_app.py", "app/test_orders.py", "orders_test.py",
            "conftest.py", "src/__tests__/a.js", "a.test.ts", "b.spec.tsx",
            "pkg/orders_test.go", "spec/models/user.js",
        ]:
            with self.subTest(path=path):
                self.assertTrue(find_log_calls.is_test_file(path))

    def test_shipped_files(self):
        for path in ["app/orders.py", "src/latest.ts", "contest.py", "main.go"]:
            with self.subTest(path=path):
                self.assertFalse(find_log_calls.is_test_file(path))


class RepoTest(unittest.TestCase):
    def setUp(self):
        patcher = mock.patch.dict(os.environ, GIT_ENV)
        patcher.start()
        self.addCleanup(patcher.stop)
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.repo = Path(temp.name).resolve() / "project"
        self.repo.mkdir()
        git(self.repo, "init", "--quiet", "--initial-branch=main")
        write(self.repo / ".gitignore", "build/\n")
        write(self.repo / "app.py", "def pay(order):\n    return order.total\n")
        git(self.repo, "add", ".")
        git(self.repo, "commit", "--quiet", "-m", "first")

    def run_main(self, *argv):
        output = io.StringIO()
        with contextlib.redirect_stdout(output):
            code = find_log_calls.main(["--repo", str(self.repo), *argv])
        return code, output.getvalue()

    def test_nothing_changed(self):
        code, output = self.run_main()
        self.assertEqual(code, 0)
        self.assertIn("log calls added: none", output)
        self.assertIn("nothing flagged", output)

    def test_clean_change_lists_calls(self):
        write(self.repo / "app.py",
              "def pay(order):\n"
              '    logger.info("order.paid", extra={"order_id": order.id})\n'
              "    return order.total\n")
        code, output = self.run_main()
        self.assertEqual(code, 0)
        self.assertIn("log calls added (1):", output)
        self.assertIn('app.py:2  info  logger.info("order.paid"', output)

    def test_line_numbers_inside_a_longer_addition(self):
        write(self.repo / "app.py",
              "def pay(order):\n"
              "    cents = order.total\n"
              "    fee = 30\n"
              '    log.info("pay " + order.id)\n'
              "    return order.total\n")
        code, output = self.run_main()
        self.assertEqual(code, 1)
        self.assertIn("app.py:4  built-message:", output)

    def test_old_lines_are_not_scanned(self):
        write(self.repo / "app.py",
              'def pay(order):\n    print("old")\n    return order.total\n')
        git(self.repo, "commit", "--quiet", "-am", "old print")
        code, output = self.run_main()
        self.assertEqual(code, 0)
        self.assertIn("log calls added: none", output)

    def test_flagged_change_exits_1(self):
        write(self.repo / "app.py",
              "def pay(order):\n"
              '    print(f"paid {order.card_number}")\n'
              "    return order.total\n")
        code, output = self.run_main()
        self.assertEqual(code, 1)
        self.assertIn("flagged (2):", output)
        self.assertIn("app.py:2  print:", output)
        self.assertIn("app.py:2  secret-name: 'card_number'", output)

    def test_cli_marker_covers_only_its_own_file(self):
        write(self.repo / "tool.py",
              '"""Copy files."""\n'
              "# logger: cli\n"
              "\n"
              'print("copied")\n')
        write(self.repo / "app.py",
              "def pay(order):\n"
              '    print("paid")\n'
              "    return order.total\n")
        code, output = self.run_main()
        self.assertEqual(code, 1)
        self.assertIn("app.py:2  print:", output)
        self.assertNotIn("tool.py", output)

    def test_untracked_files_are_read_and_ignored_ones_are_not(self):
        write(self.repo / "new.js", "console.log('hi');\n")
        write(self.repo / "build" / "out.js", "console.log('built');\n")
        code, output = self.run_main()
        self.assertEqual(code, 1)
        self.assertIn("new.js:1  print:", output)
        self.assertNotIn("out.js", output)

    def test_test_files_are_skipped(self):
        write(self.repo / "tests" / "test_app.py", "print('debugging a test')\n")
        code, output = self.run_main()
        self.assertEqual(code, 0)

    def test_other_languages_are_named(self):
        write(self.repo / "app.rb", "puts 'hi'\n")
        write(self.repo / "README.md", "hello\n")
        code, output = self.run_main()
        self.assertEqual(code, 0)
        self.assertIn("not scanned (no rules for these files): README.md, app.rb", output)

    def test_base_counts_committed_branch_work(self):
        git(self.repo, "checkout", "--quiet", "-b", "feature")
        write(self.repo / "app.py",
              'def pay(order):\n    logger.info(f"paid {order.id}")\n    return order.total\n')
        git(self.repo, "commit", "--quiet", "-am", "log it")
        code, output = self.run_main()
        self.assertEqual(code, 0)
        code, output = self.run_main("--base", "main")
        self.assertEqual(code, 1)
        self.assertIn("app.py:2  built-message:", output)

    def test_repo_with_no_commit(self):
        fresh = self.repo.parent / "fresh"
        fresh.mkdir()
        git(fresh, "init", "--quiet")
        write(fresh / "a.py", "print(1)\n")
        output = io.StringIO()
        with contextlib.redirect_stdout(output):
            code = find_log_calls.main(["--repo", str(fresh)])
        self.assertEqual(code, 1)
        self.assertIn("a.py:1  print:", output.getvalue())

    def test_file_name_with_space(self):
        write(self.repo / "my app.py", 'logger.info("x " + y)\n')
        git(self.repo, "add", "my app.py")
        code, output = self.run_main()
        self.assertEqual(code, 1)
        self.assertIn("my app.py:1  built-message:", output)

    def test_missing_folder(self):
        output = io.StringIO()
        with contextlib.redirect_stdout(output):
            code = find_log_calls.main(["--repo", str(self.repo / "nope")])
        self.assertEqual(code, 2)
        self.assertIn("cannot start: the folder does not exist", output.getvalue())

    def test_not_a_repo(self):
        plain = self.repo.parent / "plain"
        plain.mkdir()
        output = io.StringIO()
        with contextlib.redirect_stdout(output):
            code = find_log_calls.main(["--repo", str(plain)])
        self.assertEqual(code, 2)
        self.assertIn("cannot start: git rev-parse", output.getvalue())

    def test_unknown_base(self):
        code, output = self.run_main("--base", "no-such-branch")
        self.assertEqual(code, 2)
        self.assertIn("cannot start: git merge-base", output)


if __name__ == "__main__":
    unittest.main()
