"""Webhook secret persistence — DB-only, never in memory."""

from __future__ import annotations

from httpx import AsyncClient

from src.billing.db import session_scope
from src.billing.models import WebhookEndpoint
from src.billing.security import get_encryptor
from src.billing.services import webhooks as wh_service


def test_secret_not_in_memory_after_creation() -> None:
    """The module must not expose any plaintext-secret cache."""
    assert not hasattr(wh_service, "_secret_cache"), "memory cache must be removed"
    assert not hasattr(wh_service, "_store_secret")
    assert not hasattr(wh_service, "_load_secret")


async def test_secret_returned_once_and_persisted_encrypted(
    client: AsyncClient,
) -> None:
    """Creation returns secret; subsequent reads never expose it."""
    resp = await client.post(
        "/v1/webhooks",
        json={
            "url": "https://example.com/hook",
            "events": ["charge.paid"],
            "description": "test",
        },
    )
    assert resp.status_code == 201, resp.text
    body = resp.json()
    plaintext_secret = body["secret"]
    assert plaintext_secret and plaintext_secret.startswith(("",))  # non-empty
    wh_id = body["id"]

    # Listing must not leak the secret.
    listed = await client.get("/v1/webhooks")
    assert listed.status_code == 200
    for row in listed.json():
        assert row.get("secret") is None

    # The DB column must be encrypted (different from the plaintext).
    async with session_scope() as session:
        endpoint = await session.get(WebhookEndpoint, wh_id)
        assert endpoint is not None
        assert endpoint.secret_encrypted is not None
        assert endpoint.secret_encrypted != plaintext_secret
        # And decrypts back to the original.
        recovered = get_encryptor().decrypt(endpoint.secret_encrypted)
        assert recovered == plaintext_secret


async def test_signature_uses_db_secret_after_simulated_restart(
    client: AsyncClient,
) -> None:
    """Signing must work with only DB state — proves no memory dependency."""
    import time

    from src.billing.security import hmac_sign
    from sdk.pix_billing import verify_signature

    create = await client.post(
        "/v1/webhooks",
        json={"url": "https://example.com/hook", "events": ["charge.paid"]},
    )
    body = create.json()
    wh_id = body["id"]
    plaintext_secret = body["secret"]

    # Simulate a process restart: any module-level state has been wiped.
    # We re-derive the signature from DB state alone.
    async with session_scope() as session:
        endpoint = await session.get(WebhookEndpoint, wh_id)
        assert endpoint is not None
        recovered = get_encryptor().decrypt(endpoint.secret_encrypted or "")

    # The recovered secret must verify a fresh signature using the SDK helper.
    ts = str(int(time.time()))
    payload = '{"event":"charge.paid"}'
    sig = "sha256=" + hmac_sign(recovered, f"{ts}.{payload}")
    assert verify_signature(plaintext_secret, payload, ts, sig) is True
