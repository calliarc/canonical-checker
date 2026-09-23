from __future__ import annotations

import pytest

from canonical_checker.checks import CHECKS, Issue, Severity, analyze, should_fail

HOME = "https://example.com/"


@pytest.fixture
def issues(run_crawl) -> list[Issue]:
    return analyze(run_crawl(sitemaps=["https://example.com/sitemap.xml"]))


def find(issues: list[Issue], code: str, url: str | None = None, source: str | None = None):
    return [
        i
        for i in issues
        if i.code == code and (url is None or i.url == url) and (source is None or i.source == source)
    ]


def test_doubled_host_path_records_referring_page(issues):
    hit = find(issues, "doubled-host-path", "https://example.com/example.com/privacy-policy/", HOME)
    assert hit, issues
    assert "HTTP 200" in hit[0].detail


def test_raw_host_href_detected_at_source_level(issues):
    hit = find(issues, "raw-host-href", source=HOME)
    assert len(hit) == 1
    assert 'href="example.com/privacy-policy/"' in hit[0].detail


def test_mixed_www_host(issues):
    assert find(issues, "mixed-host", "https://www.example.com/contact/", HOME)


def test_http_link_on_https_site(issues):
    assert find(issues, "http-link", "http://example.com/services/", HOME)


def test_single_redirect_is_info(issues):
    hit = find(issues, "link-redirect", "http://example.com/services/", HOME)
    assert hit and hit[0].severity is Severity.INFO


def test_trailing_slash_inconsistency(issues):
    hit = find(issues, "trailing-slash", "https://example.com/blog", HOME)
    assert hit and "with a trailing slash" in hit[0].detail
    assert not find(issues, "trailing-slash", "https://example.com/about/")


def test_redirect_chain(issues):
    hit = find(issues, "redirect-chain", "https://example.com/old-page/", HOME)
    assert hit and "2 hops" in hit[0].detail
    assert "https://example.com/new-page/" in hit[0].detail


def test_broken_link(issues):
    assert find(issues, "broken-link", "https://example.com/missing/", HOME)


def test_link_to_non_canonical(issues):
    assert find(issues, "link-to-non-canonical", "https://example.com/dup/", HOME)
    # /blog canonicalises to /blog/ -> same root cause as Search Console's
    # "Alternate page with proper canonical tag".
    assert find(issues, "link-to-non-canonical", "https://example.com/blog", HOME)


def test_canonical_missing(issues):
    page = "https://example.com/no-canonical/"
    assert find(issues, "canonical-missing", page, page)


def test_canonical_relative(issues):
    assert find(issues, "canonical-relative", source="https://example.com/relative-canonical/")


def test_canonical_multiple(issues):
    hit = find(issues, "canonical-multiple", source="https://example.com/multi-canonical/")
    assert hit and "conflicting" in hit[0].detail


def test_canonical_not_self(issues):
    assert find(issues, "canonical-not-self", "https://example.com/about/", "https://example.com/dup/")


def test_canonical_points_to_redirect(issues):
    assert find(
        issues, "canonical-redirect", "https://example.com/old-page/", "https://example.com/canon-redirect/"
    )


def test_canonical_points_to_4xx(issues):
    hit = find(issues, "canonical-broken", "https://example.com/gone/", "https://example.com/canon-404/")
    assert hit and "404" in hit[0].detail


def test_canonical_cross_host(issues):
    assert find(
        issues, "canonical-cross-host", "https://other.example.org/x/", "https://example.com/cross-host/"
    )


def test_og_url_mismatch(issues):
    assert find(issues, "og-url-mismatch", source="https://example.com/og-mismatch/")
    assert not find(issues, "og-url-mismatch", source=HOME)


def test_sitemap_checks(issues):
    sm = "https://example.com/sitemap-pages.xml.gz"
    assert find(issues, "sitemap-url-redirect", "https://example.com/old-page/", sm)
    assert find(issues, "sitemap-url-broken", "https://example.com/missing/", sm)
    assert find(issues, "sitemap-url-non-canonical", "https://example.com/dup/", sm)
    assert not find(issues, "sitemap-url-non-canonical", "https://example.com/about/")


def test_clean_pages_have_no_canonical_issues(issues):
    about = "https://example.com/about/"
    assert not [i for i in issues if i.source == about and i.code.startswith("canonical")]


def test_every_issue_has_a_known_code_and_source(issues):
    assert issues
    for issue in issues:
        assert issue.code in CHECKS
        assert issue.source


def test_sitemap_error_reported(fake_site, run_crawl):
    fake_site.routes["https://example.com/sitemap.xml"] = (200, {}, b"<html>not xml")
    result = run_crawl(sitemaps=["https://example.com/sitemap.xml"])
    assert find(analyze(result), "sitemap-error", "https://example.com/sitemap.xml")


def test_should_fail_threshold(issues):
    assert should_fail(issues, Severity.ERROR)
    assert not should_fail([], Severity.INFO)
    assert not should_fail(issues, None)
