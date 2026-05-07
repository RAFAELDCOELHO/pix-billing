"""Dunning engine — retry unpaid charges before canceling a subscription."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from sqlalchemy.ext.asyncio import AsyncSession

from src.billing import events, repository
from src.billing.models import (
    ChargeStatus,
    DunningLog,
    Subscription,
    SubscriptionStatus,
)
from src.billing.security import get_audit_logger
from src.billing.services import charges as charge_service
from src.billing.services import plans as plan_service

DUNNING_SCHEDULE: list[dict[str, int | str]] = [
    {"day_offset": 1, "action": "retry_charge"},
    {"day_offset": 3, "action": "retry_charge"},
    {"day_offset": 7, "action": "retry_charge"},
    {"day_offset": 8, "action": "cancel_subscription"},
]


def _utcnow() -> datetime:
    return datetime.now(UTC)


async def run_dunning(session: AsyncSession, sub: Subscription) -> Subscription:
    """Advance dunning for ``sub`` if its latest charge is overdue.

    Idempotent — running twice on the same day produces no duplicate retries.
    """
    if sub.status not in (
        SubscriptionStatus.ACTIVE,
        SubscriptionStatus.PAST_DUE,
        SubscriptionStatus.TRIALING,
    ):
        return sub

    history = await repository.list_charges_for_subscription(session, sub.id)
    if not history:
        return sub

    latest = history[0]
    if latest.status == ChargeStatus.PAID:
        if sub.status == SubscriptionStatus.PAST_DUE:
            sub.status = SubscriptionStatus.ACTIVE
            await session.flush()
        return sub

    overdue = (_utcnow() - latest.expires_at).days
    if overdue < 1:
        return sub

    sub.status = SubscriptionStatus.PAST_DUE
    sub._emitted_event = events.SUBSCRIPTION_PAST_DUE  # type: ignore[attr-defined]

    step_idx = sub.dunning_step
    if step_idx >= len(DUNNING_SCHEDULE):
        return sub

    step = DUNNING_SCHEDULE[step_idx]
    expected_day = int(step["day_offset"])
    if overdue < expected_day:
        return sub

    action = str(step["action"])
    if action == "retry_charge":
        plan = await plan_service.get_plan(session, sub.plan_id)
        new_charge = await charge_service.create_charge(
            session,
            amount_cents=plan.amount_cents,
            description=f"Retry {step_idx + 1} - {plan.name}",
            customer_id=sub.customer_id,
            subscription_id=sub.id,
            expires_in=86400,
            actor_id="dunning",
        )
        await repository.append_dunning(
            session,
            DunningLog(
                subscription_id=sub.id,
                step=step_idx + 1,
                action=action,
                charge_id=new_charge.id,
            ),
        )
        get_audit_logger().emit(
            event_type="DUNNING_RETRY",
            actor_id="dunning",
            resource_id=sub.id,
            resource_type="SUBSCRIPTION",
            action="RETRY",
            outcome="SUCCESS",
            details={"step": step_idx + 1, "charge_id": new_charge.id},
        )
    elif action == "cancel_subscription":
        sub.status = SubscriptionStatus.CANCELED
        sub.canceled_at = _utcnow()
        sub._emitted_event = events.SUBSCRIPTION_CANCELED  # type: ignore[attr-defined]
        await repository.append_dunning(
            session,
            DunningLog(
                subscription_id=sub.id,
                step=step_idx + 1,
                action=action,
            ),
        )
        get_audit_logger().emit(
            event_type="DUNNING_CANCEL",
            actor_id="dunning",
            resource_id=sub.id,
            resource_type="SUBSCRIPTION",
            action="CANCEL",
            outcome="SUCCESS",
            details={"step": step_idx + 1},
        )

    sub.dunning_step = step_idx + 1
    sub.next_billing_date = _utcnow() + timedelta(days=1)
    await session.flush()
    return sub
