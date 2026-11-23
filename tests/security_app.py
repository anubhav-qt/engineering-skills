"""Shared helpers for the security skill's tests: script loading and a tiny local app."""

import contextlib
import http.server
import importlib
import io
import sys
import threading
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
SCRIPTS = REPO_ROOT / "skills" / "security" / "scripts"

# The scripts import each other (scope, safe_http) by name, as they do
# when run from their own folder.
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))


def load(name):
    module = importlib.import_module(name)
    # No pause between requests in tests; the pause only spares real apps.
    importlib.import_module("safe_http").DEFAULT_DELAY_SECONDS = 0
    return module


def run_main(module, argv):
    output = io.StringIO()
    with contextlib.redirect_stdout(output):
        code = module.main(argv)
    return code, output.getvalue()


class LocalApp:
    """An HTTP app on 127.0.0.1 that answers with respond(method, path, headers, body).

    respond returns (status, list of (header, value), body as str or bytes).
    Every request is kept in .seen as (method, path, headers, body).
    """

    def __init__(self, respond):
        seen = []
        self.seen = seen

        class Handler(http.server.BaseHTTPRequestHandler):
            def answer(self):
                length = int(self.headers.get("Content-Length") or 0)
                body = b""
                if length:
                    body = self.rfile.read(length)
                seen.append((self.command, self.path, self.headers, body))
                status, headers, content = respond(self.command, self.path, self.headers, body)
                if isinstance(content, str):
                    content = content.encode("utf-8")
                self.send_response(status)
                for name, value in headers:
                    self.send_header(name, value)
                self.send_header("Content-Length", str(len(content)))
                self.end_headers()
                self.wfile.write(content)

            do_GET = answer
            do_POST = answer
            do_PUT = answer
            do_PATCH = answer
            do_DELETE = answer
            do_OPTIONS = answer
            do_TRACE = answer

            def version_string(self):
                # A plain name, so the Server header shows no version.
                return "testapp"

            def log_message(self, *args):
                pass

        self.server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self.url = f"http://127.0.0.1:{self.server.server_address[1]}/"
        self.thread = threading.Thread(target=self.server.serve_forever, args=(0.05,), daemon=True)
        self.thread.start()

    def stop(self):
        self.server.shutdown()
        self.server.server_close()


def start_app(test, respond):
    app = LocalApp(respond)
    test.addCleanup(app.stop)
    return app


def html_page(body, headers=()):
    return 200, [("Content-Type", "text/html; charset=utf-8"), *headers], body


def not_found():
    return 404, [("Content-Type", "text/plain")], "not found"
