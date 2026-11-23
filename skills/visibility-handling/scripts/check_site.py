#!/usr/bin/env python3
"""Check the files and rules that cover a whole site, the way a crawler reads them.

- robots.txt: answers, size, whether Googlebot may crawl the home page
  and each --path, and what each AI crawler may do (listed by purpose:
  training, search, user fetch; a business choice, never a finding);
- sitemaps: valid, within limits, absolute same-host URLs, no ignored
  tags, and a sample of listed URLs that must answer 200, be indexable
  and canonical;
- a missing page must answer 404, not 200 (soft 404);
- on a deployed site: http goes to https, and only one host (www or not)
  serves pages;
- home page: a favicon and WebSite JSON-LD (Google's site name);
- llms.txt: its shape only if it exists (never required);
- with --crawl N: up to N same-host pages for broken links and pages
  missing from the sitemap.

With --map-host, robots.txt and sitemaps that name the live host (a
production build served on this machine) are read from the base URL
instead, so the local copy is checked, not the live site.

Matching follows Google's robots.txt rules: the most specific
user-agent group wins, the longest matching rule wins, allow wins a tie.

GET only. Exit codes: 0 nothing to fix, 1 something to fix, 2 could not start.
"""

import argparse
import re
import secrets
import socket
import sys
import xml.etree.ElementTree as ElementTree
from collections import deque
from urllib.parse import urljoin, urlsplit, urlunsplit

import crawl_http
import page_facts
from crawl_http import BLOCKER, INFO, MAJOR, MINOR, NOT_CHECKED, NOTE

ROBOTS_MAX_BYTES = 500 * 1024
SITEMAP_MAX_URLS = 50_000
SITEMAP_MAX_BYTES = 50 * 1024 * 1024
MAX_CHILD_SITEMAPS = 10
DEFAULT_SAMPLE = 20
MAX_EXAMPLES = 3
SITEMAP_NAMESPACE = "{http://www.sitemaps.org/schemas/sitemap/0.9}"

# (token, vendor, purpose). From each vendor's own page, read 2026-11-23.
AI_CRAWLERS = [
    ("GPTBot", "OpenAI", "model training"),
    ("OAI-SearchBot", "OpenAI", "ChatGPT search results"),
    ("ChatGPT-User", "OpenAI", "fetch when a user asks; robots.txt may not apply"),
    ("ClaudeBot", "Anthropic", "model training"),
    ("Claude-SearchBot", "Anthropic", "search quality"),
    ("Claude-User", "Anthropic", "fetch when a user asks"),
    ("PerplexityBot", "Perplexity", "Perplexity search"),
    ("Perplexity-User", "Perplexity", "fetch when a user asks; generally ignores robots.txt"),
    ("Google-Extended", "Google", "Gemini training and grounding; does not affect Google Search"),
]


class HostMap:
    """URLs on the live host, read from the local base URL instead (--map-host)."""

    def __init__(self, live_host, base):
        self.live_host = None
        if live_host:
            self.live_host = live_host.lower()
        self.base = urlsplit(base)

    def local(self, url):
        if self.live_host is None:
            return url
        parts = urlsplit(url)
        if (parts.hostname or "").lower() != self.live_host:
            return url
        return urlunsplit((self.base.scheme, self.base.netloc, parts.path or "/", parts.query, ""))


NO_MAP = HostMap(None, "")


def has_dns(host):
    """True when the host has an address. A lookup, not a request to the host."""
    try:
        socket.getaddrinfo(host, 443)
    except (socket.gaierror, UnicodeError):
        return False
    return True


def examples(items):
    shown = ", ".join(items[:MAX_EXAMPLES])
    if len(items) > MAX_EXAMPLES:
        shown += f" (+{len(items) - MAX_EXAMPLES} more)"
    return shown


# robots.txt


def parse_robots(text):
    """Return (groups, sitemap URLs). Each group: {"agents": [...], "rules": [(allow, path)]}."""
    groups = []
    sitemaps = []
    group = None
    last_line_was_agent = False
    for raw_line in text.splitlines():
        line = raw_line.split("#", 1)[0].strip()
        key, separator, value = line.partition(":")
        if not separator:
            continue
        key = key.strip().lower()
        value = value.strip()
        if key == "sitemap":
            sitemaps.append(value)
            continue
        if key == "user-agent":
            if group is None or not last_line_was_agent:
                group = {"agents": [], "rules": []}
                groups.append(group)
            group["agents"].append(value.lower())
            last_line_was_agent = True
            continue
        last_line_was_agent = False
        if group is None:
            # Rules before any user-agent line belong to no group.
            continue
        if key == "allow" and value:
            group["rules"].append((True, value))
        elif key == "disallow" and value:
            group["rules"].append((False, value))
    return groups, sitemaps


