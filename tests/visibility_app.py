"""Shared helpers for the visibility skill's tests: script loading and a tiny site."""

import importlib
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from security_app import LocalApp, html_page, not_found, run_main, start_app  # noqa: E402,F401

REPO_ROOT = Path(__file__).resolve().parent.parent
SKILL = REPO_ROOT / "skills" / "visibility-handling"
SCRIPTS = SKILL / "scripts"
ASSETS = SKILL / "assets"

# The scripts import each other (crawl_http, page_facts) by name, as they
# do when run from their own folder.
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))


def load(name):
    return importlib.import_module(name)


def page(head="", body="", lang="en"):
    """A full HTML page. lang=None leaves the lang attribute out."""
    lang_attribute = ""
    if lang is not None:
        lang_attribute = f' lang="{lang}"'
    return f"<!doctype html><html{lang_attribute}><head>{head}</head><body>{body}</body></html>"


def serve_site(test, files):
    """files: path -> (status, headers list, body). Anything else is a 404."""

    def respond(method, path, headers, body):
        if path in files:
            return files[path]
        return not_found()

    return start_app(test, respond)


def html(body, status=200, headers=()):
    return status, [("Content-Type", "text/html; charset=utf-8"), *headers], body


def text(body, content_type="text/plain", status=200):
    return status, [("Content-Type", content_type)], body


def redirect(location, status=301):
    return status, [("Location", location)], ""


def good_head(url, path="/", title="Plain shop", description="Hand made mugs."):
    """A head with every tag check_pages wants, for the page at url + path."""
    canonical = url.rstrip("/") + path
    image = url + "card.png"
    return (
        f"<title>{title}</title>"
        f'<meta name="description" content="{description}">'
        '<meta name="viewport" content="width=device-width, initial-scale=1">'
        f'<link rel="canonical" href="{canonical}">'
        f'<meta property="og:title" content="{title}">'
        f'<meta property="og:description" content="{description}">'
        f'<meta property="og:image" content="{image}">'
        '<meta name="twitter:card" content="summary_large_image">'
    )


def good_body(heading="Mugs"):
    return f"<main><h1>{heading}</h1><p>{'Plain words about mugs. ' * 20}</p></main>"
