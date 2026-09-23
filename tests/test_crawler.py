from __future__ import annotations

import pytest

from canonical_checker.crawler import CrawlError


def test_robots_txt_is_respected(fake_site, run_crawl):
    result = run_crawl()
    assert "https://example.com/private/secret/" in result.robots_blocked
    assert "https://example.com/private/secret/" not in fake_site.requests


def test_ignore_robots(fake_site, run_crawl):
    run_crawl(respect_robots=False)
    assert "https://example.com/private/secret/" in fake_site.requests


def test_never_fetches_external_hosts(fake_site, run_crawl):
    run_crawl()
    assert not [u for u in fake_site.requests if "external.test" in u]


def test_user_agent_sent(fake_site, run_crawl):
    seen = []
    original = fake_site.handler

    def spy(request):
        seen.append(request.headers["user-agent"])
        return original(request)

    fake_site.handler = spy
    run_crawl(user_agent="my-bot/1.0")
    assert seen and set(seen) == {"my-bot/1.0"}


def test_max_pages_limits_crawl(run_crawl):
    result = run_crawl(max_pages=3)
    assert result.pages_fetched == 3
    assert result.truncated


def test_crawl_from_sitemap_gz_index(fake_site, run_crawl):
    result = run_crawl("https://example.com/sitemap.xml", follow_links=False)
    locs = [loc for loc, _ in result.sitemap_entries]
    assert "https://example.com/about/" in locs
    assert "https://example.com/a.png" not in locs  # image:loc ignored
    assert "https://example.com/about/" in result.pages
    # --sitemap-only: links on those pages are not followed.
    assert "https://example.com/contact/" not in fake_site.requests


def test_discover_sitemaps_from_robots(run_crawl):
    result = run_crawl(discover_sitemaps=True)
    assert result.sitemap_entries


def test_doubled_path_pages_are_not_followed(fake_site, run_crawl):
    run_crawl()
    assert "https://example.com/example.com/privacy-policy/" in fake_site.requests
    assert not [u for u in fake_site.requests if u.count("example.com/") > 2]


def test_start_redirect_sets_preferred_host(fake_site, run_crawl):
    fake_site.routes["https://www.example.com/"] = (301, {"location": "https://example.com/"}, b"")
    result = run_crawl("https://www.example.com/")
    assert result.site.host == "example.com"


def test_unreachable_start_raises(fake_site, run_crawl):
    def boom(request):
        import httpx

        raise httpx.ConnectError("refused", request=request)

    fake_site.handler = boom
    with pytest.raises(CrawlError):
        run_crawl()


def test_robots_5xx_means_disallow(fake_site, run_crawl):
    fake_site.routes["https://example.com/robots.txt"] = (503, {}, b"")
    with pytest.raises(CrawlError, match="robots"):
        run_crawl()


def test_crawl_delay_from_robots(fake_site, run_crawl):
    fake_site.routes["https://example.com/robots.txt"] = (
        200,
        {},
        b"User-agent: *\nCrawl-delay: 1\nDisallow: /private/\n",
    )
    result = run_crawl(max_pages=1)
    assert any("Crawl-delay" in n for n in result.notes)
