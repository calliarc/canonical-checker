"""Detectors. Each turns crawl results into :class:`Issue` records."""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from enum import IntEnum
from urllib.parse import urlsplit

from canonical_checker.crawler import CrawlResult
from canonical_checker.urls import (
    describe_difference,
    doubled_host_segment,
    has_trailing_slash,
    host_of,
    is_absolute_http,
    raw_host_prefix,
    slash_applicable,
)


class Severity(IntEnum):
    INFO = 10
    WARNING = 20
    ERROR = 30

    @property
    def label(self) -> str:
        return self.name.lower()

    @classmethod
    def parse(cls, value: str) -> Severity:
        return cls[value.strip().upper()]


@dataclass(frozen=True)
class Check:
    code: str
    severity: Severity
    title: str
    fix: str


_CHECKS = [
    Check(
        "doubled-host-path",
        Severity.ERROR,
        "Host name repeated in the URL path",
        "Use an absolute URL (https://example.com/page/) or a root-relative one (/page/).",
    ),
    Check(
        "raw-host-href",
        Severity.ERROR,
        "href starts with a host name but has no scheme",
        "Add https:// in front of the host, or drop the host and start the href with /.",
    ),
    Check(
        "mixed-host",
        Severity.WARNING,
        "Link uses the other www / non-www host",
        "Link to the preferred host directly; keep the 301 only as a safety net.",
    ),
    Check(
        "http-link", Severity.WARNING, "http:// link on an https site", "Change internal links to https://."
    ),
    Check(
        "trailing-slash",
        Severity.WARNING,
        "Trailing slash differs from the site convention",
        "Link using the same trailing-slash form as your canonical URLs.",
    ),
    Check(
        "broken-link",
        Severity.ERROR,
        "Internal link returns 4xx/5xx",
        "Fix or remove the link, or redirect the old URL.",
    ),
    Check(
        "link-redirect",
        Severity.INFO,
        "Internal link goes through a redirect",
        "Point the link at the final URL.",
    ),
    Check(
        "redirect-chain",
        Severity.WARNING,
        "Redirect chain (2+ hops)",
        "Redirect straight to the final URL in one hop and update the link.",
    ),
    Check(
        "link-to-non-canonical",
        Severity.WARNING,
        "Link points at a page that canonicalises elsewhere",
        "Link to the canonical URL instead (the cause of 'Alternate page with proper canonical tag').",
    ),
    Check(
        "canonical-missing",
        Severity.WARNING,
        "Page has no rel=canonical",
        'Add <link rel="canonical" href="https://example.com/this-page/"> to <head>.',
    ),
    Check(
        "canonical-relative",
        Severity.WARNING,
        "Canonical href is not absolute",
        "Use a full absolute URL including https:// and the preferred host.",
    ),
    Check(
        "canonical-multiple",
        Severity.ERROR,
        "More than one rel=canonical",
        "Keep exactly one canonical tag (check theme + SEO plugin duplicates).",
    ),
    Check(
        "canonical-not-self",
        Severity.WARNING,
        "Canonical points to a different URL",
        "Make the canonical self-referencing, or stop linking to/listing this duplicate.",
    ),
    Check(
        "canonical-cross-host",
        Severity.WARNING,
        "Canonical points to another host",
        "Use the preferred host in the canonical unless cross-domain canonicalisation is intended.",
    ),
    Check(
        "canonical-redirect",
        Severity.ERROR,
        "Canonical target redirects",
        "Set the canonical to the final (200) URL.",
    ),
    Check(
        "canonical-broken",
        Severity.ERROR,
        "Canonical target is missing or invalid",
        "Point the canonical at a live 200 URL.",
    ),
    Check(
        "og-url-mismatch",
        Severity.WARNING,
        "og:url differs from the canonical",
        "Make og:url identical to the canonical URL.",
    ),
    Check(
        "sitemap-url-redirect",
        Severity.ERROR,
        "Sitemap lists a redirecting URL",
        "List only final 200 URLs in sitemap.xml.",
    ),
    Check(
        "sitemap-url-broken",
        Severity.ERROR,
        "Sitemap lists a 4xx/5xx URL",
        "Remove dead URLs from sitemap.xml.",
    ),
    Check(
        "sitemap-url-non-canonical",
        Severity.WARNING,
        "Sitemap lists a non-canonical URL",
        "List the canonical URL in the sitemap, not the duplicate.",
    ),
    Check(
        "sitemap-error",
        Severity.ERROR,
        "Sitemap could not be fetched or parsed",
        "Serve valid sitemap XML (optionally gzip) with HTTP 200.",
    ),
    Check(
        "fetch-error",
        Severity.WARNING,
        "URL could not be fetched",
        "Check timeouts, redirect loops and server errors for this URL.",
    ),
]

