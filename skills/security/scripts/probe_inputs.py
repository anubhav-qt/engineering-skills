#!/usr/bin/env python3
"""Send safe attack inputs into one parameter and judge only by strict signs.

Put FUZZ where the input goes, in the URL or the body:

    probe_inputs.py --url "http://localhost:3000/search?q=FUZZ"
    probe_inputs.py --url http://localhost:3000/api/notes --method POST \
        --data '{"title": "FUZZ"}' --header "Cookie: env:SEC_A_COOKIE" --allow-writes

Each check compares a harmless control input with the attack input, and
counts only a sign the control cannot give:
- xss: a random tag comes back unescaped;
- ssti: 1337*7331 comes back worked out as 9801547;
- sql: a quote gives SQL error text that a doubled quote does not, or a
  true and a false condition give different pages;
- path: a request for /etc/passwd returns its first line;
- cmd: "sleep 3" makes the answer slow three times out of three;
- ssrf: the server calls a one-shot listener this script starts (only
  when the target runs on this machine);
- redirect: the answer redirects to evil.example;
- leak: an attack input shows a stack trace, SQL error or file path that
  the control does not.
Payloads never change or delete data (no DROP, DELETE, UPDATE, rm).

Exit codes: 0 nothing found, 1 something to look at, 2 could not start.
"""

import argparse
import html
import http.server
import json
import re
import secrets
import sys
import threading
import time
from urllib.parse import quote, quote_plus, urljoin, urlsplit

import safe_http
import scope
from safe_http import FINDING, NOT_CHECKED, NOTE, OPEN

SLOT = "FUZZ"
CLASSES = ("xss", "ssti", "sql", "path", "cmd", "ssrf", "redirect")
SSTI_PAYLOADS = ("{{1337*7331}}", "${1337*7331}", "<%= 1337*7331 %>", "#{1337*7331}")
SSTI_RESULT = "9801547"
PASSWD_PATTERN = re.compile(r"root:[^:\n]*:0:0:")
PATH_PAYLOADS = ("../" * 8 + "etc/passwd", "/etc/passwd", "....//" * 8 + "etc/passwd")
SLEEP_SECONDS = 3
SLOW_MARGIN_SECONDS = 2.5
CMD_PAYLOADS = (";sleep 3;", "|sleep 3", "$(sleep 3)", "`sleep 3`", "&&sleep 3&&")
SSRF_WAIT_SECONDS = 3
EVIL_HOST = "evil.example"


class Target:
    """The request to probe, with SLOT where each input goes."""

    def __init__(self, method, url, data, headers, shown):
        self.method = method
        self.url = url
        self.data = data
        self.headers = headers
        self.shown = shown

    def request(self, payload, keep_slashes=False):
        url = self.url
        if SLOT in url:
            safe = ""
            if keep_slashes:
                safe = "/"
            url = url.replace(SLOT, quote(payload, safe=safe))
        body = None
        if self.data is not None:
            body = self.data.replace(SLOT, encode_for_body(self.data, payload)).encode("utf-8")
        return safe_http.Request(self.method, url, dict(self.headers), dict(self.shown), body)


def encode_for_body(data, payload):
    if data.lstrip().startswith(("{", "[")):
        # Inside a JSON string: escape it the way JSON does, without the quotes.
        return json.dumps(payload)[1:-1]
    return quote_plus(payload)


class Result:
    def __init__(self, level, check, text, request=None):
        self.level = level
        self.check = check
        self.text = text
        self.request = request


class Prober:
    def __init__(self, client, target, value):
        self.client = client
        self.target = target
        self.value = value

    def send(self, payload, keep_slashes=False):
        request = self.target.request(payload, keep_slashes)
        return request, self.client.send(request)


def without_value(text, value):
    """The answer with every echoed form of the input taken out."""
    forms = {
        value,
        html.escape(value, quote=True),
        html.escape(value, quote=True).replace("&#x27;", "&#39;"),
        html.escape(value, quote=False),
        quote(value, safe=""),
        quote_plus(value),
        json.dumps(value)[1:-1],
    }
    for form in sorted(forms, key=len, reverse=True):
        if form:
            text = text.replace(form, "")
    return text


def check_xss(prober):
    tag = f"<x-sec{secrets.token_hex(3)}>"
    results = []
    for payload in (tag, "\"'>" + tag):
        request, answer = prober.send(prober.value + payload)
        if tag not in answer.text():
            continue
        content_type = answer.header("Content-Type") or "no content type"
        if "html" in content_type.lower():
            text = "the input comes back as raw HTML; confirm it runs in the browser"
            results.append(Result(FINDING, "xss", text, request))
        else:
            text = f"the input comes back unescaped in a {content_type} answer; a risk only if a page renders it as HTML"
            results.append(Result(NOTE, "xss", text, request))
        break
    return results


def check_ssti(prober, control_text):
    if SSTI_RESULT in control_text:
        return [Result(NOT_CHECKED, "ssti", f"the page already holds {SSTI_RESULT}")]
    for payload in SSTI_PAYLOADS:
        request, answer = prober.send(prober.value + payload)
        if SSTI_RESULT in answer.text():
            text = f"the template ran {payload} and returned {SSTI_RESULT}"
            return [Result(FINDING, "ssti", text, request)]
    return []


