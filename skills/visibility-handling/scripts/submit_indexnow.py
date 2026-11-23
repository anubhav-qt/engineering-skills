"""Tell IndexNow engines (Bing, Yandex, Naver, Seznam, Yep) which URLs changed.

Run only after the human's yes in chat for this run (references/submit.md).
Google does not use IndexNow.

  key <public dir>               print the project's key, making one if none
  check-key <site URL> --allow-host <host>
                                 the live key file answers 200 with the key
  send <URLs> --allow-host <host> [--url-file <file>]
                                 check the key file, then POST the URLs

The key is public by design: anyone can read it at https://host/{key}.txt.
It only proves the sender controls the site.
"""

import argparse
import json
import re
import secrets
import sys
import urllib.error
import urllib.request
from pathlib import Path
from urllib.parse import urlsplit

import crawl_http
from crawl_http import Refused, RequestFailed

ENDPOINT = "https://api.indexnow.org/indexnow"
MAX_URLS = 10_000
KEY_PATTERN = re.compile(r"[A-Za-z0-9-]{8,128}")
TIMEOUT_SECONDS = 30

# What each answer from the IndexNow endpoint means (indexnow.org).
ANSWERS = {
    200: "OK: the URLs were received.",
    202: "Accepted: the URLs were received; the key check is still pending.",
    400: "Bad request: the format is wrong.",
    403: "Forbidden: the key is not valid (key file missing or different).",
    422: "Unprocessable: a URL is not on the key's host, or the key does not match.",
    429: "Too many requests: stop, wait 10 minutes or more, then send once.",
}
SUCCESS_CODES = (200, 202)


class SubmitError(Exception):
    """Nothing was sent; the message says why."""


def is_valid_key(key):
    return KEY_PATTERN.fullmatch(key) is not None


def find_key(public_dir):
    """The key whose file {key}.txt in public_dir holds exactly that key, or None."""
    for path in sorted(public_dir.glob("*.txt")):
        key = path.stem
        if not is_valid_key(key):
            continue
        if path.read_text(encoding="utf-8", errors="replace") == key:
            return key
    return None


def make_key(public_dir):
    """Return (key, made). Reuses the key already in public_dir, if any."""
    if not public_dir.is_dir():
        raise SubmitError(f"{public_dir} is not a folder; pass the folder the site serves at /")
    existing = find_key(public_dir)
    if existing is not None:
        return existing, False
    key = secrets.token_hex(16)
    # No newline: the file must hold exactly the key.
    (public_dir / f"{key}.txt").write_text(key, encoding="utf-8")
    return key, True


def read_url_file(path):
    try:
        text = Path(path).read_text(encoding="utf-8")
    except (OSError, UnicodeError) as error:
        raise SubmitError(f"cannot read {path}: {error}")
    urls = []
    for line in text.splitlines():
        line = line.strip()
        if line:
            urls.append(line)
    return urls


def site_of(urls):
    """Return (scheme, netloc, host) shared by every URL, or raise SubmitError."""
    if not urls:
        raise SubmitError("no URLs to send")
    first = urlsplit(urls[0])
    for url in urls:
        parts = urlsplit(url)
        if parts.scheme not in ("http", "https") or not parts.hostname:
            raise SubmitError(f"not a full http or https URL: {url}")
        if parts.netloc.lower() != first.netloc.lower():
            raise SubmitError(f"every URL must be on {first.netloc}; this one is not: {url}")
    return first.scheme, first.netloc.lower(), first.hostname.lower()


def unique(urls):
    seen = set()
    kept = []
    for url in urls:
        if url in seen:
            continue
        seen.add(url)
        kept.append(url)
    return kept


def require_allowed(host, allowed_hosts):
    allowed = {name.lower().rstrip(".") for name in allowed_hosts}
    if host not in allowed:
        raise SubmitError(
            f"{host} needs the human's yes in chat for this run, then --allow-host {host}"
        )


def key_url(scheme, netloc, key):
    return f"{scheme}://{netloc}/{key}.txt"


