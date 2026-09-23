"""End-to-end run against a real (local, loopback-only) http.server."""

from __future__ import annotations

import threading
from functools import partial
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer

import pytest

from canonical_checker.checks import analyze
from canonical_checker.crawler import CrawlConfig, crawl


class _QuietHandler(SimpleHTTPRequestHandler):
    def log_message(self, *args) -> None:  # keep pytest output clean
        pass


@pytest.fixture
def local_site(tmp_path, monkeypatch):
    monkeypatch.setenv("NO_PROXY", "127.0.0.1,localhost")
    monkeypatch.setenv("no_proxy", "127.0.0.1,localhost")
    (tmp_path / "about").mkdir()
    (tmp_path / "robots.txt").write_text("User-agent: *\nDisallow: /private/\n")
    server = ThreadingHTTPServer(("127.0.0.1", 0), partial(_QuietHandler, directory=str(tmp_path)))
    base = f"http://127.0.0.1:{server.server_address[1]}"
    (tmp_path / "index.html").write_text(
        f'<html><head><link rel="canonical" href="{base}/"></head><body>'
        f'<a href="127.0.0.1:{server.server_address[1]}/about/">raw host</a>'
        '<a href="/about">about</a><a href="/private/x/">private</a></body></html>'
    )
    (tmp_path / "about" / "index.html").write_text(
        f'<html><head><link rel="canonical" href="{base}/about/"></head></html>'
    )
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    yield base
    server.shutdown()
    server.server_close()


def test_crawl_real_http_server(local_site):
    result = crawl(CrawlConfig(start_url=local_site + "/", delay=0))
    assert result.site.origin == local_site
    codes = {(i.code, i.url) for i in analyze(result)}
    assert ("link-redirect", f"{local_site}/about") in codes  # http.server adds the slash
    assert ("trailing-slash", f"{local_site}/about") in codes
    assert any(code == "raw-host-href" for code, _ in codes)
    assert any(code == "doubled-host-path" for code, _ in codes)
    assert f"{local_site}/private/x/" in result.robots_blocked
