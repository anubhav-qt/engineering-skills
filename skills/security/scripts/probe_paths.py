#!/usr/bin/env python3
"""Look for files and pages a running app should never serve.

It asks for a fixed list of paths (env files, the git folder, database
dumps, debug and status pages, API descriptions), the source maps of the
scripts the home page loads, and a page that does not exist (to see what
its error page leaks). Each path counts only when the answer holds that
file's own content, so an app that answers 200 to every path does not
fool it. Reads only.

Exit codes: 0 nothing found, 1 something to look at, 2 could not start.
"""

import argparse
import json
import re
import secrets
import sys
from urllib.parse import urljoin

import safe_http
from safe_http import FINDING, NOT_CHECKED, NOTE

ENV_PATTERN = re.compile(r"(?m)^[A-Z][A-Z0-9_]*=")
SOURCE_MAP_COMMENT = re.compile(r"[#@] sourceMappingURL=(\S+)")

# (path, level, what it means, pattern its real content matches)
PATHS = [
    ("/.env", FINDING, "env file served (config and secrets)", ENV_PATTERN),
    ("/.env.local", FINDING, "env file served (config and secrets)", ENV_PATTERN),
    ("/.env.production", FINDING, "env file served (config and secrets)", ENV_PATTERN),
    ("/.git/HEAD", FINDING, "git folder served (the whole source can be downloaded)", re.compile(r"^ref: refs/")),
    ("/.git/config", FINDING, "git folder served (the whole source can be downloaded)", re.compile(r"\[core\]")),
    ("/.htpasswd", FINDING, "password file served", re.compile(r"(?m)^[^:\s]+:\$")),
    ("/backup.sql", FINDING, "database dump served", re.compile(r"CREATE TABLE|INSERT INTO", re.IGNORECASE)),
    ("/dump.sql", FINDING, "database dump served", re.compile(r"CREATE TABLE|INSERT INTO", re.IGNORECASE)),
    ("/docker-compose.yml", FINDING, "docker-compose file served", re.compile(r"(?m)^services:")),
    ("/actuator/env", FINDING, "Spring actuator env served (config and secrets)", re.compile(r"\"propertySources\"")),
    ("/server-status", FINDING, "Apache status page served", re.compile(r"Apache Server Status")),
    ("/phpinfo.php", FINDING, "phpinfo page served", re.compile(r"phpinfo\(\)|PHP Version")),
    ("/.DS_Store", NOTE, "Finder file served (lists file names)", re.compile(r"Bud1")),
    ("/package.json", NOTE, "package.json served (lists packages and versions)", re.compile(r"\"(dev)?[dD]ependencies\"\s*:")),
    ("/openapi.json", NOTE, "API description served (fine only if the API is public)", re.compile(r"\"(openapi|swagger)\"\s*:")),
    ("/swagger.json", NOTE, "API description served (fine only if the API is public)", re.compile(r"\"(openapi|swagger)\"\s*:")),
    ("/v3/api-docs", NOTE, "API description served (fine only if the API is public)", re.compile(r"\"(openapi|swagger)\"\s*:")),
    (
        "/graphql?query=%7B__schema%7Btypes%7Bname%7D%7D%7D",
        NOTE,
        "GraphQL introspection is on (lists every type and field)",
        re.compile(r"\"__schema\""),
    ),
]


def fetch(client, url):
    return client.send(safe_http.Request("GET", url))


def body_text(response):
    # latin-1 maps every byte to a character, so binary files match too.
    return response.body.decode("latin-1")


def check_paths(client, base):
    results = []
    for path, level, meaning, pattern in PATHS:
        url = urljoin(base, path.lstrip("/"))
        try:
            response = fetch(client, url)
        except (safe_http.Refused, safe_http.RequestFailed) as error:
            results.append((NOT_CHECKED, url, str(error)))
            continue
        if response.status == 200 and pattern.search(body_text(response)):
            results.append((level, url, meaning))
    return results


def source_map_url(script_url, script_text):
    match = SOURCE_MAP_COMMENT.search(script_text)
    if match is None:
        return script_url + ".map"
    target = match.group(1)
    if target.startswith("data:"):
        return None
    return urljoin(script_url, target)


def check_source_map(client, script_url):
    try:
        script = fetch(client, script_url)
    except (safe_http.Refused, safe_http.RequestFailed) as error:
        return [(NOT_CHECKED, script_url, str(error))]
    if script.status != 200:
        return []
    script_text = script.text()
    map_url = source_map_url(script_url, script_text)
    if map_url is None:
        return [(NOTE, script_url, "source map is inlined in the script")]
    try:
        answer = fetch(client, map_url)
    except (safe_http.Refused, safe_http.RequestFailed) as error:
        return [(NOT_CHECKED, map_url, str(error))]
    if answer.status != 200:
        return []
    try:
        data = json.loads(answer.text())
    except ValueError:
        return []
    if not isinstance(data, dict) or "mappings" not in data or "sources" not in data:
        return []
    if data.get("sourcesContent"):
        return [(FINDING, map_url, "source map served with the full source code")]
    return [(NOTE, map_url, "source map served (file names only)")]


def check_source_maps(client, base):
    try:
        page = fetch(client, base)
    except (safe_http.Refused, safe_http.RequestFailed) as error:
        return [(NOT_CHECKED, base, str(error))]
    results = []
    for script_url in safe_http.script_urls(page.text(), base):
        results.extend(check_source_map(client, script_url))
    return results


def check_error_page(client, base):
    url = urljoin(base, f"sec-missing-{secrets.token_hex(4)}")
    try:
        response = fetch(client, url)
    except (safe_http.Refused, safe_http.RequestFailed) as error:
        return [(NOT_CHECKED, url, str(error))]
    results = []
    for leak in safe_http.find_leaks(response.text()):
        results.append((FINDING, url, f"error page shows a {leak}"))
    return results


def parse_args(argv):
    parser = argparse.ArgumentParser(description="Look for files and pages an app should never serve.")
    parser.add_argument("base", help="the app's base URL, like http://localhost:3000/")
    safe_http.add_target_args(parser, writes=False)
    return parser.parse_args(argv)


def main(argv=None):
    args = parse_args(argv)
    base = args.base
    if not base.endswith("/"):
        base = base + "/"
    client = safe_http.client_from_args(args)
    try:
        client.target_kind(base)
    except safe_http.Refused as error:
        print(f"cannot start: {error}")
        return 2

    results = []
    results.extend(check_paths(client, base))
    results.extend(check_source_maps(client, base))
    results.extend(check_error_page(client, base))

    counts = {FINDING: 0, NOTE: 0, NOT_CHECKED: 0}
    for level, url, text in results:
        counts[level] += 1
        print(f"{level:<11}  {url}  {text}")
    print(f"{counts[FINDING]} finding(s), {counts[NOTE]} note(s), {counts[NOT_CHECKED]} not checked")
    if counts[FINDING] or counts[NOTE]:
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
