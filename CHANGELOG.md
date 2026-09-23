# Changelog

All notable changes to this project are documented here.
The format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project uses [Semantic Versioning](https://semver.org/).

## [Unreleased]

## [0.1.0] - 2026-09-23

First working release.

### Added

- Crawls from a start URL or a sitemap (sitemap index and `.xml.gz` supported)
- Flags doubled paths such as /example.com/page, and the raw `href="example.com/..."` that causes them
- Detects mixed www/non-www and http/https links
- Finds inconsistent trailing slashes
- Checks that canonical tags are absolute and self-referencing, that there is only one, that they do not point to redirects, 4xx pages or another host, and that `og:url` matches
- Finds redirect chains, broken internal links and links to non-canonical URLs
- Checks sitemap URLs for redirects, 404s and non-canonical entries
- Reports which page contains each bad link
- Polite by default: honours robots.txt (including `Crawl-delay`), 2 parallel requests, 0.5 s delay, custom user agent
- Rich terminal summary, CSV and JSON output; `--fail-on` exit codes and a GitHub Action for CI

[Unreleased]: https://github.com/calliarc/canonical-checker/compare/v0.1.0...HEAD
[0.1.0]: https://github.com/calliarc/canonical-checker/releases/tag/v0.1.0
