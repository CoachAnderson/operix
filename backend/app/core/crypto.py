"""Cifragem de segredos (chaves de corretora, segredo 2FA) com AES-256-GCM e rotação de chaves.

Formato armazenado: "<key_id>:<base64(nonce|ciphertext|tag)>".
A variável ENCRYPTION_KEYS aceita várias chaves ("k2:...,k1:..."); a primeira é usada para cifrar,
todas servem para decifrar. Para rotacionar: adicione a nova na frente, rode recriptografar e remova a antiga.
"""
from __future__ import annotations

import base64
import os
from functools import lru_cache

from cryptography.hazmat.primitives.ciphers.aead import AESGCM

from app.core.config import get_settings


class CryptoError(Exception):
    pass


def generate_key() -> str:
    return base64.b64encode(AESGCM.generate_key(bit_length=256)).decode()


@lru_cache
def _keys() -> list[tuple[str, bytes]]:
    raw = get_settings().encryption_keys.strip()
    if not raw:
        if get_settings().is_production:
            raise CryptoError("ENCRYPTION_KEYS não configurada")
        # Chave determinística só para desenvolvimento/teste. Nunca usar em produção.
        return [("dev", b"\x00" * 32)]
    keys: list[tuple[str, bytes]] = []
    for part in raw.split(","):
        kid, _, b64 = part.strip().partition(":")
        key = base64.b64decode(b64)
        if len(key) != 32:
            raise CryptoError(f"Chave {kid} não tem 32 bytes")
        keys.append((kid, key))
    return keys


def encrypt(plaintext: str, aad: str = "") -> str:
    kid, key = _keys()[0]
    nonce = os.urandom(12)
    ct = AESGCM(key).encrypt(nonce, plaintext.encode(), aad.encode() or None)
    return f"{kid}:{base64.b64encode(nonce + ct).decode()}"


def decrypt(token: str, aad: str = "") -> str:
    kid, _, b64 = token.partition(":")
    key = dict(_keys()).get(kid)
    if key is None:
        raise CryptoError(f"Chave de cifragem '{kid}' não disponível")
    blob = base64.b64decode(b64)
    try:
        return AESGCM(key).decrypt(blob[:12], blob[12:], aad.encode() or None).decode()
    except Exception as exc:  # noqa: BLE001 - não vazar detalhes
        raise CryptoError("Falha ao decifrar segredo") from exc
