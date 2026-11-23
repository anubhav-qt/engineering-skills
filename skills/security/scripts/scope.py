#!/usr/bin/env python3
"""Say whether a URL may be tested.

Allowed with no flag: hosts that resolve only to this machine
(localhost, 127.0.0.1, ::1, and names like app.localhost or shop.test
that point here). Any other host is allowed only when it is passed with
--allow-host, which the agent does only after the human said yes in
chat, for that run.

Every other script here imports this check, so none can skip it.

Exit codes: 0 every URL allowed, 1 some refused, 2 could not start.
"""

import argparse
import ipaddress
import socket
import sys
from urllib.parse import urlsplit

LOCAL = "local"
ALLOWED = "allowed by --allow-host"


class OutOfScope(Exception):
    """The URL may not be tested; the message says why."""


def host_of(url):
    parts = urlsplit(url)
    if parts.scheme not in ("http", "https"):
        raise OutOfScope(f"only http and https URLs can be tested: {url}")
    host = parts.hostname
    if not host:
        raise OutOfScope(f"the URL has no host: {url}")
    return host.lower().rstrip(".")


def resolve(host):
    try:
        infos = socket.getaddrinfo(host, None)
    except (socket.gaierror, UnicodeError) as error:
        raise OutOfScope(f"{host} does not resolve: {error}")
    return {info[4][0] for info in infos}


def is_loopback(address):
    # An IPv6 address can end in a zone like "%lo0"; the zone is not part
    # of the address itself.
    plain = address.split("%")[0]
    return ipaddress.ip_address(plain).is_loopback


def normalize_hosts(hosts):
    return {host.lower().rstrip(".") for host in hosts}


def check(url, allowed_hosts=()):
    """Return LOCAL or ALLOWED, or raise OutOfScope."""
    host = host_of(url)
    if host in normalize_hosts(allowed_hosts):
        return ALLOWED
    addresses = resolve(host)
    if not addresses:
        raise OutOfScope(f"{host} does not resolve to any address")
    for address in addresses:
        if not is_loopback(address):
            raise OutOfScope(
                f"{host} is not this machine ({address}); testing it needs "
                f"the human's yes in chat, then --allow-host {host}"
            )
    return LOCAL


def parse_args(argv):
    parser = argparse.ArgumentParser(description="Say whether URLs may be tested.")
    parser.add_argument("urls", nargs="+", help="the URLs to check")
    parser.add_argument(
        "--allow-host",
        action="append",
        default=[],
        help="a host the human said yes to in chat, for this run",
    )
    return parser.parse_args(argv)


def main(argv=None):
    args = parse_args(argv)
    refused = 0
    for url in args.urls:
        try:
            kind = check(url, args.allow_host)
        except OutOfScope as error:
            print(f"refused  {url}  {error}")
            refused += 1
            continue
        print(f"allowed  {url}  {kind}")
    if refused:
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
