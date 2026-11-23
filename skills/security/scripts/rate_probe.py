#!/usr/bin/env python3
"""Send a short, capped burst to one endpoint and see whether it gets limited.

Use it on login, password reset, sign-up and one-time-code endpoints
with a test account and a wrong password. It stops at the first sign of
a limit: status 429 or 423, a Retry-After header, or text like "too many
attempts". It never sends more than the hard cap.

Exit codes: 0 a limit was seen, 1 no limit seen, 2 could not start.
"""

import argparse
import re
import sys

import safe_http
from safe_http import FINDING, NOT_CHECKED

HARD_CAP = 50
DEFAULT_COUNT = 30
LIMIT_STATUSES = (429, 423)
LIMIT_TEXT = re.compile(r"too many|rate limit|locked|try again later|slow down", re.IGNORECASE)


def limit_sign(response):
    """Return what shows a limit, or None."""
    if response.status in LIMIT_STATUSES:
        return f"status {response.status}"
    if response.header("Retry-After") is not None:
        return "a Retry-After header"
    match = LIMIT_TEXT.search(response.text())
    if match is not None:
        return f"the text '{match.group(0)}'"
    return None


def burst(client, request, count):
    """Return (number of the limited request or None, the sign or None, statuses seen)."""
    statuses = []
    for number in range(1, count + 1):
        response = client.send(request)
        statuses.append(response.status)
        sign = limit_sign(response)
        if sign is not None:
            return number, sign, statuses
    return None, None, statuses


def status_summary(statuses):
    counts = {}
    for status in statuses:
        counts[status] = counts.get(status, 0) + 1
    parts = []
    for status in sorted(counts):
        parts.append(f"{counts[status]}x {status}")
    return ", ".join(parts)


def parse_args(argv):
    parser = argparse.ArgumentParser(description="Send a capped burst and see whether it gets limited.")
    parser.add_argument("--url", required=True, help="the endpoint")
    parser.add_argument("--method", default="POST", help="the HTTP method (default POST)")
    parser.add_argument("--data", help="the request body, like a login with a wrong password")
    parser.add_argument("--header", action="append", default=[], help="'Name: value'; a value env:NAME reads env var NAME")
    parser.add_argument("--count", type=int, default=DEFAULT_COUNT, help=f"requests to send (default {DEFAULT_COUNT}, at most {HARD_CAP})")
    safe_http.add_target_args(parser)
    return parser.parse_args(argv)


def build_request(args):
    headers, shown = safe_http.parse_header_lines(args.header)
    body = None
    if args.data is not None:
        body = args.data.encode("utf-8")
        if "Content-Type" not in headers:
            content_type = "application/x-www-form-urlencoded"
            if args.data.lstrip().startswith(("{", "[")):
                content_type = "application/json"
            headers["Content-Type"] = content_type
            shown["Content-Type"] = content_type
    return safe_http.Request(args.method.upper(), args.url, headers, shown, body)


def main(argv=None):
    args = parse_args(argv)
    if args.count < 1 or args.count > HARD_CAP:
        print(f"cannot start: --count must be 1 to {HARD_CAP}")
        return 2
    try:
        request = build_request(args)
    except safe_http.StartError as error:
        print(f"cannot start: {error}")
        return 2

    # No pause between requests: a burst is the point. The cap keeps it small.
    client = safe_http.Client(
        allowed_hosts=args.allow_host,
        allow_writes=args.allow_writes,
        max_requests=min(args.max_requests, HARD_CAP),
        delay=0,
    )
    try:
        limited_at, sign, statuses = burst(client, request, args.count)
    except (safe_http.Refused, safe_http.RequestFailed) as error:
        print(f"{NOT_CHECKED:<11}  {error}")
        return 2

    if limited_at is not None:
        print(f"ok           limited at request {limited_at} ({sign}); statuses: {status_summary(statuses)}")
        return 0
    print(f"{FINDING:<11}  no limit after {len(statuses)} requests; statuses: {status_summary(statuses)}")
    print(f"             proof: {request.curl()}")
    return 1


if __name__ == "__main__":
    sys.exit(main())
