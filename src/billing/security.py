"""Process-wide crypto + audit singletons and API-key helpers."""

from __future__ import annotations

import hashlib
import hmac
import json
from functools import lru_cache

from src.core.audit import AuditLogger, AuditStore
from src.core.crypto import (
    FieldEncryptor,
    KeyVault,
    Tokenizer,
    TransactionSigner,
    create_crypto_stack,
)


@lru_cache(maxsize=1)
def _stack() -> tuple[KeyVault, TransactionSigner, FieldEncryptor, Tokenizer]:
    return create_crypto_stack()


def get_key_vault() -> KeyVault:
    """Return the process-wide KeyVault."""
    return _stack()[0]


def get_signer() -> TransactionSigner:
    """Return the HMAC signer."""
    return _stack()[1]


def get_encryptor() -> FieldEncryptor:
    """Return the AES-GCM field encryptor."""
    return _stack()[2]


def get_tokenizer() -> Tokenizer:
    """Return the tokenizer."""
    return _stack()[3]


@lru_cache(maxsize=1)
def get_audit_logger() -> AuditLogger:
    """Return the process-wide audit logger."""
    return AuditLogger(AuditStore())


def hash_api_key(raw_key: str) -> str:
    """Hash an API key with HMAC-SHA256 keyed by the active vault key."""
    vault_key = get_key_vault().get_active_hmac_key()
    return hmac.new(vault_key, raw_key.encode("utf-8"), hashlib.sha256).hexdigest()


def fingerprint(value: str) -> str:
    """Deterministic SHA-256 fingerprint for indexing encrypted fields."""
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def hmac_sign(secret: str, payload: str) -> str:
    """Sign ``payload`` with ``secret`` using HMAC-SHA256."""
    return hmac.new(secret.encode("utf-8"), payload.encode("utf-8"), hashlib.sha256).hexdigest()


def constant_time_eq(a: str, b: str) -> bool:
    """Timing-safe string comparison."""
    return hmac.compare_digest(a, b)


def encode_metadata(meta: dict[str, object] | None) -> str:
    """Serialize metadata dict for storage (JSON, sorted keys)."""
    return json.dumps(meta or {}, sort_keys=True, ensure_ascii=False)


def decode_metadata(raw: str) -> dict[str, object]:
    """Inverse of :func:`encode_metadata`."""
    if not raw:
        return {}
    parsed = json.loads(raw)
    if not isinstance(parsed, dict):
        return {}
    return parsed
