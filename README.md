# PIX Billing Stack

Open-source billing API for Brazilian PIX payments. Built on FastAPI + async SQLAlchemy + APScheduler. Generates valid PIX BR-Code QR payloads, manages subscriptions, runs dunning, and delivers signed webhooks — no PSP integration required for development.

> **Status:** sandbox-only. Confirmation is manual via `POST /v1/charges/{id}/confirm`. Wire a real PSP webhook before going live.

## Quickstart

```bash
uv sync
uv run uvicorn main:app --reload
# Swagger UI → http://localhost:8000/docs
# Dashboard  → http://localhost:8000/dashboard
```

Bootstrap an API key (one-time):

```bash
uv run python -c "import asyncio; from src.api.auth import bootstrap_api_key; \
  from src.billing.db import init_db; \
  asyncio.run((lambda: (init_db(), bootstrap_api_key('local')))[1]())"
```

## Using the SDK

```python
from sdk.pix_billing import PixBilling

client = PixBilling(api_key="pk_test_...", base_url="http://localhost:8000")

customer = client.customers.create(
    name="Acme Ltda",
    email="contact@acme.com",
    document="11144477735",  # valid CPF for the docs example
)

plan = client.plans.create(name="Pro", amount=15000, interval="monthly", trial_days=7)
sub = client.subscriptions.create(customer_id=customer.id, plan_id=plan.id)

charge = client.charges.create(amount=15000, description="Plano Pro - Maio")
print(charge.pix_payload)              # paste into any bank app
print(charge.qr_code_base64[:60], "…")  # base64 PNG for embedding
```

## Endpoints

| Method | Path | Purpose |
| ------ | ---- | ------- |
| POST | `/v1/charges` | Create a PIX charge (returns payload + QR) |
| GET  | `/v1/charges/{id}` | Charge status |
| POST | `/v1/charges/{id}/confirm` | Sandbox: simulate payment |
| POST | `/v1/charges/{id}/cancel` | Cancel a pending charge |
| POST | `/v1/customers` | Create a customer (CPF/CNPJ encrypted) |
| GET  | `/v1/customers/{id}` | Fetch customer (PII masked) |
| POST | `/v1/plans` | Create a recurring plan |
| GET  | `/v1/plans` | List plans |
| POST | `/v1/subscriptions` | Subscribe a customer to a plan |
| GET  | `/v1/subscriptions/{id}` | Subscription state |
| GET  | `/v1/subscriptions/{id}/invoices` | Charge history |
| DELETE | `/v1/subscriptions/{id}` | Cancel (end of period or `?immediate=true`) |
| POST | `/v1/webhooks` | Register webhook URL (returns secret once) |
| GET  | `/v1/webhooks` | List endpoints |
| POST | `/v1/webhooks/{id}/test` | Fire a test event |
| GET  | `/v1/events` | List supported event types |

## Webhook signature verification

Every outbound webhook carries `X-Pix-Signature: sha256=<hex>` and `X-Pix-Timestamp`. Verify with:

```python
from sdk.pix_billing import verify_signature

ok = verify_signature(
    secret=YOUR_SECRET,
    payload=request.body.decode(),
    timestamp=request.headers["X-Pix-Timestamp"],
    signature_header=request.headers["X-Pix-Signature"],
)
```

## Architecture

See [ARCHITECTURE.md](docs/ARCHITECTURE.md). Layered, strict: API → Service → Repository → Core. Core (`src/core/`) is frozen and reused from the parent VAULT codebase.

## Development

```bash
uv run ruff check src/
uv run mypy src/
uv run bandit -r src/
uv run pytest --cov=src
```

## License

MIT.
