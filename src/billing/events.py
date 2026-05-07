"""Event-name constants for the webhook engine."""

from __future__ import annotations

from typing import Final

CHARGE_CREATED: Final = "charge.created"
CHARGE_PAID: Final = "charge.paid"
CHARGE_EXPIRED: Final = "charge.expired"
CHARGE_CANCELED: Final = "charge.canceled"

SUBSCRIPTION_ACTIVATED: Final = "subscription.activated"
SUBSCRIPTION_PAST_DUE: Final = "subscription.past_due"
SUBSCRIPTION_CANCELED: Final = "subscription.canceled"
SUBSCRIPTION_RENEWED: Final = "subscription.renewed"

ALL_EVENTS: Final[tuple[str, ...]] = (
    CHARGE_CREATED,
    CHARGE_PAID,
    CHARGE_EXPIRED,
    CHARGE_CANCELED,
    SUBSCRIPTION_ACTIVATED,
    SUBSCRIPTION_PAST_DUE,
    SUBSCRIPTION_CANCELED,
    SUBSCRIPTION_RENEWED,
)
