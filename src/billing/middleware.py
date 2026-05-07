"""
Security middleware for PIX Billing Stack.

CloudflareMiddleware: when CLOUDFLARE_ONLY=true, rejects any request
that did not pass through Cloudflare's proxy. Safe to enable only after
the domain is pointed at Cloudflare. Leave false in development.
"""

from __future__ import annotations

import ipaddress
import logging
from collections.abc import Awaitable, Callable

from fastapi import Request, Response
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.types import ASGIApp

log = logging.getLogger(__name__)

# Official Cloudflare IP ranges (updated May 2026)
# Full list: https://www.cloudflare.com/ips/
CLOUDFLARE_RANGES: list[ipaddress.IPv4Network | ipaddress.IPv6Network] = [
    ipaddress.IPv4Network("103.21.244.0/22"),
    ipaddress.IPv4Network("103.22.200.0/22"),
    ipaddress.IPv4Network("103.31.4.0/22"),
    ipaddress.IPv4Network("104.16.0.0/13"),
    ipaddress.IPv4Network("104.24.0.0/14"),
    ipaddress.IPv4Network("108.162.192.0/18"),
    ipaddress.IPv4Network("131.0.72.0/22"),
    ipaddress.IPv4Network("141.101.64.0/18"),
    ipaddress.IPv4Network("162.158.0.0/15"),
    ipaddress.IPv4Network("172.64.0.0/13"),
    ipaddress.IPv4Network("173.245.48.0/20"),
    ipaddress.IPv4Network("188.114.96.0/20"),
    ipaddress.IPv4Network("190.93.240.0/20"),
    ipaddress.IPv4Network("197.234.240.0/22"),
    ipaddress.IPv4Network("198.41.128.0/17"),
    ipaddress.IPv6Network("2400:cb00::/32"),
    ipaddress.IPv6Network("2606:4700::/32"),
    ipaddress.IPv6Network("2803:f800::/32"),
    ipaddress.IPv6Network("2405:b500::/32"),
    ipaddress.IPv6Network("2405:8100::/32"),
    ipaddress.IPv6Network("2a06:98c0::/29"),
    ipaddress.IPv6Network("2c0f:f248::/32"),
]


def _is_cloudflare_ip(ip_str: str) -> bool:
    """Return True if the IP belongs to a known Cloudflare range."""
    try:
        ip = ipaddress.ip_address(ip_str)
        return any(ip in net for net in CLOUDFLARE_RANGES)
    except ValueError:
        return False


class CloudflareMiddleware(BaseHTTPMiddleware):
    """Reject requests that did not pass through Cloudflare."""

    def __init__(self, app: ASGIApp, *, cloudflare_only: bool = False) -> None:
        super().__init__(app)
        self.cloudflare_only = cloudflare_only
        if cloudflare_only:
            log.info("CloudflareMiddleware: ACTIVE — non-Cloudflare traffic will be rejected")
        else:
            log.info("CloudflareMiddleware: INACTIVE — pass-through mode (development)")

    async def dispatch(
        self,
        request: Request,
        call_next: Callable[[Request], Awaitable[Response]],
    ) -> Response:
        if not self.cloudflare_only:
            return await call_next(request)

        connecting_ip = request.client.host if request.client else None
        cf_header = request.headers.get("CF-Connecting-IP")

        if not cf_header or not connecting_ip:
            log.warning("Blocked request: missing Cloudflare headers from %s", connecting_ip)
            return Response("Forbidden", status_code=403)

        if not _is_cloudflare_ip(connecting_ip):
            log.warning("Blocked request: non-Cloudflare IP %s", connecting_ip)
            return Response("Forbidden", status_code=403)

        return await call_next(request)
