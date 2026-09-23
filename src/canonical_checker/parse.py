"""HTML parsing with selectolax: links, canonical tags and og:url."""

from __future__ import annotations

from dataclasses import dataclass, field
from urllib.parse import urljoin

from selectolax.parser import HTMLParser

from canonical_checker.urls import HOST_PORT_RE, SKIP_SCHEMES, normalize, scheme_of


@dataclass(frozen=True)
class Link:
    """An ``<a href>`` found on a page: the raw attribute value and the resolved URL."""

    raw: str
    url: str


@dataclass
class Page:
    """A parsed HTML page."""

    url: str
    base: str
    canonicals: list[str] = field(default_factory=list)
    og_url: str | None = None
    links: list[Link] = field(default_factory=list)

    def resolve(self, raw: str) -> str | None:
        return normalize(urljoin(self.base, raw.strip())) if raw.strip() else None

    @property
    def canonical(self) -> str | None:
        """The resolved first canonical URL (search engines use the first one)."""
        return self.resolve(self.canonicals[0]) if self.canonicals else None


def parse_html(url: str, html: str) -> Page:
    tree = HTMLParser(html)
    base = url
    base_node = tree.css_first("base[href]")
    if base_node is not None:
        href = (base_node.attributes.get("href") or "").strip()
        if href:
            base = urljoin(url, href)

    page = Page(url=url, base=base)

    for node in tree.css("link[rel]"):
        rel = (node.attributes.get("rel") or "").lower().split()
        if "canonical" in rel:
            page.canonicals.append((node.attributes.get("href") or "").strip())

    for node in tree.css("meta[property]"):
        if (node.attributes.get("property") or "").strip().lower() == "og:url":
            page.og_url = (node.attributes.get("content") or "").strip() or None
            break

    seen: set[tuple[str, str]] = set()
    for node in tree.css("a[href]"):
        raw = node.attributes.get("href")
        if raw is None:
            continue
        raw = raw.strip()
        if not raw or raw.startswith("#") or scheme_of(raw) in SKIP_SCHEMES:
            continue
        resolved = normalize(urljoin(base, raw))
        if resolved is None and HOST_PORT_RE.match(raw):
            # "example.com:8080/x" looks like a scheme to URL parsers; keep it so the
            # raw-host-href detector can flag it.
            resolved = normalize(urljoin(base, "./" + raw))
        if resolved is None:
            continue
        key = (raw, resolved)
        if key not in seen:
            seen.add(key)
            page.links.append(Link(raw=raw, url=resolved))
    return page
