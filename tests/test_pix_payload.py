"""Tests for the EMV PIX payload generator."""

from __future__ import annotations

from src.billing.pix import (
    PixChargeSpec,
    build_pix_payload,
    render_qr_base64,
    verify_payload_crc,
)


def test_payload_starts_with_format_indicator() -> None:
    spec = PixChargeSpec(
        pix_key="demo@pix.dev",
        txid="ABC1234567",
        amount_cents=15000,
        description="Plano Pro",
        merchant_name="DEMO",
        merchant_city="FORTALEZA",
    )
    payload = build_pix_payload(spec)
    assert payload.startswith("000201")


def test_payload_contains_amount_and_currency() -> None:
    spec = PixChargeSpec(
        pix_key="demo@pix.dev",
        txid="ABC1234567",
        amount_cents=15000,
        description="Plano Pro",
        merchant_name="DEMO",
        merchant_city="FORTALEZA",
    )
    payload = build_pix_payload(spec)
    assert "5303986" in payload  # currency BRL
    assert "150.00" in payload


def test_payload_crc_is_valid() -> None:
    spec = PixChargeSpec(
        pix_key="demo@pix.dev",
        txid="ABC1234567",
        amount_cents=999,
        description="Test",
        merchant_name="X",
        merchant_city="Y",
    )
    payload = build_pix_payload(spec)
    assert verify_payload_crc(payload)


def test_qr_render_returns_png_base64() -> None:
    spec = PixChargeSpec(
        pix_key="demo@pix.dev",
        txid="ABC1234567",
        amount_cents=100,
        description="X",
        merchant_name="DEMO",
        merchant_city="FORTALEZA",
    )
    qr = render_qr_base64(build_pix_payload(spec))
    import base64

    raw = base64.b64decode(qr)
    assert raw.startswith(b"\x89PNG\r\n\x1a\n")
