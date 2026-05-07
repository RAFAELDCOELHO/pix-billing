"""Lightweight Python SDK for the PIX Billing Stack.

Example:
    >>> from sdk.pix_billing import PixBilling
    >>> client = PixBilling(api_key="pk_test_xxx", base_url="http://localhost:8000")
    >>> charge = client.charges.create(amount=15000, description="Plano Pro")
    >>> print(charge.pix_payload)
"""

from __future__ import annotations

import hashlib
import hmac
from dataclasses import dataclass
from typing import Any

import httpx


class PixBillingError(Exception):
    """Raised when the API returns a non-2xx response."""


@dataclass
class Charge:
    """A PIX charge as returned by the API."""

    charge_id: str
    txid: str
    amount: int
    description: str
    status: str
    pix_payload: str
    qr_code_base64: str
    expires_at: str
    paid_at: str | None
    customer_id: str | None
    subscription_id: str | None
    created_at: str

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> Charge:
        """Build a :class:`Charge` from an API response body."""
        return cls(
            charge_id=data["charge_id"],
            txid=data["txid"],
            amount=data["amount"],
            description=data["description"],
            status=data["status"],
            pix_payload=data["pix_payload"],
            qr_code_base64=data["qr_code_base64"],
            expires_at=data["expires_at"],
            paid_at=data.get("paid_at"),
            customer_id=data.get("customer_id"),
            subscription_id=data.get("subscription_id"),
            created_at=data["created_at"],
        )


@dataclass
class Customer:
    """Customer record."""

    id: str
    name: str
    email_masked: str
    document_type: str
    document_masked: str
    metadata: dict[str, Any]
    created_at: str

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> Customer:
        """Build a :class:`Customer` from an API response body."""
        return cls(**data)


@dataclass
class Plan:
    """Plan record."""

    id: str
    name: str
    amount: int
    interval: str
    trial_days: int
    active: bool
    created_at: str

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> Plan:
        """Build a :class:`Plan` from an API response body."""
        return cls(**data)


@dataclass
class Subscription:
    """Subscription record."""

    id: str
    customer_id: str
    plan_id: str
    status: str
    current_period_start: str
    current_period_end: str
    next_billing_date: str
    trial_end: str | None
    cancel_at_period_end: bool
    canceled_at: str | None
    created_at: str

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> Subscription:
        """Build a :class:`Subscription` from an API response body."""
        return cls(**data)


@dataclass
class Webhook:
    """Webhook endpoint record. ``secret`` is non-None only on creation."""

    id: str
    url: str
    description: str
    events: list[str]
    active: bool
    secret: str | None
    created_at: str

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> Webhook:
        """Build a :class:`Webhook` from an API response body."""
        return cls(**data)


# ─── resource clients ──────────────────────────────────────────────────────


class _Resource:
    def __init__(self, client: PixBilling) -> None:
        self._client = client


class _Charges(_Resource):
    def create(
        self,
        *,
        amount: int,
        description: str,
        customer_id: str | None = None,
        expires_in: int = 1800,
        idempotency_key: str | None = None,
    ) -> Charge:
        body: dict[str, Any] = {
            "amount": amount,
            "description": description,
            "expires_in": expires_in,
        }
        if customer_id:
            body["customer_id"] = customer_id
        if idempotency_key:
            body["idempotency_key"] = idempotency_key
        return Charge.from_dict(self._client._request("POST", "/v1/charges", json=body))

    def retrieve(self, charge_id: str) -> Charge:
        return Charge.from_dict(self._client._request("GET", f"/v1/charges/{charge_id}"))

    def confirm(self, charge_id: str) -> Charge:
        """Sandbox-only: simulate a payment confirmation."""
        return Charge.from_dict(
            self._client._request("POST", f"/v1/charges/{charge_id}/confirm")
        )

    def cancel(self, charge_id: str) -> Charge:
        return Charge.from_dict(
            self._client._request("POST", f"/v1/charges/{charge_id}/cancel")
        )


class _Customers(_Resource):
    def create(
        self,
        *,
        name: str,
        email: str,
        document: str,
        metadata: dict[str, Any] | None = None,
    ) -> Customer:
        return Customer.from_dict(
            self._client._request(
                "POST",
                "/v1/customers",
                json={
                    "name": name,
                    "email": email,
                    "document": document,
                    "metadata": metadata or {},
                },
            )
        )

    def retrieve(self, customer_id: str) -> Customer:
        return Customer.from_dict(
            self._client._request("GET", f"/v1/customers/{customer_id}")
        )


