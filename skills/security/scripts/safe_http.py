"""Send HTTP requests only where the rules allow. Shared by the scripts here.

Rules enforced on every request:
- the target must pass the scope check (scope.py);
- only reads (GET, HEAD, OPTIONS, TRACE) go to hosts other than this
  machine; writes go only to this machine, and only with --allow-writes,
  which the agent passes after the human's yes for this run;
- redirects are never followed, so a request cannot hop to another host;
- every run has a request cap.
"""

import os
import re
import shlex
import time
import urllib.error
import urllib.request
from dataclasses import dataclass, field
from typing import Optional
from urllib.parse import urljoin, urlsplit

import scope

FINDING = "FINDING"
NOTE = "NOTE"
OPEN = "OPEN"
NOT_CHECKED = "NOT CHECKED"

READ_METHODS = ("GET", "HEAD", "OPTIONS", "TRACE")
DEFAULT_MAX_REQUESTS = 300
DEFAULT_TIMEOUT_SECONDS = 15
DEFAULT_DELAY_SECONDS = 0.05
MAX_BODY_BYTES = 5_000_000
MAX_SCRIPTS = 30
SENSITIVE_HEADER_WORDS = ("cookie", "authorization", "token", "key", "secret", "session")

SQL_ERROR_PATTERN = re.compile(
    r"SQL syntax|SQLITE_ERROR|sqlite3\.OperationalError|unrecognized token"
    r"|unterminated quoted string|syntax error at or near|PG::SyntaxError"
    r"|Unclosed quotation mark|ORA-\d{5}|SQLSTATE\[|near \"[^\"]*\": syntax error",
    re.IGNORECASE,
)

LEAK_PATTERNS = [
    (
        "stack trace",
        re.compile(
            r"Traceback \(most recent call last\)"
            r"|\n\s+at [\w.$<>\[\] ]+ \([^)\s]+:\d+:\d+\)"
            r"|Exception in thread \""
            r"|\tat [\w.$]+\([\w]+\.java:\d+\)"
        ),
    ),
    ("debug page", re.compile(r"Werkzeug Debugger|You're seeing this error because you have DEBUG = True")),
    ("SQL error text", SQL_ERROR_PATTERN),
    ("server file path", re.compile(r"(/home/|/Users/|/var/www/|/srv/|C:\\\\Users\\\\)[\w.-]+/")),
]


class StartError(Exception):
    """The run cannot start; the message says why."""


class Refused(Exception):
    """The request was not sent: out of scope, a write not allowed, or the cap."""


class RequestFailed(Exception):
    """The request was sent, but no HTTP answer came back."""


@dataclass
class Request:
    method: str
    url: str
    headers: dict = field(default_factory=dict)
    shown_headers: dict = field(default_factory=dict)
    body: Optional[bytes] = None

    def curl(self):
        """A command the human can run to repeat this request, secrets hidden."""
        parts = ["curl", "-i", "-X", self.method, shlex.quote(self.url)]
        for name in self.headers:
            shown = self.shown_headers.get(name, "***")
            if shown.startswith("$"):
                # Double quotes so the shell fills in the env var.
                parts.append(f'-H "{name}: {shown}"')
            else:
                parts.append("-H " + shlex.quote(f"{name}: {shown}"))
        if self.body is not None:
            parts.append("--data-raw " + shlex.quote(self.body.decode("utf-8", errors="replace")))
        return " ".join(parts)


@dataclass
class Response:
    status: int
    headers: object
    body: bytes
    seconds: float

    def text(self):
        return self.body.decode("utf-8", errors="replace")

    def header(self, name):
        return self.headers.get(name)

    def header_list(self, name):
        values = self.headers.get_all(name)
        if values is None:
            return []
        return values


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *args, **kwargs):
        # A 3xx comes back as the answer itself and is never followed.
        return None


