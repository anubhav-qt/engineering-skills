#!/usr/bin/env python3
"""See each page the way a search or AI crawler sees it, with no JavaScript.

Give it the public pages to check (the ones a change adds or touches).
For each page it reports: final status and redirects, noindex in the
header or a meta tag, title, description, canonical, lang, viewport, H1,
social cards, JSON-LD, hreflang return links and images with no alt.
Across pages: titles and descriptions used more than once.

With --rendered it also compares the raw HTML with what the built-in
browser rendered (the JSON from assets/page_fields.js): anything that
only appears after JavaScript is invisible to AI crawlers.

With --kept-out, pages meant to stay out of search (an admin page, a
thank-you page) are checked only for the noindex that keeps them out.

GET only. Exit codes: 0 nothing to fix, 1 something to fix, 2 could not start.
"""

import argparse
import json
import re
import sys
from urllib.parse import urljoin, urlsplit

import crawl_http
import page_facts
from crawl_http import BLOCKER, MAJOR, MINOR, NOT_CHECKED, NOTE

# Directives in X-Robots-Tag that take a value after a colon, so the part
# before the colon is not a crawler's name.
VALUE_DIRECTIVES = ("max-snippet", "max-image-preview", "max-video-preview", "unavailable_after")
NOINDEX_WORDS = ("noindex", "none")
RICH_RESULT_GONE = {
    "FAQPage": "FAQ rich results stopped showing in Google on 2026-05-07",
    "HowTo": "HowTo rich results stopped showing in Google in 2023",
}
HREFLANG_PATTERN = re.compile(r"^([a-z]{2})(-[a-z]{4})?(-([a-z]{2}|\d{3}))?$")
BAD_REGIONS = {"uk": "use GB for the United Kingdom", "eu": "EU is not a country code"}
FILE_NAME_ALT = re.compile(r"\.(png|jpe?g|gif|webp|svg|avif)$|^(img|dsc|image|photo)[-_ ]?\d+", re.IGNORECASE)
GENERIC_ALTS = ("image", "picture", "photo", "img", "graphic", "icon", "logo")
EMPTY_SHELL_CHARS = 200
MAX_RETURN_LINK_CHECKS = 10
MAX_EXAMPLES = 3


def header_noindex(values):
    """True when an X-Robots-Tag value says noindex to every crawler or to Googlebot."""
    for value in values:
        crawler = None
        head, separator, rest = value.partition(":")
        name = head.strip().lower()
        if separator and name not in VALUE_DIRECTIVES and " " not in name and "," not in name:
            crawler = name
            value = rest
        if crawler not in (None, "googlebot"):
            continue
        for token in value.split(","):
            if token.strip().lower() in NOINDEX_WORDS:
                return True
    return False


def examples(items):
    shown = ", ".join(items[:MAX_EXAMPLES])
    if len(items) > MAX_EXAMPLES:
        shown += f" (+{len(items) - MAX_EXAMPLES} more)"
    return shown


def fetch_page(client, url):
    """Return (followed, results). followed is None when the page could not be read."""
    try:
        followed = crawl_http.follow(client, url)
    except crawl_http.Refused as error:
        return None, [(NOT_CHECKED, url, str(error))]
    except crawl_http.RequestFailed as error:
        return None, [(BLOCKER, url, f"no answer: {error}")]
    results = []
    if followed.problem:
        return None, [(BLOCKER, url, followed.problem)]
    response = followed.response
    if len(followed.hops) == 1:
        results.append((NOTE, url, f"redirects ({followed.hops[0][0]}) to {response.url}"))
    elif len(followed.hops) > 1:
        results.append((MINOR, url, f"{len(followed.hops)} redirects in a row to {response.url}; link to the final URL"))
    if response.status != 200:
        results.append((BLOCKER, url, f"answers {response.status}; a page meant for search must answer 200"))
        return None, results
    if not response.is_html():
        results.append((NOT_CHECKED, url, f"not HTML ({response.header('Content-Type')})"))
        return None, results
    return followed, results


def check_robots(url, response, facts):
    results = []
    if header_noindex(response.header_list("X-Robots-Tag")):
        results.append((BLOCKER, url, "X-Robots-Tag header says noindex; Google will drop this page"))
    directives = facts.robots_directives()
    for word in NOINDEX_WORDS:
        if word in directives:
            results.append((BLOCKER, url, f"meta robots says {word}; Google will drop this page"))
            break
    if "nofollow" in directives:
        results.append((NOTE, url, "meta robots says nofollow; crawlers will not follow this page's links"))
    return results


