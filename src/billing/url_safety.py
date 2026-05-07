"""SSRF guard: webhook URL validation."""

from __future__ import annotations

import ipaddress
import socket
from urllib.parse import urlparse

_BLOCKED_PORTS = {0, 22, 23, 25, 53, 110, 143, 445, 3306, 5432, 6379, 9200, 11211, 27017}


class UnsafeUrlError(ValueError):
    """Raised when a URL fails SSRF/webhook safety checks."""


def validate_webhook_url(url: str, *, require_https: bool) -> None:
    """Reject URLs that would let an attacker pivot through this service.

    Checks:
    - Scheme must be http or https (https only when ``require_https``).
    - Host must be present.
    - Port not in a blocklist of common internal services.
    - All resolved IPs (A/AAAA) must be public — no loopback, link-local,
      private, multicast, reserved, or unspecified addresses.
    """
    parsed = urlparse(url)

    if parsed.scheme not in ("http", "https"):
        raise UnsafeUrlError("scheme must be http or https")
    if require_https and parsed.scheme != "https":
        raise UnsafeUrlError("https required in production")

    host = parsed.hostname
    if not host:
        raise UnsafeUrlError("missing host")

    if parsed.port is not None and parsed.port in _BLOCKED_PORTS:
        raise UnsafeUrlError(f"port {parsed.port} is blocked")

    candidates = _resolve(host)
    if not candidates:
        raise UnsafeUrlError("could not resolve host")
    for ip in candidates:
        if not _is_public(ip):
            raise UnsafeUrlError(f"resolved address {ip} is not publicly routable")


def _resolve(host: str) -> list[ipaddress.IPv4Address | ipaddress.IPv6Address]:
    """Resolve ``host`` to a list of IP addresses (DNS or literal)."""
    try:
        ip = ipaddress.ip_address(host)
        return [ip]
    except ValueError:
        pass
    try:
        infos = socket.getaddrinfo(host, None)
    except socket.gaierror:
        return []
    out: list[ipaddress.IPv4Address | ipaddress.IPv6Address] = []
    for info in infos:
        sockaddr = info[4]
        try:
            out.append(ipaddress.ip_address(sockaddr[0]))
        except (ValueError, IndexError):
            continue
    return out


def _is_public(ip: ipaddress.IPv4Address | ipaddress.IPv6Address) -> bool:
    """Return True only for publicly routable unicast addresses."""
    if (
        ip.is_loopback
        or ip.is_link_local
        or ip.is_multicast
        or ip.is_reserved
        or ip.is_unspecified
        or ip.is_private
    ):
        return False
    return True
