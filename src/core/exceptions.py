"""
VAULT Banking — Custom Exception Hierarchy
All exceptions carry an error_code for idempotent client retry logic.
"""

from dataclasses import dataclass


@dataclass
class VaultException(Exception):
    message: str
    error_code: str
    transaction_id: str | None = None
    retryable: bool = False

    def __str__(self) -> str:
        return f"[{self.error_code}] {self.message}"


class ValidationError(VaultException):
    def __init__(self, message: str, field: str = ""):
        super().__init__(message=message, error_code="VALIDATION_ERROR", retryable=False)
        self.field = field


class InsufficientFundsError(VaultException):
    def __init__(self, transaction_id: str):
        super().__init__(
            message="Insufficient funds",
            error_code="INSUFFICIENT_FUNDS",
            transaction_id=transaction_id,
            retryable=False,
        )


class DailyLimitExceededError(VaultException):
    def __init__(self, transaction_id: str, limit: float):
        super().__init__(
            message=f"Daily limit of R${limit:,.2f} would be exceeded",
            error_code="DAILY_LIMIT_EXCEEDED",
            transaction_id=transaction_id,
            retryable=False,
        )


class OptimisticLockError(VaultException):
    def __init__(self, account_id: str):
        super().__init__(
            message=f"Concurrent modification detected on account {account_id[:8]}***",
            error_code="OPTIMISTIC_LOCK_CONFLICT",
            retryable=True,
        )


class IdempotencyConflictError(VaultException):
    def __init__(self, idempotency_key: str):
        super().__init__(
            message="Idempotency key already used with different payload",
            error_code="IDEMPOTENCY_CONFLICT",
            retryable=False,
        )


class AtomicityViolationError(VaultException):
    def __init__(self, transaction_id: str, detail: str = ""):
        super().__init__(
            message=f"Atomicity violation during transaction; rollback executed. {detail}",
            error_code="ATOMICITY_VIOLATION",
            transaction_id=transaction_id,
            retryable=False,
        )


class AuthenticationError(VaultException):
    def __init__(self, reason: str = "Authentication failed"):
        super().__init__(message=reason, error_code="AUTH_FAILED", retryable=False)


class RateLimitError(VaultException):
    def __init__(self, scope: str, retry_after_seconds: int = 60):
        super().__init__(
            message=f"Rate limit exceeded for scope: {scope}",
            error_code="RATE_LIMIT_EXCEEDED",
            retryable=True,
        )
        self.retry_after_seconds = retry_after_seconds


class FraudBlockError(VaultException):
    def __init__(self, transaction_id: str, risk_score: float):
        super().__init__(
            message="Transaction blocked by fraud detection",
            error_code="FRAUD_BLOCKED",
            transaction_id=transaction_id,
            retryable=False,
        )
        self.risk_score = risk_score


class ExternalServiceError(VaultException):
    def __init__(self, service: str, detail: str = ""):
        super().__init__(
            message=f"External service '{service}' unavailable. {detail}",
            error_code="EXTERNAL_SERVICE_ERROR",
            retryable=True,
        )
        self.service = service


class CircuitOpenError(VaultException):
    def __init__(self, service: str):
        super().__init__(
            message=f"Circuit breaker OPEN for service '{service}'",
            error_code="CIRCUIT_BREAKER_OPEN",
            retryable=True,
        )


class RollbackError(VaultException):
    def __init__(self, transaction_id: str, original_error: str):
        super().__init__(
            message=f"CRITICAL: Rollback failed for txn {transaction_id}. Original error: {original_error}",
            error_code="ROLLBACK_FAILED",
            transaction_id=transaction_id,
            retryable=False,
        )