def says_noindex(response, facts):
    """True when the header or a meta tag says noindex."""
    if header_noindex(response.header_list("X-Robots-Tag")):
        return True
    directives = facts.robots_directives()
    for word in NOINDEX_WORDS:
        if word in directives:
            return True
    return False


def check_kept_out(url, response, facts):
    """A page meant to stay out of search needs its noindex, and nothing else."""
    if says_noindex(response, facts):
        return [(NOTE, url, "noindex, kept out of search on purpose")]
    return [(MAJOR, url, "meant to stay out of search, but has no noindex; it can show in results")]


def check_title_and_description(url, facts):
    results = []
    if not facts.title():
        results.append((MAJOR, url, "no title"))
    if len(facts.titles) > 1:
        results.append((MINOR, url, f"{len(facts.titles)} title tags; keep one"))
    if not facts.meta("description"):
        results.append((MINOR, url, "no meta description"))
    if facts.meta("keywords") is not None:
        results.append((NOTE, url, "meta keywords is ignored by Google; safe to remove"))
    return results


def check_canonical(client, url, final_url, facts):
    hrefs = facts.canonicals()
    if not hrefs:
        return [(MINOR, url, "no canonical link")]
    if len(hrefs) > 1:
        return [(MAJOR, url, f"{len(hrefs)} canonical links; Google may ignore them all")]
    href = hrefs[0]
    results = []
    if not urlsplit(href).scheme:
        results.append((MINOR, url, f"canonical is relative ({href}); use an absolute URL"))
    target = crawl_http.normalize_url(urljoin(final_url, href))
    here = crawl_http.normalize_url(final_url)
    if target == here:
        return results
    if urlsplit(target).path == "/" and urlsplit(here).path != "/":
        results.append((MAJOR, url, f"canonical points at the home page ({target}); this page will drop out of search"))
        return results
    try:
        answer = client.get(target)
    except (crawl_http.Refused, crawl_http.RequestFailed) as error:
        results.append((NOT_CHECKED, url, f"canonical target {target}: {error}"))
        return results
    if answer.status != 200:
        results.append((MAJOR, url, f"canonical points at {target}, which answers {answer.status}"))
        return results
    results.append((NOTE, url, f"canonical points at another URL ({target}); this page itself will not be indexed"))
    return results


def check_basics(url, facts):
    results = []
    if not facts.lang:
        results.append((MAJOR, url, "no lang on <html>; screen readers guess the language (WCAG 3.1.1)"))
    if facts.meta("viewport") is None:
        results.append((MINOR, url, "no viewport meta; phones show a zoomed-out desktop page"))
    if not facts.h1s:
        results.append((MINOR, url, "no H1 in the raw HTML"))
    return results


def check_social(client, url, final_url, facts):
    results = []
    missing = []
    for key in ("og:title", "og:description", "og:image"):
        if not facts.meta(key):
            missing.append(key)
    if missing:
        results.append((MINOR, url, f"link previews miss {', '.join(missing)}"))
    if facts.meta("twitter:card") is None:
        results.append((NOTE, url, "no twitter:card; X falls back to a small preview"))
    image = facts.meta("og:image")
    if not image:
        return results
    if not urlsplit(image).scheme:
        results.append((MINOR, url, f"og:image is relative ({image}); previews need an absolute URL"))
    image_url = urljoin(final_url, image)
    try:
        answer = client.get(image_url)
    except (crawl_http.Refused, crawl_http.RequestFailed) as error:
        results.append((NOT_CHECKED, url, f"og:image {image_url}: {error}"))
        return results
    if answer.status != 200:
        results.append((MINOR, url, f"og:image {image_url} answers {answer.status}"))
    return results


def check_jsonld(url, facts):
    results = []
    types, errors = facts.jsonld_types()
    for error in errors:
        results.append((MAJOR, url, f"JSON-LD does not parse: {error}"))
    for kind in types:
        if kind in RICH_RESULT_GONE:
            results.append((NOTE, url, f"{kind}: {RICH_RESULT_GONE[kind]}; keep it only if the page really shows it"))
    return results


def hreflang_problem(code):
    """Why an hreflang code is wrong, or "" when Google accepts it."""
    lowered = code.lower()
    if lowered == "x-default":
        return ""
    match = HREFLANG_PATTERN.match(lowered)
    if match is None:
        return "not a language(-region) code"
    region = match.group(4)
    if region in BAD_REGIONS:
        return BAD_REGIONS[region]
    if region is not None and region.isdigit():
        return "Google does not support number regions like 419"
    return ""