CHECKS: dict[str, Check] = {c.code: c for c in _CHECKS}


@dataclass(frozen=True)
class Issue:
    code: str
    url: str
    source: str
    detail: str

    @property
    def check(self) -> Check:
        return CHECKS[self.code]

    @property
    def severity(self) -> Severity:
        return self.check.severity

    def to_dict(self) -> dict[str, str]:
        return {
            "severity": self.severity.label,
            "code": self.code,
            "url": self.url,
            "source": self.source,
            "detail": self.detail,
            "fix": self.check.fix,
        }


class _Collector:
    def __init__(self) -> None:
        self._items: dict[tuple[str, str, str], Issue] = {}

    def add(self, code: str, url: str, source: str, detail: str) -> None:
        assert code in CHECKS, code
        key = (code, url, source)
        if key not in self._items:
            self._items[key] = Issue(code, url, source, detail)

    def sorted(self) -> list[Issue]:
        return sorted(self._items.values(), key=lambda i: (-i.severity, i.code, i.url, i.source))


def _status_text(result) -> str:
    if result is None:
        return "not fetched"
    if result.status is None:
        return result.error or "error"
    return f"HTTP {result.status}"


def _chain_text(result) -> str:
    hops = [f"{url} ({status})" for url, status in result.chain]
    return " -> ".join([*hops, f"{result.final_url} ({_status_text(result)})"])


def analyze(result: CrawlResult) -> list[Issue]:
    """Run every detector over a finished crawl."""
    site = result.site
    hosts = site.hosts
    out = _Collector()

    # ---------------------------------------------------------- link checks
    def check_target(url: str, source: str, raw: str | None, from_sitemap: bool) -> None:
        if raw is not None:
            prefix = raw_host_prefix(raw, hosts)
            if prefix:
                out.add(
                    "raw-host-href",
                    url,
                    source,
                    f'href="{raw}" has no scheme or leading slash, so browsers treat '
                    f'"{prefix}" as a folder and resolve it to {url}',
                )
        if not site.in_scope(url):
            return
        parts = urlsplit(url)
        fetched = result.fetches.get(url)

        segment = doubled_host_segment(url, hosts)
        if segment:
            out.add(
                "doubled-host-path",
                url,
                source,
                f'path contains the host "{segment}" ({_status_text(fetched)})',
            )
        if (parts.hostname or "") != site.host:
            out.add("mixed-host", url, source, f"uses {parts.hostname}; site's preferred host is {site.host}")
        if parts.scheme == "http" and site.scheme == "https":
            out.add("http-link", url, source, "insecure http:// URL on an https site")

        if fetched is None:
            return
        if fetched.chain:
            if from_sitemap:
                out.add("sitemap-url-redirect", url, source, _chain_text(fetched))
            elif len(fetched.chain) >= 2:
                out.add("redirect-chain", url, source, f"{len(fetched.chain)} hops: {_chain_text(fetched)}")
            else:
                out.add("link-redirect", url, source, _chain_text(fetched))
        if fetched.status is None:
            if not fetched.offsite:
                code = "sitemap-url-broken" if from_sitemap else "fetch-error"
                out.add(code, url, source, fetched.error or "fetch failed")
            return
        if fetched.status >= 400:
            code = "sitemap-url-broken" if from_sitemap else "broken-link"
            out.add(code, url, source, f"HTTP {fetched.status}")
            return
        if fetched.chain or segment:
            return
        page = result.pages.get(fetched.final_url)
        canonical = page.canonical if page else None
        if canonical and canonical != url:
            code = "sitemap-url-non-canonical" if from_sitemap else "link-to-non-canonical"
            out.add(
                code,
                url,
                source,
                f"page declares canonical {canonical} ({describe_difference(url, canonical)})",
            )

    for page in result.pages.values():
        for link in page.links:
            check_target(link.url, page.url, link.raw, from_sitemap=False)
    for loc, sitemap_url in result.sitemap_entries:
        check_target(loc, sitemap_url, None, from_sitemap=True)
    for sitemap_url, error in result.sitemap_errors:
        out.add("sitemap-error", sitemap_url, sitemap_url, error)

    # ------------------------------------------------------- trailing slash
    _check_trailing_slash(result, out)

    # ------------------------------------------------------ canonical tags
    for page in result.pages.values():
        _check_canonical(result, page, out)

    return out.sorted()


