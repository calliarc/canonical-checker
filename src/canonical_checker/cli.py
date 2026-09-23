"""Typer command-line interface."""

from __future__ import annotations

import sys
from enum import Enum
from pathlib import Path
from typing import List, Optional  # Typer-friendly on 3.10

import httpx
import typer
from rich.console import Console

from canonical_checker import DEFAULT_USER_AGENT, __version__
from canonical_checker.checks import Severity, analyze, should_fail
from canonical_checker.crawler import CrawlConfig, CrawlError, crawl
from canonical_checker.report import render, to_csv, to_json, write_output

#: Test hook: an httpx transport to use instead of the network.
TRANSPORT: httpx.AsyncBaseTransport | None = None


class Level(str, Enum):
    none = "none"
    info = "info"
    warning = "warning"
    error = "error"


app = typer.Typer(
    add_completion=False,
    no_args_is_help=True,
    help="Crawl a site and flag doubled paths, mixed hosts and canonical mismatches.",
)


def _version(value: bool) -> None:
    if value:
        typer.echo(f"canonical-checker {__version__}")
        raise typer.Exit()


@app.command()
def main(
    url: str = typer.Argument(
        ..., help="Start URL (https://example.com/) or a sitemap URL (…/sitemap.xml, .xml.gz)."
    ),
    sitemap: List[str] = typer.Option(
        [], "--sitemap", "-s", help="Extra sitemap URL(s) to check and crawl. Repeatable."
    ),
    discover_sitemaps: bool = typer.Option(
        False, "--discover-sitemaps", help="Also use Sitemap: lines from robots.txt."
    ),
    sitemap_only: bool = typer.Option(
        False, "--sitemap-only", help="Only check sitemap URLs; do not follow links."
    ),
    max_pages: int = typer.Option(500, "--max-pages", "-n", min=1, help="Maximum URLs to fetch."),
    concurrency: int = typer.Option(
        2, "--concurrency", "-c", min=1, max=16, help="Parallel requests (keep it low)."
    ),
    delay: float = typer.Option(0.5, "--delay", "-d", min=0.0, help="Seconds to wait before each request."),
    timeout: float = typer.Option(15.0, "--timeout", min=1.0, help="Per-request timeout (s)."),
    user_agent: str = typer.Option(DEFAULT_USER_AGENT, "--user-agent", "-A"),
    ignore_robots: bool = typer.Option(
        False, "--ignore-robots", help="Do not honour robots.txt (only for sites you own)."
    ),
    csv_path: Optional[str] = typer.Option(
        None, "--csv", help="Write all issues as CSV to this file ('-' for stdout)."
    ),
    json_path: Optional[str] = typer.Option(
        None, "--json", help="Write a JSON report to this file ('-' for stdout)."
    ),
    fail_on: Level = typer.Option(
        Level.none,
        "--fail-on",
        case_sensitive=False,
        help="Exit with code 1 if any issue has at least this severity.",
    ),
    min_severity: Level = typer.Option(
        Level.info,
        "--min-severity",
        case_sensitive=False,
        help="Hide issues below this severity in all outputs.",
    ),
    max_rows: int = typer.Option(50, "--max-rows", min=0, help="Issue rows shown in the table."),
    quiet: bool = typer.Option(False, "--quiet", "-q", help="No table; only files / exit code."),
    version: Optional[bool] = typer.Option(
        None, "--version", callback=_version, is_eager=True, help="Show version and exit."
    ),
) -> None:
    """Crawl URL and report canonicalisation problems."""
    to_stdout = "-" in (csv_path, json_path)
    console = Console(stderr=to_stdout)
    err = Console(stderr=True)

    config = CrawlConfig(
        start_url=url,
        sitemaps=list(sitemap),
        max_pages=max_pages,
        concurrency=concurrency,
        delay=delay,
        timeout=timeout,
        user_agent=user_agent,
        respect_robots=not ignore_robots,
        follow_links=not sitemap_only,
        discover_sitemaps=discover_sitemaps,
    )

    show_progress = not quiet and err.is_terminal
    try:
        if show_progress:
            with err.status("Crawling…") as status:
                result = crawl(
                    config,
                    transport=TRANSPORT,
                    on_progress=lambda n, u: status.update(f"[{n}] {u}"),
                )
        else:
            result = crawl(config, transport=TRANSPORT)
    except CrawlError as exc:
        err.print(f"[bold red]error:[/] {exc}")
        raise typer.Exit(code=2) from exc

    all_issues = analyze(result)
    shown = all_issues
    if min_severity is not Level.none:
        floor = Severity.parse(min_severity.value)
        shown = [i for i in all_issues if i.severity >= floor]

    if csv_path:
        if csv_path == "-":
            sys.stdout.write(to_csv(shown))
        else:
            write_output(Path(csv_path), to_csv(shown))
    if json_path:
        if json_path == "-":
            sys.stdout.write(to_json(result, shown) + "\n")
        else:
            write_output(Path(json_path), to_json(result, shown))
    if not quiet:
        render(console, result, shown, max_rows=max_rows)

    threshold = None if fail_on is Level.none else Severity.parse(fail_on.value)
    if should_fail(all_issues, threshold):
        raise typer.Exit(code=1)


def run() -> None:
    app()


if __name__ == "__main__":  # pragma: no cover
    run()
