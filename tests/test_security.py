"""Security regression tests."""

from __future__ import annotations

import time

from httpx import AsyncClient

from sdk.pix_billing import verify_signature
from src.billing.security import hmac_sign
from src.billing.url_safety import UnsafeUrlError, validate_webhook_url


async def test_security_headers_present(client: AsyncClient) -> None:
    resp = await client.get("/health")
    assert resp.headers["X-Content-Type-Options"] == "nosniff"
    assert resp.headers["X-Frame-Options"] == "DENY"
    assert "Strict-Transport-Security" in resp.headers
    assert "Content-Security-Policy" in resp.headers
    assert resp.headers["Referrer-Policy"] == "no-referrer"


async def test_dashboard_requires_basic_auth(client: AsyncClient) -> None:
    bearer = client.headers.pop("Authorization")
    try:
        resp = await client.get("/dashboard")
    finally:
        client.headers["Authorization"] = bearer
    assert resp.status_code == 401
    assert "Basic" in resp.headers.get("WWW-Authenticate", "")


def test_signature_replay_rejected() -> None:
    secret = "shh"
    payload = '{"event":"charge.paid"}'
    old_ts = str(int(time.time()) - 3600)  # one hour ago
    sig = "sha256=" + hmac_sign(secret, f"{old_ts}.{payload}")
    assert verify_signature(secret, payload, old_ts, sig) is False


def test_signature_fresh_accepted() -> None:
    secret = "shh"
    payload = '{"event":"charge.paid"}'
    ts = str(int(time.time()))
    sig = "sha256=" + hmac_sign(secret, f"{ts}.{payload}")
    assert verify_signature(secret, payload, ts, sig) is True


def test_signature_tampered_rejected() -> None:
    secret = "shh"
    payload = '{"event":"charge.paid"}'
    ts = str(int(time.time()))
    sig = "sha256=" + hmac_sign(secret, f"{ts}.{payload}")
    assert verify_signature(secret, payload + "x", ts, sig) is False


def test_ssrf_blocks_localhost() -> None:
    import pytest

    with pytest.raises(UnsafeUrlError):
        validate_webhook_url("http://127.0.0.1/hook", require_https=False)
    with pytest.raises(UnsafeUrlError):
        validate_webhook_url("http://10.0.0.1/hook", require_https=False)
    with pytest.raises(UnsafeUrlError):
        validate_webhook_url("http://192.168.1.1/hook", require_https=False)


def test_ssrf_https_required_in_prod() -> None:
    import pytest

    with pytest.raises(UnsafeUrlError):
        validate_webhook_url("http://example.com/hook", require_https=True)


async def test_strict_pydantic_rejects_string_amount(client: AsyncClient) -> None:
    resp = await client.post(
        "/v1/charges", json={"amount": "100", "description": "x"}
    )
    assert resp.status_code == 422


async def test_invalid_api_key_rejected(client: AsyncClient) -> None:
    client.headers["Authorization"] = "Bearer pk_test_definitelynotreal"
    resp = await client.post("/v1/charges", json={"amount": 100, "description": "x"})
    assert resp.status_code == 401
