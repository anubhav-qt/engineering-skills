#!/usr/bin/env python3
"""Replay each request as every other test identity and as nobody.

The plan file (JSON) lists the test identities and the requests:

    {
      "identities": {
        "A": {"Cookie": "env:SEC_A_COOKIE"},
        "B": {"Authorization": "Bearer <B's test token>"}
      },
      "requests": [
        {"name": "A's order", "as": "A", "method": "GET",
         "url": "http://localhost:3000/api/orders/12", "marker": "order-of-A-7f3"},
        {"name": "rename A's order", "as": "A", "method": "PATCH",
         "url": "http://localhost:3000/api/orders/12", "body": {"title": "sec-was-here"},
         "check": {"url": "http://localhost:3000/api/orders/12", "marker": "sec-was-here"}}
      ]
    }

"as" is the owner. A "marker" is text only the owner's answer holds; a
leak counts only when another identity's answer holds it, or, with no
marker, when that answer is exactly the owner's. A header value
"env:NAME" is read from env var NAME and printed as $NAME; other secret
header values print as ***. Writes run only on this machine with
--allow-writes; their "check" is read as the owner after each try to see
whether the owner's data changed.

Exit codes: 0 every try blocked, 1 something to look at, 2 could not start.
"""

import argparse
import json
import sys

import safe_http
from safe_http import FINDING, NOT_CHECKED, OPEN

ANONYMOUS = "anonymous"
BLOCKED = "ok"


class Identity:
    def __init__(self, name, headers, shown):
        self.name = name
        self.headers = headers
        self.shown = shown


def load_plan(path):
    try:
        with open(path, encoding="utf-8") as plan_file:
            plan = json.load(plan_file)
    except (OSError, ValueError) as error:
        raise safe_http.StartError(f"cannot read the plan {path}: {error}")
    if not isinstance(plan, dict):
        raise safe_http.StartError("the plan must be a JSON object")

    identities = {ANONYMOUS: Identity(ANONYMOUS, {}, {})}
    for name, pairs in (plan.get("identities") or {}).items():
        if name == ANONYMOUS:
            raise safe_http.StartError("the name 'anonymous' is kept for no identity")
        headers, shown = safe_http.parse_header_dict(pairs)
        identities[name] = Identity(name, headers, shown)
    if len(identities) < 3:
        raise safe_http.StartError("the plan needs at least two identities, like A and B")

    requests = plan.get("requests") or []
    if not requests:
        raise safe_http.StartError("the plan has no requests")
    for spec in requests:
        for key in ("name", "as", "url"):
            if key not in spec:
                raise safe_http.StartError(f"a request is missing '{key}': {spec}")
        if spec["as"] not in identities:
            raise safe_http.StartError(f"request '{spec['name']}' is owned by unknown identity {spec['as']}")
    return identities, requests


def encode_body(body):
    """Return (bytes or None, extra headers)."""
    if body is None:
        return None, {}
    if isinstance(body, str):
        return body.encode("utf-8"), {}
    return json.dumps(body).encode("utf-8"), {"Content-Type": "application/json"}


def build(method, url, identity, extra_headers=None, body=None):
    data, body_headers = encode_body(body)
    headers = dict(body_headers)
    shown = dict(body_headers)
    for name, value in (extra_headers or {}).items():
        headers[name] = value
        shown[name] = value
    headers.update(identity.headers)
    shown.update(identity.shown)
    return safe_http.Request(method, url, headers, shown, data)


def is_success(status):
    return 200 <= status < 300


def judge_failure(status):
    if status >= 500:
        return OPEN, f"server error (status {status}); check by hand"
    return BLOCKED, f"blocked (status {status})"


def judge_read(owner_answer, answer, marker):
    if not is_success(answer.status):
        return judge_failure(answer.status)
    if marker:
        if marker in answer.text():
            return FINDING, f"got the owner's data (marker found, status {answer.status})"
        return BLOCKED, f"status {answer.status} but without the owner's data"
    if answer.body == owner_answer.body:
        return FINDING, f"got exactly the owner's answer (status {answer.status})"
    return OPEN, f"status {answer.status} with a different answer; check by hand or add a marker"


def judge_write(answer, changed):
    if not is_success(answer.status):
        return judge_failure(answer.status)
    if changed is None:
        return OPEN, f"write accepted (status {answer.status}); check by hand whether the owner's data changed"
    if changed:
        return FINDING, f"changed the owner's data (status {answer.status})"
    return BLOCKED, f"status {answer.status} but the owner's data did not change"


