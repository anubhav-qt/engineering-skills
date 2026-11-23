"""Read the facts a crawler sees in a page's raw HTML. Shared by the scripts here.

No JavaScript runs: this is what a crawler without a browser sees, which
is every AI crawler measured so far.
"""

import json
from dataclasses import dataclass, field
from html.parser import HTMLParser
from urllib.parse import urljoin

# Text inside these is never shown as page text.
HIDDEN_TEXT_TAGS = ("head", "script", "style", "template", "noscript", "svg")
# The end tag that closes each kind of captured text.
CAPTURE_END_TAG = {"title": "title", "h1": "h1", "jsonld": "script"}
VOID_TAGS = ("area", "base", "br", "col", "embed", "hr", "img", "input", "link", "meta", "source", "track", "wbr")


@dataclass
class PageFacts:
    lang: str = None
    titles: list = field(default_factory=list)
    metas: list = field(default_factory=list)
    links: list = field(default_factory=list)
    h1s: list = field(default_factory=list)
    images: list = field(default_factory=list)
    anchors: list = field(default_factory=list)
    jsonld_blocks: list = field(default_factory=list)
    script_count: int = 0
    text_parts: list = field(default_factory=list)

    def text(self):
        return " ".join(" ".join(self.text_parts).split())

    def text_length(self):
        return len(self.text())

    def title(self):
        """The first title, whitespace collapsed, or None when there is none."""
        if not self.titles:
            return None
        return self.titles[0]

    def meta(self, key):
        """Content of the first meta tag whose name or property is key."""
        for meta in self.metas:
            if meta.get("name") == key or meta.get("property") == key:
                return meta.get("content")
        return None

    def robots_directives(self):
        """Lowercase directives from meta robots and meta googlebot."""
        directives = set()
        for meta in self.metas:
            if meta.get("name") not in ("robots", "googlebot"):
                continue
            for token in (meta.get("content") or "").split(","):
                token = token.strip().lower()
                if token:
                    directives.add(token)
        return directives

    def links_with_rel(self, rel):
        found = []
        for link in self.links:
            if rel in link["rel"]:
                found.append(link)
        return found

    def canonicals(self):
        hrefs = []
        for link in self.links_with_rel("canonical"):
            hrefs.append(link["href"])
        return hrefs

    def hreflangs(self):
        """(code, href) for each alternate link that has an hreflang."""
        pairs = []
        for link in self.links_with_rel("alternate"):
            if link["hreflang"]:
                pairs.append((link["hreflang"], link["href"]))
        return pairs

    def has_icon(self):
        for link in self.links:
            if "icon" in link["rel"]:
                return True
        return False

    def jsonld_types(self):
        """(types found, errors). Each JSON-LD block that does not parse adds an error."""
        types = []
        errors = []
        for block in self.jsonld_blocks:
            try:
                data = json.loads(block)
            except ValueError as error:
                errors.append(str(error))
                continue
            collect_types(data, types)
        return types, errors

    def jsonld_items(self):
        """Every parsed JSON-LD object, with @graph lists opened up."""
        items = []
        for block in self.jsonld_blocks:
            try:
                data = json.loads(block)
            except ValueError:
                continue
            collect_items(data, items)
        return items

    def internal_links(self, page_url):
        urls = []
        for href in self.anchors:
            urls.append(urljoin(page_url, href))
        return urls


def collect_items(data, items):
    if isinstance(data, list):
        for entry in data:
            collect_items(entry, items)
        return
    if not isinstance(data, dict):
        return
    items.append(data)
    graph = data.get("@graph")
    if graph is not None:
        collect_items(graph, items)


def collect_types(data, types):
    items = []
    collect_items(data, items)
    for item in items:
        kind = item.get("@type")
        if isinstance(kind, list):
            for name in kind:
                types.append(str(name))
        elif kind is not None:
            types.append(str(kind))


class FactParser(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.facts = PageFacts()
        self.open_tags = []
        self.capture = None
        self.captured = []

    def inside(self, tag):
        return tag in self.open_tags

    def text_is_hidden(self):
        for tag in HIDDEN_TEXT_TAGS:
            if self.inside(tag):
                return True
        return False

    def handle_starttag(self, tag, attrs):
        values = {}
        for name, value in attrs:
            if name not in values:
                values[name] = value
        self.start(tag, values)
        if tag not in VOID_TAGS:
            self.open_tags.append(tag)

    def handle_startendtag(self, tag, attrs):
        values = {}
        for name, value in attrs:
            if name not in values:
                values[name] = value
        self.start(tag, values)

    def start(self, tag, attrs):
        facts = self.facts
        if tag == "html" and facts.lang is None:
            facts.lang = (attrs.get("lang") or "").strip()
        elif tag == "title" and not self.inside("svg"):
            self.begin_capture("title")
        elif tag == "h1":
            self.begin_capture("h1")
        elif tag == "meta":
            facts.metas.append(meta_attrs(attrs))
        elif tag == "link":
            facts.links.append(link_attrs(attrs))
        elif tag == "img":
            facts.images.append(attrs)
        elif tag == "a" and attrs.get("href"):
            facts.anchors.append(attrs["href"].strip())
        elif tag == "script":
            facts.script_count += 1
            kind = (attrs.get("type") or "").strip().lower()
            if kind == "application/ld+json":
                self.begin_capture("jsonld")

    def begin_capture(self, kind):
        self.capture = kind
        self.captured = []

    def end_capture(self):
        text = "".join(self.captured)
        kind = self.capture
        self.capture = None
        self.captured = []
        if kind == "jsonld":
            self.facts.jsonld_blocks.append(text)
            return
        collapsed = " ".join(text.split())
        if kind == "title":
            self.facts.titles.append(collapsed)
        elif kind == "h1":
            self.facts.h1s.append(collapsed)

    def handle_endtag(self, tag):
        if self.capture is not None and CAPTURE_END_TAG[self.capture] == tag:
            self.end_capture()
        if tag not in self.open_tags:
            return
        # Close the tag and anything left open inside it.
        while self.open_tags:
            closed = self.open_tags.pop()
            if closed == tag:
                break

    def handle_data(self, data):
        if self.capture is not None:
            self.captured.append(data)
        if self.capture == "jsonld" or self.text_is_hidden():
            return
        self.facts.text_parts.append(data)


def meta_attrs(attrs):
    meta = {}
    for key in ("name", "property", "content", "http-equiv"):
        value = attrs.get(key)
        if value is None:
            continue
        if key == "content":
            meta[key] = value.strip()
        else:
            meta[key] = value.strip().lower()
    return meta


def link_attrs(attrs):
    rel_tokens = (attrs.get("rel") or "").lower().split()
    return {
        "rel": rel_tokens,
        "href": (attrs.get("href") or "").strip(),
        "hreflang": (attrs.get("hreflang") or "").strip(),
    }


def parse(html):
    parser = FactParser()
    parser.feed(html)
    parser.close()
    if parser.capture is not None:
        parser.end_capture()
    return parser.facts
