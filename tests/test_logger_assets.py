"""Tests for skills/logger/assets (json_logging.py and logger.mjs).

Run from the repo root: python3 -m unittest discover tests
"""

import importlib.util
import io
import json
import logging
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
ASSETS = REPO_ROOT / "skills" / "logger" / "assets"

spec = importlib.util.spec_from_file_location("json_logging", ASSETS / "json_logging.py")
json_logging = importlib.util.module_from_spec(spec)
spec.loader.exec_module(json_logging)


class PythonLoggingTest(unittest.TestCase):
    def setUp(self):
        self.stream = io.StringIO()
        root = logging.getLogger()
        saved_handlers = list(root.handlers)
        saved_level = root.level

        def restore():
            for handler in list(root.handlers):
                root.removeHandler(handler)
            for handler in saved_handlers:
                root.addHandler(handler)
            root.setLevel(saved_level)

        self.addCleanup(restore)
        json_logging.setup_logging(level="DEBUG", stream=self.stream)
        self.log = logging.getLogger("shop.orders")

    def lines(self):
        return [json.loads(line) for line in self.stream.getvalue().splitlines()]

    def test_one_json_line_with_fields(self):
        self.log.info("order.paid", extra={"order_id": 7, "cents": 1250})
        [line] = self.lines()
        self.assertEqual(line["level"], "info")
        self.assertEqual(line["event"], "order.paid")
        self.assertEqual(line["logger"], "shop.orders")
        self.assertEqual(line["order_id"], 7)
        self.assertEqual(line["cents"], 1250)
        self.assertRegex(line["time"], r"^\d{4}-\d\d-\d\dT\d\d:\d\d:\d\d\.\d{3}Z$")

    def test_secret_keys_are_redacted_at_any_depth(self):
        self.log.info("user.login", extra={
            "password": "hunter2",
            "user": {"id": 3, "Api-Key": "k", "tokens": [{"token": "t"}]},
        })
        [line] = self.lines()
        self.assertEqual(line["password"], "[redacted]")
        self.assertEqual(line["user"]["id"], 3)
        self.assertEqual(line["user"]["Api-Key"], "[redacted]")
        self.assertEqual(line["user"]["tokens"], [{"token": "[redacted]"}])
        self.assertNotIn("hunter2", self.stream.getvalue())

    def test_line_breaks_in_input_cannot_forge_a_line(self):
        self.log.warning("search.rejected", extra={"query": 'x\n{"event": "admin.login"}'})
        self.assertEqual(len(self.stream.getvalue().splitlines()), 1)

    def test_exception_details(self):
        try:
            raise ValueError("bad cents")
        except ValueError:
            self.log.exception("order.failed", extra={"order_id": 7})
        [line] = self.lines()
        self.assertEqual(line["level"], "error")
        self.assertEqual(line["error.type"], "ValueError")
        self.assertIn("bad cents", line["error.stack"])

    def test_values_json_cannot_hold_become_text(self):
        self.log.info("x", extra={"when": object()})
        [line] = self.lines()
        self.assertIn("object object", line["when"])

    def test_trace_ids_are_renamed_and_empty_ones_dropped(self):
        self.log.info("a", extra={"otelTraceID": "abc", "otelSpanID": "0", "otelServiceName": "s"})
        [line] = self.lines()
        self.assertEqual(line["trace_id"], "abc")
        self.assertNotIn("span_id", line)
        self.assertNotIn("otelServiceName", line)

    def test_broken_value_never_breaks_the_app(self):
        class Broken:
            def __str__(self):
                raise RuntimeError("no")

        self.log.info("x", extra={"thing": Broken()})
        [line] = self.lines()
        self.assertEqual(line["event"], "log.format_failed")

    def test_level_filter(self):
        json_logging.setup_logging(level="WARNING", stream=self.stream)
        self.log.info("quiet")
        self.log.warning("loud")
        self.assertEqual([line["event"] for line in self.lines()], ["loud"])

    def test_setup_twice_keeps_one_handler(self):
        json_logging.setup_logging(stream=self.stream)
        self.log.info("once")
        self.assertEqual(len(self.lines()), 1)

    def test_request_event_ok(self):
        with json_logging.request_event(self.log, "job.invoice", invoice_id=4) as event:
            event["lines"] = 3
        [line] = self.lines()
        self.assertEqual(line["event"], "job.invoice")
        self.assertEqual(line["level"], "info")
        self.assertEqual((line["invoice_id"], line["lines"], line["outcome"]), (4, 3, "ok"))
        self.assertGreaterEqual(line["duration_ms"], 0)

    def test_request_event_error_logs_once_and_reraises(self):
        with self.assertRaises(KeyError):
            with json_logging.request_event(self.log, "job.invoice", invoice_id=4):
                raise KeyError("missing")
        [line] = self.lines()
        self.assertEqual((line["level"], line["outcome"]), ("error", "error"))
        self.assertEqual(line["error.type"], "KeyError")
        self.assertIn("error.stack", line)


