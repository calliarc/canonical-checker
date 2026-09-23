"""Async, polite, same-site crawler built on httpx."""

from __future__ import annotations

import asyncio
import re
from collections.abc import Callable
from dataclasses import dataclass, field
from urllib.parse import urljoin, urlsplit
from urllib.robotparser import RobotFileParser

import httpx

from canonical_checker import DEFAULT_USER_AGENT
from canonical_checker.parse import Page, parse_html
from canonical_checker.sitemap import SitemapError, parse_sitemap
from canonical_checker.urls import Site, doubled_host_segment, is_sitemap_url, normalize

REDIRECT_CODES = frozenset({301, 302, 303, 307, 308})
MAX_BODY_BYTES = 5 * 1024 * 1024
MAX_CRAWL_DELAY = 10.0


class CrawlError(RuntimeError):
    """Fatal problem, e.g. the start URL cannot be fetched."""


@dataclass
class CrawlConfig:
    start_url: str
    sitemaps: list[str] = field(default_factory=list)
    max_pages: int = 500
    concurrency: int = 2
    delay: float = 0.5
    timeout: float = 15.0
    user_agent: str = DEFAULT_USER_AGENT
    respect_robots: bool = True
    follow_links: bool = True
    discover_sitemaps: bool = False
    max_redirects: int = 10
    max_sitemap_urls: int = 50_000


@dataclass
class FetchResult:
    url: str
    final_url: str
    status: int | None
    chain: list[tuple[str, int]] = field(default_factory=list)
    content_type: str = ""
    body: bytes = b""
    error: str | None = None
    offsite: bool = False

    @property
    def is_html(self) -> bool:
        ctype = self.content_type.lower()
        return not ctype or "html" in ctype

    @property
    def text(self) -> str:
        match = re.search(r"charset=([\w\-]+)", self.content_type, re.I)
        encoding = match.group(1) if match else "utf-8"
        try:
            return self.body.decode(encoding, errors="replace")
        except LookupError:
            return self.body.decode("utf-8", errors="replace")


@dataclass
class CrawlResult:
    config: CrawlConfig
    site: Site
    pages: dict[str, Page]
    fetches: dict[str, FetchResult]
    sitemap_entries: list[tuple[str, str]]  # (loc, sitemap it came from)
    sitemap_errors: list[tuple[str, str]]  # (sitemap url, error)
    robots_blocked: set[str]
    pages_fetched: int
    truncated: bool
    notes: list[str]


