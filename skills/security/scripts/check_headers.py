#!/usr/bin/env python3
"""Check pages' security headers, cookies and CORS by value, not presence.

For each URL it sends a GET, three CORS probes and one TRACE, never
following redirects. A FINDING is a real hole to rate; a NOTE is
hardening, not a hole on its own; NOT CHECKED says what could not be
checked and why.

Exit codes: 0 nothing found, 1 something to look at, 2 could not start.
"""

import argparse
import re
import sys
from urllib.parse import urlsplit

import safe_http
from safe_http import FINDING, NOT_CHECKED, NOTE

ONE_YEAR_SECONDS = 31_536_000
EVIL_ORIGIN = "https://evil.example"
WIDE_SCRIPT_SOURCES = ("*", "http:", "https:", "data:")
SESSION_COOKIE_PATTERN = re.compile(r"sess|sid|auth|token|jwt|login|remember", re.IGNORECASE)
WEAK_REFERRER_POLICIES = ("unsafe-url", "no-referrer-when-downgrade")
# Headers that tell an attacker the software in use. Based on the OWASP
# Secure Headers Project's list of headers to remove.
LEAK_HEADERS = (
    "X-Powered-By",
    "X-AspNet-Version",
    "X-AspNetMvc-Version",
    "X-Generator",
    "X-Runtime",
    "X-Version",
    "X-Backend-Server",
    "X-Drupal-Cache",
    "X-Debug-Token",
    "X-Debug-Token-Link",
    "SourceMap",
    "X-SourceMap",
)


def parse_csp(policy):
    """Directive name -> list of lowercase sources. The first one wins."""
    directives = {}
    for part in policy.split(";"):
        tokens = part.strip().lower().split()
        if not tokens:
            continue
        name = tokens[0]
        if name not in directives:
            directives[name] = tokens[1:]
    return directives


def check_csp(headers):
    policy = headers.get("Content-Security-Policy")
    if policy is None:
        if headers.get("Content-Security-Policy-Report-Only") is not None:
            return [(NOTE, "CSP is report-only, so it blocks nothing")]
        return [(NOTE, "no Content-Security-Policy, so nothing limits an XSS")]

    results = []
    directives = parse_csp(policy)
    default = directives.get("default-src")
    script = directives.get("script-src", default)
    if script is None:
        results.append((NOTE, "CSP has no script-src or default-src, so scripts are not limited"))
    else:
        results.extend(check_script_sources(script))

    objects = directives.get("object-src", default)
    if objects != ["'none'"]:
        results.append((NOTE, "CSP object-src is not 'none'"))
    if "base-uri" not in directives:
        results.append((NOTE, "CSP has no base-uri"))
    return results


def check_script_sources(sources):
    results = []
    has_nonce_or_hash = False
    for source in sources:
        if source.startswith("'nonce-") or source.startswith("'sha"):
            has_nonce_or_hash = True
    # Browsers ignore 'unsafe-inline' when a nonce or hash is present.
    if "'unsafe-inline'" in sources and not has_nonce_or_hash:
        results.append((NOTE, "CSP allows inline scripts ('unsafe-inline')"))
    if "'unsafe-eval'" in sources:
        results.append((NOTE, "CSP allows eval ('unsafe-eval')"))
    for source in sources:
        if source in WIDE_SCRIPT_SOURCES:
            results.append((NOTE, f"CSP lets scripts load from anywhere ({source})"))
    return results


def check_framing(headers):
    policy = headers.get("Content-Security-Policy")
    if policy is not None and "frame-ancestors" in parse_csp(policy):
        return []
    frame_options = (headers.get("X-Frame-Options") or "").strip().upper()
    if frame_options in ("DENY", "SAMEORIGIN"):
        return []
    return [(NOTE, "other sites can frame this page (no frame-ancestors or X-Frame-Options)")]


def check_hsts(headers, https):
    if not https:
        return [(NOT_CHECKED, "HSTS and Secure cookies need HTTPS to check")]
    value = headers.get("Strict-Transport-Security")
    if value is None:
        return [(NOTE, "no Strict-Transport-Security")]
    match = re.search(r"max-age\s*=\s*\"?(\d+)", value, re.IGNORECASE)
    if match is None or int(match.group(1)) < ONE_YEAR_SECONDS:
        return [(NOTE, "Strict-Transport-Security max-age is under one year")]
    return []


def check_simple_headers(headers):
    results = []
    sniff = (headers.get("X-Content-Type-Options") or "").strip().lower()
    if sniff != "nosniff":
        results.append((NOTE, "no X-Content-Type-Options: nosniff"))
    referrer = (headers.get("Referrer-Policy") or "").strip().lower()
    if referrer in WEAK_REFERRER_POLICIES:
        results.append((NOTE, f"Referrer-Policy {referrer} sends full URLs to other sites"))
    return results


