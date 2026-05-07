"""Subscription engine — recurring charges + state machine."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from sqlalchemy.ext.asyncio import AsyncSession

from src.billing import events, ids, repository
from src.billing.models import (
    ChargeStatus,
    Subscription,
    SubscriptionStatus,
)
from src.billing.security import get_audit_logger
from src.billing.services import charges as charge_service
from src.billing.services import customers as customer_service
from src.billing.services import plans as plan_service


class SubscriptionError(Exception):
    """Domain error for subscription operations."""


def _utcnow() -> datetime:
    return datetime.now(UTC)


async def create_subscription(
    session: AsyncSession,
    *,
    customer_id: str,
    plan_id: str,
    actor_id: str = "system",
) -> Subscription:
    """Attach a customer to a plan and start the billing cycle."""
    customer = await customer_service.get_customer(session, customer_id)
    plan = await plan_service.get_plan(session, plan_id)
    if not plan.active:
        raise SubscriptionError("plan is not active")

    now = _utcnow()
    interval_days = plan_service.interval_to_timedelta_days(plan.interval)
    period_end = now + timedelta(days=interval_days)
    if plan.trial_days > 0:
        trial_end = now + timedelta(days=plan.trial_days)
        next_billing = trial_end
        status = SubscriptionStatus.TRIALING
    else:
        trial_end = None
        next_billing = now
        status = SubscriptionStatus.TRIALING  # advanced to ACTIVE when first charge is created

    sub = Subscription(
        id=ids.new_subscription_id(),
        customer_id=customer.id,
        plan_id=plan.id,
        status=status,
        current_period_start=now,
        current_period_end=period_end,
        next_billing_date=next_billing,
        trial_end=trial_end,
        cancel_at_period_end=False,
        dunning_step=0,
    )
    await repository.create_subscription(session, sub)

    get_audit_logger().emit(
        event_type="SUBSCRIPTION_CREATED",
        actor_id=actor_id,
        resource_id=sub.id,
        resource_type="SUBSCRIPTION",
        action="CREATE",
        outcome="SUCCESS",
        details={"plan_id": plan.id, "trial_days": plan.trial_days},
    )
    return sub


async def cancel_subscription(
    session: AsyncSession,
    sub_id: str,
    *,
    actor_id: str = "system",
    immediate: bool = False,
) -> Subscription:
    """Cancel a subscription — immediately or at end of period."""
    sub = await repository.get_subscription(session, sub_id)
    if sub is None:
        raise SubscriptionError("subscription not found")
    if sub.status == SubscriptionStatus.CANCELED:
        return sub

    if immediate:
        sub.status = SubscriptionStatus.CANCELED
        sub.canceled_at = _utcnow()
    else:
        sub.cancel_at_period_end = True
    await session.flush()

    get_audit_logger().emit(
        event_type="SUBSCRIPTION_CANCELED",
        actor_id=actor_id,
        resource_id=sub.id,
        resource_type="SUBSCRIPTION",
        action="CANCEL",
        outcome="SUCCESS",
        details={"immediate": immediate},
    )
    if immediate:
        sub._emitted_event = events.SUBSCRIPTION_CANCELED  # type: ignore[attr-defined]
    return sub


async def renew_subscription(
    session: AsyncSession,
    sub: Subscription,
) -> tuple[Subscription, object]:
    """Generate the next charge for ``sub`` and advance billing state.

    Returns a ``(subscription, charge)`` tuple. Idempotent — if there is
    already a PENDING charge for the current period, that charge is returned.
    """
    plan = await plan_service.get_plan(session, sub.plan_id)
    existing = await repository.list_charges_for_subscription(session, sub.id)
    pending = [c for c in existing if c.status == ChargeStatus.PENDING]
    if pending:
        return sub, pending[0]

    charge = await charge_service.create_charge(
        session,
        amount_cents=plan.amount_cents,
        description=f"{plan.name} - {sub.id}",
        customer_id=sub.customer_id,
        subscription_id=sub.id,
        actor_id="scheduler",
    )

    if sub.status == SubscriptionStatus.TRIALING:
        sub.status = SubscriptionStatus.ACTIVE
        sub._emitted_event = events.SUBSCRIPTION_ACTIVATED  # type: ignore[attr-defined]
    else:
        sub._emitted_event = events.SUBSCRIPTION_RENEWED  # type: ignore[attr-defined]

    interval_days = plan_service.interval_to_timedelta_days(plan.interval)
    sub.current_period_start = sub.current_period_end
    sub.current_period_end = sub.current_period_end + timedelta(days=interval_days)
    sub.next_billing_date = sub.current_period_end
    sub.dunning_step = 0
    await session.flush()
    return sub, charge


async def list_invoices(session: AsyncSession, sub_id: str) -> list[object]:
    """Return all charges (invoices) for a subscription."""
    sub = await repository.get_subscription(session, sub_id)
    if sub is None:
        raise SubscriptionError("subscription not found")
    return list(await repository.list_charges_for_subscription(session, sub_id))
