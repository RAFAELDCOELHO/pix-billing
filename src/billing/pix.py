"""PIX EMV QR-code payload generator (BACEN spec).

Implements the BR-Code static/dynamic payload format used by every Brazilian
bank app. No external PIX dependency — pure-Python EMV TLV encoding plus the
ISO-13616 CRC16-CCITT checksum.
"""

from __future__ import annotations

import base64
import io
from dataclasses import dataclass

import qrcode


def _emv(tag: str, value: str) -> str:
    """Encode a TLV (tag, length, value) triple."""
    return f"{tag}{len(value):02d}{value}"


def _crc16_ccitt(payload: str) -> str:
    """ISO/IEC 13239 CRC16 — polynomial 0x1021, seed 0xFFFF."""
    crc = 0xFFFF
    for byte in payload.encode("utf-8"):
        crc ^= byte << 8
        for _ in range(8):
            crc = ((crc << 1) ^ 0x1021) & 0xFFFF if crc & 0x8000 else (crc << 1) & 0xFFFF
    return f"{crc:04X}"


def _sanitize(text: str, max_len: int) -> str:
    """Strip accents/forbidden chars and uppercase for EMV string fields."""
    import unicodedata

    nfkd = unicodedata.normalize("NFKD", text)
    ascii_only = "".join(c for c in nfkd if not unicodedata.combining(c))
    cleaned = "".join(c for c in ascii_only.upper() if c.isalnum() or c in " ").strip()
    return cleaned[:max_len] or "PAYMENT"


@dataclass(frozen=True)
class PixChargeSpec:
    """Inputs needed to render a PIX BR-Code payload."""

    pix_key: str
    txid: str
    amount_cents: int
    description: str
    merchant_name: str
    merchant_city: str


def build_pix_payload(spec: PixChargeSpec) -> str:
    """Build the PIX BR-Code copia-e-cola string for ``spec``.

    Returns the EMV payload including CRC16. Any bank app that supports PIX
    should be able to scan or paste this and present a payment screen.
    """
    if spec.amount_cents <= 0:
        raise ValueError("amount_cents must be positive")
    if len(spec.txid) > 25:
        raise ValueError("txid must be at most 25 chars (EMV TLV limit)")

    amount_brl = f"{spec.amount_cents / 100:.2f}"
    description = _sanitize(spec.description, 50)

    merchant_account = _emv("00", "br.gov.bcb.pix") + _emv("01", spec.pix_key)
    if description:
        merchant_account += _emv("02", description[:25])

    additional_data = _emv("05", spec.txid)

    body = (
        _emv("00", "01")  # payload format indicator
        + _emv("01", "12")  # point of initiation method (12 = dynamic)
        + _emv("26", merchant_account)
        + _emv("52", "0000")  # merchant category code
        + _emv("53", "986")  # transaction currency (BRL)
        + _emv("54", amount_brl)
        + _emv("58", "BR")  # country
        + _emv("59", _sanitize(spec.merchant_name, 25))
        + _emv("60", _sanitize(spec.merchant_city, 15))
        + _emv("62", additional_data)
        + "6304"  # CRC tag + length placeholder
    )
    crc = _crc16_ccitt(body)
    return body + crc


def render_qr_base64(payload: str, *, box_size: int = 6, border: int = 2) -> str:
    """Render ``payload`` as a base64-encoded PNG QR code."""
    qr = qrcode.QRCode(
        version=None,
        error_correction=qrcode.constants.ERROR_CORRECT_M,
        box_size=box_size,
        border=border,
    )
    qr.add_data(payload)
    qr.make(fit=True)
    img = qr.make_image(fill_color="black", back_color="white")
    buf = io.BytesIO()
    img.save(buf)
    return base64.b64encode(buf.getvalue()).decode("ascii")


def verify_payload_crc(payload: str) -> bool:
    """Re-compute the CRC16 and verify it matches the trailing bytes."""
    if len(payload) < 4:
        return False
    body, crc = payload[:-4], payload[-4:]
    return _crc16_ccitt(body) == crc.upper()
