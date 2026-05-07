"""CPF/CNPJ validation and PII masking helpers."""

from __future__ import annotations


def _digits(value: str) -> str:
    return "".join(c for c in value if c.isdigit())


def is_valid_cpf(cpf: str) -> bool:
    """Validate a Brazilian CPF (Cadastro de Pessoas Físicas)."""
    digits = _digits(cpf)
    if len(digits) != 11 or digits == digits[0] * 11:
        return False
    nums = [int(c) for c in digits]
    for j in range(9, 11):
        s = sum(nums[i] * ((j + 1) - i) for i in range(j))
        check = (s * 10) % 11
        if check == 10:
            check = 0
        if check != nums[j]:
            return False
    return True


def is_valid_cnpj(cnpj: str) -> bool:
    """Validate a Brazilian CNPJ (Cadastro Nacional da Pessoa Jurídica)."""
    digits = _digits(cnpj)
    if len(digits) != 14 or digits == digits[0] * 14:
        return False
    nums = [int(c) for c in digits]
    weights1 = [5, 4, 3, 2, 9, 8, 7, 6, 5, 4, 3, 2]
    weights2 = [6, 5, 4, 3, 2, 9, 8, 7, 6, 5, 4, 3, 2]
    s1 = sum(nums[i] * weights1[i] for i in range(12))
    d1 = 0 if s1 % 11 < 2 else 11 - (s1 % 11)
    if d1 != nums[12]:
        return False
    s2 = sum(nums[i] * weights2[i] for i in range(13))
    d2 = 0 if s2 % 11 < 2 else 11 - (s2 % 11)
    return d2 == nums[13]


def normalize_document(value: str) -> tuple[str, str]:
    """Return (digits_only, document_type) — raises ValueError if invalid."""
    digits = _digits(value)
    if len(digits) == 11:
        if not is_valid_cpf(digits):
            raise ValueError("Invalid CPF")
        return digits, "CPF"
    if len(digits) == 14:
        if not is_valid_cnpj(digits):
            raise ValueError("Invalid CNPJ")
        return digits, "CNPJ"
    raise ValueError("Document must be 11 (CPF) or 14 (CNPJ) digits")


def mask_email(email: str) -> str:
    """Return ``r***@domain.com`` style mask."""
    if "@" not in email:
        return "***"
    local, _, domain = email.partition("@")
    if not local:
        return "***"
    return f"{local[0]}***@{domain}"


def mask_cpf(cpf: str) -> str:
    """Mask CPF as ``***.123.456-**``."""
    digits = _digits(cpf)
    if len(digits) != 11:
        return "***masked***"
    return f"***.{digits[3:6]}.{digits[6:9]}-**"


def mask_cnpj(cnpj: str) -> str:
    """Mask CNPJ as ``**.345.678/0001-**``."""
    digits = _digits(cnpj)
    if len(digits) != 14:
        return "***masked***"
    return f"**.{digits[2:5]}.{digits[5:8]}/{digits[8:12]}-**"
