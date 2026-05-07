"""Customer service — encrypts CPF/CNPJ at rest."""

from __future__ import annotations

from sqlalchemy.ext.asyncio import AsyncSession

from src.billing import ids, repository
from src.billing.models import Customer, DocumentType
from src.billing.security import (
    encode_metadata,
    fingerprint,
    get_audit_logger,
    get_encryptor,
)
from src.billing.validators import normalize_document


class CustomerError(Exception):
    """Domain error for customer operations."""


async def create_customer(
    session: AsyncSession,
    *,
    name: str,
    email: str,
    document: str,
    metadata: dict[str, object] | None = None,
    actor_id: str = "system",
) -> Customer:
    """Persist a new customer with encrypted document field."""
    if not name.strip():
        raise CustomerError("name is required")
    if "@" not in email:
        raise CustomerError("invalid email")
    try:
        digits, doc_type = normalize_document(document)
    except ValueError as exc:
        raise CustomerError(str(exc)) from exc

    encryptor = get_encryptor()
    normalized_email = email.strip().lower()
    customer = Customer(
        id=ids.new_customer_id(),
        name=name.strip(),
        email_encrypted=encryptor.encrypt(normalized_email),
        email_fingerprint=fingerprint(normalized_email),
        document_encrypted=encryptor.encrypt(digits),
        document_type=DocumentType(doc_type),
        document_fingerprint=fingerprint(digits),
        extra_metadata=encode_metadata(metadata),
    )
    await repository.create_customer(session, customer)
    get_audit_logger().emit(
        event_type="CUSTOMER_CREATED",
        actor_id=actor_id,
        resource_id=customer.id,
        resource_type="CUSTOMER",
        action="CREATE",
        outcome="SUCCESS",
        details={"document_type": doc_type},
    )
    return customer


async def get_customer(session: AsyncSession, customer_id: str) -> Customer:
    """Fetch a customer or raise."""
    customer = await repository.get_customer(session, customer_id)
    if customer is None:
        raise CustomerError("customer not found")
    return customer
