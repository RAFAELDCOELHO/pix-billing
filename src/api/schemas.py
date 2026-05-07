"""Pydantic v2 request/response models for every endpoint."""

from __future__ import annotations

from datetime import datetime
from typing import Annotated, Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator


class _Base(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)


# ─── Charges ───────────────────────────────────────────────────────────────


class ChargeCreate(_Base):
    """Input for ``POST /v1/charges``."""

    amount: Annotated[int, Field(ge=100, le=5_000_000, description="Amount in cents")]
    description: Annotated[str, Field(min_length=1, max_length=140)]
    customer_id: str | None = None
    expires_in: Annotated[int, Field(ge=60, le=86_400)] = 1800
    idempotency_key: str | None = None


class ChargeOut(_Base):
    """Output for charge endpoints."""

    charge_id: str
    txid: str
    amount: int
    description: str
    status: str
    pix_payload: str
    qr_code_base64: str
    expires_at: datetime
    paid_at: datetime | None = None
    customer_id: str | None = None
    subscription_id: str | None = None
    created_at: datetime


# ─── Customers ─────────────────────────────────────────────────────────────


class CustomerCreate(_Base):
    """Input for ``POST /v1/customers``."""

    name: Annotated[str, Field(min_length=1, max_length=200)]
    email: Annotated[str, Field(min_length=3, max_length=320)]
    document: Annotated[str, Field(min_length=11, max_length=20)]
    metadata: dict[str, Any] = Field(default_factory=dict)

    @field_validator("email")
    @classmethod
    def _email_has_at(cls, v: str) -> str:
        if "@" not in v:
            raise ValueError("invalid email")
        return v


class CustomerOut(_Base):
    """Output shape for a customer (PII masked)."""

    id: str
    name: str
    email_masked: str
    document_type: str
    document_masked: str
    metadata: dict[str, Any]
    created_at: datetime


# ─── Plans ─────────────────────────────────────────────────────────────────


class PlanCreate(_Base):
    """Input for ``POST /v1/plans``."""

    name: Annotated[str, Field(min_length=1, max_length=200)]
    amount: Annotated[int, Field(ge=100, le=5_000_000)]
    interval: Literal["monthly", "quarterly", "annual"]
    trial_days: Annotated[int, Field(ge=0, le=365)] = 0


class PlanOut(_Base):
    """Plan response."""

    id: str
    name: str
    amount: int
    interval: str
    trial_days: int
    active: bool
    created_at: datetime


# ─── Subscriptions ─────────────────────────────────────────────────────────


class SubscriptionCreate(_Base):
    """Input for ``POST /v1/subscriptions``."""

    customer_id: str
    plan_id: str


class SubscriptionOut(_Base):
    """Subscription response."""

    id: str
    customer_id: str
    plan_id: str
    status: str
    current_period_start: datetime
    current_period_end: datetime
    next_billing_date: datetime
    trial_end: datetime | None = None
    cancel_at_period_end: bool
    canceled_at: datetime | None = None
    created_at: datetime


# ─── Webhooks ──────────────────────────────────────────────────────────────


class WebhookCreate(_Base):
    """Input for ``POST /v1/webhooks``."""

    url: Annotated[str, Field(min_length=8, max_length=2048)]
    events: Annotated[list[str], Field(min_length=1, max_length=32)]
    description: Annotated[str, Field(max_length=200)] = ""


class WebhookOut(_Base):
    """Webhook endpoint response."""

    id: str
    url: str
    description: str
    events: list[str]
    active: bool
    secret: str | None = Field(
        default=None,
        description="Plaintext secret — returned only on creation.",
    )
    created_at: datetime


class WebhookTestRequest(_Base):
    """Input for ``POST /v1/webhooks/{id}/test``."""

    event: Literal[
        "charge.created",
        "charge.paid",
        "charge.expired",
        "charge.canceled",
        "subscription.activated",
        "subscription.past_due",
        "subscription.canceled",
        "subscription.renewed",
    ] = "charge.paid"
