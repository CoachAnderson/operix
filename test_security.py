import uuid

import pyotp
import pytest

from app.core import crypto
from app.core.security import create_token, decode_token, hash_password, verify_password, verify_totp
from app.services.mercadopago import verify_webhook_signature


def test_password_hash_roundtrip():
    h = hash_password("Senha-forte-123")
    assert h.startswith("$argon2id$")
    assert verify_password("Senha-forte-123", h)
    assert not verify_password("errada", h)


def test_token_type_is_enforced():
    uid = uuid.uuid4()
    access = create_token(uid, 0, "access")
    assert decode_token(access, "access")["sub"] == str(uid)
    assert decode_token(access, "refresh") is None
    assert decode_token(access + "x", "access") is None


def test_encryption_roundtrip_and_aad_binding():
    blob = crypto.encrypt("segredo-da-binance", aad="user:cred")
    assert "segredo" not in blob
    assert crypto.decrypt(blob, aad="user:cred") == "segredo-da-binance"
    with pytest.raises(crypto.CryptoError):
        crypto.decrypt(blob, aad="outro:usuario")


def test_totp():
    secret = pyotp.random_base32()
    assert verify_totp(secret, pyotp.TOTP(secret).now())
    assert not verify_totp(secret, "000000x")


def test_mp_signature():
    import hashlib
    import hmac

    secret, rid, ts, data_id = "s3cr3t", "req-1", "1700000000", "abc123"
    v1 = hmac.new(secret.encode(), f"id:{data_id};request-id:{rid};ts:{ts};".encode(), hashlib.sha256).hexdigest()
    header = f"ts={ts},v1={v1}"
    assert verify_webhook_signature(x_signature=header, x_request_id=rid, data_id=data_id, secret=secret)
    assert not verify_webhook_signature(x_signature=header, x_request_id="outro", data_id=data_id, secret=secret)
    assert not verify_webhook_signature(x_signature="", x_request_id=rid, data_id=data_id, secret=secret)