def rules_for(groups, token):
    """The rules that apply to a crawler: its own groups, else the * groups."""
    wanted = token.lower()
    own = []
    star = []
    for group in groups:
        if wanted in group["agents"]:
            own.extend(group["rules"])
        if "*" in group["agents"]:
            star.extend(group["rules"])
    if own:
        return own
    return star


def rule_pattern(path):
    """A robots.txt path as a regex: * is any text, a final $ ends the URL."""
    ends_here = path.endswith("$")
    if ends_here:
        path = path[:-1]
    pattern = ""
    for piece in path.split("*"):
        if pattern:
            pattern += ".*"
        pattern += re.escape(piece)
    if ends_here:
        pattern += "$"
    return re.compile(pattern)


def is_allowed(rules, path):
    """Google's rule: the longest matching path wins; on a tie, allow wins."""
    best_length = -1
    allowed = True
    for allow, rule_path in rules:
        if not rule_pattern(rule_path).match(path):
            continue
        length = len(rule_path)
        if length > best_length:
            best_length = length
            allowed = allow
        elif length == best_length and allow:
            allowed = True
    return allowed


def check_robots(client, base, paths):
    """Return (results, sitemap URLs from robots.txt)."""
    url = urljoin(base, "robots.txt")
    try:
        followed = crawl_http.follow(client, url)
    except crawl_http.Refused as error:
        return [(NOT_CHECKED, url, str(error))], []
    except crawl_http.RequestFailed as error:
        return [(MAJOR, url, f"no answer: {error}")], []
    if followed.problem:
        return [(MAJOR, url, f"{followed.problem}; Google treats robots.txt as missing")], []
    response = followed.response
    if response.status == 429 or response.status >= 500:
        return [(MAJOR, url, f"answers {response.status}; Google stops crawling the site while it does")], []
    if response.status >= 400:
        return [(NOTE, url, f"answers {response.status}: no robots.txt, so crawlers may fetch everything")], []
    results = []
    if len(response.body) > ROBOTS_MAX_BYTES:
        results.append((MAJOR, url, "larger than 500 KiB; Google ignores everything after that"))
    text = response.text()
    if "<html" in text.lower():
        results.append((MINOR, url, "answers with an HTML page (a catch-all route?); no rules apply"))
        return results, []
    groups, sitemaps = parse_robots(text)
    google_rules = rules_for(groups, "googlebot")
    for path in paths:
        if not is_allowed(google_rules, path):
            if path == "/":
                results.append((BLOCKER, url, "blocks Googlebot from the whole site (Disallow: /)"))
            else:
                results.append((BLOCKER, url, f"blocks Googlebot from {path}"))
    for token, vendor, purpose in AI_CRAWLERS:
        if is_allowed(rules_for(groups, token), "/"):
            verdict = "allowed"
        else:
            verdict = "blocked"
        results.append((INFO, url, f"{token} ({vendor}, {purpose}): {verdict}"))
    return results, sitemaps


# Sitemaps


def read_sitemap(client, url):
    """Return (root element or None, results)."""
    try:
        followed = crawl_http.follow(client, url)
    except crawl_http.Refused as error:
        return None, [(NOT_CHECKED, url, str(error))]
    except crawl_http.RequestFailed as error:
        return None, [(MAJOR, url, f"no answer: {error}")]
    if followed.problem:
        return None, [(MAJOR, url, followed.problem)]
    response = followed.response
    if response.status != 200:
        return None, [(MAJOR, url, f"sitemap answers {response.status}")]
    if len(response.body) > SITEMAP_MAX_BYTES:
        return None, [(MAJOR, url, "sitemap is larger than 50 MB; split it with a sitemap index")]
    text = response.text()
    if "<!doctype" in text.lower() or "<!entity" in text.lower():
        if "<html" in text.lower():
            return None, [(MAJOR, url, "answers with an HTML page, not a sitemap (a catch-all route?)")]
        return None, [(MAJOR, url, "sitemap has a DOCTYPE or ENTITY; not parsed (unsafe and not needed)")]
    try:
        root = ElementTree.fromstring(response.body)
    except ElementTree.ParseError as error:
        return None, [(MAJOR, url, f"sitemap is not valid XML: {error}")]
    return root, []


