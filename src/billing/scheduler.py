"""APScheduler wiring for periodic billing jobs."""

from __future__ import annotations

import logging
from datetime import UTC, datetime

from apscheduler.schedulers.asyncio import AsyncIOScheduler

from src.billing.db import session_scope
from src.billing.repository import list_active_subscriptions, list_subscriptions_due
from src.billing.services import charges as charge_service
from src.billing.services import dunning as dunning_service
from src.billing.services import subscriptions as subscription_service
from src.billing.services import webhooks as webhook_service

log = logging.getLogger("pix_billing.scheduler")

_scheduler: AsyncIOScheduler | None = None


async def _renew_due_subscriptions() -> None:
    """Tick: generate the next charge for any subscription whose period ended."""
    pending_events: list[tuple[str, str, str]] = []
    async with session_scope() as session:
        due = await list_subscriptions_due(session, datetime.now(UTC))
        for sub in due:
            try:
                await subscription_service.renew_subscription(session, sub)
                emitted = getattr(sub, "_emitted_event", None)
                if emitted:
                    pending_events.append((emitted, sub.id, sub.customer_id))
            except Exception as exc:
                log.exception("renew failed for %s: %s", sub.id, exc)
                continue
    for ev, sub_id, customer_id in pending_events:
        await webhook_service.emit_event(
            ev, {"subscription_id": sub_id, "customer_id": customer_id}
        )


async def _expire_charges() -> None:
    """Tick: move PENDING charges past their TTL into EXPIRED."""
    async with session_scope() as session:
        expired = await charge_service.expire_all_due(session)
    for charge in expired:
        await webhook_service.emit_event(
            "charge.expired",
            {"charge_id": charge.id, "amount": charge.amount_cents},
        )


async def _run_dunning() -> None:
    """Tick: advance dunning for every active subscription with an overdue charge."""
    async with session_scope() as session:
        subs = await list_active_subscriptions(session)
        for sub in subs:
            try:
                await dunning_service.run_dunning(session, sub)
            except Exception as exc:
                log.exception("dunning failed for %s: %s", sub.id, exc)


def start_scheduler() -> AsyncIOScheduler:
    """Create and start the AsyncIOScheduler with billing jobs."""
    global _scheduler
    if _scheduler is not None:
        return _scheduler
    sched = AsyncIOScheduler(timezone="UTC")
    sched.add_job(_expire_charges, "interval", minutes=1, id="expire_charges")
    sched.add_job(_renew_due_subscriptions, "interval", minutes=5, id="renew_subscriptions")
    sched.add_job(_run_dunning, "interval", hours=1, id="dunning")
    sched.start()
    _scheduler = sched
    log.info("scheduler started: %s", [j.id for j in sched.get_jobs()])
    return sched


def stop_scheduler() -> None:
    """Shut the scheduler down cleanly."""
    global _scheduler
    if _scheduler is not None:
        _scheduler.shutdown(wait=False)
        _scheduler = None