class _Plans(_Resource):
    def create(
        self,
        *,
        name: str,
        amount: int,
        interval: str,
        trial_days: int = 0,
    ) -> Plan:
        return Plan.from_dict(
            self._client._request(
                "POST",
                "/v1/plans",
                json={
                    "name": name,
                    "amount": amount,
                    "interval": interval,
                    "trial_days": trial_days,
                },
            )
        )

    def list(self) -> list[Plan]:
        return [Plan.from_dict(p) for p in self._client._request("GET", "/v1/plans")]


class _Subscriptions(_Resource):
    def create(self, *, customer_id: str, plan_id: str) -> Subscription:
        return Subscription.from_dict(
            self._client._request(
                "POST",
                "/v1/subscriptions",
                json={"customer_id": customer_id, "plan_id": plan_id},
            )
        )

    def retrieve(self, sub_id: str) -> Subscription:
        return Subscription.from_dict(
            self._client._request("GET", f"/v1/subscriptions/{sub_id}")
        )

    def cancel(self, sub_id: str, *, immediate: bool = False) -> Subscription:
        return Subscription.from_dict(
            self._client._request(
                "DELETE", f"/v1/subscriptions/{sub_id}?immediate={'true' if immediate else 'false'}"
            )
        )

    def invoices(self, sub_id: str) -> list[Charge]:
        return [
            Charge.from_dict(c)
            for c in self._client._request("GET", f"/v1/subscriptions/{sub_id}/invoices")
        ]


class _Webhooks(_Resource):
    def create(
        self, *, url: str, events: list[str], description: str = ""
    ) -> Webhook:
        return Webhook.from_dict(
            self._client._request(
                "POST",
                "/v1/webhooks",
                json={"url": url, "events": events, "description": description},
            )
        )

    def list(self) -> list[Webhook]:
        return [
            Webhook.from_dict(w) for w in self._client._request("GET", "/v1/webhooks")
        ]


# ─── top-level client ──────────────────────────────────────────────────────


class PixBilling:
    """Synchronous client for the PIX Billing Stack."""

    def __init__(
        self,
        api_key: str,
        *,
        base_url: str = "http://localhost:8000",
        timeout: float = 30.0,
    ) -> None:
        if not api_key.startswith(("pk_test_", "pk_live_")):
            raise ValueError("api_key must start with pk_test_ or pk_live_")
        self.api_key = api_key
        self.base_url = base_url.rstrip("/")
        self._client = httpx.Client(
            timeout=timeout,
            headers={"Authorization": f"Bearer {api_key}"},
        )
        self.charges = _Charges(self)
        self.customers = _Customers(self)
        self.plans = _Plans(self)
        self.subscriptions = _Subscriptions(self)
        self.webhooks = _Webhooks(self)

    def close(self) -> None:
        """Close the underlying HTTP connection pool."""
        self._client.close()

    def __enter__(self) -> PixBilling:
        return self

    def __exit__(self, *_exc: object) -> None:
        self.close()

    def _request(
        self,
        method: str,
        path: str,
        *,
        json: dict[str, Any] | None = None,
    ) -> Any:
        url = f"{self.base_url}{path}"
        resp = self._client.request(method, url, json=json)
        if resp.status_code >= 400:
            raise PixBillingError(f"HTTP {resp.status_code}: {resp.text}")
        if resp.status_code == 204 or not resp.content:
            return None
        return resp.json()


MAX_WEBHOOK_AGE_SECONDS = 300


def verify_signature(
    secret: str,
    payload: str,
    timestamp: str,
    signature_header: str,
    *,
    max_age_seconds: int = MAX_WEBHOOK_AGE_SECONDS,
) -> bool:
    """Verify a webhook signature on the receiver side.

    Rejects payloads older than ``max_age_seconds`` (default 5 minutes) to
    prevent replay attacks.

    Args:
        secret: Plaintext secret returned when the webhook was registered.
        payload: Raw request body as a string (do not re-serialize).
        timestamp: Value of ``X-Pix-Timestamp`` header.
        signature_header: Value of ``X-Pix-Signature`` header (e.g. ``sha256=…``).
        max_age_seconds: Reject payloads older than this many seconds.
    """
    import time

    if not signature_header.startswith("sha256="):
        return False
    try:
        ts = float(timestamp)
    except ValueError:
        return False
    if abs(time.time() - ts) > max_age_seconds:
        return False
    expected = hmac.new(
        secret.encode("utf-8"),
        f"{timestamp}.{payload}".encode("utf-8"),
        hashlib.sha256,
    ).hexdigest()
    return hmac.compare_digest(expected, signature_header.split("=", 1)[1])