def links_back(client, alternate_url, page_url):
    """True, False, or the error text when the alternate could not be read."""
    try:
        followed = crawl_http.follow(client, alternate_url)
    except (crawl_http.Refused, crawl_http.RequestFailed) as error:
        return str(error)
    if followed.problem or followed.response.status != 200:
        return False
    facts = page_facts.parse(followed.response.text())
    wanted = crawl_http.normalize_url(page_url)
    for code, href in facts.hreflangs():
        if crawl_http.normalize_url(urljoin(followed.response.url, href)) == wanted:
            return True
    return False


def check_hreflang(client, url, final_url, facts):
    pairs = facts.hreflangs()
    if not pairs:
        return []
    results = []
    here = crawl_http.normalize_url(final_url)
    targets = []
    for code, href in pairs:
        problem = hreflang_problem(code)
        if problem:
            results.append((MAJOR, url, f"hreflang {code!r}: {problem}"))
        target = crawl_http.normalize_url(urljoin(final_url, href))
        if target not in targets:
            targets.append(target)
    if here not in targets:
        results.append((MINOR, url, "the hreflang set does not list this page itself"))
    others = []
    for target in targets:
        if target != here:
            others.append(target)
    for target in others[:MAX_RETURN_LINK_CHECKS]:
        answer = links_back(client, target, final_url)
        if answer is True:
            continue
        if answer is False:
            results.append((MAJOR, url, f"hreflang alternate {target} does not link back; Google ignores the pair"))
        else:
            results.append((NOT_CHECKED, url, f"hreflang alternate {target}: {answer}"))
    return results


def check_images(url, facts):
    results = []
    no_alt = []
    weak_alt = []
    for image in facts.images:
        source = image.get("src") or "(no src)"
        alt = image.get("alt")
        if alt is None:
            no_alt.append(source)
            continue
        cleaned = alt.strip()
        if FILE_NAME_ALT.search(cleaned) or cleaned.lower() in GENERIC_ALTS:
            weak_alt.append(f"{source} alt={alt!r}")
    if no_alt:
        results.append((MAJOR, url, f"{len(no_alt)} image(s) with no alt (WCAG 1.1.1): {examples(no_alt)}"))
    if weak_alt:
        results.append((MINOR, url, f"{len(weak_alt)} image(s) with alt that says nothing: {examples(weak_alt)}"))
    return results


def check_empty_shell(url, facts):
    length = facts.text_length()
    if length < EMPTY_SHELL_CHARS and facts.script_count > 0:
        return [(
            MAJOR,
            url,
            f"raw HTML has only {length} characters of text; crawlers that skip JavaScript "
            "(every AI crawler measured) see an empty page. Confirm with --rendered",
        )]
    return []


def check_rendered(url, facts, rendered):
    """Compare the raw HTML with what the browser rendered for this page."""
    results = []
    raw_title = facts.title() or ""
    shown_title = " ".join((rendered.get("title") or "").split())
    if raw_title != shown_title:
        if not raw_title:
            results.append((MAJOR, url, f"title only exists after JavaScript ({shown_title!r})"))
        else:
            results.append((MAJOR, url, f"JavaScript changes the title from {raw_title!r} to {shown_title!r}"))
    raw_canonicals = facts.canonicals()
    shown_canonicals = rendered.get("canonicals") or []
    if raw_canonicals != shown_canonicals:
        results.append((MAJOR, url, f"JavaScript changes the canonical from {raw_canonicals} to {shown_canonicals}"))
    raw_noindex = bool(facts.robots_directives() & set(NOINDEX_WORDS))
    shown_noindex = False
    for content in rendered.get("robots") or []:
        for token in content.split(","):
            if token.strip().lower() in NOINDEX_WORDS:
                shown_noindex = True
    if shown_noindex and not raw_noindex:
        results.append((BLOCKER, url, "JavaScript adds noindex; Google drops the page after rendering"))
    if raw_noindex and not shown_noindex:
        results.append((NOTE, url, "JavaScript removes the raw noindex, but Google may skip rendering a noindex page"))
    if not facts.h1s and rendered.get("h1Count", 0) > 0:
        results.append((MAJOR, url, "the H1 only exists after JavaScript"))
    raw_length = facts.text_length()
    shown_length = int(rendered.get("textLength") or 0)
    # More than half of the text the browser shows is not in the raw HTML.
    if shown_length > 2 * raw_length:
        results.append((
            MAJOR,
            url,
            f"most text appears only after JavaScript (raw {raw_length}, rendered {shown_length} characters); "
            "AI crawlers will not see it",
        ))
    return results