def check_sql_error(prober, control_text):
    quote_request, quote_answer = prober.send(prober.value + "'")
    _, doubled_answer = prober.send(prober.value + "''")
    control_error = safe_http.SQL_ERROR_PATTERN.search(control_text) is not None
    quote_error = safe_http.SQL_ERROR_PATTERN.search(quote_answer.text()) is not None
    doubled_error = safe_http.SQL_ERROR_PATTERN.search(doubled_answer.text()) is not None
    if quote_error and not doubled_error and not control_error:
        text = "a single quote gives SQL error text and a doubled quote does not"
        return [Result(FINDING, "sql", text, quote_request)]
    if quote_answer.status >= 500 and doubled_answer.status < 500:
        text = "a single quote gives a server error and a doubled quote does not; may be SQL injection"
        return [Result(OPEN, "sql", text, quote_request)]
    return []


def check_sql_boolean(prober, control_text, again_text):
    control = without_value(control_text, prober.value)
    if control != without_value(again_text, prober.value):
        return [Result(NOT_CHECKED, "sql", "the page changes on every load, so true/false cannot be compared")]
    pairs = (
        ("' AND '1'='1", "' AND '1'='2"),
        (" AND 1=1", " AND 1=2"),
    )
    for true_part, false_part in pairs:
        true_value = prober.value + true_part
        false_value = prober.value + false_part
        _, true_answer = prober.send(true_value)
        false_request, false_answer = prober.send(false_value)
        if true_answer.status >= 400 or false_answer.status >= 500:
            continue
        same_when_true = without_value(true_answer.text(), true_value) == control
        differs_when_false = without_value(false_answer.text(), false_value) != control
        if same_when_true and differs_when_false:
            text = f"a true condition ({true_part.strip()}) keeps the page and a false one changes it"
            return [Result(FINDING, "sql", text, false_request)]
    return []


def check_path(prober, control_text):
    if PASSWD_PATTERN.search(control_text):
        return [Result(NOT_CHECKED, "path", "the page already looks like /etc/passwd")]
    for payload in PATH_PAYLOADS:
        for keep_slashes in (False, True):
            request, answer = prober.send(payload, keep_slashes)
            if PASSWD_PATTERN.search(answer.text()):
                text = "the answer holds /etc/passwd, so files outside the folder can be read"
                return [Result(FINDING, "path", text, request)]
    return []


def check_cmd(prober, control_seconds):
    for payload in CMD_PAYLOADS:
        request, answer = prober.send(prober.value + payload)
        if answer.seconds < control_seconds + SLOW_MARGIN_SECONDS:
            continue
        slow_count = 1
        for _ in range(2):
            _, again = prober.send(prober.value + payload)
            if again.seconds >= control_seconds + SLOW_MARGIN_SECONDS:
                slow_count += 1
        _, control = prober.send(prober.value)
        control_fast = control.seconds < control_seconds + SLOW_MARGIN_SECONDS
        if slow_count == 3 and control_fast:
            text = f"'{payload}' made the answer {SLEEP_SECONDS}s slower three times out of three"
            return [Result(FINDING, "cmd", text, request)]
        return [Result(OPEN, "cmd", f"'{payload}' was slow only {slow_count} of 3 times; check by hand", request)]
    return []


class Listener:
    """A one-shot HTTP listener on 127.0.0.1 that records the paths it is asked for."""

    def __init__(self):
        hits = []
        self.hits = hits

        class Handler(http.server.BaseHTTPRequestHandler):
            def do_GET(self):
                hits.append(self.path)
                self.send_response(204)
                self.end_headers()

            do_POST = do_GET
            do_HEAD = do_GET

            def log_message(self, *args):
                pass

        self.server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self.port = self.server.server_address[1]
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)

    def __enter__(self):
        self.thread.start()
        return self

    def __exit__(self, *args):
        self.server.shutdown()
        self.server.server_close()

    def was_hit(self, path):
        deadline = time.monotonic() + SSRF_WAIT_SECONDS
        while time.monotonic() < deadline:
            if path in self.hits:
                return True
            time.sleep(0.1)
        return path in self.hits


def check_ssrf(prober, target_kind):
    if target_kind != scope.LOCAL:
        return [Result(NOT_CHECKED, "ssrf", "the listener only works when the app runs on this machine")]
    path = f"/sec{secrets.token_hex(4)}"
    with Listener() as listener:
        payload = f"http://127.0.0.1:{listener.port}{path}"
        request, _ = prober.send(payload)
        if listener.was_hit(path):
            text = "the server fetched a URL taken from the input (SSRF)"
            return [Result(FINDING, "ssrf", text, request)]
    return []


