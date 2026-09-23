# Canonical Checker

CLI that crawls a site and flags doubled paths, mixed hosts and canonical mismatches.

[![License: MIT](https://img.shields.io/badge/License-MIT-blue.svg)](LICENSE)
![Status: in development](https://img.shields.io/badge/status-in%20development-orange)

> **Status:** in active development. Star or watch the repo to follow progress.

## Features

- Crawls from a start URL or a sitemap
- Flags doubled paths such as /example.com/page
- Detects mixed www/non-www and http/https links
- Finds inconsistent trailing slashes
- Checks that canonical tags are absolute and self-referencing
- Reports which page contains each bad link
- CSV and JSON output; usable in CI

## Tech stack

- Python 3.11+
- httpx
- selectolax
- Typer (CLI)

## Getting started

Setup instructions will be added with the first release.

## Roadmap

- [ ] Initial release
- [ ] Documentation and examples
- [ ] CI and automated tests

Have an idea? [Open an issue](https://github.com/calliarc/canonical-checker/issues).

## Contributing

Contributions are welcome. See [CONTRIBUTING.md](CONTRIBUTING.md).

## License

[MIT](LICENSE) © 2026 CalliArc

---

Built and maintained by [CalliArc](https://www.calliarc.com/). Need help with custom software development? [Talk to our team](https://www.calliarc.com/services/custom-software-development/).
