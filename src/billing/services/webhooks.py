"""Webhook engine — register endpoints, deliver events with HMAC + retry."""

from __future__ import annotations

import asyncio
import json
import logging
import secrets
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

import httpx
from sqlalchemy.ext.asyncio import AsyncSession

from src.billing import ids, repository
from src.billing.config import get_settings
from src.billing.db import session_scope
from src.billing.events import ALL_EVENTS
from src.billing.models import (
    WebhookDelivery,
    WebhookDeliveryStatus,
    WebhookEndpoint,
)
from src.billing.security import (
    constant_time_eq,
    fingerprint,
    get_audit_logger,
    hmac_sign,
)
from src.billing.url_safety import UnsafeUrlError, validate_webhook_url

log = logging.getLogger("pix_billing.webhooks")

_BACKGROUND_TASKS: set[asyncio.Task[None]] = set()


class WebhookError(Exception):
    """Domain error for webhook operations."""


@dataclass(frozen=True)
class CreatedEndpoint:
    """Result of creating a webhook endpoint — secret returned only here."""

    endpoint: WebhookEndpoint
    plaintext_secret: str


# ─── secret storage ────────────────────────────────────────────────────────


_secret_cache: dict[str, str] = {}
"""Maps endpoint_id -> plaintext secret. In production, keep secrets in a
proper KMS — for an MVP we hold them in memory after creation and on
rotation. The hashed copy in the DB is the source of truth for verification.
"""


def _store_secret(endpoint_id: str, secret: str) -> None:
    _secret_cache[endpoint_id] = secret


def _load_secret(endpoint_id: str) -> str | None:
    return _secret_cache.get(endpoint_id)


# ─── public API ────────────────────────────────────────────────────────────


async def register_endpoint(
    session: AsyncSession,
    *,
    url: str,
    events: list[str],
    description: str = "",
) -> CreatedEndpoint:
    """Register a new webhook endpoint and return the freshly minted secret."""
    settings = get_settings()
    require_https = settings.environment == "production"
    try:
        validate_webhook_url(url, require_https=require_https)
    except UnsafeUrlError as exc:
        raise WebhookError(str(exc)) from exc
    if any(e not in ALL_EVENTS for e in events):
        raise WebhookError("unknown event type")

    secret = secrets.token_urlsafe(32)
    endpoint = WebhookEndpoint(
        id=ids.new_webhook_id(),
        url=url,
        description=description[:200],
        events=",".join(events),
        secret_hash=fingerprint(secret),
        active=True,
    )
    await repository.create_webhook(session, endpoint)
    _store_secret(endpoint.id, secret)
    get_audit_logger().emit(
        event_type="WEBHOOK_REGISTERED",
        actor_id="system",
        resource_id=endpoint.id,
        resource_type="WEBHOOK",
        action="CREATE",
        outcome="SUCCESS",
        details={"events": events},
    )
    return CreatedEndpoint(endpoint=endpoint, plaintext_secret=secret)


async def emit_event(
    event_type: str,
    data: dict[str, Any],
) -> None:
    """Fan out ``event_type`` to every endpoint subscribed to it.

    Creates a `WebhookDelivery` row per endpoint, then schedules background
    delivery. Returns immediately — never blocks the request path.
    """
    if event_type not in ALL_EVENTS:
        raise WebhookError(f"unknown event type: {event_type}")

    payload = {
        "event": event_type,
        "id": ids.new_event_id(),
        "created_at": datetime.now(UTC).isoformat(),
        "data": data,
    }
    payload_json = json.dumps(payload, sort_keys=True, ensure_ascii=False)

    async with session_scope() as session:
        endpoints = await repository.list_webhooks_for_event(session, event_type)
        deliveries: list[tuple[str, str, str]] = []
        for endpoint in endpoints:
            delivery = WebhookDelivery(
                id=ids.new_delivery_id(),
                endpoint_id=endpoint.id,
                event_id=payload["id"],
                event_type=event_type,
                payload=payload_json,
                status=WebhookDeliveryStatus.PENDING,
                attempts=0,
            )
            await repository.create_delivery(session, delivery)
            deliveries.append((delivery.id, endpoint.id, endpoint.url))

    for delivery_id, endpoint_id, url in deliveries:
        task = asyncio.create_task(_deliver(delivery_id, endpoint_id, url, payload_json))
        _BACKGROUND_TASKS.add(task)
        task.add_done_callback(_BACKGROUND_TASKS.discard)


