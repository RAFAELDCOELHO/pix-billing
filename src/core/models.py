"""
VAULT Banking — Domain Models
"""

from __future__ import annotations

import hashlib
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal
from enum import Enum
from typing import NewType

AccountId = NewType("AccountId", str)
TransactionId = NewType("TransactionId", str)
IdempotencyKey = NewType("IdempotencyKey", str)
Cents = NewType("Cents", int)


def cents_to_brl(c: Cents) -> Decimal:
    return Decimal(c) / Decimal(100)


def brl_to_cents(v: Decimal) -> Cents:
    centavos = v * 100
    if centavos != centavos.to_integral_value():
        raise ValueError(f"Sub-cent value not allowed: {v}")
    return Cents(int(centavos))


class TransactionType(str, Enum):
    PIX = "PIX"
    TED = "TED"
    DOC = "DOC"
    CARD_DEBIT = "CARD_DEBIT"
    CARD_CREDIT = "CARD_CREDIT"
    INTERNAL = "INTERNAL"


class TransactionStatus(str, Enum):
    PENDING = "PENDING"
    PROCESSING = "PROCESSING"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"
    REVERSED = "REVERSED"
    QUARANTINE = "QUARANTINE"
    IDEMPOTENT = "IDEMPOTENT"


class AccountType(str, Enum):
    CHECKING = "CHECKING"
    SAVINGS = "SAVINGS"
    PAYMENT = "PAYMENT"


class AccountStatus(str, Enum):
    ACTIVE = "ACTIVE"
    BLOCKED = "BLOCKED"
    CLOSED = "CLOSED"


def mask_cpf(cpf: str) -> str:
    digits = "".join(c for c in cpf if c.isdigit())
    if len(digits) == 11:
        return f"***.{digits[3:6]}.{digits[6:9]}-**"
    return "***masked***"


def mask_account(account_id: str) -> str:
    return f"{account_id[:4]}***"


def mask_amount_presence(cents: Cents) -> str:
    brl = cents_to_brl(cents)
    if brl < 100:
        return "[< R$100]"
    elif brl < 1_000:
        return "[R$100-999]"
    elif brl < 10_000:
        return "[R$1k-9.9k]"
    elif brl < 50_000:
        return "[R$10k-49.9k]"
    else:
        return "[>= R$50k]"


@dataclass
class Account:
    id: AccountId
    owner_id: str
    account_type: AccountType
    status: AccountStatus
    balance_cents: Cents
    version: int
    daily_limit_cents: Cents
    daily_spent_cents: Cents
    daily_limit_reset_at: datetime
    created_at: datetime
    updated_at: datetime

    @property
    def available_cents(self) -> Cents:
        return self.balance_cents

    @property
    def daily_remaining_cents(self) -> Cents:
        now = datetime.now(UTC)
        if now >= self.daily_limit_reset_at:
            return self.daily_limit_cents
        return Cents(max(0, self.daily_limit_cents - self.daily_spent_cents))

    def is_operable(self) -> bool:
        return self.status == AccountStatus.ACTIVE

    def log_safe_repr(self) -> str:
        return (
            f"Account(id={mask_account(self.id)}, "
            f"type={self.account_type.value}, "
            f"status={self.status.value}, "
            f"balance={mask_amount_presence(self.balance_cents)}, "
            f"version={self.version})"
        )


@dataclass
class TransactionRequest:
    idempotency_key: IdempotencyKey
    transaction_type: TransactionType
    origin_account_id: AccountId
    dest_account_id: AccountId
    amount_cents: Cents
    description: str
    initiated_by: str
    initiated_from_ip: str
    device_fingerprint: str | None = None
    scheduled_at: datetime | None = None

    def validate_basic(self) -> None:
        if self.amount_cents <= 0:
            raise ValueError("amount_cents must be positive")
        if self.origin_account_id == self.dest_account_id:
            raise ValueError("Origin and destination accounts must differ")
        if len(self.description) > 140:
            raise ValueError("Description exceeds 140 characters")
        try:
            uuid.UUID(self.idempotency_key)
        except ValueError:
            raise ValueError("idempotency_key must be a valid UUID4")

    @property
    def log_safe_ip(self) -> str:
        parts = self.initiated_from_ip.split(".")
        if len(parts) == 4:
            return f"{parts[0]}.{parts[1]}.{parts[2]}.*"
        return "***"


@dataclass
class Transaction:
    id: TransactionId
    idempotency_key: IdempotencyKey
    transaction_type: TransactionType
    status: TransactionStatus
    origin_account_id: AccountId
    dest_account_id: AccountId
    amount_cents: Cents
    description: str
    initiated_by: str
    initiated_from_ip: str
    device_fingerprint: str | None
    created_at: datetime
    processed_at: datetime | None
    completed_at: datetime | None
    reversed_at: datetime | None
    integrity_hash: str
    version: int
    risk_score: float | None = None
    failure_reason: str | None = None
    reversal_ref: TransactionId | None = None

    @classmethod
    def new_id(cls) -> TransactionId:
        return TransactionId(f"txn_{uuid.uuid4().hex}")

    def canonical_payload(self) -> str:
        return (
            f"{self.id}|{self.idempotency_key}|{self.transaction_type.value}|"
            f"{self.origin_account_id}|{self.dest_account_id}|"
            f"{self.amount_cents}|{self.created_at.isoformat()}"
        )

    def verify_integrity(self, hmac_key: bytes) -> bool:
        import hmac as hmac_mod

        expected = hmac_mod.new(
            hmac_key,
            self.canonical_payload().encode(),
            hashlib.sha256,
        ).hexdigest()
        return hmac_mod.compare_digest(expected, self.integrity_hash)

    def log_safe_repr(self) -> str:
        return (
            f"Transaction(id={self.id}, "
            f"type={self.transaction_type.value}, "
            f"status={self.status.value}, "
            f"origin={mask_account(self.origin_account_id)}, "
            f"dest={mask_account(self.dest_account_id)}, "
            f"amount={mask_amount_presence(self.amount_cents)}, "
            f"risk={self.risk_score})"
        )


@dataclass
class LedgerEntry:
    id: str
    transaction_id: TransactionId
    account_id: AccountId
    entry_type: str
    amount_cents: Cents
    balance_after_cents: Cents
    created_at: datetime
    integrity_hash: str

    @classmethod
    def new_id(cls) -> str:
        return f"led_{uuid.uuid4().hex}"


@dataclass
class IdempotencyRecord:
    key: IdempotencyKey
    transaction_id: TransactionId
    status: TransactionStatus
    response_hash: str
    created_at: datetime
    expires_at: datetime
    request_hash: str
