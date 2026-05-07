# Security Policy

PIX Billing Stack handles money and PII. Security is a first-class feature, not a checklist. This document describes the model, the controls, and how to report a vulnerability.

## Reporting a vulnerability

Email **security@pix-billing.dev** (or open a GitHub Security Advisory) with:

- a clear description of the issue,
- minimal reproduction steps, and
- impact (what could an attacker do?).

We acknowledge within **48 hours** and aim to ship a patch within **14 days** for high-severity issues. Please do not file public issues for vulnerabilities. We support coordinated disclosure and will credit reporters in the changelog unless asked otherwise.

**Out of scope**

- Reports based on automated scanner output without proof of exploitability.
- Self-XSS, social-engineering, or attacks requiring physical device access.
- Volumetric DoS against the public sandbox demo.

## Security architecture

### Layered design

```
HTTP → Security headers → Auth (Bearer) → Rate limit → Pydantic strict → Service → Repository → Core
```

Every request crosses every layer. Security controls live at the boundary they belong to:

- **Transport** — HSTS, CSP, X-Frame-Options, X-Content-Type-Options, no-store cache (see [`src/api/security_headers.py`](src/api/security_headers.py)).
- **Auth** — `Authorization: Bearer pk_*` on every `/v1/*` endpoint; HTTP Basic on `/dashboard`.
- **Rate limits** — per-API-key for all writes/reads, plus per-customer cap on charge creation.
- **Validation** — Pydantic v2 strict mode (no implicit type coercion, no extra fields).
- **Persistence** — soft deletes only, encrypted PII columns, hashed secrets.

### Threat model (summary)

| Threat | Control |
| --- | --- |
| Stolen API key | 256-bit entropy keys, HMAC-stored, key-prefix logged for audit |
| Brute force | Rate limit + 401 with constant timing path |
| Replay attack on webhooks | Timestamp window (5 min) + HMAC over `ts.payload` |
| SSRF via webhook URL | DNS resolution + private-IP/loopback/multicast blocklist on register **and** on every delivery |
| SQL injection | All queries via SQLAlchemy ORM; zero string-formatted SQL |
| Tampered request body | Pydantic strict, server re-derives plan amount on subscription charges |
| PII leakage in logs | Mask helpers (`mask_cpf`, `mask_cnpj`, `mask_email`) used at the boundary; raw values never logged |
| Tampered audit trail | Hash-chained audit log; chain tip can be exported and verified offline |

## API keys

- **Generation**: `secrets.token_urlsafe(32)` → 256 bits of entropy. Prefix `pk_test_` (sandbox) or `pk_live_` (production).
- **Storage**: HMAC-SHA256 hash, keyed by the server vault key (`src/billing/security.py::hash_api_key`). The plaintext is shown **once** on creation.
- **Comparison**: lookup is by hash; `hmac.compare_digest` everywhere a secret is verified.
- **Rotation**: `bootstrap_api_key()` creates new keys; deactivate old ones by flipping `active=False` (24h grace recommended).
- **Live keys** disable sandbox-only endpoints (`POST /v1/charges/{id}/confirm` returns 403 in live mode).

## Webhook secrets

Secrets are generated with `secrets.token_urlsafe(32)` (256-bit entropy),
encrypted at rest with AES-256-GCM using the application's master key,
and stored in the database. The plaintext secret is returned **once** at
creation and never stored or returned again. Signing uses decrypt-on-demand
— the secret is decrypted in memory only during webhook delivery and
immediately discarded after the HMAC has been computed. There is no
in-process cache; deliveries survive a full restart with zero loss.

To rotate a secret: delete the endpoint and create a new one.

## Webhook signatures

Every outbound webhook carries:

- `X-Pix-Timestamp: <unix seconds>`
- `X-Pix-Signature: sha256=<HMAC-SHA256(secret, "<ts>.<body>")>`

Receivers MUST:

1. Reject payloads where `|now - timestamp| > 300s` (anti-replay).
2. Recompute the HMAC and compare with `hmac.compare_digest` (constant time).
3. Treat the body as opaque bytes — do not re-serialize before verifying.

The SDK ships [`sdk.pix_billing.verify_signature`](sdk/pix_billing.py) implementing both checks.

## PII protection

- **CPF/CNPJ** — validated with the BACEN check-digit algorithm, encrypted at rest with AES-256-GCM, stored alongside a deterministic SHA-256 fingerprint for indexed lookups.
- **Email** — encrypted at rest, stored alongside a fingerprint.
- **Logs** — masked at the boundary: CPF as `***.xxx.xxx-**`, CNPJ as `**.xxx.xxx/xxxx-**`, email as `r***@domain.com`.
- **Error responses** — a global handler returns `{"error": "internal_error"}` with HTTP 500 instead of stack traces. Domain errors carry safe, human-readable messages.
- **Audit trail** — every state change (charge created/paid/expired/canceled, subscription transitions, dunning steps, webhook deliveries) is appended to a hash-chained log.

## Rate limits

| Scope | Default |
| --- | --- |
| Writes per API key | 100 / minute |
| Reads per API key | 300 / minute |
| Charges per customer | 10 / minute |

`429 Too Many Requests` responses include a `Retry-After` header.

## Cryptography

- **Symmetric**: AES-256-GCM (`cryptography` library) for at-rest field encryption. Per-record nonce, key-id prefixed for rotation.
- **MAC**: HMAC-SHA256 for API-key hashing, webhook signing, and the audit chain.
- **Key vault**: rotation-aware; each key has 90-day default lifetime. Old keys remain decryptable for grace period.

## Known limitations

- **Sandbox only.** `POST /v1/charges/{id}/confirm` simulates payment. Wire a real PSP webhook (Gerencianet, Asaas, OpenPIX) and disable manual confirm before going live.
- **Webhook secrets** are persisted encrypted in the DB (see "Webhook Secrets" below). Migrating the master key into a KMS / secret manager is recommended for multi-region deployments.
- **Single tenant.** No multi-tenant isolation in this MVP — every API key sees every record. Add tenant scoping before sharing the deployment.
- **In-memory rate limiter.** Replace with Redis token-bucket for multi-instance deployments.
- **No 2FA / SSO.** Dashboard auth is HTTP Basic with the API key as password — sufficient for an internal operator dashboard, not a customer portal.

## Quality gate

```bash
uv run ruff check src/          # zero linting errors
uv run mypy src/                # zero type errors (strict)
uv run bandit -r src/ -ll       # zero high/medium findings
uv run pip-audit --skip-editable
uv run safety check
uv run pytest --cov=src tests/  # 25 tests passing
```

All gates pass on `main` at every commit.
