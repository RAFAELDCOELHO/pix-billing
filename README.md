# PIX Billing Stack

![Tests](https://img.shields.io/badge/tests-16%20passing-brightgreen)
![Python](https://img.shields.io/badge/python-3.11%2B-blue)
![Mypy](https://img.shields.io/badge/mypy-strict-blue)
![License](https://img.shields.io/badge/license-MIT-green)

Open-source billing API built for LatAm SaaS products.

Stripe doesn't speak PIX. Asaas and Gerencianet have outdated APIs, poor documentation, and no modern SDK. PIX Billing Stack fills that gap: a clean, async, type-safe billing layer that generates valid PIX BR-Code QR payloads, manages subscriptions, retries failed charges, and delivers signed webhooks — with a developer experience that doesn't make you want to quit.

> **Status:** sandbox mode. Payment confirmation is manual via `POST /v1/charges/{id}/confirm`.
> Wire a real PSP webhook before going live.

## Features

- **PIX QR Code generation** — valid EMV BR-Code payloads, base64 QR image, configurable TTL
- **Customer registry** — CPF/CNPJ validated and encrypted at rest (AES-256-GCM)
- **Subscription engine** — TRIALING → ACTIVE → PAST_DUE → CANCELED state machine, APScheduler-powered
- **Dunning engine** — configurable retry schedule, new QR per attempt, auto-cancels after exhaustion
- **Signed webhooks** — HMAC-SHA256, exponential backoff, anti-replay timestamp validation
- **Python SDK** — typed, zero-dependency wrapper, 10-line quickstart
- **Security-first** — mypy strict, bandit clean, rate limiting, soft deletes, full audit trail

## Quickstart

**Requirements:** Python 3.11+, [uv](https://docs.astral.sh/uv/)

```bash
git clone https://github.com/RAFAELDCOELHO/pix-billing.git
cd pix-billing
uv sync
uv run python scripts/bootstrap.py   # creates your first API key
uv run uvicorn main:app --reload
```

Open:
- **Swagger UI** → http://localhost:8000/docs
- **Dashboard** → http://localhost:8000/dashboard

## SDK Usage

```python
from sdk.pix_billing import PixBilling

client = PixBilling(api_key="pk_test_...", base_url="http://localhost:8000")

# Create a customer
customer = client.customers.create(
    name="Acme Ltda",
    email="contact@acme.com",
    document="11144477735",
)

# Create a plan
plan = client.plans.create(name="Pro", amount=15000, interval="monthly", trial_days=7)

# Subscribe
sub = client.subscriptions.create(customer_id=customer.id, plan_id=plan.id)

# One-off charge
charge = client.charges.create(amount=15000, description="Plano Pro - Maio")
print(charge.pix_payload)       # paste into any bank app
```

## Webhook Verification

Every outbound webhook carries `X-Pix-Signature: sha256=<hex>` and `X-Pix-Timestamp`.

```python
from sdk.pix_billing import verify_signature

ok = verify_signature(
    secret=YOUR_WEBHOOK_SECRET,
    payload=request.body.decode(),
    timestamp=request.headers["X-Pix-Timestamp"],
    signature_header=request.headers["X-Pix-Signature"],
)
```

Payloads older than 5 minutes are automatically rejected.

## API Reference

| Method | Path | Description |
|--------|------|-------------|
| POST | `/v1/charges` | Create a PIX charge |
| GET | `/v1/charges/{id}` | Get charge status |
| POST | `/v1/charges/{id}/confirm` | Sandbox: simulate payment |
| POST | `/v1/charges/{id}/cancel` | Cancel a pending charge |
| POST | `/v1/customers` | Create a customer |
| GET | `/v1/customers/{id}` | Get customer (PII masked) |
| POST | `/v1/plans` | Create a recurring plan |
| GET | `/v1/plans` | List plans |
| POST | `/v1/subscriptions` | Subscribe customer to plan |
| GET | `/v1/subscriptions/{id}` | Get subscription state |
| GET | `/v1/subscriptions/{id}/invoices` | Charge history |
| DELETE | `/v1/subscriptions/{id}` | Cancel subscription |
| POST | `/v1/webhooks` | Register webhook endpoint |
| GET | `/v1/webhooks` | List endpoints |
| POST | `/v1/webhooks/{id}/test` | Fire a test event |

Full interactive docs at `/docs` when running locally.

## Quality

```bash
uv run ruff check src/          # zero linting errors
uv run mypy src/                # zero type errors (strict)
uv run bandit -r src/           # zero high-severity findings
uv run pytest --cov=src tests/  # 16 tests, 90%+ coverage
```

## Architecture

Strict layered architecture: API → Service → Repository → Core.

See [ARCHITECTURE.md](docs/ARCHITECTURE.md) for full data flow and design decisions.

## Contributing

See [CONTRIBUTING.md](CONTRIBUTING.md).

## License

MIT
