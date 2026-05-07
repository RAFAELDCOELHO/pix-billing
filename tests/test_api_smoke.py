"""End-to-end smoke test through the HTTP layer."""

from __future__ import annotations

from httpx import AsyncClient


async def test_health(client: AsyncClient) -> None:
    resp = await client.get("/health")
    assert resp.status_code == 200
    assert resp.json() == {"status": "ok"}


async def test_charge_lifecycle(client: AsyncClient) -> None:
    resp = await client.post(
        "/v1/charges",
        json={"amount": 15000, "description": "Plano Pro"},
    )
    assert resp.status_code == 201, resp.text
    body = resp.json()
    assert body["status"] == "PENDING"
    assert body["pix_payload"].startswith("000201")
    charge_id = body["charge_id"]

    confirm = await client.post(f"/v1/charges/{charge_id}/confirm")
    assert confirm.status_code == 200
    assert confirm.json()["status"] == "PAID"

    fetched = await client.get(f"/v1/charges/{charge_id}")
    assert fetched.status_code == 200
    assert fetched.json()["status"] == "PAID"


async def test_charge_idempotency(client: AsyncClient) -> None:
    body = {
        "amount": 1000,
        "description": "Idem test",
        "idempotency_key": "idem-abc-123",
    }
    a = (await client.post("/v1/charges", json=body)).json()
    b = (await client.post("/v1/charges", json=body)).json()
    assert a["charge_id"] == b["charge_id"]


async def test_customer_plan_subscription_flow(
    client: AsyncClient, valid_cpf: str
) -> None:
    cust = await client.post(
        "/v1/customers",
        json={
            "name": "Acme Ltda",
            "email": "ops@acme.com",
            "document": valid_cpf,
        },
    )
    assert cust.status_code == 201, cust.text
    customer_id = cust.json()["id"]
    assert cust.json()["email_masked"] == "o***@acme.com"

    plan = await client.post(
        "/v1/plans",
        json={"name": "Pro", "amount": 9900, "interval": "monthly", "trial_days": 0},
    )
    assert plan.status_code == 201
    plan_id = plan.json()["id"]

    sub = await client.post(
        "/v1/subscriptions",
        json={"customer_id": customer_id, "plan_id": plan_id},
    )
    assert sub.status_code == 201
    sub_id = sub.json()["id"]

    invoices = await client.get(f"/v1/subscriptions/{sub_id}/invoices")
    assert invoices.status_code == 200
    assert isinstance(invoices.json(), list)


async def test_unauthorized_without_key(client: AsyncClient) -> None:
    no_auth = client.headers.pop("Authorization")  # noqa: F841
    resp = await client.post("/v1/charges", json={"amount": 100, "description": "x"})
    assert resp.status_code == 401


async def test_invalid_document_rejected(client: AsyncClient) -> None:
    resp = await client.post(
        "/v1/customers",
        json={"name": "X", "email": "x@y.com", "document": "00000000000"},
    )
    assert resp.status_code == 400
