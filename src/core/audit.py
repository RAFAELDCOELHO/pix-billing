"""Immutable hash-chained audit log.

Every state change in the billing system appends a hash-linked entry. The
chain tip can be exported to detect tampering after the fact.
"""

from __future__ import annotations

import hashlib
import json
import logging
import uuid
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime, timedelta
from typing import Any

logger = logging.getLogger("pix_billing.audit")


@dataclass
class AuditEntry:
    """One immutable record in the audit chain."""

    entry_id: str
    event_type: str
    severity: str
    timestamp: str
    actor_id: str
    source_ip: str
    resource_id: str
    resource_type: str
    action: str
    outcome: str
    details: dict[str, Any]
    prev_hash: str
    entry_hash: str
    retention_until: str

    def to_json(self) -> str:
        """Return canonical JSON representation."""
        return json.dumps(asdict(self), ensure_ascii=False, sort_keys=True)

    @classmethod
    def new_id(cls) -> str:
        """Generate a fresh audit-entry identifier."""
        return f"aud_{uuid.uuid4().hex}"


def _compute_hash(prev_hash: str, entry: AuditEntry) -> str:
    """Compute the SHA-256 hash linking ``entry`` to ``prev_hash``."""
    canonical = json.dumps(
        {
            "entry_id": entry.entry_id,
            "event_type": entry.event_type,
            "timestamp": entry.timestamp,
            "actor_id": entry.actor_id,
            "resource_id": entry.resource_id,
            "action": entry.action,
            "outcome": entry.outcome,
            "details": entry.details,
        },
        sort_keys=True,
    )
    return hashlib.sha256(f"{prev_hash}|{canonical}".encode()).hexdigest()


@dataclass
class AuditStore:
    """In-memory append-only hash-chained log."""

    _entries: list[AuditEntry] = field(default_factory=list)
    _chain_tip: str = "0" * 64

    def append(self, entry: AuditEntry) -> None:
        """Append ``entry`` if its prev_hash matches the current chain tip."""
        if entry.prev_hash != self._chain_tip:
            raise ValueError("Hash chain broken")
        self._entries.append(entry)
        self._chain_tip = entry.entry_hash
        log_fn = (
            logger.critical
            if entry.severity == "CRITICAL"
            else logger.warning
            if entry.severity == "WARNING"
            else logger.info
        )
        log_fn("AUDIT %s", entry.to_json())

    def verify_chain(self) -> tuple[bool, int]:
        """Re-hash the chain. Returns (ok, count_or_first_bad_index)."""
        prev = "0" * 64
        for i, entry in enumerate(self._entries):
            if entry.prev_hash != prev:
                return False, i
            if _compute_hash(prev, entry) != entry.entry_hash:
                return False, i
            prev = entry.entry_hash
        return True, len(self._entries)

    def get_by_resource(self, resource_id: str) -> list[AuditEntry]:
        """Return all entries that reference ``resource_id``."""
        return [e for e in self._entries if e.resource_id == resource_id]

    @property
    def chain_tip(self) -> str:
        """Current chain tip — SHA-256 hex digest."""
        return self._chain_tip

    @property
    def entry_count(self) -> int:
        """Number of entries in the chain."""
        return len(self._entries)


class AuditLogger:
    """High-level facade over :class:`AuditStore`."""

    RETENTION_YEARS = 5

    def __init__(self, store: AuditStore) -> None:
        self._store = store

    def emit(
        self,
        *,
        event_type: str,
        actor_id: str,
        resource_id: str,
        resource_type: str,
        action: str,
        outcome: str,
        details: dict[str, Any] | None = None,
        source_ip: str = "unknown",
        severity: str = "INFO",
    ) -> AuditEntry:
        """Append a structured audit event to the chain."""
        now = datetime.now(UTC)
        entry = AuditEntry(
            entry_id=AuditEntry.new_id(),
            event_type=event_type,
            severity=severity,
            timestamp=now.isoformat(),
            actor_id=actor_id,
            source_ip=_mask_ip(source_ip),
            resource_id=resource_id,
            resource_type=resource_type,
            action=action,
            outcome=outcome,
            details=details or {},
            prev_hash=self._store.chain_tip,
            entry_hash="",
            retention_until=(now + timedelta(days=365 * self.RETENTION_YEARS)).date().isoformat(),
        )
        entry.entry_hash = _compute_hash(self._store.chain_tip, entry)
        self._store.append(entry)
        return entry


def _mask_ip(ip: str) -> str:
    parts = ip.split(".")
    if len(parts) == 4:
        return f"{parts[0]}.{parts[1]}.{parts[2]}.*"
    return "***"