class Client:
    def __init__(
        self,
        allowed_hosts=(),
        allow_writes=False,
        max_requests=DEFAULT_MAX_REQUESTS,
        timeout=DEFAULT_TIMEOUT_SECONDS,
        delay=None,
    ):
        self.allowed_hosts = tuple(allowed_hosts)
        self.allow_writes = allow_writes
        self.max_requests = max_requests
        self.timeout = timeout
        if delay is None:
            delay = DEFAULT_DELAY_SECONDS
        self.delay = delay
        self.sent = 0
        # No proxy from the environment: requests go straight to the target.
        self.opener = urllib.request.build_opener(urllib.request.ProxyHandler({}), NoRedirect())

    def target_kind(self, url):
        try:
            return scope.check(url, self.allowed_hosts)
        except scope.OutOfScope as error:
            raise Refused(str(error))

    def check(self, request):
        kind = self.target_kind(request.url)
        if request.method not in READ_METHODS:
            if kind != scope.LOCAL:
                raise Refused(
                    f"{request.method} is a write, and hosts other than this "
                    "machine are read-only"
                )
            if not self.allow_writes:
                raise Refused(
                    f"{request.method} is a write; pass --allow-writes only after "
                    "the human said yes to writes for this run"
                )
        if self.sent >= self.max_requests:
            raise Refused(f"the cap of {self.max_requests} requests is reached")

    def send(self, request):
        self.check(request)
        if self.sent > 0 and self.delay > 0:
            time.sleep(self.delay)
        self.sent += 1
        raw = urllib.request.Request(
            request.url,
            data=request.body,
            headers=request.headers,
            method=request.method,
        )
        start = time.monotonic()
        try:
            answer = self.opener.open(raw, timeout=self.timeout)
        except urllib.error.HTTPError as error:
            # 4xx, 5xx and unfollowed 3xx answers arrive as HTTPError.
            answer = error
        except (urllib.error.URLError, OSError) as error:
            raise RequestFailed(f"{request.method} {request.url}: {error}")
        try:
            body = answer.read(MAX_BODY_BYTES)
        except OSError as error:
            raise RequestFailed(f"{request.method} {request.url}: {error}")
        finally:
            answer.close()
        seconds = time.monotonic() - start
        return Response(answer.getcode(), answer.headers, body, seconds)


def is_sensitive_header(name):
    lowered = name.lower()
    for word in SENSITIVE_HEADER_WORDS:
        if word in lowered:
            return True
    return False


def header_value(name, value):
    """Return (real value, value safe to print). "env:NAME" reads env var NAME."""
    if value.startswith("env:"):
        variable = value[len("env:"):]
        if variable not in os.environ:
            raise StartError(f"env var {variable} is not set (used by header {name})")
        return os.environ[variable], "$" + variable
    if is_sensitive_header(name):
        return value, "***"
    return value, value


def parse_header_lines(lines):
    """Turn "Name: value" lines into (real headers, headers safe to print)."""
    pairs = {}
    for line in lines:
        name, separator, value = line.partition(":")
        if not separator or not name.strip():
            raise StartError(f"a header must look like 'Name: value': {line}")
        pairs[name.strip()] = value.strip()
    return parse_header_dict(pairs)


def parse_header_dict(pairs):
    real = {}
    shown = {}
    for name, value in pairs.items():
        real_value, shown_value = header_value(name, str(value))
        real[name] = real_value
        shown[name] = shown_value
    return real, shown


def secret_values(real, shown):
    """The header values that must never be printed."""
    secrets = []
    for name, value in real.items():
        if shown.get(name) != value:
            secrets.append(value)
    return secrets


def redact(text, secrets):
    for secret in secrets:
        if len(secret) >= 4:
            text = text.replace(secret, "***")
    return text


def shorten(text, limit=160):
    flat = " ".join(text.split())
    if len(flat) > limit:
        return flat[:limit] + "..."
    return flat


def find_leaks(text):
    """Return the names of the leak patterns found in a response body."""
    found = []
    for name, pattern in LEAK_PATTERNS:
        if pattern.search(text):
            found.append(name)
    return found


SCRIPT_SRC_PATTERN = re.compile(r"<script[^>]+src\s*=\s*[\"']([^\"']+)[\"']", re.IGNORECASE)


def script_urls(html, page_url):
    """Same-host script URLs a page loads, at most MAX_SCRIPTS."""
    page_host = urlsplit(page_url).netloc
    urls = []
    for source in SCRIPT_SRC_PATTERN.findall(html):
        url = urljoin(page_url, source)
        if urlsplit(url).netloc != page_host:
            continue
        if url not in urls:
            urls.append(url)
        if len(urls) >= MAX_SCRIPTS:
            break
    return urls


def add_target_args(parser, writes=True):
    parser.add_argument(
        "--allow-host",
        action="append",
        default=[],
        help="a host the human said yes to in chat, for this run (read-only)",
    )
    if writes:
        parser.add_argument(
            "--allow-writes",
            action="store_true",
            help="allow POST, PUT, PATCH, DELETE on this machine, after the human's yes",
        )
    parser.add_argument(
        "--max-requests",
        type=int,
        default=DEFAULT_MAX_REQUESTS,
        help=f"stop after this many requests (default {DEFAULT_MAX_REQUESTS})",
    )


def client_from_args(args, delay=None):
    allow_writes = getattr(args, "allow_writes", False)
    return Client(
        allowed_hosts=args.allow_host,
        allow_writes=allow_writes,
        max_requests=args.max_requests,
        delay=delay,
    )