def check_leak_headers(headers):
    results = []
    server = headers.get("Server")
    if server is not None and re.search(r"\d", server):
        results.append((NOTE, f"Server header shows a version: {server}"))
    for name in LEAK_HEADERS:
        value = headers.get(name)
        if value is not None:
            results.append((NOTE, f"{name} header shows the software: {value}"))
    return results


def parse_cookie(line):
    """Return (name, set of lowercase flags, samesite value or "")."""
    parts = line.split(";")
    name = parts[0].split("=", 1)[0].strip()
    flags = set()
    samesite = ""
    for part in parts[1:]:
        key, _, value = part.strip().partition("=")
        key = key.strip().lower()
        flags.add(key)
        if key == "samesite":
            samesite = value.strip().lower()
    return name, flags, samesite


def check_cookies(set_cookie_lines, https):
    results = []
    for line in set_cookie_lines:
        name, flags, samesite = parse_cookie(line)
        looks_like_session = SESSION_COOKIE_PATTERN.search(name) is not None
        if looks_like_session and "httponly" not in flags:
            results.append((NOTE, f"cookie {name} is readable by page scripts (no HttpOnly)"))
        if https and "secure" not in flags:
            results.append((NOTE, f"cookie {name} can travel over plain HTTP (no Secure)"))
        if samesite == "none" and "secure" not in flags:
            results.append((NOTE, f"cookie {name} has SameSite=None without Secure, so browsers drop it"))
    return results


def cors_origins(url):
    host = urlsplit(url).hostname or "app"
    return [EVIL_ORIGIN, "null", f"https://{host}.evil.example"]


def check_cors_answer(origin, response):
    allowed = response.header("Access-Control-Allow-Origin")
    if allowed is None or allowed.strip() != origin:
        return []
    credentials = (response.header("Access-Control-Allow-Credentials") or "").strip().lower()
    if credentials == "true":
        return [(FINDING, f"CORS trusts Origin {origin} with cookies, so that site can read answers as the user")]
    return [(NOTE, f"CORS echoes Origin {origin} (no cookies, so only public data)")]


def check_trace(response):
    if response.status == 200 and "TRACE /" in response.text():
        return [(NOTE, "TRACE is on and echoes the request")]
    return []


def get(client, url, headers=None, method="GET"):
    request = safe_http.Request(method, url, headers or {})
    return client.send(request)


def check_url(client, url):
    """Return (whether the page answered, results)."""
    try:
        response = get(client, url)
    except (safe_http.Refused, safe_http.RequestFailed) as error:
        return False, [(NOT_CHECKED, str(error))]

    https = urlsplit(url).scheme == "https"
    headers = response.headers
    results = []
    if 300 <= response.status < 400:
        location = response.header("Location") or ""
        results.append((NOT_CHECKED, f"answered {response.status} to {location}; check that URL too"))
    results.extend(check_csp(headers))
    results.extend(check_framing(headers))
    results.extend(check_hsts(headers, https))
    results.extend(check_simple_headers(headers))
    results.extend(check_leak_headers(headers))
    results.extend(check_cookies(response.header_list("Set-Cookie"), https))

    for origin in cors_origins(url):
        try:
            answer = get(client, url, {"Origin": origin})
        except (safe_http.Refused, safe_http.RequestFailed) as error:
            results.append((NOT_CHECKED, f"CORS probe: {error}"))
            continue
        results.extend(check_cors_answer(origin, answer))

    try:
        results.extend(check_trace(get(client, url, method="TRACE")))
    except (safe_http.Refused, safe_http.RequestFailed) as error:
        results.append((NOT_CHECKED, f"TRACE probe: {error}"))
    return True, results


def parse_args(argv):
    parser = argparse.ArgumentParser(description="Check security headers, cookies and CORS.")
    parser.add_argument("urls", nargs="+", help="pages and API URLs to check")
    safe_http.add_target_args(parser, writes=False)
    return parser.parse_args(argv)


def main(argv=None):
    args = parse_args(argv)
    client = safe_http.client_from_args(args)
    counts = {FINDING: 0, NOTE: 0, NOT_CHECKED: 0}
    checked_any = False
    for url in args.urls:
        answered, results = check_url(client, url)
        if answered:
            checked_any = True
        for level, text in results:
            counts[level] += 1
            print(f"{level:<11}  {url}  {text}")

    if not checked_any:
        print("could not check any URL")
        return 2
    print(f"{counts[FINDING]} finding(s), {counts[NOTE]} note(s), {counts[NOT_CHECKED]} not checked")
    if counts[FINDING] or counts[NOTE]:
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