async def _deliver(
    delivery_id: str,
    endpoint_id: str,
    url: str,
    payload_json: str,
) -> None:
    """Deliver one webhook with exponential-backoff retries."""
    settings = get_settings()
    secret = _load_secret(endpoint_id) or ""
    if not secret:
        log.warning("no secret cached for endpoint %s — delivery dropped", endpoint_id)
        async with session_scope() as session:
            delivery = await session.get(WebhookDelivery, delivery_id)
            if delivery is not None:
                await repository.update_delivery_status(
                    session,
                    delivery,
                    status=WebhookDeliveryStatus.DROPPED,
                    response_code=None,
                    response_body=None,
                    error="missing secret",
                )
        return

    settings_for_check = get_settings()
    try:
        validate_webhook_url(
            url, require_https=settings_for_check.environment == "production"
        )
    except UnsafeUrlError as exc:
        async with session_scope() as session:
            delivery = await session.get(WebhookDelivery, delivery_id)
            if delivery is not None:
                await repository.update_delivery_status(
                    session,
                    delivery,
                    status=WebhookDeliveryStatus.DROPPED,
                    response_code=None,
                    response_body=None,
                    error=f"unsafe url: {exc}",
                )
        return

    timestamp = str(int(datetime.now(UTC).timestamp()))
    signed = f"{timestamp}.{payload_json}"
    signature = hmac_sign(secret, signed)
    headers = {
        "Content-Type": "application/json",
        "X-Pix-Signature": f"sha256={signature}",
        "X-Pix-Timestamp": timestamp,
        "User-Agent": "pix-billing/0.1",
    }

    delays = [1, 4, 16]
    last_code: int | None = None
    last_body: str | None = None
    last_error: str | None = None

    for attempt in range(settings.webhook_max_attempts):
        try:
            async with httpx.AsyncClient(timeout=settings.webhook_timeout_seconds) as client:
                resp = await client.post(url, content=payload_json, headers=headers)
            last_code = resp.status_code
            last_body = resp.text[:1000]
            if resp.status_code == 410:
                last_error = "endpoint returned 410 Gone — disabling"
                async with session_scope() as session:
                    delivery = await session.get(WebhookDelivery, delivery_id)
                    endpoint = await session.get(WebhookEndpoint, endpoint_id)
                    if endpoint is not None:
                        endpoint.active = False
                    if delivery is not None:
                        await repository.update_delivery_status(
                            session,
                            delivery,
                            status=WebhookDeliveryStatus.DROPPED,
                            response_code=last_code,
                            response_body=last_body,
                            error=last_error,
                        )
                return
            if 200 <= resp.status_code < 300:
                async with session_scope() as session:
                    delivery = await session.get(WebhookDelivery, delivery_id)
                    if delivery is not None:
                        await repository.update_delivery_status(
                            session,
                            delivery,
                            status=WebhookDeliveryStatus.SUCCESS,
                            response_code=last_code,
                            response_body=last_body,
                            error=None,
                        )
                return
            last_error = f"HTTP {resp.status_code}"
        except httpx.HTTPError as exc:
            last_error = type(exc).__name__
            last_code = None
            last_body = None

        if attempt < settings.webhook_max_attempts - 1:
            await asyncio.sleep(delays[min(attempt, len(delays) - 1)])

    async with session_scope() as session:
        delivery = await session.get(WebhookDelivery, delivery_id)
        if delivery is not None:
            await repository.update_delivery_status(
                session,
                delivery,
                status=WebhookDeliveryStatus.FAILED,
                response_code=last_code,
                response_body=last_body,
                error=last_error,
            )


MAX_WEBHOOK_AGE_SECONDS = 300


def verify_signature(
    secret: str,
    payload: str,
    timestamp: str,
    signature_header: str,
    *,
    max_age_seconds: int = MAX_WEBHOOK_AGE_SECONDS,
) -> bool:
    """Verify ``X-Pix-Signature`` and reject replays older than 5 minutes."""
    if not signature_header.startswith("sha256="):
        return False
    try:
        ts = float(timestamp)
    except ValueError:
        return False
    age = abs(datetime.now(UTC).timestamp() - ts)
    if age > max_age_seconds:
        return False
    expected = hmac_sign(secret, f"{timestamp}.{payload}")
    return constant_time_eq(expected, signature_header.split("=", 1)[1])
