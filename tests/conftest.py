"""A fake website served through httpx.MockTransport (no network access)."""

from __future__ import annotations

import gzip
from collections.abc import Callable

import httpx
import pytest

from canonical_checker.crawler import CrawlConfig, CrawlResult, crawl

Response = tuple[int, dict[str, str], bytes]


def html(body: str = "", head: str = "") -> bytes:
    return f"<!doctype html><html><head>{head}</head><body>{body}</body></html>".encode()


def canon(url: str) -> str:
    return f'<link rel="canonical" href="{url}">'


def page(path: str, links: str = "", extra_head: str = "") -> Response:
    return (
        200,
        {"content-type": "text/html; charset=utf-8"},
        html(links, canon(f"https://example.com{path}") + extra_head),
    )


def redirect(to: str, status: int = 301) -> Response:
    return status, {"location": to}, b""


NOT_FOUND: Response = (404, {"content-type": "text/html"}, html("not found"))

HOME_LINKS = """
<a href="example.com/privacy-policy/">Privacy (broken, no scheme)</a>
<a href="/about/">About</a>
<a href="https://www.example.com/contact/">Contact (www)</a>
<a href="http://example.com/services/">Services (http)</a>
<a href="/blog">Blog (no trailing slash)</a>
<a href="/old-page/">Old page (redirect chain)</a>
<a href="/missing/">Missing (404)</a>
<a href="/private/secret/">Private (robots.txt)</a>
<a href="/dup/">Duplicate</a>
<a href="/no-canonical/">No canonical</a>
<a href="/relative-canonical/">Relative canonical</a>
<a href="/multi-canonical/">Multiple canonicals</a>
<a href="/canon-redirect/">Canonical redirects</a>
<a href="/canon-404/">Canonical 404</a>
<a href="/cross-host/">Cross-host canonical</a>
<a href="/og-mismatch/">og:url mismatch</a>
<a href="mailto:hi@example.com">Mail</a>
<a href="#top">Top</a>
<a href="https://external.test/">External</a>
"""

SITEMAP_INDEX = b"""<?xml version="1.0" encoding="UTF-8"?>
<sitemapindex xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">
  <sitemap><loc>https://example.com/sitemap-pages.xml.gz</loc></sitemap>
</sitemapindex>"""

SITEMAP_PAGES = b"""<?xml version="1.0" encoding="UTF-8"?>
<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9"
        xmlns:image="http://www.google.com/schemas/sitemap-image/1.1">
  <url><loc>https://example.com/</loc></url>
  <url><loc>https://example.com/about/</loc>
       <image:image><image:loc>https://example.com/a.png</image:loc></image:image></url>
  <url><loc>https://example.com/old-page/</loc></url>
  <url><loc>https://example.com/missing/</loc></url>
  <url><loc>https://example.com/dup/</loc></url>
</urlset>"""


def build_site() -> dict[str, Response]:
    ok = "https://example.com"
    return {
        f"{ok}/robots.txt": (
            200,
            {"content-type": "text/plain"},
            b"User-agent: *\nDisallow: /private/\nSitemap: https://example.com/sitemap.xml\n",
        ),
        f"{ok}/": (
            200,
            {"content-type": "text/html"},
            html(
                HOME_LINKS,
                canon("https://example.com/") + '<meta property="og:url" content="https://example.com/">',
            ),
        ),
        f"{ok}/about/": page("/about/", '<a href="/">Home</a>'),
        "https://www.example.com/robots.txt": redirect(f"{ok}/robots.txt"),
        "https://www.example.com/contact/": redirect(f"{ok}/contact/"),
        f"{ok}/contact/": page("/contact/"),
        "http://example.com/robots.txt": redirect(f"{ok}/robots.txt"),
        "http://example.com/services/": redirect(f"{ok}/services/"),
        f"{ok}/services/": page("/services/"),
        f"{ok}/blog": (200, {"content-type": "text/html"}, html("", canon(f"{ok}/blog/"))),
        f"{ok}/blog/": page("/blog/"),
        f"{ok}/old-page/": redirect("/interim/"),
        f"{ok}/interim/": redirect("/new-page/"),
        f"{ok}/new-page/": page("/new-page/"),
        f"{ok}/private/secret/": page("/private/secret/"),
        f"{ok}/dup/": (200, {"content-type": "text/html"}, html("", canon(f"{ok}/about/"))),
        f"{ok}/no-canonical/": (200, {"content-type": "text/html"}, html("no canonical")),
        f"{ok}/relative-canonical/": (
            200,
            {"content-type": "text/html"},
            html("", canon("/relative-canonical/")),
        ),
        f"{ok}/multi-canonical/": (
            200,
            {"content-type": "text/html"},
            html("", canon(f"{ok}/multi-canonical/") + canon(f"{ok}/other/")),
        ),
        f"{ok}/canon-redirect/": (
            200,
            {"content-type": "text/html"},
            html("", canon(f"{ok}/old-page/")),
        ),
        f"{ok}/canon-404/": (200, {"content-type": "text/html"}, html("", canon(f"{ok}/gone/"))),
        f"{ok}/cross-host/": (
            200,
            {"content-type": "text/html"},
            html("", canon("https://other.example.org/x/")),
        ),
        f"{ok}/og-mismatch/": page(
            "/og-mismatch/", extra_head='<meta property="og:url" content="https://example.com/og/">'
        ),
        f"{ok}/sitemap.xml": (200, {"content-type": "application/xml"}, SITEMAP_INDEX),
        f"{ok}/sitemap-pages.xml.gz": (
            200,
            {"content-type": "application/gzip"},
            gzip.compress(SITEMAP_PAGES),
        ),
    }


class FakeSite:
    """Routes requests to a dict of responses and records every URL requested."""

    def __init__(self, routes: dict[str, Response]) -> None:
        self.routes = routes
        self.requests: list[str] = []

    def handler(self, request: httpx.Request) -> httpx.Response:
        url = str(request.url)
        self.requests.append(url)
        if request.url.host == "external.test":
            raise AssertionError("crawler must not fetch external hosts")
        if url in self.routes:
            status, headers, body = self.routes[url]
            return httpx.Response(status, headers=headers, content=body)
        if "/example.com/" in request.url.path:
            # Like many CMSs, the server happily serves the doubled path with 200.
            return httpx.Response(
                200,
                headers={"content-type": "text/html"},
                content=html("soft duplicate", canon("https://example.com/")),
            )
        status, headers, body = NOT_FOUND
        return httpx.Response(status, headers=headers, content=body)

    @property
    def transport(self) -> httpx.MockTransport:
        return httpx.MockTransport(self.handler)


@pytest.fixture
def fake_site() -> FakeSite:
    return FakeSite(build_site())


@pytest.fixture
def run_crawl(fake_site: FakeSite) -> Callable[..., CrawlResult]:
    def _run(start: str = "https://example.com/", **kwargs) -> CrawlResult:
        kwargs.setdefault("delay", 0)
        return crawl(CrawlConfig(start_url=start, **kwargs), transport=fake_site.transport)

    return _run
