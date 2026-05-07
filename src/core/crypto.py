"""
VAULT Banking — Cryptography Module
"""

from __future__ import annotations

import base64
import hashlib
import hmac as hmac_mod
import secrets
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

try:
    from cryptography.hazmat.primitives.ciphers.aead import AESGCM

    _HAS_CRYPTO = True
except ImportError:
    _HAS_CRYPTO = False
    AESGCM = None


@dataclass
class CryptoKey:
    key_id: str
    key_bytes: bytes
    algorithm: str
    created_at: datetime
    expires_at: datetime
    is_active: bool = True

    def is_expired(self) -> bool:
        return datetime.now(UTC) > self.expires_at

    def __repr__(self) -> str:
        return f"CryptoKey(id={self.key_id}, algo={self.algorithm}, active={self.is_active})"


class KeyVault:
    KEY_ROTATION_DAYS = 90
    KEY_GRACE_DAYS = 30

    def __init__(self) -> None:
        self._keys: dict[str, CryptoKey] = {}
        self._active_hmac_key_id: str | None = None
        self._active_enc_key_id: str | None = None
        self._initialize_keys()

    def _initialize_keys(self) -> None:
        hmac_key = self._generate_key("HMAC-SHA256")
        enc_key = self._generate_key("AES-256-GCM")
        self._active_hmac_key_id = hmac_key.key_id
        self._active_enc_key_id = enc_key.key_id

    def _generate_key(self, algorithm: str) -> CryptoKey:
        now = datetime.now(UTC)
        key = CryptoKey(
            key_id=f"key_{uuid.uuid4().hex[:12]}",
            key_bytes=secrets.token_bytes(32),
            algorithm=algorithm,
            created_at=now,
            expires_at=now + timedelta(days=self.KEY_ROTATION_DAYS),
            is_active=True,
        )
        self._keys[key.key_id] = key
        return key

    def rotate_keys(self) -> tuple[str, str]:
        if self._active_hmac_key_id:
            self._keys[self._active_hmac_key_id].is_active = False
        if self._active_enc_key_id:
            self._keys[self._active_enc_key_id].is_active = False
        new_hmac = self._generate_key("HMAC-SHA256")
        new_enc = self._generate_key("AES-256-GCM")
        self._active_hmac_key_id = new_hmac.key_id
        self._active_enc_key_id = new_enc.key_id
        return new_hmac.key_id, new_enc.key_id

    def get_active_hmac_key(self) -> bytes:
        key = self._keys[self._active_hmac_key_id]
        if key.is_expired():
            self.rotate_keys()
            key = self._keys[self._active_hmac_key_id]
        return key.key_bytes

    def get_active_enc_key(self) -> bytes:
        key = self._keys[self._active_enc_key_id]
        if key.is_expired():
            self.rotate_keys()
            key = self._keys[self._active_enc_key_id]
        return key.key_bytes

    def get_key_by_id(self, key_id: str) -> CryptoKey | None:
        return self._keys.get(key_id)


class TransactionSigner:
    def __init__(self, key_vault: KeyVault) -> None:
        self._vault = key_vault

    def sign(self, canonical_payload: str) -> str:
        key = self._vault.get_active_hmac_key()
        return hmac_mod.new(key, canonical_payload.encode("utf-8"), hashlib.sha256).hexdigest()

    def verify(self, canonical_payload: str, stored_hash: str) -> bool:
        key = self._vault.get_active_hmac_key()
        expected = hmac_mod.new(key, canonical_payload.encode("utf-8"), hashlib.sha256).hexdigest()
        return hmac_mod.compare_digest(expected, stored_hash)


class FieldEncryptor:
    NONCE_SIZE = 12

    def __init__(self, key_vault: KeyVault) -> None:
        self._vault = key_vault

    def encrypt(self, plaintext: str) -> str:
        if not _HAS_CRYPTO:
            return f"NOCRYPTO:{plaintext.encode().hex()}"
        key_id = self._vault._active_enc_key_id
        key_bytes = self._vault.get_active_enc_key()
        nonce = secrets.token_bytes(self.NONCE_SIZE)
        aesgcm = AESGCM(key_bytes)
        ciphertext = aesgcm.encrypt(nonce, plaintext.encode("utf-8"), None)
        payload = key_id.encode() + b"|" + nonce + ciphertext
        return base64.urlsafe_b64encode(payload).decode()

    def decrypt(self, encrypted_token: str) -> str:
        if encrypted_token.startswith("NOCRYPTO:"):
            return bytes.fromhex(encrypted_token[9:]).decode()
        if not _HAS_CRYPTO:
            raise RuntimeError("cryptography package not available")
        payload = base64.urlsafe_b64decode(encrypted_token.encode())
        sep_idx = payload.index(b"|")
        key_id = payload[:sep_idx].decode()
        rest = payload[sep_idx + 1 :]
        nonce = rest[: self.NONCE_SIZE]
        ciphertext = rest[self.NONCE_SIZE :]
        key_obj = self._vault.get_key_by_id(key_id)
        if key_obj is None:
            raise ValueError(f"Decryption key {key_id} not found")
        aesgcm = AESGCM(key_obj.key_bytes)
        return aesgcm.decrypt(nonce, ciphertext, None).decode("utf-8")


@dataclass
class TokenRecord:
    token: str
    ciphertext: str
    data_type: str
    created_at: datetime


class Tokenizer:
    def __init__(self, encryptor: FieldEncryptor) -> None:
        self._encryptor = encryptor
        self._token_store: dict[str, TokenRecord] = {}
        self._value_to_token: dict[str, str] = {}

    def tokenize(self, value: str, data_type: str) -> str:
        value_hash = hashlib.sha256(value.encode()).hexdigest()
        if value_hash in self._value_to_token:
            return self._value_to_token[value_hash]
        token = self._generate_token(data_type)
        ciphertext = self._encryptor.encrypt(value)
        record = TokenRecord(
            token=token, ciphertext=ciphertext, data_type=data_type, created_at=datetime.now(UTC)
        )
        self._token_store[token] = record
        self._value_to_token[value_hash] = token
        return token

    def detokenize(self, token: str) -> str:
        record = self._token_store.get(token)
        if record is None:
            raise KeyError(f"Token not found: {token[:12]}***")
        return self._encryptor.decrypt(record.ciphertext)

    def _generate_token(self, data_type: str) -> str:
        rand = secrets.token_hex(8)
        prefixes = {"CPF": "cpf", "PAN": "pan", "PIX_KEY": "pix", "ACCOUNT": "acc"}
        return f"{prefixes.get(data_type, 'tok')}_{rand}"


def create_crypto_stack() -> tuple[KeyVault, TransactionSigner, FieldEncryptor, Tokenizer]:
    vault = KeyVault()
    signer = TransactionSigner(vault)
    encryptor = FieldEncryptor(vault)
    tokenizer = Tokenizer(encryptor)
    return vault, signer, encryptor, tokenizer
