"""CPF/CNPJ validation tests."""

from __future__ import annotations

import pytest

from src.billing.validators import (
    is_valid_cnpj,
    is_valid_cpf,
    mask_cnpj,
    mask_cpf,
    mask_email,
    normalize_document,
)


def test_valid_cpf() -> None:
    assert is_valid_cpf("111.444.777-35")
    assert is_valid_cpf("11144477735")


def test_invalid_cpf() -> None:
    assert not is_valid_cpf("111.444.777-36")
    assert not is_valid_cpf("00000000000")
    assert not is_valid_cpf("123")


def test_valid_cnpj() -> None:
    assert is_valid_cnpj("11.222.333/0001-81")
    assert is_valid_cnpj("11222333000181")


def test_invalid_cnpj() -> None:
    assert not is_valid_cnpj("11222333000182")
    assert not is_valid_cnpj("00000000000000")


def test_normalize_document() -> None:
    digits, dtype = normalize_document("111.444.777-35")
    assert digits == "11144477735"
    assert dtype == "CPF"
    digits, dtype = normalize_document("11.222.333/0001-81")
    assert digits == "11222333000181"
    assert dtype == "CNPJ"
    with pytest.raises(ValueError):
        normalize_document("nonsense")


def test_mask_helpers() -> None:
    assert mask_email("rafael@example.com") == "r***@example.com"
    assert mask_cpf("11144477735") == "***.444.777-**"
    assert mask_cnpj("11222333000181") == "**.222.333/0001-**"