class Crawler:
    def __init__(
        self,
        config: CrawlConfig,
        transport: httpx.AsyncBaseTransport | None = None,
        on_progress: Callable[[int, str], None] | None = None,
    ) -> None:
        self.config = config
        self._transport = transport
        self._on_progress = on_progress
        self._delay = max(0.0, config.delay)
        self.site: Site | None = None
        self.fetches: dict[str, FetchResult] = {}
        self.pages: dict[str, Page] = {}
        self.robots_blocked: set[str] = set()
        self.sitemap_entries: list[tuple[str, str]] = []
        self.sitemap_errors: list[tuple[str, str]] = []
        self.notes: list[str] = []
        self.pages_fetched = 0
        self.truncated = False
        self._tasks: dict[str, asyncio.Future[FetchResult]] = {}
        self._robots: dict[str, RobotFileParser] = {}
        self._robots_sitemaps: dict[str, list[str]] = {}
        self._robots_lock = asyncio.Lock()
        self._seen: set[str] = set()
        self._queue: asyncio.Queue[str] = asyncio.Queue()

    # ------------------------------------------------------------------ public

    async def run(self) -> CrawlResult:
        cfg = self.config
        async with httpx.AsyncClient(
            transport=self._transport,
            headers={
                "User-Agent": cfg.user_agent,
                "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            },
            timeout=httpx.Timeout(cfg.timeout),
            follow_redirects=False,
            limits=httpx.Limits(max_connections=max(1, cfg.concurrency)),
        ) as client:
            self._client = client
            self._sem = asyncio.Semaphore(max(1, cfg.concurrency))
            await self._crawl()
        assert self.site is not None
        return CrawlResult(
            config=cfg,
            site=self.site,
            pages=self.pages,
            fetches=self.fetches,
            sitemap_entries=self.sitemap_entries,
            sitemap_errors=self.sitemap_errors,
            robots_blocked=self.robots_blocked,
            pages_fetched=self.pages_fetched,
            truncated=self.truncated,
            notes=self.notes,
        )

    # --------------------------------------------------------------- crawling

    async def _crawl(self) -> None:
        cfg = self.config
        start = normalize(cfg.start_url)
        if start is None:
            raise CrawlError(f"not an http(s) URL: {cfg.start_url!r}")
        sitemaps = [s for s in (normalize(u) for u in cfg.sitemaps) if s]
        start_is_sitemap = is_sitemap_url(start)

        if start_is_sitemap:
            sitemaps.insert(0, start)
            # The sitemap's own host (after redirects) defines the site.
            probe = await self._fetch_follow(start, any_body=True)
            if probe.status is None:
                raise CrawlError(f"could not fetch sitemap {start}: {probe.error}")
            self.site = Site.from_url(probe.final_url)
        else:
            self.site = Site.from_url(start)
            if not await self.allowed(start):
                raise CrawlError(
                    f"start URL is disallowed by robots.txt: {start} (use --ignore-robots to override)"
                )
            first = await self.fetch(start)
            if first.status is None:
                raise CrawlError(f"could not fetch start URL {start}: {first.error}")
            # Where the start URL redirects to is the site's preferred scheme + host.
            self.site = Site.from_url(first.final_url)

        await self._load_robots(self.site.origin)
        if cfg.discover_sitemaps:
            for sm in self._robots_sitemaps.get(self.site.origin, []):
                norm = normalize(sm)
                if norm and norm not in sitemaps:
                    sitemaps.append(norm)

        if sitemaps:
            await self._load_sitemaps(sitemaps)

        if not start_is_sitemap:
            self._enqueue(start)
        for loc, _source in self.sitemap_entries:
            if self.site.in_scope(loc):
                self._enqueue(loc)

        workers = [asyncio.create_task(self._worker()) for _ in range(max(1, cfg.concurrency))]
        await self._queue.join()
        for worker in workers:
            worker.cancel()
        await asyncio.gather(*workers, return_exceptions=True)

        # Check that every in-scope canonical target resolves with 200.
        targets = {
            page.canonical
            for page in self.pages.values()
            if page.canonical and self.site.in_scope(page.canonical)
        }
        await asyncio.gather(*(self._check_target(t) for t in sorted(targets) if t not in self.fetches))
        if self.truncated:
            self.notes.append(f"Stopped after --max-pages={cfg.max_pages}; some URLs were not checked.")

    def _enqueue(self, url: str) -> None:
        if url not in self._seen:
            self._seen.add(url)
            self._queue.put_nowait(url)

    async def _worker(self) -> None:
        while True:
            url = await self._queue.get()
            try:
                await self._process(url)
            except Exception as exc:  # pragma: no cover - defensive
                self.notes.append(f"internal error while processing {url}: {exc!r}")
            finally:
                self._queue.task_done()

    async def _process(self, url: str) -> None:
        assert self.site is not None
        if self.pages_fetched >= self.config.max_pages:
            self.truncated = True
            return
        if not await self.allowed(url):
            self.robots_blocked.add(url)
            return
        if self.pages_fetched >= self.config.max_pages:
            self.truncated = True
            return
        self.pages_fetched += 1
        result = await self.fetch(url)
        if self._on_progress:
            self._on_progress(self.pages_fetched, url)
        final = result.final_url
        if result.status != 200 or not result.is_html or final in self.pages:
            return
        if not self.site.in_scope(final) or doubled_host_segment(final, self.site.hosts):
            # Doubled-path copies are reported via the links pointing at them;
            # following their links would just nest the problem deeper.
            return
        page = parse_html(final, result.text)
        self.pages[final] = page
        if self.config.follow_links:
            for link in page.links:
                if self.site.in_scope(link.url):
                    self._enqueue(link.url)

    async def _check_target(self, url: str) -> None:
        if await self.allowed(url):
            await self.fetch(url)

    # ---------------------------------------------------------------- sitemaps

    async def _load_sitemaps(self, urls: list[str], max_depth: int = 3) -> None:
        pending = [(u, "(command line)", 0) for u in urls]
        visited: set[str] = set()
        while pending:
            sm_url, parent, depth = pending.pop(0)
            if sm_url in visited:
                continue
            visited.add(sm_url)
            result = await self._fetch_follow(sm_url, any_body=True)
            if result.status != 200:
                reason = result.error or f"HTTP {result.status}"
                self.sitemap_errors.append((sm_url, f"could not fetch sitemap ({reason})"))
                continue
            try:
                parsed = parse_sitemap(result.body)
            except SitemapError as exc:
                self.sitemap_errors.append((sm_url, str(exc)))
                continue
            if parsed.kind == "sitemapindex":
                if depth >= max_depth:
                    self.sitemap_errors.append((sm_url, "sitemap index nested too deeply"))
                    continue
                for loc in parsed.locs:
                    norm = normalize(loc)
                    if norm:
                        pending.append((norm, sm_url, depth + 1))
            else:
                for loc in parsed.locs:
                    if len(self.sitemap_entries) >= self.config.max_sitemap_urls:
                        self.notes.append("sitemap URL limit reached; remaining entries ignored")
                        return
                    norm = normalize(loc)
                    if norm is None:
                        self.sitemap_errors.append((sm_url, f"invalid <loc>: {loc!r}"))
                    else:
                        self.sitemap_entries.append((norm, sm_url))

    # ------------------------------------------------------------------ robots

    async def allowed(self, url: str) -> bool:
        if not self.config.respect_robots:
            return True
        parts = urlsplit(url)
        origin = f"{parts.scheme}://{parts.netloc}"
        parser = await self._load_robots(origin)
        return parser.can_fetch(self.config.user_agent, url)

    async def _load_robots(self, origin: str) -> RobotFileParser:
        async with self._robots_lock:
            if origin in self._robots:
                return self._robots[origin]
            parser = RobotFileParser()
            result = await self._fetch_follow(f"{origin}/robots.txt", any_body=True, scoped=False)
            if result.status is not None and 200 <= result.status < 300:
                text = result.body.decode("utf-8", errors="replace")
                parser.parse(text.splitlines())
                self._robots_sitemaps[origin] = list(parser.site_maps() or [])
                crawl_delay = parser.crawl_delay(self.config.user_agent)
                if crawl_delay and self.config.respect_robots:
                    wanted = min(float(crawl_delay), MAX_CRAWL_DELAY)
                    if wanted > self._delay:
                        self._delay = wanted
                        self.notes.append(f"Using Crawl-delay {wanted:g}s from {origin}/robots.txt")
            elif result.status is not None and result.status >= 500:
                # RFC 9309: an unreachable robots.txt means "assume full disallow".
                parser.disallow_all = True
                if self.config.respect_robots:
                    self.notes.append(
                        f"{origin}/robots.txt returned HTTP {result.status}; treating site as disallowed"
                    )
            else:
                parser.allow_all = True
            self._robots[origin] = parser
            return parser

    # ------------------------------------------------------------------- http

    async def fetch(self, url: str) -> FetchResult:
        """Fetch a page URL once (results are cached and shared between callers)."""
        future = self._tasks.get(url)
        if future is None:
            future = asyncio.ensure_future(self._fetch_follow(url))
            self._tasks[url] = future
        result = await future
        self.fetches[url] = result
        return result

    async def _get(self, url: str, any_body: bool) -> tuple[int | None, httpx.Headers, bytes, str]:
        async with self._sem:
            if self._delay:
                await asyncio.sleep(self._delay)
            try:
                async with self._client.stream("GET", url) as resp:
                    body = b""
                    ctype = resp.headers.get("content-type", "")
                    wants_body = any_body or not ctype or "html" in ctype.lower()
                    if resp.status_code not in REDIRECT_CODES and wants_body:
                        chunks: list[bytes] = []
                        size = 0
                        async for chunk in resp.aiter_bytes():
                            chunks.append(chunk)
                            size += len(chunk)
                            if size >= MAX_BODY_BYTES:
                                break
                        body = b"".join(chunks)
                    return resp.status_code, resp.headers, body, ""
            except httpx.HTTPError as exc:
                return None, httpx.Headers(), b"", f"{type(exc).__name__}: {exc}".strip()

    async def _fetch_follow(self, url: str, any_body: bool = False, scoped: bool = True) -> FetchResult:
        chain: list[tuple[str, int]] = []
        current = url
        visited = {url}
        for _ in range(self.config.max_redirects + 1):
            status, headers, body, error = await self._get(current, any_body)
            if status is None:
                return FetchResult(url, current, None, chain, error=error)
            location = headers.get("location")
            if status in REDIRECT_CODES and location:
                chain.append((current, status))
                target = normalize(urljoin(current, location))
                if target is None:
                    return FetchResult(url, location, None, chain, error="invalid redirect target")
                if target in visited:
                    return FetchResult(url, target, None, chain, error="redirect loop")
                if scoped and self.site is not None and not self.site.in_scope(target):
                    return FetchResult(
                        url,
                        target,
                        None,
                        chain,
                        error="redirects off-site (not followed)",
                        offsite=True,
                    )
                visited.add(target)
                current = target
                continue
            return FetchResult(url, current, status, chain, headers.get("content-type", ""), body)
        return FetchResult(url, current, None, chain, error="too many redirects")


def crawl(
    config: CrawlConfig,
    transport: httpx.AsyncBaseTransport | None = None,
    on_progress: Callable[[int, str], None] | None = None,
) -> CrawlResult:
    """Synchronous convenience wrapper around :class:`Crawler`."""
    return asyncio.run(Crawler(config, transport=transport, on_progress=on_progress).run())
