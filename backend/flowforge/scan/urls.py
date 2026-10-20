"""URLs as the scan keeps them (D21): scheme, host and path only. Credentials, query and fragment are dropped."""

from __future__ import annotations

import ipaddress
import re
from urllib.parse import urlsplit

_TEMPLATE = re.compile(r"[{}$<>]")
_API_PATH = re.compile(r"/api(/|$)|/v\d+(\.\d+)?(/|$)")
# never a dependency: documentation and namespace hosts (D21)
_NOT_SERVICES = ("example.com", "example.org", "example.net", "w3.org", "json-schema.org", "schemas.xmlsoap.org")


def clean_url(text: str) -> str | None:
    """`text` reduced to scheme://host[:port]/path when the whole string starts with an http(s) URL, else None."""
    if not text.startswith(("http://", "https://")) or len(text) > 2000:
        return None
    try:
        parts = urlsplit(text)
        host, port = parts.hostname, parts.port
    except ValueError:
        return None
    if not host:
        return None
    labels = [label for label in host.split(".") if label and not _TEMPLATE.search(label)]  # {s}.tile.x.org
    if len(labels) < 1:
        return None
    netloc = ".".join(labels) + (f":{port}" if port else "")
    path = re.split(r"[{$<\s]", parts.path)[0][:120]   # stop before template parts: /driving/$path, /{z}/
    return f"{parts.scheme}://{netloc}{path}"


def host_of(url: str) -> str:
    """host[:port] of a cleaned URL."""
    return urlsplit(url).netloc


def is_local(host: str) -> bool:
    """localhost, private and link-local addresses, `.local` names: on this machine or its network."""
    name = host.rsplit(":", 1)[0] if host.count(":") == 1 else host
    if name in ("localhost", "0.0.0.0") or name.endswith((".local", ".localhost", ".internal")):
        return True
    try:
        ip = ipaddress.ip_address(name.strip("[]"))
    except ValueError:
        return False
    return ip.is_private or ip.is_loopback or ip.is_link_local


def is_ignored(host: str) -> bool:
    name = host.split(":")[0]
    return any(name == h or name.endswith("." + h) for h in _NOT_SERVICES)


def api_shaped(url: str) -> bool:
    """A host that starts with `api.`, or a path with /api/ or a version segment like /v1/."""
    parts = urlsplit(url)
    return parts.netloc.startswith("api.") or bool(_API_PATH.search(parts.path))