class Report:
    def __init__(self):
        self.counts = {FINDING: 0, OPEN: 0, BLOCKED: 0, NOT_CHECKED: 0}

    def add(self, level, name, who, text, proofs=()):
        self.counts[level] += 1
        if who:
            print(f"{level:<11}  {name}  as {who}: {text}")
        else:
            print(f"{level:<11}  {name}  {text}")
        for label, request in proofs:
            print(f"             {label}: {request.curl()}")


def others(identities, owner):
    return [identity for name, identity in identities.items() if name != owner]


def check_read(client, identities, spec, report):
    owner = identities[spec["as"]]
    method = spec.get("method", "GET").upper()
    marker = spec.get("marker")
    owner_request = build(method, spec["url"], owner, spec.get("headers"), spec.get("body"))
    owner_answer = client.send(owner_request)
    if not is_success(owner_answer.status):
        report.add(NOT_CHECKED, spec["name"], "", f"the owner's own request failed (status {owner_answer.status})")
        return
    if marker and marker not in owner_answer.text():
        report.add(NOT_CHECKED, spec["name"], "", "the owner's own answer does not hold the marker")
        return
    for identity in others(identities, owner.name):
        request = build(method, spec["url"], identity, spec.get("headers"), spec.get("body"))
        answer = client.send(request)
        level, text = judge_read(owner_answer, answer, marker)
        proofs = []
        if level == FINDING:
            proofs = [("owner", owner_request), (identity.name, request)]
        report.add(level, spec["name"], identity.name, text, proofs)


def marker_present(client, owner, check):
    answer = client.send(build("GET", check["url"], owner))
    if not is_success(answer.status):
        return None
    return check["marker"] in answer.text()


def check_write(client, identities, spec, report):
    owner = identities[spec["as"]]
    method = spec.get("method", "GET").upper()
    check = spec.get("check")
    if check is not None:
        before = marker_present(client, owner, check)
        if before is None:
            report.add(NOT_CHECKED, spec["name"], "", "the owner cannot read the check URL")
            return
        if before:
            report.add(NOT_CHECKED, spec["name"], "", "the check marker is there before any write; pick a new one")
            return
    for identity in others(identities, owner.name):
        request = build(method, spec["url"], identity, spec.get("headers"), spec.get("body"))
        answer = client.send(request)
        changed = None
        if check is not None and is_success(answer.status):
            changed = marker_present(client, owner, check)
        level, text = judge_write(answer, changed)
        proofs = []
        if level == FINDING:
            proofs = [(identity.name, request)]
        report.add(level, spec["name"], identity.name, text, proofs)
        if level == FINDING:
            # The marker is in place now, so later tries would all look changed.
            report.add(NOT_CHECKED, spec["name"], "", "the other identities were not tried after the first change")
            return


def run(client, identities, requests, report):
    for spec in requests:
        method = spec.get("method", "GET").upper()
        try:
            if method in safe_http.READ_METHODS:
                check_read(client, identities, spec, report)
            else:
                check_write(client, identities, spec, report)
        except (safe_http.Refused, safe_http.RequestFailed) as error:
            report.add(NOT_CHECKED, spec["name"], "", str(error))


def parse_args(argv):
    parser = argparse.ArgumentParser(description="Replay requests as other identities and as nobody.")
    parser.add_argument("--plan", required=True, help="the JSON plan file")
    safe_http.add_target_args(parser)
    return parser.parse_args(argv)


def main(argv=None):
    args = parse_args(argv)
    try:
        identities, requests = load_plan(args.plan)
    except safe_http.StartError as error:
        print(f"cannot start: {error}")
        return 2

    client = safe_http.client_from_args(args)
    report = Report()
    run(client, identities, requests, report)
    counts = report.counts
    print(
        f"{counts[FINDING]} finding(s), {counts[OPEN]} open, "
        f"{counts[BLOCKED]} blocked, {counts[NOT_CHECKED]} not checked"
    )
    if counts[FINDING] == 0 and counts[OPEN] == 0 and counts[BLOCKED] == 0:
        print("could not check anything")
        return 2
    if counts[FINDING] or counts[OPEN] or counts[NOT_CHECKED]:
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
