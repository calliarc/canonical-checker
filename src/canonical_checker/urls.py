"""URL helpers: normalisation, scope and pattern detection."""

from __future__ import annotations

import re
from dataclasses import dataclass
from urllib.parse import urlsplit, urlunsplit

_SCHEME_RE = re.compile(r"^[a-zA-Z][a-zA-Z0-9+.\-]*:")
_DEFAULT_PORTS = {"http": 80, "https": 443}
# "example.com:8080/..." parses as scheme "example.com"; it is really host:port.
HOST_PORT_RE = re.compile(r"^[a-z0-9-]+(\.[a-z0-9-]+)+:\d+(/|$)", re.I)

#: href schemes that are never crawled or checked.
SKIP_SCHEMES = frozenset(
    {"mailto", "tel", "javascript", "data", "sms", "ftp", "file", "about", "blob", "callto"}
)


def normalize(url: str) -> str | None:
    """Return a comparable form of an http(s) URL, or ``None`` if it is not one.

    Lower-cases scheme and host, drops default ports, user info and fragments,
    and turns an empty path into ``/``. Paths (including trailing slashes) and
    query strings are kept as-is because they are significant for canonicals.
    """
    try:
        parts = urlsplit(url.strip())
        port = parts.port
    except ValueError:
        return None
    scheme = parts.scheme.lower()
    if scheme not in _DEFAULT_PORTS:
        return None
    host = (parts.hostname or "").lower().rstrip(".")
    if not host:
        return None
    if ":" in host:  # IPv6 literal
        host = f"[{host}]"
    netloc = host if port in (None, _DEFAULT_PORTS[scheme]) else f"{host}:{port}"
    return urlunsplit((scheme, netloc, parts.path or "/", parts.query, ""))


def host_of(url: str) -> str:
    return (urlsplit(url).hostname or "").lower()


def bare_host(host: str) -> str:
    host = host.lower()
    return host[4:] if host.startswith("www.") else host


def has_scheme(raw: str) -> bool:
    return bool(_SCHEME_RE.match(raw.strip()))


def scheme_of(raw: str) -> str:
    match = _SCHEME_RE.match(raw.strip())
    return match.group(0)[:-1].lower() if match else ""


def is_absolute_http(raw: str) -> bool:
    """True for ``https://host/...`` style URLs (not relative, not protocol-relative)."""
    return scheme_of(raw) in _DEFAULT_PORTS and raw.strip()[len(scheme_of(raw)) + 1 :].startswith("//")


def is_sitemap_url(url: str) -> bool:
    path = urlsplit(url).path.lower()
    return path.endswith((".xml", ".xml.gz"))


@dataclass(frozen=True)
class Site:
    """The site being checked: its preferred scheme/host and the hosts in scope."""

    scheme: str
    host: str
    port: int | None = None

    @property
    def hosts(self) -> frozenset[str]:
        bare = bare_host(self.host)
        return frozenset({bare, f"www.{bare}"})

    @property
    def origin(self) -> str:
        default = _DEFAULT_PORTS.get(self.scheme)
        port = f":{self.port}" if self.port and self.port != default else ""
        return f"{self.scheme}://{self.host}{port}"

    @classmethod
    def from_url(cls, url: str) -> Site:
        parts = urlsplit(url)
        return cls(scheme=parts.scheme.lower(), host=(parts.hostname or "").lower(), port=parts.port)

    def in_scope(self, url: str) -> bool:
        """Same-site scope: the preferred host and its www / non-www twin, http or https."""
        parts = urlsplit(url)
        return parts.scheme in _DEFAULT_PORTS and (parts.hostname or "").lower() in self.hosts


def raw_host_prefix(raw: str, hosts: frozenset[str]) -> str | None:
    """Detect hrefs such as ``example.com/page`` written without a scheme or leading slash.

    Browsers treat these as *relative* paths, which produces URLs like
    ``https://example.com/current/example.com/page``. Returns the host-like
    first segment when the href looks like that, else ``None``.
    """
    value = raw.strip()
    if not value or value.startswith(("/", "#", "?", ".")):
        return None
    if has_scheme(value) and not HOST_PORT_RE.match(value):
        return None
    first = re.split(r"[/?#]", value, maxsplit=1)[0].lower()
    first = re.sub(r":\d+$", "", first)  # "example.com:8080/x"
    if first in hosts:
        return first
    if first.startswith("www.") and "." in first[4:]:
        return first
    return None


def doubled_host_segment(url: str, hosts: frozenset[str]) -> str | None:
    """Return the path segment that repeats the site's host name (``/example.com/...``)."""
    for segment in urlsplit(url).path.split("/"):
        if segment and re.sub(r":\d+$", "", segment.lower()) in hosts:
            return segment
    return None


def slash_applicable(path: str) -> bool:
    """Trailing-slash style only matters for non-root paths that do not look like files."""
    if path in ("", "/"):
        return False
    last = path.rstrip("/").rsplit("/", 1)[-1]
    return "." not in last


def has_trailing_slash(path: str) -> bool:
    return path.endswith("/")


def describe_difference(a: str, b: str) -> str:
    """Human-readable explanation of how two URLs differ (used in issue details)."""
    pa, pb = urlsplit(a), urlsplit(b)
    diffs = []
    if pa.scheme != pb.scheme:
        diffs.append(f"scheme {pa.scheme} vs {pb.scheme}")
    if pa.netloc != pb.netloc:
        diffs.append(f"host {pa.netloc} vs {pb.netloc}")
    if pa.path != pb.path:
        if pa.path.rstrip("/") == pb.path.rstrip("/"):
            diffs.append("trailing slash")
        else:
            diffs.append("path")
    if pa.query != pb.query:
        diffs.append("query string")
    return ", ".join(diffs) if diffs else "identical"
