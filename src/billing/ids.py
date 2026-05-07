"""Resource identifier generators (Stripe-style prefixed IDs)."""

from __future__ import annotations

import secrets
import string

_ALPHABET = string.ascii_lowercase + string.digits


def _rand(n: int = 16) -> str:
    return "".join(secrets.choice(_ALPHABET) for _ in range(n))


def new_customer_id() -> str:
    """Generate a customer identifier."""
    return f"cus_{_rand(16)}"


def new_plan_id() -> str:
    """Generate a plan identifier."""
    return f"plan_{_rand(16)}"


def new_charge_id() -> str:
    """Generate a charge identifier."""
    return f"ch_{_rand(16)}"


def new_subscription_id() -> str:
    """Generate a subscription identifier."""
    return f"sub_{_rand(16)}"


def new_webhook_id() -> str:
    """Generate a webhook endpoint identifier."""
    return f"wh_{_rand(16)}"


def new_event_id() -> str:
    """Generate an event identifier."""
    return f"evt_{_rand(16)}"


def new_delivery_id() -> str:
    """Generate a webhook delivery identifier."""
    return f"whd_{_rand(16)}"


def new_api_key(live: bool = False) -> str:
    """Generate a fresh API key (sandbox or live)."""
    prefix = "pk_live_" if live else "pk_test_"
    return prefix + secrets.token_urlsafe(24).replace("-", "").replace("_", "")[:28]


def new_api_key_id() -> str:
    """Generate the public identifier for an API key record."""
    return f"key_{_rand(16)}"


def new_txid() -> str:
    """Generate a 25-char alphanumeric PIX TXID (BACEN EMV TLV limit)."""
    chars = string.ascii_uppercase + string.digits
    return "".join(secrets.choice(chars) for _ in range(25))