NODE = shutil.which("node")

NODE_SCRIPT = r"""
import { createLogger } from %s;
const lines = [];
const log = createLogger({ service: 'shop' }, { level: 'debug', write: (t) => lines.push(t) });
log.info('order.paid', { orderId: 7, accessToken: 'abc', headers: { 'Set-Cookie': 'c', host: 'h' } });
log.warn('search.rejected', { query: 'x\n{"event":"admin"}' });
const shared = { id: 1 };
log.info('shared', { a: shared, b: shared });
const loop = { id: 2 }; loop.self = loop;
log.info('loop', { loop });
log.info('big', { n: 10n });
const ok = log.startEvent('http.request', { route: '/pay' });
ok.add({ userId: 3 }); ok.end(); ok.end();
const bad = log.startEvent('http.request', { route: '/pay' });
bad.fail(new TypeError('boom')); bad.end();
log.child({ requestId: 'r1' }).error('thrown', { error: 'plain string' });
const quiet = createLogger({}, { level: 'warn', write: (t) => lines.push(t) });
quiet.info('hidden'); quiet.debug('hidden');
const broken = { toJSON() { throw new Error('no'); } };
log.info('broken', { broken });
process.stdout.write(JSON.stringify(lines.map((t) => JSON.parse(t))));
"""


@unittest.skipIf(NODE is None, "node is not installed")
class NodeLoggerTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        with tempfile.TemporaryDirectory() as folder:
            script = Path(folder) / "run.mjs"
            target = json.dumps((ASSETS / "logger.mjs").as_uri())
            script.write_text(NODE_SCRIPT % target, encoding="utf-8")
            result = subprocess.run([NODE, str(script)], capture_output=True, text=True)
        if result.returncode != 0:
            raise AssertionError(result.stderr)
        cls.lines = json.loads(result.stdout)

    def line(self, event):
        return [line for line in self.lines if line["event"] == event]

    def test_fields_base_and_redaction(self):
        [line] = self.line("order.paid")
        self.assertEqual((line["service"], line["orderId"], line["level"]), ("shop", 7, "info"))
        self.assertEqual(line["accessToken"], "[redacted]")
        self.assertEqual(line["headers"], {"Set-Cookie": "[redacted]", "host": "h"})
        self.assertRegex(line["time"], r"Z$")

    def test_line_break_stays_inside_the_value(self):
        [line] = self.line("search.rejected")
        self.assertEqual(line["query"], 'x\n{"event":"admin"}')

    def test_shared_object_is_not_a_loop_but_a_loop_is(self):
        [shared] = self.line("shared")
        self.assertEqual(shared["a"], {"id": 1})
        self.assertEqual(shared["b"], {"id": 1})
        [loop] = self.line("loop")
        self.assertEqual(loop["loop"]["self"], "[circular]")

    def test_bigint(self):
        [line] = self.line("big")
        self.assertEqual(line["n"], "10")

    def test_events_log_once(self):
        events = self.line("http.request")
        self.assertEqual(len(events), 2)
        ok, bad = events
        self.assertEqual((ok["outcome"], ok["userId"], ok["level"]), ("ok", 3, "info"))
        self.assertGreaterEqual(ok["duration_ms"], 0)
        self.assertEqual((bad["outcome"], bad["level"]), ("error", "error"))
        self.assertEqual(bad["error"]["type"], "TypeError")
        self.assertIn("boom", bad["error"]["stack"])

    def test_child_and_non_error_values(self):
        [line] = self.line("thrown")
        self.assertEqual((line["requestId"], line["error"]), ("r1", "plain string"))

    def test_level_filter(self):
        self.assertEqual(self.line("hidden"), [])

    def test_broken_value_never_breaks_the_app(self):
        self.assertEqual(len(self.line("log.format_failed")), 1)


if __name__ == "__main__":
    unittest.main()
