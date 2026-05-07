"""ORM models — Customer, Plan, Subscription, Charge, Webhook, Delivery, ApiKey."""

from __future__ import annotations

from datetime import UTC, datetime
from enum import StrEnum

from sqlalchemy import (
    Boolean,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from src.billing.db import Base


def utcnow() -> datetime:
    """Return current UTC datetime (timezone-aware)."""
    return datetime.now(UTC)


class ChargeStatus(StrEnum):
    """Lifecycle of a single PIX charge."""

    PENDING = "PENDING"
    PAID = "PAID"
    EXPIRED = "EXPIRED"
    CANCELED = "CANCELED"


class SubscriptionStatus(StrEnum):
    """Lifecycle of a recurring subscription."""

    TRIALING = "TRIALING"
    ACTIVE = "ACTIVE"
    PAST_DUE = "PAST_DUE"
    CANCELED = "CANCELED"


class PlanInterval(StrEnum):
    """Billing-cycle granularity."""

    MONTHLY = "monthly"
    QUARTERLY = "quarterly"
    ANNUAL = "annual"


class DocumentType(StrEnum):
    """Brazilian taxpayer ID type."""

    CPF = "CPF"
    CNPJ = "CNPJ"


class WebhookDeliveryStatus(StrEnum):
    """Outcome of a single webhook delivery attempt."""

    PENDING = "PENDING"
    SUCCESS = "SUCCESS"
    FAILED = "FAILED"
    DROPPED = "DROPPED"


class ApiKey(Base):
    """API key — stored as HMAC hash, never plaintext."""

    __tablename__ = "api_keys"

    id: Mapped[str] = mapped_column(String(40), primary_key=True)
    name: Mapped[str] = mapped_column(String(100), nullable=False)
    key_hash: Mapped[str] = mapped_column(String(128), nullable=False, unique=True, index=True)
    prefix: Mapped[str] = mapped_column(String(20), nullable=False)
    is_live: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class Customer(Base):
    """End-user being billed."""

    __tablename__ = "customers"

    id: Mapped[str] = mapped_column(String(40), primary_key=True)
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    email_encrypted: Mapped[str] = mapped_column(Text, nullable=False)
    email_fingerprint: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    document_encrypted: Mapped[str] = mapped_column(Text, nullable=False)
    document_type: Mapped[DocumentType] = mapped_column(String(8), nullable=False)
    document_fingerprint: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    extra_metadata: Mapped[str] = mapped_column(Text, default="{}", nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    subscriptions: Mapped[list[Subscription]] = relationship(back_populates="customer")
    charges: Mapped[list[Charge]] = relationship(back_populates="customer")


class Plan(Base):
    """Subscription template — interval + amount."""

    __tablename__ = "plans"

    id: Mapped[str] = mapped_column(String(40), primary_key=True)
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    amount_cents: Mapped[int] = mapped_column(Integer, nullable=False)
    interval: Mapped[PlanInterval] = mapped_column(String(16), nullable=False)
    trial_days: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class Subscription(Base):
    """Recurring billing relationship between a customer and a plan."""

    __tablename__ = "subscriptions"

    id: Mapped[str] = mapped_column(String(40), primary_key=True)
    customer_id: Mapped[str] = mapped_column(
        String(40), ForeignKey("customers.id"), nullable=False, index=True
    )
    plan_id: Mapped[str] = mapped_column(String(40), ForeignKey("plans.id"), nullable=False)
    status: Mapped[SubscriptionStatus] = mapped_column(String(16), nullable=False)
    current_period_start: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    current_period_end: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    next_billing_date: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, index=True
    )
    trial_end: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    canceled_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    cancel_at_period_end: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    dunning_step: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    customer: Mapped[Customer] = relationship(back_populates="subscriptions")
    plan: Mapped[Plan] = relationship()
    charges: Mapped[list[Charge]] = relationship(back_populates="subscription")


class Charge(Base):
    """A single PIX charge (QR code + payload + lifecycle)."""

    __tablename__ = "charges"
    __table_args__ = (
        UniqueConstraint("txid", name="uq_charges_txid"),
        UniqueConstraint("idempotency_key", name="uq_charges_idem"),
        Index("ix_charges_status_due", "status", "expires_at"),
    )

    id: Mapped[str] = mapped_column(String(40), primary_key=True)
    customer_id: Mapped[str | None] = mapped_column(
        String(40), ForeignKey("customers.id"), nullable=True, index=True
    )
    subscription_id: Mapped[str | None] = mapped_column(
        String(40), ForeignKey("subscriptions.id"), nullable=True, index=True
    )
    txid: Mapped[str] = mapped_column(String(35), nullable=False)
    amount_cents: Mapped[int] = mapped_column(Integer, nullable=False)
    description: Mapped[str] = mapped_column(String(140), nullable=False)
    status: Mapped[ChargeStatus] = mapped_column(String(16), nullable=False)
    pix_payload: Mapped[str] = mapped_column(Text, nullable=False)
    qr_code_base64: Mapped[str] = mapped_column(Text, nullable=False)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    paid_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    idempotency_key: Mapped[str | None] = mapped_column(String(80), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    customer: Mapped[Customer | None] = relationship(back_populates="charges")
    subscription: Mapped[Subscription | None] = relationship(back_populates="charges")


class WebhookEndpoint(Base):
    """Customer-registered webhook URL with HMAC secret."""

    __tablename__ = "webhook_endpoints"

    id: Mapped[str] = mapped_column(String(40), primary_key=True)
    url: Mapped[str] = mapped_column(String(2048), nullable=False)
    description: Mapped[str] = mapped_column(String(200), default="", nullable=False)
    events: Mapped[str] = mapped_column(Text, nullable=False)  # JSON list[str]
    secret_hash: Mapped[str] = mapped_column(String(128), nullable=False)
    active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class WebhookDelivery(Base):
    """One delivery attempt for one event to one endpoint."""

    __tablename__ = "webhook_deliveries"
    __table_args__ = (Index("ix_webhook_deliveries_created", "created_at"),)

    id: Mapped[str] = mapped_column(String(40), primary_key=True)
    endpoint_id: Mapped[str] = mapped_column(
        String(40), ForeignKey("webhook_endpoints.id"), nullable=False, index=True
    )
    event_id: Mapped[str] = mapped_column(String(40), nullable=False, index=True)
    event_type: Mapped[str] = mapped_column(String(64), nullable=False)
    payload: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[WebhookDeliveryStatus] = mapped_column(String(16), nullable=False)
    attempts: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    last_response_code: Mapped[int | None] = mapped_column(Integer, nullable=True)
    last_response_body: Mapped[str | None] = mapped_column(Text, nullable=True)
    last_error: Mapped[str | None] = mapped_column(String(500), nullable=True)
    next_attempt_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class DunningLog(Base):
    """One row per dunning step executed against a subscription."""

    __tablename__ = "dunning_log"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    subscription_id: Mapped[str] = mapped_column(
        String(40), ForeignKey("subscriptions.id"), nullable=False, index=True
    )
    step: Mapped[int] = mapped_column(Integer, nullable=False)
    action: Mapped[str] = mapped_column(String(40), nullable=False)
    charge_id: Mapped[str | None] = mapped_column(String(40), nullable=True)
    risk_score: Mapped[float | None] = mapped_column(Float, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