def child_text(element, name):
    child = element.find(SITEMAP_NAMESPACE + name)
    if child is None or child.text is None:
        return None
    return child.text.strip()


def has_child(element, name):
    return element.find(SITEMAP_NAMESPACE + name) is not None


def check_urlset(url, root, base_host, hosts=NO_MAP):
    """Return (results, listed URLs)."""
    results = []
    locations = []
    ignored_tags = set()
    lastmods = []
    for entry in root.findall(SITEMAP_NAMESPACE + "url"):
        location = child_text(entry, "loc")
        if location:
            locations.append(hosts.local(location))
        for name in ("priority", "changefreq"):
            if has_child(entry, name):
                ignored_tags.add(name)
        lastmod = child_text(entry, "lastmod")
        if lastmod:
            lastmods.append(lastmod)
    if len(locations) > SITEMAP_MAX_URLS:
        results.append((MAJOR, url, f"{len(locations)} URLs; one sitemap holds at most 50,000"))
    relative = []
    other_host = []
    for location in locations:
        parts = urlsplit(location)
        if parts.scheme not in ("http", "https"):
            relative.append(location)
        elif (parts.hostname or "").lower() != base_host:
            other_host.append(location)
    if relative:
        results.append((MAJOR, url, f"{len(relative)} URL(s) not absolute: {examples(relative)}"))
    if other_host:
        results.append((MAJOR, url, f"{len(other_host)} URL(s) on another host: {examples(other_host)}"))
    if ignored_tags:
        results.append((NOTE, url, f"{' and '.join(sorted(ignored_tags))} are ignored by Google; safe to remove"))
    if len(lastmods) > 1 and len(set(lastmods)) == 1:
        results.append((NOTE, url, "every lastmod is the same; Google ignores lastmod it cannot trust"))
    return results, locations


def check_listed_url(client, sitemap_url, location, hosts=NO_MAP):
    try:
        response = client.get(location)
    except (crawl_http.Refused, crawl_http.RequestFailed) as error:
        return [(NOT_CHECKED, location, str(error))]
    if response.status != 200:
        return [(MAJOR, location, f"listed in {sitemap_url} but answers {response.status}; list only final 200 URLs")]
    if not response.is_html():
        return []
    facts = page_facts.parse(response.text())
    for word in ("noindex", "none"):
        if word in facts.robots_directives():
            return [(MAJOR, location, f"listed in {sitemap_url} but says {word}")]
    canonicals = facts.canonicals()
    if len(canonicals) == 1:
        target = crawl_http.normalize_url(hosts.local(urljoin(location, canonicals[0])))
        if target != crawl_http.normalize_url(location):
            return [(MINOR, location, f"listed in {sitemap_url} but its canonical is {target}")]
    return []


def check_sitemaps(client, base, robots_sitemaps, sample, hosts=NO_MAP):
    """Return (results, every listed URL)."""
    sources = []
    for source in robots_sitemaps:
        sources.append(hosts.local(source))
    if not sources:
        sources = [urljoin(base, "sitemap.xml")]
    base_host = crawl_http.host_of(base)
    results = []
    listed = []
    found_one = False
    queue = deque(sources)
    children_read = 0
    while queue:
        url = queue.popleft()
        root, read_results = read_sitemap(client, url)
        results.extend(read_results)
        if root is None:
            continue
        found_one = True
        if root.tag == SITEMAP_NAMESPACE + "sitemapindex":
            for entry in root.findall(SITEMAP_NAMESPACE + "sitemap"):
                location = child_text(entry, "loc")
                if not location:
                    continue
                if children_read >= MAX_CHILD_SITEMAPS:
                    results.append((NOT_CHECKED, location, f"only the first {MAX_CHILD_SITEMAPS} child sitemaps are read"))
                    break
                children_read += 1
                queue.append(hosts.local(location))
            continue
        if root.tag != SITEMAP_NAMESPACE + "urlset":
            results.append((MAJOR, url, f"not a sitemap (root tag {root.tag})"))
            continue
        urlset_results, locations = check_urlset(url, root, base_host, hosts)
        results.extend(urlset_results)
        listed.extend(locations)
        # URLs already flagged as relative or on another host are not fetched.
        same_host = []
        for location in locations:
            if same_site_page(location, base_host):
                same_host.append(location)
        for location in same_host[:sample]:
            results.extend(check_listed_url(client, url, location, hosts))
    if not found_one and not results_have_level(results, NOT_CHECKED):
        results.append((MINOR, sources[0], "no sitemap found; list your public pages in one"))
    return results, listed


