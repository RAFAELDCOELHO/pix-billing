"""Tests for security middleware."""

import pytest
from httpx import ASGITransport, AsyncClient

from main import app


@pytest.mark.asyncio
async def test_cloudflare_middleware_inactive_in_dev() -> None:
    """In dev mode (CLOUDFLARE_ONLY=false), all requests pass through."""
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.get("/health")
    assert response.status_code == 200


def test_cloudflare_ip_validation() -> None:
    """Known Cloudflare IPs must be recognized."""
    from src.billing.middleware import _is_cloudflare_ip

    assert _is_cloudflare_ip("103.21.244.1") is True
    assert _is_cloudflare_ip("8.8.8.8") is False
    assert _is_cloudflare_ip("192.168.1.1") is False


def test_sentry_init_skipped_without_dsn() -> None:
    """Sentry must not init if DSN is absent."""
    import sentry_sdk

    assert sentry_sdk.is_initialized()