def _check_trailing_slash(result: CrawlResult, out: _Collector) -> None:
    site = result.site

    def styles(urls: Iterable[str]) -> list[bool]:
        return [
            has_trailing_slash(urlsplit(u).path)
            for u in urls
            if site.in_scope(u)
            and slash_applicable(urlsplit(u).path)
            and not doubled_host_segment(u, site.hosts)
        ]

    links = [(link, page.url) for page in result.pages.values() for link in page.links]
    canonical_styles = styles(p.canonical for p in result.pages.values() if p.canonical)
    link_styles = styles(link.url for link, _ in links)
    basis_styles, basis = (
        (canonical_styles, "canonical URLs") if canonical_styles else (link_styles, "internal links")
    )
    if not basis_styles or len(set(canonical_styles + link_styles)) < 2:
        return
    with_slash = sum(basis_styles)
    without = len(basis_styles) - with_slash
    prefer_slash = with_slash >= without
    convention = (
        f"site convention is {'with' if prefer_slash else 'without'} a trailing slash "
        f"({max(with_slash, without)} of {len(basis_styles)} {basis})"
    )
    for link, source in links:
        path = urlsplit(link.url).path
        if (
            site.in_scope(link.url)
            and slash_applicable(path)
            and not doubled_host_segment(link.url, site.hosts)
            and has_trailing_slash(path) != prefer_slash
        ):
            out.add("trailing-slash", link.url, source, convention)


def _check_canonical(result: CrawlResult, page, out: _Collector) -> None:
    site = result.site
    url = page.url
    if not page.canonicals:
        out.add("canonical-missing", url, url, 'no <link rel="canonical"> found')
        return

    resolved = [page.resolve(raw) for raw in page.canonicals]
    if len(page.canonicals) > 1:
        distinct = sorted({r or "(empty)" for r in resolved})
        kind = "conflicting" if len(distinct) > 1 else "identical"
        out.add(
            "canonical-multiple",
            url,
            url,
            f"{len(page.canonicals)} {kind} canonical tags: {', '.join(distinct)}",
        )

    raw = page.canonicals[0]
    canonical = resolved[0]
    if canonical is None:
        out.add("canonical-broken", url, url, f'invalid canonical href="{raw}"')
        return
    if not is_absolute_http(raw):
        out.add("canonical-relative", canonical, url, f'href="{raw}" is relative; resolves to {canonical}')
    if host_of(canonical) != host_of(url):
        out.add(
            "canonical-cross-host",
            canonical,
            url,
            f"canonical host {host_of(canonical)} differs from page host {host_of(url)}",
        )
    elif canonical != url:
        out.add(
            "canonical-not-self",
            canonical,
            url,
            f"canonical differs from page URL ({describe_difference(url, canonical)})",
        )

    target = result.fetches.get(canonical)
    if target is not None and site.in_scope(canonical):
        if target.chain:
            out.add("canonical-redirect", canonical, url, _chain_text(target))
        elif target.status is None or target.status >= 400:
            out.add("canonical-broken", canonical, url, _status_text(target))

    if page.og_url:
        og = page.resolve(page.og_url)
        if og != canonical:
            out.add(
                "og-url-mismatch",
                og or page.og_url,
                url,
                f"og:url {og or page.og_url} vs canonical {canonical}",
            )


def should_fail(issues: Iterable[Issue], threshold: Severity | None) -> bool:
    return threshold is not None and any(i.severity >= threshold for i in issues)
