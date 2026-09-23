# Canonical Checker

CLI that crawls a site and flags doubled paths, mixed hosts and canonical mismatches.

[![CI](https://github.com/calliarc/canonical-checker/actions/workflows/ci.yml/badge.svg)](https://github.com/calliarc/canonical-checker/actions/workflows/ci.yml)
[![License: MIT](https://img.shields.io/badge/License-MIT-blue.svg)](LICENSE)
[![Release](https://img.shields.io/github/v/release/calliarc/canonical-checker?include_prereleases&sort=semver)](https://github.com/calliarc/canonical-checker/releases)
[![Built by CalliArc](https://img.shields.io/badge/built%20by-CalliArc-0a66c2)](https://www.calliarc.com/)

> **Status:** v0.1.0, the first working release. Feedback and issues are welcome.

A single slip like `<a href="example.com/privacy-policy/">` (no `https://` and no leading `/`) makes browsers
and crawlers request `https://example.com/example.com/privacy-policy/`. Add a mix of `www` and non-`www`
links and inconsistent trailing slashes, and Search Console fills up with *"Alternate page with proper
canonical tag"* and *"Duplicate without user-selected canonical"*. Canonical Checker finds these problems
and tells you **which page contains each bad link**, so you know exactly what to fix.

## Features

- Crawls from a start URL or a sitemap (sitemap index and `.xml.gz` supported)
- Flags doubled paths such as /example.com/page, and the raw `href="example.com/..."` that causes them
- Detects mixed www/non-www and http/https links
- Finds inconsistent trailing slashes
- Checks that canonical tags are absolute and self-referencing, that there is only one, that they do not
  point to redirects, 4xx pages or another host, and that `og:url` matches
- Finds redirect chains, broken internal links and links to non-canonical URLs
- Checks sitemap URLs for redirects, 404s and non-canonical entries
- Reports which page contains each bad link
- Polite by default: honours robots.txt (including `Crawl-delay`), 2 parallel requests, 0.5 s delay, custom user agent
- Rich terminal summary, CSV and JSON output; `--fail-on` exit codes and a GitHub Action for CI

## Tech stack

- Python 3.10+
- httpx (async)
- selectolax
- Typer (CLI) and rich (terminal output)
- pytest (tests run against a mocked site, no network)

## Getting started

### Install

```bash
pip install "git+https://github.com/calliarc/canonical-checker.git"
# or, from a clone:
git clone https://github.com/calliarc/canonical-checker.git
cd canonical-checker
pip install .
```

### Usage

```bash
# Crawl from the home page (same-site only, up to 500 URLs)
canonical-checker https://example.com/

# Start from a sitemap (index and .gz supported) and only check the listed URLs
canonical-checker https://example.com/sitemap.xml --sitemap-only

# Crawl links and also check a sitemap, or the sitemaps listed in robots.txt
canonical-checker https://example.com/ --sitemap https://example.com/sitemap.xml
canonical-checker https://example.com/ --discover-sitemaps

# Save full reports
canonical-checker https://example.com/ --csv report.csv --json report.json

# CI: exit code 1 when any error-level issue is found
canonical-checker https://example.com/ --fail-on error --quiet --json report.json

# JSON to stdout for piping (the table goes to stderr)
canonical-checker https://example.com/ --json - --quiet | jq '.summary'
```

| Option | Default | Description |
| --- | --- | --- |
| `--sitemap, -s URL` | none | Extra sitemap(s) to check; repeatable |
| `--discover-sitemaps` | off | Also use `Sitemap:` lines from robots.txt |
| `--sitemap-only` | off | Check sitemap URLs without following links |
| `--max-pages, -n` | 500 | Maximum URLs to fetch |
| `--concurrency, -c` | 2 | Parallel requests (max 16) |
| `--delay, -d` | 0.5 | Seconds to wait before each request (raised to robots.txt `Crawl-delay`, up to 10 s) |
| `--timeout` | 15 | Per-request timeout in seconds |
| `--user-agent, -A` | `canonical-checker/0.1.0 (+https://github.com/calliarc/canonical-checker)` | User-Agent header |
| `--ignore-robots` | off | Skip robots.txt (only for sites you own) |
| `--csv PATH`, `--json PATH` | none | Write reports (`-` for stdout) |
| `--fail-on` | `none` | `none`, `info`, `warning` or `error`: exit 1 if any issue is at least this severe |
| `--min-severity` | `info` | Hide lower-severity issues in all outputs |
| `--max-rows` | 50 | Issue rows shown in the terminal table |
| `--quiet, -q` | off | No table, only files and exit code |

Exit codes: `0` success (or no issue at the `--fail-on` level), `1` issues at or above `--fail-on`,
`2` fatal error (start URL unreachable, blocked by robots.txt, invalid URL).

Scope: the start URL's host plus its `www`/non-`www` twin, over http or https. The host the start URL
redirects to becomes the *preferred* host. External links are never fetched, and redirects that leave the
site are not followed.

### Sample output

Run against the fixture site used in the test suite (abridged):

```text
canonical-checker 0.1.0 - https://example.com  pages fetched: 16, HTML pages parsed: 14, sitemap URLs: 5, blocked by robots.txt: 1
                                               Summary
┏━━━━━━━━━━┳━━━━━━━━━━━━━━━━━━━━━━━━━━━┳━━━━━━━┳━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━┓
┃ Severity ┃ Check                     ┃ Count ┃ What it means                                      ┃
┡━━━━━━━━━━╇━━━━━━━━━━━━━━━━━━━━━━━━━━━╇━━━━━━━╇━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━┩
│ error    │ broken-link               │     1 │ Internal link returns 4xx/5xx                      │
│ error    │ canonical-broken          │     1 │ Canonical target is missing or invalid             │
│ error    │ doubled-host-path         │     1 │ Host name repeated in the URL path                 │
│ error    │ raw-host-href             │     1 │ href starts with a host name but has no scheme     │
│ error    │ sitemap-url-redirect      │     1 │ Sitemap lists a redirecting URL                    │
│ warning  │ link-to-non-canonical     │     5 │ Link points at a page that canonicalises elsewhere │
│ warning  │ mixed-host                │     1 │ Link uses the other www / non-www host             │
│ warning  │ trailing-slash            │     1 │ Trailing slash differs from the site convention    │
│ info     │ link-redirect             │     2 │ Internal link goes through a redirect              │
│ ...      │                           │       │                                                    │
└──────────┴───────────────────────────┴───────┴────────────────────────────────────────────────────┘
                                                         Issues
┏━━━━━━━┳━━━━━━━━━━━━━━━━━━━┳━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━┳━━━━━━━━━━━━━━━━━━━━━━┳━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━┓
┃ Sev   ┃ Check             ┃ URL                                             ┃ Found on             ┃ Detail                       ┃
┡━━━━━━━╇━━━━━━━━━━━━━━━━━━━╇━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━╇━━━━━━━━━━━━━━━━━━━━━━╇━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━┩
│ error │ doubled-host-path │ https://example.com/example.com/privacy-policy/ │ https://example.com/ │ path contains the host       │
│       │                   │                                                 │                      │ "example.com" (HTTP 200)     │
│ error │ raw-host-href     │ https://example.com/example.com/privacy-policy/ │ https://example.com/ │ href="example.com/privacy-   │
│       │                   │                                                 │                      │ policy/" has no scheme or    │
│       │                   │                                                 │                      │ leading slash ...            │
└───────┴───────────────────┴─────────────────────────────────────────────────┴──────────────────────┴──────────────────────────────┘
Total: 8 error(s), 18 warning(s), 2 info
```

CSV columns are `severity, code, url, source, detail, fix` (`source` is the referring page, or the sitemap
that listed the URL). The JSON report adds crawl stats and a `summary` of counts per severity:

```json
{
  "tool": "canonical-checker",
  "version": "0.1.0",
  "site": "https://example.com",
  "pages_fetched": 16,
  "summary": { "error": 8, "warning": 18, "info": 2 },
  "issues": [
    {
      "severity": "error",
      "code": "raw-host-href",
      "url": "https://example.com/example.com/privacy-policy/",
      "source": "https://example.com/",
      "detail": "href=\"example.com/privacy-policy/\" has no scheme or leading slash, ...",
      "fix": "Add https:// in front of the host, or drop the host and start the href with /."
    }
  ]
}
```

### GitHub Action

```yaml
# .github/workflows/canonical.yml
name: Canonical check
on:
  schedule: [{ cron: "0 6 * * 1" }]
  workflow_dispatch:
jobs:
  check:
    runs-on: ubuntu-latest
    steps:
      - id: canonical
        uses: calliarc/canonical-checker@v0.1.0
        with:
          url: https://example.com/
          sitemap: https://example.com/sitemap.xml
          fail-on: error          # none | info | warning | error
          max-pages: "300"
      - if: always()
        uses: actions/upload-artifact@v4
        with:
          name: canonical-report
          path: canonical-checker-report/
```

Inputs: `url` (required), `sitemap`, `max-pages`, `concurrency`, `delay`, `fail-on` (default `error`),
`output-dir`, `extra-args`, `python-version`. Outputs: `json-report`, `csv-report`.

## Checks

Every issue has a severity, the offending URL, and the **source**: the page that contains the link or tag
(or the sitemap that lists the URL).

| Check | Severity | What it means | How to fix |
| --- | --- | --- | --- |
| `raw-host-href` | error | An href such as `example.com/page` or `www.example.com` has no scheme and no leading slash, so it resolves *relative to the current page* | Write `https://example.com/page` or `/page` |
| `doubled-host-path` | error | The URL path contains the site's host, e.g. `/example.com/page/` (usually caused by the above); the detail shows whether the server answers it with 200 | Fix the source link; ideally make such paths 404 or 301 |
| `mixed-host` | warning | Internal link uses the other `www`/non-`www` host | Link to the preferred host |
| `http-link` | warning | `http://` internal link on an https site | Use `https://` |
| `trailing-slash` | warning | Link's trailing slash differs from the site convention (taken from the canonical URLs, or from links if there are none; ties count as "with slash") | Match the canonical form |
| `broken-link` | error | Internal link returns 4xx/5xx | Fix or remove the link, or redirect it |
| `link-redirect` | info | Internal link goes through one redirect | Link to the final URL |
| `redirect-chain` | warning | Link goes through 2 or more redirects | Redirect in one hop and update the link |
| `link-to-non-canonical` | warning | Link points at a 200 page whose canonical is a different URL. This is what produces "Alternate page with proper canonical tag" | Link to the canonical URL |
| `canonical-missing` | warning | No `<link rel="canonical">` | Add a self-referencing absolute canonical |
| `canonical-relative` | warning | Canonical href is relative or protocol-relative | Use an absolute `https://` URL |
| `canonical-multiple` | error | More than one canonical tag (often theme + SEO plugin); Google may ignore them all | Keep exactly one |
| `canonical-not-self` | warning | Canonical points to a different URL on the same host (the detail says whether it is the path, trailing slash, scheme or query) | Make it self-referencing, or stop linking to and listing the duplicate |
| `canonical-cross-host` | warning | Canonical points to a different host (including `www` vs non-`www`) | Use the preferred host, unless cross-domain canonicalisation is intended |
| `canonical-redirect` | error | Canonical target redirects | Point it at the final 200 URL |
| `canonical-broken` | error | Canonical target returns 4xx/5xx or is not a valid URL | Point it at a live page |
| `og-url-mismatch` | warning | `og:url` differs from the canonical | Make them identical |
| `sitemap-url-redirect` | error | Sitemap lists a URL that redirects | List final URLs only |
| `sitemap-url-broken` | error | Sitemap lists a 4xx/5xx URL | Remove it |
| `sitemap-url-non-canonical` | warning | Sitemap lists a URL whose canonical points elsewhere | List the canonical URL |
| `sitemap-error` | error | Sitemap could not be fetched or parsed | Serve valid XML (or gzip) with HTTP 200 |
| `fetch-error` | warning | An in-scope URL failed (timeout, redirect loop, connection error) | Check the server |

Mixed-host and http links on sitemap entries are reported too, with the sitemap as the source.

## Development

```bash
python -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]"
ruff check src tests
pytest -q
```

The tests serve a small fake site through `httpx.MockTransport` (plus one end-to-end run against a
loopback `http.server`) and cover every detector, robots.txt handling, sitemaps (index + gzip) and the
CLI. They never touch the public internet.

## Roadmap

- [x] Initial release
- [x] Documentation and examples
- [x] CI and automated tests
- [ ] `hreflang` alternate checks
- [ ] Canonicals sent in the HTTP `Link:` header
- [ ] HTML report output

Have an idea? [Open an issue](https://github.com/calliarc/canonical-checker/issues).

## Contributing

Contributions are welcome. See [CONTRIBUTING.md](CONTRIBUTING.md).

## Changelog

See [CHANGELOG.md](CHANGELOG.md).

## License

[MIT](LICENSE) © 2026 CalliArc

---

Built and maintained by [CalliArc](https://www.calliarc.com/). Need help with custom software development? [Talk to our team](https://www.calliarc.com/services/custom-software-development/).
