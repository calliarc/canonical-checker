"""sitemap.xml parsing (urlset, sitemap index, gzip)."""

from __future__ import annotations

import gzip
import xml.etree.ElementTree as ET
from dataclasses import dataclass


class SitemapError(ValueError):
    pass


@dataclass
class ParsedSitemap:
    kind: str  # "urlset" or "sitemapindex"
    locs: list[str]


def _local(tag: str) -> str:
    return tag.rsplit("}", 1)[-1].lower()


def parse_sitemap(content: bytes, max_bytes: int = 50 * 1024 * 1024) -> ParsedSitemap:
    """Parse sitemap XML (optionally gzip-compressed) into its <loc> entries."""
    if content[:2] == b"\x1f\x8b":
        try:
            content = gzip.decompress(content)
        except (OSError, EOFError) as exc:
            raise SitemapError(f"invalid gzip data: {exc}") from exc
    if len(content) > max_bytes:
        raise SitemapError("sitemap exceeds size limit")
    head = content[:4096].lower()
    if b"<!doctype" in head or b"<!entity" in content.lower():
        # Sitemaps never need DTDs; refuse them to avoid entity-expansion tricks.
        raise SitemapError("sitemap contains a DOCTYPE/ENTITY declaration")
    try:
        root = ET.fromstring(content)
    except ET.ParseError as exc:
        raise SitemapError(f"invalid XML: {exc}") from exc

    kind = _local(root.tag)
    if kind not in ("urlset", "sitemapindex"):
        raise SitemapError(f"unexpected root element <{kind}>")
    child_tag = "url" if kind == "urlset" else "sitemap"
    locs: list[str] = []
    for child in root:
        if _local(child.tag) != child_tag:
            continue
        for grandchild in child:
            # Only the direct <loc>; ignores image:loc, video:loc, etc.
            if _local(grandchild.tag) == "loc" and grandchild.text and grandchild.text.strip():
                locs.append(grandchild.text.strip())
                break
    return ParsedSitemap(kind=kind, locs=locs)