def results_have_level(results, level):
    for result in results:
        if result[0] == level:
            return True
    return False


# Pages and hosts


def check_soft_404(client, base):
    url = urljoin(base, f"visibility-missing-{secrets.token_hex(4)}")
    try:
        response = client.get(url)
    except (crawl_http.Refused, crawl_http.RequestFailed) as error:
        return [(NOT_CHECKED, url, str(error))]
    if response.status != 200:
        return []
    if not says_noindex(response):
        return [(MAJOR, url, "a missing page answers 200 (soft 404); answer 404 or add noindex on the error view")]
    # A noindex on every page (a stray one in the app shell) is not an
    # error-view fix: once it is removed, the soft 404 is back.
    try:
        home = crawl_http.follow(client, base)
    except (crawl_http.Refused, crawl_http.RequestFailed) as error:
        return [(NOT_CHECKED, url, f"a missing page answers 200 with noindex; home page not read to compare: {error}")]
    if home.response is not None and says_noindex(home.response):
        return [(MAJOR, url, "a missing page answers 200 (soft 404); the home page says noindex too, so it is not an error-view fix")]
    return [(NOTE, url, "a missing page answers 200 with noindex (Google's accepted fix for apps)")]


def says_noindex(response):
    """True when an HTML response has meta robots noindex or none."""
    if not response.is_html():
        return False
    directives = page_facts.parse(response.text()).robots_directives()
    return "noindex" in directives or "none" in directives


def swap_host(url, host):
    parts = urlsplit(url)
    netloc = host
    if parts.port:
        netloc = f"{host}:{parts.port}"
    return urlunsplit((parts.scheme, netloc, "/", "", ""))


def check_https(client, base):
    parts = urlsplit(base)
    if parts.scheme != "https":
        return [(MAJOR, base, "the site is served over http; serve it over https")]
    plain = urlunsplit(("http", parts.hostname, "/", "", ""))
    try:
        response = client.get(plain)
    except crawl_http.Refused as error:
        return [(NOT_CHECKED, plain, str(error))]
    except crawl_http.RequestFailed:
        return [(NOTE, plain, "nothing answers on http; fine if no one links to it")]
    location = urljoin(plain, response.header("Location") or "")
    goes_to_https = urlsplit(location).scheme == "https"
    if response.status in (301, 308) and goes_to_https:
        return []
    if response.status in (302, 307) and goes_to_https:
        return [(MINOR, plain, f"http goes to https with a temporary {response.status}; use 301")]
    return [(MAJOR, plain, f"http answers {response.status} without moving to https")]


def check_one_host(client, base, resolves=has_dns):
    host = crawl_http.host_of(base)
    if host.startswith("www."):
        other = host[len("www."):]
    else:
        other = "www." + host
    url = swap_host(base, other)
    try:
        client.check(url)
    except crawl_http.Refused:
        if not resolves(other):
            return [(NOTE, url, f"{other} has no DNS record; nothing to redirect")]
        return [(NOT_CHECKED, url, f"pass --allow-host {other} (after the human's yes) to check one host")]
    try:
        response = client.get(url)
    except crawl_http.RequestFailed:
        return []
    if response.status == 200:
        return [(MAJOR, url, f"both {host} and {other} serve pages; pick one and 301 the other to it")]
    return []


def check_home(client, base):
    try:
        followed = crawl_http.follow(client, base)
    except (crawl_http.Refused, crawl_http.RequestFailed) as error:
        return [(NOT_CHECKED, base, str(error))]
    if followed.problem or followed.response.status != 200:
        return [(BLOCKER, base, "the home page does not answer 200")]
    facts = page_facts.parse(followed.response.text())
    results = []
    if not facts.has_icon() and not favicon_file_exists(client, base):
        results.append((MINOR, base, "no favicon (no icon link and no /favicon.ico)"))
    named = False
    for item in facts.jsonld_items():
        if item.get("@type") == "WebSite" and item.get("name"):
            named = True
    if not named:
        results.append((NOTE, base, "no WebSite JSON-LD with a name; Google picks the site name itself"))
    return results


def favicon_file_exists(client, base):
    try:
        response = client.get(urljoin(base, "favicon.ico"))
    except (crawl_http.Refused, crawl_http.RequestFailed):
        return False
    if response.status != 200 or response.is_html():
        return False
    return True