def check_redirect(prober):
    path = f"/sec{secrets.token_hex(3)}"
    for payload in (f"https://{EVIL_HOST}{path}", f"//{EVIL_HOST}{path}"):
        request, answer = prober.send(payload)
        location = answer.header("Location")
        if not (300 <= answer.status < 400) or not location:
            continue
        if urlsplit(urljoin(request.url, location)).hostname == EVIL_HOST:
            text = f"the answer redirects to {EVIL_HOST} (open redirect)"
            return [Result(FINDING, "redirect", text, request)]
    return []


class LeakWatch:
    """Wraps a prober and notes leaks that the control answer did not show."""

    def __init__(self, prober, control_text):
        self.prober = prober
        self.value = prober.value
        self.known = set(safe_http.find_leaks(control_text))
        self.results = []

    def send(self, payload, keep_slashes=False):
        request, answer = self.prober.send(payload, keep_slashes)
        for leak in safe_http.find_leaks(answer.text()):
            if leak in self.known:
                continue
            self.known.add(leak)
            text = f"a bad input shows a {leak}"
            self.results.append(Result(FINDING, "leak", text, request))
        return request, answer


def probe(client, target, value, classes):
    target_kind = client.target_kind(target.request(value).url)
    prober = Prober(client, target, value)
    _, control = prober.send(value)
    _, again = prober.send(value)
    control_text = control.text()
    control_seconds = max(control.seconds, again.seconds)
    watch = LeakWatch(prober, control_text)

    results = []
    for name in classes:
        try:
            results.extend(run_check(name, watch, control_text, again.text(), control_seconds, target_kind))
        except (safe_http.Refused, safe_http.RequestFailed) as error:
            results.append(Result(NOT_CHECKED, name, str(error)))
    results.extend(watch.results)
    return results


def run_check(name, prober, control_text, again_text, control_seconds, target_kind):
    if name == "xss":
        return check_xss(prober)
    if name == "ssti":
        return check_ssti(prober, control_text)
    if name == "sql":
        results = check_sql_error(prober, control_text)
        if results:
            return results
        return check_sql_boolean(prober, control_text, again_text)
    if name == "path":
        return check_path(prober, control_text)
    if name == "cmd":
        return check_cmd(prober, control_seconds)
    if name == "ssrf":
        return check_ssrf(prober, target_kind)
    return check_redirect(prober)


def parse_classes(text):
    if not text:
        return list(CLASSES)
    classes = []
    for name in text.split(","):
        name = name.strip()
        if name not in CLASSES:
            raise safe_http.StartError(f"unknown check {name}; pick from {', '.join(CLASSES)}")
        classes.append(name)
    return classes


def parse_args(argv):
    parser = argparse.ArgumentParser(description="Send safe attack inputs into one parameter.")
    parser.add_argument("--url", required=True, help=f"the URL, with {SLOT} where the input goes if it goes there")
    parser.add_argument("--method", default="GET", help="the HTTP method (default GET)")
    parser.add_argument("--data", help=f"the request body, with {SLOT} where the input goes if it goes there")
    parser.add_argument("--header", action="append", default=[], help="'Name: value'; a value env:NAME reads env var NAME")
    parser.add_argument("--value", default="sec1", help="a harmless value the field normally takes (default sec1)")
    parser.add_argument("--only", help=f"comma list of checks to run: {', '.join(CLASSES)}")
    safe_http.add_target_args(parser)
    return parser.parse_args(argv)


def build_target(args):
    in_url = SLOT in args.url
    in_data = args.data is not None and SLOT in args.data
    if not in_url and not in_data:
        raise safe_http.StartError(f"put {SLOT} in --url or --data where the input goes")
    headers, shown = safe_http.parse_header_lines(args.header)
    if args.data is not None and args.data.lstrip().startswith(("{", "[")):
        if "Content-Type" not in headers:
            headers["Content-Type"] = "application/json"
            shown["Content-Type"] = "application/json"
    elif args.data is not None and "Content-Type" not in headers:
        headers["Content-Type"] = "application/x-www-form-urlencoded"
        shown["Content-Type"] = "application/x-www-form-urlencoded"
    return Target(args.method.upper(), args.url, args.data, headers, shown)


def main(argv=None):
    args = parse_args(argv)
    try:
        classes = parse_classes(args.only)
        target = build_target(args)
    except safe_http.StartError as error:
        print(f"cannot start: {error}")
        return 2

    client = safe_http.client_from_args(args)
    try:
        results = probe(client, target, args.value, classes)
    except (safe_http.Refused, safe_http.RequestFailed) as error:
        print(f"cannot start: {error}")
        return 2

    counts = {FINDING: 0, NOTE: 0, OPEN: 0, NOT_CHECKED: 0}
    for result in results:
        counts[result.level] += 1
        print(f"{result.level:<11}  {result.check}: {result.text}")
        if result.request is not None and result.level in (FINDING, OPEN):
            print(f"             proof: {result.request.curl()}")
    print(
        f"{counts[FINDING]} finding(s), {counts[NOTE]} note(s), {counts[OPEN]} open, "
        f"{counts[NOT_CHECKED]} not checked, {client.sent} requests sent"
    )
    if counts[FINDING] or counts[NOTE] or counts[OPEN]:
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
