# Architecture

## Layers

```
HTTP request
   │
   ▼
┌──────────────────────────────────────────────────────┐
│ API layer  (src/api/*)                               │
│  - FastAPI routes                                    │
│  - Pydantic v2 request/response schemas              │
│  - Bearer-token auth + per-key rate limiting         │
└──────────────────────────────────────────────────────┘
                        │
                        ▼
┌──────────────────────────────────────────────────────┐
│ Service layer  (src/billing/services/*)              │
│  - charges, customers, plans, subscriptions          │
│  - dunning, webhooks                                 │
│  - business rules; emits events                      │
└──────────────────────────────────────────────────────┘
                        │
                        ▼
┌──────────────────────────────────────────────────────┐
│ Repository layer  (src/billing/repository.py)        │
│  - all SQL access; soft deletes; no business logic   │
└──────────────────────────────────────────────────────┘
                        │
                        ▼
┌──────────────────────────────────────────────────────┐
│ Core  (src/core/*) — FROZEN                          │
│  exceptions · models (Cents) · crypto · audit chain  │
└──────────────────────────────────────────────────────┘
```

### Cross-layer rules

- API never imports from `repository` directly. Always goes through a service.
- Services never import from `api`.
- Core depends on nothing — it's the only thing safe to import everywhere.
- Forbidden: services patching ORM models from another service's table; create a new service.

## PIX QR generation

`src/billing/pix.py` builds the EMV BR-Code TLV payload BACEN expects, then computes the trailing CRC-16/CCITT checksum (poly 0x1021, seed 0xFFFF). The `qrcode` package renders the resulting copia-e-cola string as a PNG which we base64-encode for transport. No PIX PSP is involved in development; integrate one (Gerencianet, Asaas, OpenPIX) when going live, replacing the manual `/confirm` endpoint with a webhook handler that posts to the same service entry point.

## Subscription state machine

```
       create
        │
        ▼
   ┌─────────┐  trial_end                  ┌───────────┐
   │TRIALING │─────────────────────────────▶│  ACTIVE   │
   └─────────┘                               └───────────┘
        │                                       │   ▲
        │ paid                                  │   │ paid
        │                                       ▼   │
        │            unpaid > 1 day        ┌───────────┐
        └────────────────────────────────▶│ PAST_DUE  │
                                           └───────────┘
                                                 │
                                  dunning exhausted
                                                 ▼
                                           ┌───────────┐
                                           │ CANCELED  │
                                           └───────────┘
```

State transitions are atomic and produce both an audit-chain entry (`src/core/audit.py`) and a webhook event. The dunning schedule is configurable in `src/billing/services/dunning.py` (default: retry +1d, +3d, +7d, then cancel +8d).

## Webhook delivery

1. Service emits an event by calling `webhook_service.emit_event(name, data)`.
2. A `WebhookDelivery` row is persisted per matching endpoint (PENDING).
3. An asyncio task POSTs the JSON body to the registered URL, signed `sha256=HMAC(secret, timestamp + "." + body)`, header `X-Pix-Signature`. Timestamp goes in `X-Pix-Timestamp` (recipient should reject older than 5 minutes).
4. Retry with backoff [1s, 4s, 16s] up to 3 attempts. HTTP 410 disables the endpoint.
5. The delivery row is updated with response code/body and final status (SUCCESS/FAILED/DROPPED).

## Audit chain

Every state change appends a SHA-256 hash-linked entry. The chain tip is maintained in memory and persisted in production via your log shipping pipeline. `AuditStore.verify_chain()` re-hashes everything and detects tampering.

## Data integrity

- Cents (int) everywhere. No float arithmetic.
- Pydantic v2 strict models on every request boundary.
- CPF/CNPJ validated with check digits and encrypted at rest (AES-256-GCM).
- Idempotency keys on charge creation — duplicate `idempotency_key` returns the existing charge.
- Soft deletes: `deleted_at` column instead of `DELETE FROM`.

## What's intentionally missing for MVP

- Real PSP integration (replace manual `/confirm` with PSP webhook).
- Persistent webhook secrets (currently in-memory cache after creation; move to KMS).
- Alembic migrations beyond bootstrap (`init_db()` covers dev).
- Multi-tenant isolation (single global tenant per process today).
