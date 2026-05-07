"""HTTP routes for charges, customers, plans, subscriptions, webhooks."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from src.api.auth import AuthContext, authenticate, get_session, rate_limit
from src.api.schemas import (
    ChargeCreate,
    ChargeOut,
    CustomerCreate,
    CustomerOut,
    PlanCreate,
    PlanOut,
    SubscriptionCreate,
    SubscriptionOut,
    WebhookCreate,
    WebhookOut,
    WebhookTestRequest,
)
from src.billing import repository
from src.billing.events import ALL_EVENTS
from src.billing.models import Charge, Customer, Plan, Subscription, WebhookEndpoint
from src.billing.security import decode_metadata, get_encryptor
from src.billing.services import charges as charge_service
from src.billing.services import customers as customer_service
from src.billing.services import plans as plan_service
from src.billing.services import subscriptions as subscription_service
from src.billing.services import webhooks as webhook_service
from src.billing.validators import mask_cnpj, mask_cpf, mask_email

router = APIRouter(prefix="/v1")


# ─── helpers ───────────────────────────────────────────────────────────────


def _charge_out(c: Charge) -> ChargeOut:
    return ChargeOut(
        charge_id=c.id,
        txid=c.txid,
        amount=c.amount_cents,
        description=c.description,
        status=c.status.value if hasattr(c.status, "value") else str(c.status),
        pix_payload=c.pix_payload,
        qr_code_base64=c.qr_code_base64,
        expires_at=c.expires_at,
        paid_at=c.paid_at,
        customer_id=c.customer_id,
        subscription_id=c.subscription_id,
        created_at=c.created_at,
    )


def _customer_out(cu: Customer) -> CustomerOut:
    encryptor = get_encryptor()
    digits = encryptor.decrypt(cu.document_encrypted)
    masked = mask_cpf(digits) if cu.document_type.value == "CPF" else mask_cnpj(digits)
    return CustomerOut(
        id=cu.id,
        name=cu.name,
        email_masked=mask_email(cu.email),
        document_type=cu.document_type.value,
        document_masked=masked,
        metadata=decode_metadata(cu.extra_metadata),
        created_at=cu.created_at,
    )


def _plan_out(p: Plan) -> PlanOut:
    return PlanOut(
        id=p.id,
        name=p.name,
        amount=p.amount_cents,
        interval=p.interval.value,
        trial_days=p.trial_days,
        active=p.active,
        created_at=p.created_at,
    )


def _sub_out(s: Subscription) -> SubscriptionOut:
    return SubscriptionOut(
        id=s.id,
        customer_id=s.customer_id,
        plan_id=s.plan_id,
        status=s.status.value,
        current_period_start=s.current_period_start,
        current_period_end=s.current_period_end,
        next_billing_date=s.next_billing_date,
        trial_end=s.trial_end,
        cancel_at_period_end=s.cancel_at_period_end,
        canceled_at=s.canceled_at,
        created_at=s.created_at,
    )


def _wh_out(w: WebhookEndpoint, secret: str | None = None) -> WebhookOut:
    return WebhookOut(
        id=w.id,
        url=w.url,
        description=w.description,
        events=w.events.split(",") if w.events else [],
        active=w.active,
        secret=secret,
        created_at=w.created_at,
    )


# ─── charges ───────────────────────────────────────────────────────────────


@router.post(
    "/charges",
    response_model=ChargeOut,
    status_code=status.HTTP_201_CREATED,
    summary="Create a PIX charge",
)
async def create_charge(
    body: ChargeCreate,
    session: AsyncSession = Depends(get_session),
    ctx: AuthContext = Depends(rate_limit("charges", write=True)),
) -> ChargeOut:
    """Issue a fresh PIX QR code for ``amount`` cents."""
    try:
        charge = await charge_service.create_charge(
            session,
            amount_cents=body.amount,
            description=body.description,
            customer_id=body.customer_id,
            expires_in=body.expires_in,
            idempotency_key=body.idempotency_key,
            actor_id=ctx.api_key_id,
        )
    except charge_service.ChargeError as exc:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(exc)) from exc
    emitted = getattr(charge, "_emitted_event", None)
    out = _charge_out(charge)
    if emitted:
        await webhook_service.emit_event(
            emitted,
            {"charge_id": charge.id, "amount": charge.amount_cents},
        )
    return out


@router.get("/charges/{charge_id}", response_model=ChargeOut)
async def get_charge(
    charge_id: str,
    session: AsyncSession = Depends(get_session),
    _: AuthContext = Depends(rate_limit("charges", write=False)),
) -> ChargeOut:
    """Fetch the current state of a charge."""
    charge = await repository.get_charge(session, charge_id)
    if charge is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "charge not found")
    return _charge_out(charge)


@router.post("/charges/{charge_id}/confirm", response_model=ChargeOut)
async def confirm_charge(
    charge_id: str,
    session: AsyncSession = Depends(get_session),
    ctx: AuthContext = Depends(rate_limit("charges", write=True)),
) -> ChargeOut:
    """Sandbox confirmation — equivalent to a PSP payment-received webhook."""
    if ctx.is_live:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "manual confirm disabled in live mode")
    try:
        charge = await charge_service.confirm_charge(session, charge_id, actor_id=ctx.api_key_id)
    except charge_service.ChargeError as exc:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(exc)) from exc
    emitted = getattr(charge, "_emitted_event", None)
    out = _charge_out(charge)
    if emitted:
        await webhook_service.emit_event(
            emitted,
            {
                "charge_id": charge.id,
                "amount": charge.amount_cents,
                "customer_id": charge.customer_id,
                "subscription_id": charge.subscription_id,
            },
        )
    return out


@router.post("/charges/{charge_id}/cancel", response_model=ChargeOut)
async def cancel_charge(
    charge_id: str,
    session: AsyncSession = Depends(get_session),
    ctx: AuthContext = Depends(rate_limit("charges", write=True)),
) -> ChargeOut:
    """Cancel a pending charge."""
    try:
        charge = await charge_service.cancel_charge(session, charge_id, actor_id=ctx.api_key_id)
    except charge_service.ChargeError as exc:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(exc)) from exc
    out = _charge_out(charge)
    await webhook_service.emit_event("charge.canceled", {"charge_id": charge.id})
    return out


# ─── customers ─────────────────────────────────────────────────────────────


@router.post(
    "/customers",
    response_model=CustomerOut,
    status_code=status.HTTP_201_CREATED,
)
async def create_customer(
    body: CustomerCreate,
    session: AsyncSession = Depends(get_session),
    ctx: AuthContext = Depends(rate_limit("customers", write=True)),
) -> CustomerOut:
    """Persist a new customer (CPF/CNPJ encrypted at rest)."""
    try:
        customer = await customer_service.create_customer(
            session,
            name=body.name,
            email=body.email,
            document=body.document,
            metadata=body.metadata,
            actor_id=ctx.api_key_id,
        )
    except customer_service.CustomerError as exc:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(exc)) from exc
    return _customer_out(customer)


@router.get("/customers/{customer_id}", response_model=CustomerOut)
async def get_customer(
    customer_id: str,
    session: AsyncSession = Depends(get_session),
    _: AuthContext = Depends(rate_limit("customers", write=False)),
) -> CustomerOut:
    """Fetch a customer (PII masked)."""
    try:
        customer = await customer_service.get_customer(session, customer_id)
    except customer_service.CustomerError as exc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, str(exc)) from exc
    return _customer_out(customer)


# ─── plans ─────────────────────────────────────────────────────────────────


@router.post("/plans", response_model=PlanOut, status_code=status.HTTP_201_CREATED)
async def create_plan(
    body: PlanCreate,
    session: AsyncSession = Depends(get_session),
    _: AuthContext = Depends(rate_limit("plans", write=True)),
) -> PlanOut:
    """Create a recurring plan."""
    try:
        plan = await plan_service.create_plan(
            session,
            name=body.name,
            amount_cents=body.amount,
            interval=body.interval,
            trial_days=body.trial_days,
        )
    except plan_service.PlanError as exc:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(exc)) from exc
    return _plan_out(plan)


@router.get("/plans", response_model=list[PlanOut])
async def list_plans(
    session: AsyncSession = Depends(get_session),
    _: AuthContext = Depends(rate_limit("plans", write=False)),
) -> list[PlanOut]:
    """List active plans."""
    plans = await repository.list_plans(session)
    return [_plan_out(p) for p in plans]


# ─── subscriptions ─────────────────────────────────────────────────────────


@router.post(
    "/subscriptions",
    response_model=SubscriptionOut,
    status_code=status.HTTP_201_CREATED,
)
async def create_subscription(
    body: SubscriptionCreate,
    session: AsyncSession = Depends(get_session),
    ctx: AuthContext = Depends(rate_limit("subscriptions", write=True)),
) -> SubscriptionOut:
    """Attach a customer to a plan."""
    try:
        sub = await subscription_service.create_subscription(
            session,
            customer_id=body.customer_id,
            plan_id=body.plan_id,
            actor_id=ctx.api_key_id,
        )
    except (
        subscription_service.SubscriptionError,
        customer_service.CustomerError,
        plan_service.PlanError,
    ) as exc:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(exc)) from exc
    return _sub_out(sub)


@router.get("/subscriptions/{sub_id}", response_model=SubscriptionOut)
async def get_subscription(
    sub_id: str,
    session: AsyncSession = Depends(get_session),
    _: AuthContext = Depends(rate_limit("subscriptions", write=False)),
) -> SubscriptionOut:
    """Fetch a subscription."""
    sub = await repository.get_subscription(session, sub_id)
    if sub is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "subscription not found")
    return _sub_out(sub)


@router.delete("/subscriptions/{sub_id}", response_model=SubscriptionOut)
async def cancel_subscription(
    sub_id: str,
    immediate: bool = False,
    session: AsyncSession = Depends(get_session),
    ctx: AuthContext = Depends(rate_limit("subscriptions", write=True)),
) -> SubscriptionOut:
    """Cancel — at end of period by default, immediate if ``immediate=true``."""
    try:
        sub = await subscription_service.cancel_subscription(
            session, sub_id, actor_id=ctx.api_key_id, immediate=immediate
        )
    except subscription_service.SubscriptionError as exc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, str(exc)) from exc
    out = _sub_out(sub)
    emitted = getattr(sub, "_emitted_event", None)
    if emitted:
        await webhook_service.emit_event(
            emitted,
            {"subscription_id": sub.id, "customer_id": sub.customer_id},
        )
    return out


@router.get("/subscriptions/{sub_id}/invoices", response_model=list[ChargeOut])
async def list_subscription_invoices(
    sub_id: str,
    session: AsyncSession = Depends(get_session),
    _: AuthContext = Depends(rate_limit("subscriptions", write=False)),
) -> list[ChargeOut]:
    """Return every charge issued under ``sub_id``."""
    try:
        invoices = await subscription_service.list_invoices(session, sub_id)
    except subscription_service.SubscriptionError as exc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, str(exc)) from exc
    return [_charge_out(c) for c in invoices]  # type: ignore[arg-type]


# ─── webhooks ──────────────────────────────────────────────────────────────


@router.post("/webhooks", response_model=WebhookOut, status_code=status.HTTP_201_CREATED)
async def register_webhook(
    body: WebhookCreate,
    session: AsyncSession = Depends(get_session),
    _: AuthContext = Depends(rate_limit("webhooks", write=True)),
) -> WebhookOut:
    """Register a webhook URL. Returns the secret — once."""
    try:
        result = await webhook_service.register_endpoint(
            session, url=body.url, events=body.events, description=body.description
        )
    except webhook_service.WebhookError as exc:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(exc)) from exc
    return _wh_out(result.endpoint, secret=result.plaintext_secret)


@router.get("/webhooks", response_model=list[WebhookOut])
async def list_webhooks(
    session: AsyncSession = Depends(get_session),
    _: AuthContext = Depends(rate_limit("webhooks", write=False)),
) -> list[WebhookOut]:
    """List registered webhook endpoints."""
    rows = await repository.list_webhooks(session)
    return [_wh_out(w) for w in rows]


@router.post("/webhooks/{wh_id}/test", response_model=dict[str, Any])
async def test_webhook(
    wh_id: str,
    body: WebhookTestRequest,
    session: AsyncSession = Depends(get_session),
    _: AuthContext = Depends(rate_limit("webhooks", write=True)),
) -> dict[str, Any]:
    """Fire a test event to the registered endpoint."""
    wh = await repository.get_webhook(session, wh_id)
    if wh is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "webhook not found")
    await webhook_service.emit_event(body.event, {"test": True, "endpoint_id": wh.id})
    return {"status": "queued", "event": body.event}


# ─── events ────────────────────────────────────────────────────────────────


@router.get("/events", response_model=list[str])
async def list_events(_: AuthContext = Depends(authenticate)) -> list[str]:
    """List supported event types."""
    return list(ALL_EVENTS)