def load_rendered(path):
    """Map normalized URL -> rendered fields. Raises StartError."""
    try:
        with open(path, encoding="utf-8") as handle:
            data = json.load(handle)
    except (OSError, ValueError) as error:
        raise crawl_http.StartError(f"cannot read {path}: {error}")
    if isinstance(data, dict):
        data = [data]
    if not isinstance(data, list):
        raise crawl_http.StartError(f"{path} must hold a JSON list of page_fields.js results")
    by_url = {}
    for entry in data:
        if not isinstance(entry, dict) or not entry.get("url"):
            raise crawl_http.StartError(f"{path}: every entry needs a url")
        by_url[crawl_http.normalize_url(entry["url"])] = entry
    return by_url


def find_rendered(rendered_by_url, url, final_url):
    for candidate in (url, final_url):
        entry = rendered_by_url.get(crawl_http.normalize_url(candidate))
        if entry is not None:
            return entry
    return None


def check_page(client, url, rendered_by_url, kept_out=False):
    """Return (results, facts or None, final URL). Facts is None for a kept-out page too."""
    followed, results = fetch_page(client, url)
    if followed is None:
        return results, None, url
    response = followed.response
    final_url = response.url
    facts = page_facts.parse(response.text())
    if kept_out:
        results.extend(check_kept_out(url, response, facts))
        return results, None, final_url
    results.extend(check_robots(url, response, facts))
    results.extend(check_title_and_description(url, facts))
    results.extend(check_canonical(client, url, final_url, facts))
    results.extend(check_basics(url, facts))
    results.extend(check_social(client, url, final_url, facts))
    results.extend(check_jsonld(url, facts))
    results.extend(check_hreflang(client, url, final_url, facts))
    results.extend(check_images(url, facts))
    if rendered_by_url is None:
        results.extend(check_empty_shell(url, facts))
        return results, facts, final_url
    rendered = find_rendered(rendered_by_url, url, final_url)
    if rendered is None:
        results.append((NOT_CHECKED, url, "no entry for this page in the --rendered file"))
        results.extend(check_empty_shell(url, facts))
    else:
        results.extend(check_rendered(url, facts, rendered))
    return results, facts, final_url


def same_value_results(label, values):
    """values: list of (url, value). One result per value used on more than one page."""
    groups = {}
    for url, value in values:
        if value:
            groups.setdefault(value, []).append(url)
    results = []
    for value, urls in groups.items():
        if len(urls) > 1:
            results.append((MINOR, urls[0], f"same {label} {value!r} on {len(urls)} pages: {examples(urls)}"))
    return results


def check_duplicates(pages):
    """pages: list of (url, facts). Same title or description on more than one page."""
    titles = []
    descriptions = []
    for url, facts in pages:
        titles.append((url, facts.title()))
        descriptions.append((url, facts.meta("description")))
    results = same_value_results("title", titles)
    results.extend(same_value_results("description", descriptions))
    return results


def parse_args(argv):
    parser = argparse.ArgumentParser(description="See each page the way a crawler without JavaScript sees it.")
    parser.add_argument("urls", nargs="*", help="the public pages to check")
    parser.add_argument("--rendered", help="JSON saved from assets/page_fields.js in the built-in browser")
    parser.add_argument(
        "--kept-out",
        action="append",
        default=[],
        metavar="URL",
        help="a page meant to stay out of search; checked only for its noindex (repeat for more)",
    )
    crawl_http.add_target_args(parser)
    args = parser.parse_args(argv)
    if not args.urls and not args.kept_out:
        parser.error("give at least one page, or --kept-out URL")
    return args


def main(argv=None):
    args = parse_args(argv)
    client = crawl_http.client_from_args(args)
    rendered_by_url = None
    try:
        if args.rendered:
            rendered_by_url = load_rendered(args.rendered)
        for url in args.urls + args.kept_out:
            client.check(url)
    except (crawl_http.StartError, crawl_http.Refused) as error:
        print(f"cannot start: {error}")
        return 2

    kept_out = set()
    for url in args.kept_out:
        kept_out.add(crawl_http.normalize_url(url))
    to_check = list(args.urls)
    for url in args.kept_out:
        if url not in to_check:
            to_check.append(url)

    results = []
    pages = []
    seen_final = set()
    for url in to_check:
        is_kept_out = crawl_http.normalize_url(url) in kept_out
        page_results, facts, final_url = check_page(client, url, rendered_by_url, is_kept_out)
        results.extend(page_results)
        if facts is None:
            continue
        # Two URLs that land on the same page are one page, not a duplicate.
        final_key = crawl_http.normalize_url(final_url)
        if final_key in seen_final:
            continue
        seen_final.add(final_key)
        pages.append((url, facts))
    results.extend(check_duplicates(pages))
    return crawl_http.print_results(results)


if __name__ == "__main__":
    sys.exit(main())