def check_llms_txt(client, base):
    url = urljoin(base, "llms.txt")
    try:
        response = client.get(url)
    except (crawl_http.Refused, crawl_http.RequestFailed):
        return []
    if response.status != 200 or response.is_html():
        return []
    first_line = ""
    for line in response.text().splitlines():
        if line.strip():
            first_line = line.strip()
            break
    if not first_line.startswith("# "):
        return [(MINOR, url, "llms.txt must start with an H1 line like '# Name'")]
    return [(INFO, url, "llms.txt is present (optional; no search engine has shown it helps)")]


# Crawl


def same_site_page(url, base_host):
    parts = urlsplit(url)
    if parts.scheme not in ("http", "https"):
        return False
    return (parts.hostname or "").lower() == base_host


def crawl(client, base, limit, listed):
    base_host = crawl_http.host_of(base)
    start = crawl_http.normalize_url(base)
    queue = deque([(start, None)])
    seen = {start}
    results = []
    redirects = []
    indexable = []
    fetched = 0
    while queue and fetched < limit:
        url, linked_from = queue.popleft()
        try:
            response = client.get(url)
        except (crawl_http.Refused, crawl_http.RequestFailed) as error:
            results.append((NOT_CHECKED, url, str(error)))
            continue
        fetched += 1
        if 300 <= response.status < 400:
            redirects.append(url)
            continue
        if response.status >= 400:
            results.append((MAJOR, url, f"broken internal link ({response.status}), linked from {linked_from}"))
            continue
        if not response.is_html():
            continue
        facts = page_facts.parse(response.text())
        directives = facts.robots_directives()
        if "noindex" not in directives and "none" not in directives:
            indexable.append(url)
        for link in facts.internal_links(url):
            target = crawl_http.normalize_url(link)
            if same_site_page(target, base_host) and target not in seen:
                seen.add(target)
                queue.append((target, url))
    if queue:
        results.append((NOTE, base, f"crawl stopped at {limit} pages; pass a larger --crawl to see more"))
    if redirects:
        results.append((NOTE, base, f"{len(redirects)} internal link(s) redirect; link to the final URL: {examples(redirects)}"))
    if listed:
        in_sitemap = set()
        for location in listed:
            in_sitemap.add(crawl_http.normalize_url(location))
        missing = []
        for url in indexable:
            if url not in in_sitemap:
                missing.append(url)
        if missing:
            results.append((NOTE, base, f"{len(missing)} crawled page(s) not in the sitemap: {examples(missing)}"))
    return results


def parse_args(argv):
    parser = argparse.ArgumentParser(description="Check robots.txt, sitemaps and site-wide rules.")
    parser.add_argument("base", help="the site's base URL, like http://localhost:3000/")
    parser.add_argument(
        "--path",
        action="append",
        default=[],
        help="a key page path Googlebot must be allowed to crawl (the home page is always checked)",
    )
    parser.add_argument("--sample", type=int, default=DEFAULT_SAMPLE, help="sitemap URLs to fetch (default 20)")
    parser.add_argument("--crawl", type=int, default=0, help="crawl up to this many pages for broken links (default off)")
    parser.add_argument(
        "--map-host",
        metavar="LIVE_HOST",
        help="read robots.txt and sitemap URLs on this live host from the base URL instead",
    )
    crawl_http.add_target_args(parser)
    return parser.parse_args(argv)


def main(argv=None):
    args = parse_args(argv)
    base = args.base
    if not base.endswith("/"):
        base = base + "/"
    client = crawl_http.client_from_args(args)
    try:
        client.check(base)
    except crawl_http.Refused as error:
        print(f"cannot start: {error}")
        return 2

    paths = ["/"]
    for path in args.path:
        if path not in paths:
            paths.append(path)
    results = []
    robots_results, robots_sitemaps = check_robots(client, base, paths)
    results.extend(robots_results)
    hosts = HostMap(args.map_host, base)
    sitemap_results, listed = check_sitemaps(client, base, robots_sitemaps, args.sample, hosts)
    results.extend(sitemap_results)
    results.extend(check_soft_404(client, base))
    if client.is_local(crawl_http.host_of(base)):
        results.append((NOT_CHECKED, base, "https and one host (www or not): check these on the deployed site"))
    else:
        results.extend(check_https(client, base))
        results.extend(check_one_host(client, base))
    results.extend(check_home(client, base))
    results.extend(check_llms_txt(client, base))
    if args.crawl > 0:
        results.extend(crawl(client, base, args.crawl, listed))
    return crawl_http.print_results(results)


if __name__ == "__main__":
    sys.exit(main())
