"""Fetch pages the way a plain crawler does, only where the rules allow.

Shared by the scripts here. Rules enforced on every request:
- the host must resolve only to this machine, or be passed with
  --allow-host, which the agent does only after the human's yes in chat;
- GET only: this skill never changes anything on a site;
- redirects are never followed by urllib; follow() walks them one hop at
  a time, so every hop is checked against the rules and recorded;
- every run has a request cap, and hosts other than this machine get a
  pause between requests.
"""

import ipaddress
import socket
import time
import urllib.error
import urllib.request
from dataclasses import dataclass
from urllib.parse import urljoin, urlsplit, urlunsplit

BLOCKER = "BLOCKER"
MAJOR = "MAJOR"
MINOR = "MINOR"
NOTE = "NOTE"
INFO = "INFO"
NOT_CHECKED = "NOT CHECKED"

COUNTED_LEVELS = (BLOCKER, MAJOR, MINOR, NOTE, NOT_CHECKED)
PROBLEM_LEVELS = (BLOCKER, MAJOR, MINOR)

DEFAULT_MAX_REQUESTS = 200
DEFAULT_TIMEOUT_SECONDS = 15
REMOTE_DELAY_SECONDS = 0.5
MAX_BODY_BYTES = 5_000_000
MAX_REDIRECT_HOPS = 5
USER_AGENT = "Mozilla/5.0 (compatible; visibility-check/1.0)"


class StartError(Exception):
    """The run cannot start; the message says why."""


class Refused(Exception):
    """The request was not sent: out of scope or the cap is reached."""


class RequestFailed(Exception):
    """The request was sent, but no HTTP answer came back."""


@dataclass
class Response:
    url: str
    status: int
    headers: object
    body: bytes

    def text(self):
        return self.body.decode("utf-8", errors="replace")

    def header(self, name):
        return self.headers.get(name)

    def header_list(self, name):
        values = self.headers.get_all(name)
        if values is None:
            return []
        return values

    def is_html(self):
        content_type = self.header("Content-Type") or ""
        return "html" in content_type.lower()


def host_of(url):
    parts = urlsplit(url)
    if parts.scheme not in ("http", "https"):
        raise Refused(f"only http and https URLs can be checked: {url}")
    host = parts.hostname
    if not host:
        raise Refused(f"the URL has no host: {url}")
    return host.lower().rstrip(".")


def is_loopback(address):
    # An IPv6 address can end in a zone like "%lo0"; the zone is not part
    # of the address itself.
    plain = address.split("%")[0]
    return ipaddress.ip_address(plain).is_loopback


def is_local_host(host):
    """True when the host resolves, and only to this machine."""
    try:
        infos = socket.getaddrinfo(host, None)
    except (socket.gaierror, UnicodeError):
        return False
    addresses = {info[4][0] for info in infos}
    if not addresses:
        return False
    for address in addresses:
        if not is_loopback(address):
            return False
    return True


def normalize_url(url):
    """Drop the fragment, lowercase scheme and host, and give an empty path "/"."""
    parts = urlsplit(url)
    path = parts.path
    if path == "":
        path = "/"
    return urlunsplit((parts.scheme.lower(), parts.netloc.lower(), path, parts.query, ""))


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *args, **kwargs):
        # A 3xx comes back as the answer itself and is never followed.
        return None


class Client:
    def __init__(self, allowed_hosts=(), max_requests=DEFAULT_MAX_REQUESTS, timeout=DEFAULT_TIMEOUT_SECONDS):
        self.allowed_hosts = {host.lower().rstrip(".") for host in allowed_hosts}
        self.max_requests = max_requests
        self.timeout = timeout
        self.sent = 0
        self.local_hosts = {}
        # No proxy from the environment: requests go straight to the target.
        self.opener = urllib.request.build_opener(urllib.request.ProxyHandler({}), NoRedirect())

    def is_local(self, host):
        if host not in self.local_hosts:
            self.local_hosts[host] = is_local_host(host)
        return self.local_hosts[host]

    def check(self, url):
        """Raise Refused unless this URL may be fetched now."""
        host = host_of(url)
        if host not in self.allowed_hosts and not self.is_local(host):
            raise Refused(
                f"{host} is not this machine; checking it needs the human's "
                f"yes in chat, then --allow-host {host}"
            )
        if self.sent >= self.max_requests:
            raise Refused(f"the cap of {self.max_requests} requests is reached")

    def pause(self, url):
        if self.sent == 0:
            return
        if self.is_local(host_of(url)):
            return
        time.sleep(REMOTE_DELAY_SECONDS)

    def get(self, url, max_bytes=MAX_BODY_BYTES):
        self.check(url)
        self.pause(url)
        self.sent += 1
        request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT}, method="GET")
        try:
            answer = self.opener.open(request, timeout=self.timeout)
        except urllib.error.HTTPError as error:
            # 4xx, 5xx and unfollowed 3xx answers arrive as HTTPError.
            answer = error
        except (urllib.error.URLError, OSError) as error:
            raise RequestFailed(f"GET {url}: {error}")
        try:
            body = answer.read(max_bytes)
        except OSError as error:
            raise RequestFailed(f"GET {url}: {error}")
        finally:
            answer.close()
        return Response(url, answer.getcode(), answer.headers, body)


@dataclass
class Followed:
    """Where a URL ends up. hops lists (status, url) for each redirect."""

    hops: list
    response: object
    problem: str


def follow(client, url, max_hops=MAX_REDIRECT_HOPS):
    """GET url and walk its redirects by hand. Raises Refused or RequestFailed."""
    hops = []
    seen = {normalize_url(url)}
    current = url
    while True:
        response = client.get(current)
        location = response.header("Location")
        if response.status not in (301, 302, 303, 307, 308) or not location:
            return Followed(hops, response, "")
        hops.append((response.status, current))
        current = urljoin(current, location)
        if normalize_url(current) in seen:
            return Followed(hops, None, f"redirect loop back to {current}")
        if len(hops) >= max_hops:
            return Followed(hops, None, f"more than {max_hops} redirects")
        seen.add(normalize_url(current))


def add_target_args(parser):
    parser.add_argument(
        "--allow-host",
        action="append",
        default=[],
        help="a deployed host the human said yes to in chat, for this run (GET only)",
    )
    parser.add_argument(
        "--max-requests",
        type=int,
        default=DEFAULT_MAX_REQUESTS,
        help=f"stop after this many requests (default {DEFAULT_MAX_REQUESTS})",
    )


def client_from_args(args):
    return Client(allowed_hosts=args.allow_host, max_requests=args.max_requests)


def print_results(results):
    """Print one line per result and a summary. Return the exit code."""
    counts = {}
    for level in COUNTED_LEVELS:
        counts[level] = 0
    for level, url, text in results:
        if level in counts:
            counts[level] += 1
        print(f"{level:<11}  {url}  {text}")
    print(
        f"{counts[BLOCKER]} blocker(s), {counts[MAJOR]} major, {counts[MINOR]} minor, "
        f"{counts[NOTE]} note(s), {counts[NOT_CHECKED]} not checked"
    )
    for level in PROBLEM_LEVELS:
        if counts[level]:
            return 1
    return 0