def check_key_file(client, url, key):
    """Raise SubmitError unless url answers 200 with exactly the key."""
    try:
        response = client.get(url)
    except (Refused, RequestFailed) as error:
        raise SubmitError(f"key file not checked: {error}")
    if response.status != 200:
        raise SubmitError(f"key file {url} answered {response.status}, not 200; deploy it first")
    body = response.text()
    if body == key:
        return
    if body.strip() == key:
        raise SubmitError(f"key file {url} has spaces or a newline around the key; it must hold only the key")
    raise SubmitError(f"key file {url} does not hold the key {key}")


def payload(host, key, location, urls):
    data = {"host": host, "key": key, "keyLocation": location, "urlList": urls}
    return json.dumps(data).encode("utf-8")


def post(body):
    """POST body to ENDPOINT and return the status code. Redirects are not followed."""
    request = urllib.request.Request(
        ENDPOINT,
        data=body,
        headers={"Content-Type": "application/json; charset=utf-8", "User-Agent": crawl_http.USER_AGENT},
        method="POST",
    )
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}), crawl_http.NoRedirect())
    try:
        answer = opener.open(request, timeout=TIMEOUT_SECONDS)
    except urllib.error.HTTPError as error:
        answer = error
    except (urllib.error.URLError, OSError) as error:
        raise RequestFailed(f"POST {ENDPOINT}: {error}")
    answer.close()
    return answer.getcode()


def meaning(code):
    if code in ANSWERS:
        return ANSWERS[code]
    return "Unexpected answer: report it and do not resend."


def run_key(args):
    key, made = make_key(Path(args.public_dir))
    if made:
        print(f"made key {key}; deploy {args.public_dir}/{key}.txt, then run check-key")
    else:
        print(f"key {key} already exists in {args.public_dir}")
    return 0


def checked_site(urls, args):
    """Check the URLs and the live key file. Return (host, key file URL)."""
    if not is_valid_key(args.key):
        raise SubmitError("the key must be 8 to 128 letters, digits or dashes")
    scheme, netloc, host = site_of(urls)
    require_allowed(host, args.allow_host)
    location = key_url(scheme, netloc, args.key)
    client = crawl_http.Client(allowed_hosts=args.allow_host, max_requests=1)
    check_key_file(client, location, args.key)
    return host, location


def run_check_key(args):
    _, location = checked_site([args.site], args)
    print(f"OK  key file {location} answers 200 with the key")
    return 0


def run_send(args):
    urls = list(args.urls)
    if args.url_file:
        urls.extend(read_url_file(args.url_file))
    urls = unique(urls)
    if len(urls) > MAX_URLS:
        raise SubmitError(f"{len(urls)} URLs is more than {MAX_URLS}; send only the changed ones")
    host, location = checked_site(urls, args)
    try:
        code = post(payload(host, args.key, location, urls))
    except RequestFailed as error:
        raise SubmitError(f"not sent: {error}")
    print(f"{code}  {len(urls)} URL(s) for {host}: {meaning(code)}")
    if code in SUCCESS_CODES:
        return 0
    return 1


def build_parser():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    commands = parser.add_subparsers(dest="command", required=True)

    key = commands.add_parser("key", help="print the project's key, making one if none")
    key.add_argument("public_dir", help="the project folder the site serves at / (for example public/)")
    key.set_defaults(run=run_key)

    check = commands.add_parser("check-key", help="check the live key file")
    check.add_argument("site", help="the live site URL, for example https://example.com/")
    check.set_defaults(run=run_check_key)

    send = commands.add_parser("send", help="check the key file, then send the URLs")
    send.add_argument("urls", nargs="*", help="changed URLs, all on one host")
    send.add_argument("--url-file", help="a file with one URL per line")
    send.set_defaults(run=run_send)

    for command in (check, send):
        command.add_argument("--key", required=True, help="the key from the key command")
        command.add_argument(
            "--allow-host",
            action="append",
            default=[],
            help="the live host the human said yes to in chat, for this run",
        )
    return parser


def main(argv=None):
    args = build_parser().parse_args(argv)
    try:
        return args.run(args)
    except SubmitError as error:
        print(f"STOPPED  {error}")
        return 2


if __name__ == "__main__":
    sys.exit(main())
