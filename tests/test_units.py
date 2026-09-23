from __future__ import annotations

import gzip

import pytest

from canonical_checker.parse import parse_html
from canonical_checker.sitemap import SitemapError, parse_sitemap
from canonical_checker.urls import (
    Site,
    describe_difference,
    doubled_host_segment,
    is_absolute_http,
    normalize,
    raw_host_prefix,
    slash_applicable,
)

HOSTS = Site("https", "example.com").hosts


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("HTTPS://Example.COM:443/a?b=1#frag", "https://example.com/a?b=1"),
        ("http://example.com", "http://example.com/"),
        ("http://example.com:8080/x", "http://example.com:8080/x"),
        ("mailto:a@b.c", None),
        ("https://example.com:bad/", None),
    ],
)
def test_normalize(raw, expected):
    assert normalize(raw) == expected


@pytest.mark.parametrize(
    ("raw", "hit"),
    [
        ("example.com/privacy-policy/", "example.com"),
        ("www.example.com", "www.example.com"),
        ("www.other-site.org/page", "www.other-site.org"),
        ("/example.com/x", None),
        ("page.html", None),
        ("https://example.com/", None),
        ("./about/", None),
        ("example.com:8080/x", "example.com"),
    ],
)
def test_raw_host_prefix(raw, hit):
    assert raw_host_prefix(raw, HOSTS) == hit


def test_doubled_host_segment():
    assert doubled_host_segment("https://example.com/blog/www.example.com/x", HOSTS)
    assert doubled_host_segment("https://example.com/blog/x", HOSTS) is None


def test_site_scope():
    site = Site("https", "www.example.com")
    assert site.in_scope("http://example.com/x")
    assert site.in_scope("https://www.example.com/")
    assert not site.in_scope("https://blog.example.com/")
    assert Site.from_url("http://127.0.0.1:8765/a").origin == "http://127.0.0.1:8765"
    assert Site.from_url("https://example.com:443/").origin == "https://example.com"


def test_misc_helpers():
    assert is_absolute_http("https://example.com/")
    assert not is_absolute_http("//example.com/")
    assert not is_absolute_http("/x")
    assert slash_applicable("/about")
    assert not slash_applicable("/")
    assert not slash_applicable("/file.pdf")
    assert describe_difference("https://example.com/a", "https://example.com/a/") == "trailing slash"


def test_parse_html_base_and_canonical():
    page = parse_html(
        "https://example.com/dir/page",
        """<html><head><base href="https://example.com/root/">
        <link rel="Canonical" href="/dir/page">
        <meta property="og:url" content="https://example.com/dir/page">
        </head><body><a href="child">c</a><a href="javascript:void(0)">j</a>
        <a href="tel:123">t</a><a href="#x">x</a><a href="example.com:8080/p">p</a></body></html>""",
    )
    assert page.canonicals == ["/dir/page"]
    assert page.canonical == "https://example.com/dir/page"
    assert page.og_url == "https://example.com/dir/page"
    assert [link.url for link in page.links] == [
        "https://example.com/root/child",
        "https://example.com/root/example.com:8080/p",
    ]


URLSET = b"""<?xml version="1.0"?><urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">
<url><loc> https://example.com/a/ </loc></url></urlset>"""


def test_parse_sitemap_plain_and_gzip():
    assert parse_sitemap(URLSET).locs == ["https://example.com/a/"]
    parsed = parse_sitemap(gzip.compress(URLSET))
    assert parsed.kind == "urlset" and parsed.locs == ["https://example.com/a/"]


def test_parse_sitemap_rejects_entities_and_garbage():
    with pytest.raises(SitemapError):
        parse_sitemap(b'<?xml version="1.0"?><!DOCTYPE x [<!ENTITY a "b">]><urlset/>')
    with pytest.raises(SitemapError):
        parse_sitemap(b"<html></html>")
    with pytest.raises(SitemapError):
        parse_sitemap(b"not xml")
