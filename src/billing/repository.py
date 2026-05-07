"""Repository layer — all DB access. No business logic here."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.billing.models import (
    ApiKey,
    Charge,
    ChargeStatus,
    Customer,
    DunningLog,
    Plan,
    Subscription,
    SubscriptionStatus,
    WebhookDelivery,
    WebhookDeliveryStatus,
    WebhookEndpoint,
)


def _now() -> datetime:
    return datetime.now(UTC)


# ─── ApiKey ────────────────────────────────────────────────────────────────


async def create_api_key(session: AsyncSession, key: ApiKey) -> ApiKey:
    """Persist a new API-key record."""
    session.add(key)
    await session.flush()
    return key


async def find_api_key_by_hash(session: AsyncSession, key_hash: str) -> ApiKey | None:
    """Look up an active API-key by its hashed value."""
    stmt = select(ApiKey).where(
        ApiKey.key_hash == key_hash,
        ApiKey.active.is_(True),
        ApiKey.deleted_at.is_(None),
    )
    return (await session.execute(stmt)).scalar_one_or_none()


# ─── Customer ──────────────────────────────────────────────────────────────


async def create_customer(session: AsyncSession, customer: Customer) -> Customer:
    """Persist a new customer."""
    session.add(customer)
    await session.flush()
    return customer


async def get_customer(session: AsyncSession, customer_id: str) -> Customer | None:
    """Fetch a customer by id (excluding soft-deleted)."""
    stmt = select(Customer).where(
        Customer.id == customer_id, Customer.deleted_at.is_(None)
    )
    return (await session.execute(stmt)).scalar_one_or_none()


async def list_customers(session: AsyncSession, limit: int = 50) -> list[Customer]:
    """Return up to ``limit`` non-deleted customers, newest first."""
    stmt = (
        select(Customer)
        .where(Customer.deleted_at.is_(None))
        .order_by(Customer.created_at.desc())
        .limit(limit)
    )
    return list((await session.execute(stmt)).scalars().all())


# ─── Plan ──────────────────────────────────────────────────────────────────


async def create_plan(session: AsyncSession, plan: Plan) -> Plan:
    """Persist a new plan."""
    session.add(plan)
    await session.flush()
    return plan


async def get_plan(session: AsyncSession, plan_id: str) -> Plan | None:
    """Fetch a plan by id (excluding soft-deleted)."""
    stmt = select(Plan).where(Plan.id == plan_id, Plan.deleted_at.is_(None))
    return (await session.execute(stmt)).scalar_one_or_none()


async def list_plans(session: AsyncSession) -> list[Plan]:
    """Return all active plans."""
    stmt = select(Plan).where(Plan.deleted_at.is_(None)).order_by(Plan.created_at.desc())
    return list((await session.execute(stmt)).scalars().all())


# ─── Charge ────────────────────────────────────────────────────────────────


async def create_charge(session: AsyncSession, charge: Charge) -> Charge:
    """Persist a new charge."""
    session.add(charge)
    await session.flush()
    return charge


async def get_charge(session: AsyncSession, charge_id: str) -> Charge | None:
    """Fetch a charge by id."""
    stmt = select(Charge).where(Charge.id == charge_id, Charge.deleted_at.is_(None))
    return (await session.execute(stmt)).scalar_one_or_none()


async def find_charge_by_idempotency(
    session: AsyncSession, idempotency_key: str
) -> Charge | None:
    """Idempotency lookup."""
    stmt = select(Charge).where(
        Charge.idempotency_key == idempotency_key, Charge.deleted_at.is_(None)
    )
    return (await session.execute(stmt)).scalar_one_or_none()


async def list_recent_charges(session: AsyncSession, limit: int = 50) -> list[Charge]:
    """Return the most recent charges."""
    stmt = (
        select(Charge)
        .where(Charge.deleted_at.is_(None))
        .order_by(Charge.created_at.desc())
        .limit(limit)
    )
    return list((await session.execute(stmt)).scalars().all())


async def list_expired_pending_charges(session: AsyncSession) -> list[Charge]:
    """Return PENDING charges whose expires_at has passed."""
    stmt = select(Charge).where(
        Charge.status == ChargeStatus.PENDING,
        Charge.expires_at <= _now(),
        Charge.deleted_at.is_(None),
    )
    return list((await session.execute(stmt)).scalars().all())


async def list_charges_for_subscription(
    session: AsyncSession, subscription_id: str
) -> list[Charge]:
    """Charges belonging to ``subscription_id``."""
    stmt = (
        select(Charge)
        .where(
            Charge.subscription_id == subscription_id,
            Charge.deleted_at.is_(None),
        )
        .order_by(Charge.created_at.desc())
    )
    return list((await session.execute(stmt)).scalars().all())


# ─── Subscription ──────────────────────────────────────────────────────────


async def create_subscription(session: AsyncSession, sub: Subscription) -> Subscription:
    """Persist a new subscription."""
    session.add(sub)
    await session.flush()
    return sub


async def get_subscription(session: AsyncSession, sub_id: str) -> Subscription | None:
    """Fetch a subscription."""
    stmt = select(Subscription).where(
        Subscription.id == sub_id, Subscription.deleted_at.is_(None)
    )
    return (await session.execute(stmt)).scalar_one_or_none()


async def list_subscriptions_due(session: AsyncSession, now: datetime) -> list[Subscription]:
    """Subscriptions whose next_billing_date is at or before ``now``."""
    stmt = select(Subscription).where(
        Subscription.deleted_at.is_(None),
        Subscription.status.in_(
            [SubscriptionStatus.ACTIVE, SubscriptionStatus.TRIALING, SubscriptionStatus.PAST_DUE]
        ),
        Subscription.next_billing_date <= now,
    )
    return list((await session.execute(stmt)).scalars().all())


async def list_active_subscriptions(session: AsyncSession) -> list[Subscription]:
    """All non-canceled subscriptions."""
    stmt = (
        select(Subscription)
        .where(
            Subscription.deleted_at.is_(None),
            Subscription.status != SubscriptionStatus.CANCELED,
        )
        .order_by(Subscription.created_at.desc())
    )
    return list((await session.execute(stmt)).scalars().all())


# ─── Webhook ───────────────────────────────────────────────────────────────


async def create_webhook(session: AsyncSession, wh: WebhookEndpoint) -> WebhookEndpoint:
    """Persist a new webhook endpoint."""
    session.add(wh)
    await session.flush()
    return wh


async def get_webhook(session: AsyncSession, wh_id: str) -> WebhookEndpoint | None:
    """Fetch a webhook endpoint."""
    stmt = select(WebhookEndpoint).where(
        WebhookEndpoint.id == wh_id, WebhookEndpoint.deleted_at.is_(None)
    )
    return (await session.execute(stmt)).scalar_one_or_none()


async def list_webhooks_for_event(
    session: AsyncSession, event_type: str
) -> list[WebhookEndpoint]:
    """Return active webhooks subscribing to ``event_type``."""
    stmt = select(WebhookEndpoint).where(
        WebhookEndpoint.active.is_(True),
        WebhookEndpoint.deleted_at.is_(None),
    )
    rows = list((await session.execute(stmt)).scalars().all())
    return [w for w in rows if event_type in w.events.split(",")]


async def list_webhooks(session: AsyncSession) -> list[WebhookEndpoint]:
    """Return all active webhooks."""
    stmt = (
        select(WebhookEndpoint)
        .where(WebhookEndpoint.deleted_at.is_(None))
        .order_by(WebhookEndpoint.created_at.desc())
    )
    return list((await session.execute(stmt)).scalars().all())


async def create_delivery(session: AsyncSession, delivery: WebhookDelivery) -> WebhookDelivery:
    """Persist a webhook delivery record."""
    session.add(delivery)
    await session.flush()
    return delivery


async def list_recent_deliveries(
    session: AsyncSession, limit: int = 50
) -> list[WebhookDelivery]:
    """Most recent webhook deliveries (for dashboard)."""
    stmt = (
        select(WebhookDelivery).order_by(WebhookDelivery.created_at.desc()).limit(limit)
    )
    return list((await session.execute(stmt)).scalars().all())


async def update_delivery_status(
    session: AsyncSession,
    delivery: WebhookDelivery,
    *,
    status: WebhookDeliveryStatus,
    response_code: int | None,
    response_body: str | None,
    error: str | None,
) -> None:
    """Patch a delivery row after an attempt."""
    delivery.status = status
    delivery.last_response_code = response_code
    delivery.last_response_body = (response_body or "")[:2000] or None
    delivery.last_error = (error or "")[:500] or None
    delivery.attempts = delivery.attempts + 1
    if status in (WebhookDeliveryStatus.SUCCESS, WebhookDeliveryStatus.DROPPED):
        delivery.completed_at = _now()
    await session.flush()


# ─── DunningLog ────────────────────────────────────────────────────────────


async def append_dunning(session: AsyncSession, row: DunningLog) -> DunningLog:
    """Persist a dunning-log row."""
    session.add(row)
    await session.flush()
    return row


async def list_dunning_for_subscription(
    session: AsyncSession, subscription_id: str
) -> list[DunningLog]:
    """Return dunning history for a subscription."""
    stmt = (
        select(DunningLog)
        .where(DunningLog.subscription_id == subscription_id)
        .order_by(DunningLog.created_at.asc())
    )
    return list((await session.execute(stmt)).scalars().all())


# ─── Generic helpers ───────────────────────────────────────────────────────


async def soft_delete(session: AsyncSession, instance: Any) -> None:
    """Set ``deleted_at`` on any model with the column."""
    instance.deleted_at = _now()
    await session.flush()
