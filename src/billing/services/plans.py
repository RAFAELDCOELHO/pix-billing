"""Plan service — create and look up subscription plans."""

from __future__ import annotations

from sqlalchemy.ext.asyncio import AsyncSession

from src.billing import ids, repository
from src.billing.config import get_settings
from src.billing.models import Plan, PlanInterval


class PlanError(Exception):
    """Domain error for plan operations."""


async def create_plan(
    session: AsyncSession,
    *,
    name: str,
    amount_cents: int,
    interval: str,
    trial_days: int = 0,
) -> Plan:
    """Persist a new billing plan."""
    settings = get_settings()
    if not name.strip():
        raise PlanError("name is required")
    if amount_cents < settings.charge_min_cents:
        raise PlanError(f"amount must be at least {settings.charge_min_cents} cents")
    if amount_cents > settings.charge_max_cents:
        raise PlanError(f"amount must be at most {settings.charge_max_cents} cents")
    if trial_days < 0 or trial_days > 365:
        raise PlanError("trial_days out of range")
    try:
        interval_enum = PlanInterval(interval)
    except ValueError as exc:
        raise PlanError(f"invalid interval: {interval}") from exc

    plan = Plan(
        id=ids.new_plan_id(),
        name=name.strip(),
        amount_cents=amount_cents,
        interval=interval_enum,
        trial_days=trial_days,
        active=True,
    )
    await repository.create_plan(session, plan)
    return plan


async def get_plan(session: AsyncSession, plan_id: str) -> Plan:
    """Fetch a plan or raise."""
    plan = await repository.get_plan(session, plan_id)
    if plan is None:
        raise PlanError("plan not found")
    return plan


def interval_to_timedelta_days(interval: PlanInterval) -> int:
    """Approximate days per cycle for ``interval``."""
    match interval:
        case PlanInterval.MONTHLY:
            return 30
        case PlanInterval.QUARTERLY:
            return 90
        case PlanInterval.ANNUAL:
            return 365
