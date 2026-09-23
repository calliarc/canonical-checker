"""Output: rich terminal summary, CSV and JSON."""

from __future__ import annotations

import csv
import io
import json
from collections import Counter
from pathlib import Path

from rich.console import Console
from rich.table import Table

from canonical_checker import __version__
from canonical_checker.checks import CHECKS, Issue, Severity
from canonical_checker.crawler import CrawlResult

CSV_FIELDS = ["severity", "code", "url", "source", "detail", "fix"]
_STYLE = {Severity.ERROR: "bold red", Severity.WARNING: "yellow", Severity.INFO: "cyan"}


def summary(issues: list[Issue]) -> dict[str, int]:
    counts = Counter(i.severity.label for i in issues)
    return {s.label: counts.get(s.label, 0) for s in sorted(Severity, reverse=True)}


def render(console: Console, result: CrawlResult, issues: list[Issue], max_rows: int = 50) -> None:
    site = result.site
    console.print(
        f"[bold]canonical-checker {__version__}[/] - {site.origin}  "
        f"pages fetched: {result.pages_fetched}, HTML pages parsed: {len(result.pages)}, "
        f"sitemap URLs: {len(result.sitemap_entries)}, blocked by robots.txt: "
        f"{len(result.robots_blocked)}"
    )
    for note in result.notes:
        console.print(f"[dim]note: {note}[/]")

    if not issues:
        console.print("[bold green]No issues found.[/]")
        return

    by_code = Counter(i.code for i in issues)
    table = Table(title="Summary", show_lines=False, expand=False)
    table.add_column("Severity")
    table.add_column("Check")
    table.add_column("Count", justify="right")
    table.add_column("What it means")
    for code, count in sorted(by_code.items(), key=lambda kv: (-CHECKS[kv[0]].severity, kv[0])):
        check = CHECKS[code]
        style = _STYLE[check.severity]
        table.add_row(f"[{style}]{check.severity.label}[/]", code, str(count), check.title)
    console.print(table)

    details = Table(title="Issues", show_lines=False, expand=True)
    details.add_column("Sev", no_wrap=True)
    details.add_column("Check", no_wrap=True)
    details.add_column("URL", overflow="fold")
    details.add_column("Found on (referring page)", overflow="fold")
    details.add_column("Detail", overflow="fold")
    for issue in issues[:max_rows]:
        style = _STYLE[issue.severity]
        details.add_row(
            f"[{style}]{issue.severity.label}[/]", issue.code, issue.url, issue.source, issue.detail
        )
    console.print(details)
    if len(issues) > max_rows:
        console.print(
            f"[dim]... {len(issues) - max_rows} more issue(s) not shown; "
            "use --csv / --json for the full list or --max-rows to show more.[/]"
        )
    counts = summary(issues)
    console.print(
        f"[bold]Total:[/] [bold red]{counts['error']} error(s)[/], "
        f"[yellow]{counts['warning']} warning(s)[/], [cyan]{counts['info']} info[/]"
    )


def to_csv(issues: list[Issue]) -> str:
    buffer = io.StringIO()
    writer = csv.DictWriter(buffer, fieldnames=CSV_FIELDS, lineterminator="\n")
    writer.writeheader()
    for issue in issues:
        writer.writerow(issue.to_dict())
    return buffer.getvalue()


def to_json(result: CrawlResult, issues: list[Issue]) -> str:
    payload = {
        "tool": "canonical-checker",
        "version": __version__,
        "site": result.site.origin,
        "start_url": result.config.start_url,
        "pages_fetched": result.pages_fetched,
        "pages_parsed": len(result.pages),
        "sitemap_urls": len(result.sitemap_entries),
        "robots_blocked": sorted(result.robots_blocked),
        "truncated": result.truncated,
        "notes": result.notes,
        "summary": summary(issues),
        "issues": [i.to_dict() for i in issues],
    }
    return json.dumps(payload, indent=2)


def write_output(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")
