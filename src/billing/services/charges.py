"""Charge service — issuance, expiry, manual confirmation."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from sqlalchemy.ext.asyncio import AsyncSession

from src.billing import events, ids, repository
from src.billing.config import get_settings
from src.billing.models import Charge, ChargeStatus
from src.billing.pix import PixChargeSpec, build_pix_payload, render_qr_base64
from src.billing.security import get_audit_logger


class ChargeError(Exception):
    """Domain error raised by the charge service."""


def _utcnow() -> datetime:
    return datetime.now(UTC)


async def create_charge(
    session: AsyncSession,
    *,
    amount_cents: int,
    description: str,
    customer_id: str | None = None,
    subscription_id: str | None = None,
    expires_in: int | None = None,
    idempotency_key: str | None = None,
    actor_id: str = "system",
) -> Charge:
    """Generate a fresh PIX charge and emit ``charge.created``.

    If an ``idempotency_key`` is supplied and a charge already exists with the
    same key, that charge is returned unchanged (Stripe-style idempotency).
    """
    settings = get_settings()

    if amount_cents < settings.charge_min_cents:
        raise ChargeError(f"amount must be at least {settings.charge_min_cents} cents")
    if amount_cents > settings.charge_max_cents:
        raise ChargeError(f"amount must be at most {settings.charge_max_cents} cents")
    if len(description) > 140:
        raise ChargeError("description exceeds 140 chars")

    if idempotency_key:
        existing = await repository.find_charge_by_idempotency(session, idempotency_key)
        if existing is not None:
            return existing

    ttl = expires_in or settings.charge_default_ttl_seconds
    txid = ids.new_txid()
    payload = build_pix_payload(
        PixChargeSpec(
            pix_key=settings.pix_default_key,
            txid=txid,
            amount_cents=amount_cents,
            description=description,
            merchant_name=settings.pix_merchant_name,
            merchant_city=settings.pix_merchant_city,
        )
    )
    qr_b64 = render_qr_base64(payload)

    charge = Charge(
        id=ids.new_charge_id(),
        customer_id=customer_id,
        subscription_id=subscription_id,
        txid=txid,
        amount_cents=amount_cents,
        description=description,
        status=ChargeStatus.PENDING,
        pix_payload=payload,
        qr_code_base64=qr_b64,
        expires_at=_utcnow() + timedelta(seconds=ttl),
        idempotency_key=idempotency_key,
    )
    await repository.create_charge(session, charge)

    get_audit_logger().emit(
        event_type="CHARGE_CREATED",
        actor_id=actor_id,
        resource_id=charge.id,
        resource_type="CHARGE",
        action="CREATE",
        outcome="SUCCESS",
        details={"amount_cents": amount_cents, "txid": txid},
    )

    # event emission is handled by the api layer via webhook engine
    charge._emitted_event = events.CHARGE_CREATED  # type: ignore[attr-defined]
    return charge


async def confirm_charge(
    session: AsyncSession,
    charge_id: str,
    *,
    actor_id: str = "system",
) -> Charge:
    """Mark a charge as PAID — sandbox replacement for a real PSP webhook."""
    charge = await repository.get_charge(session, charge_id)
    if charge is None:
        raise ChargeError("charge not found")
    if charge.status == ChargeStatus.PAID:
        return charge
    if charge.status != ChargeStatus.PENDING:
        raise ChargeError(f"cannot confirm charge in status {charge.status.value}")

    charge.status = ChargeStatus.PAID
    charge.paid_at = _utcnow()
    await session.flush()

    get_audit_logger().emit(
        event_type="CHARGE_PAID",
        actor_id=actor_id,
        resource_id=charge.id,
        resource_type="CHARGE",
        action="CONFIRM",
        outcome="SUCCESS",
        details={"amount_cents": charge.amount_cents},
    )
    charge._emitted_event = events.CHARGE_PAID  # type: ignore[attr-defined]
    return charge


async def expire_charge(session: AsyncSession, charge: Charge) -> Charge:
    """Move ``charge`` from PENDING → EXPIRED."""
    if charge.status != ChargeStatus.PENDING:
        return charge
    charge.status = ChargeStatus.EXPIRED
    await session.flush()
    get_audit_logger().emit(
        event_type="CHARGE_EXPIRED",
        actor_id="scheduler",
        resource_id=charge.id,
        resource_type="CHARGE",
        action="EXPIRE",
        outcome="SUCCESS",
        details={},
    )
    charge._emitted_event = events.CHARGE_EXPIRED  # type: ignore[attr-defined]
    return charge


async def expire_all_due(session: AsyncSession) -> list[Charge]:
    """Expire every pending charge whose expires_at is in the past."""
    due = await repository.list_expired_pending_charges(session)
    out: list[Charge] = []
    for c in due:
        out.append(await expire_charge(session, c))
    return out


async def cancel_charge(session: AsyncSession, charge_id: str, *, actor_id: str) -> Charge:
    """Cancel a pending charge."""
    charge = await repository.get_charge(session, charge_id)
    if charge is None:
        raise ChargeError("charge not found")
    if charge.status != ChargeStatus.PENDING:
        raise ChargeError(f"cannot cancel charge in status {charge.status.value}")
    charge.status = ChargeStatus.CANCELED
    await session.flush()
    get_audit_logger().emit(
        event_type="CHARGE_CANCELED",
        actor_id=actor_id,
        resource_id=charge.id,
        resource_type="CHARGE",
        action="CANCEL",
        outcome="SUCCESS",
        details={},
    )
    charge._emitted_event = events.CHARGE_CANCELED  # type: ignore[attr-defined]
    return charge
