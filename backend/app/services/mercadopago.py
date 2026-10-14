"""Cliente mínimo do Mercado Pago para assinaturas (preapproval) e validação de webhook."""
from __future__ import annotations

import hashlib
import hmac
import uuid
from decimal import Decimal
from typing import Any

import httpx

from app.core.config import get_settings


class MercadoPagoError(Exception):
    pass


# Mapeamento do status do preapproval no MP para o status interno.
PREAPPROVAL_STATUS = {
    "pending": "pending",
    "authorized": "active",
    "paused": "paused",
    "cancelled": "cancelled",
}


class MercadoPagoClient:
    def __init__(self, access_token: str | None = None, base_url: str | None = None, transport: httpx.AsyncBaseTransport | None = None):
        s = get_settings()
        self._client = httpx.AsyncClient(
            base_url=base_url or s.mp_api_base,
            headers={"Authorization": f"Bearer {access_token or s.mp_access_token}"},
            timeout=15,
            transport=transport,
        )

    async def __aenter__(self) -> MercadoPagoClient:
        return self

    async def __aexit__(self, *exc: object) -> None:
        await self._client.aclose()

    async def _request(self, method: str, path: str, **kw: Any) -> dict[str, Any]:
        resp = await self._client.request(method, path, **kw)
        if resp.status_code >= 400:
            raise MercadoPagoError(f"MP {method} {path} -> {resp.status_code}: {resp.text[:300]}")
        return resp.json()

    async def create_preapproval(
        self,
        *,
        reason: str,
        amount: Decimal,
        payer_email: str,
        external_reference: str,
        back_url: str,
    ) -> dict[str, Any]:
        body = {
            "reason": reason[:255],
            "external_reference": external_reference,
            "payer_email": payer_email,
            "auto_recurring": {
                "frequency": 1,
                "frequency_type": "months",
                "transaction_amount": float(amount),
                "currency_id": "BRL",
            },
            "back_url": back_url,
            "status": "pending",
        }
        return await self._request("POST", "/preapproval", json=body, headers={"X-Idempotency-Key": str(uuid.uuid4())})

    async def get_preapproval(self, preapproval_id: str) -> dict[str, Any]:
        return await self._request("GET", f"/preapproval/{preapproval_id}")

    async def cancel_preapproval(self, preapproval_id: str) -> dict[str, Any]:
        return await self._request("PUT", f"/preapproval/{preapproval_id}", json={"status": "cancelled"})

    async def get_authorized_payment(self, payment_id: str) -> dict[str, Any]:
        return await self._request("GET", f"/authorized_payments/{payment_id}")


def parse_signature_header(header: str) -> tuple[str | None, str | None]:
    parts: dict[str, str] = {}
    for chunk in header.split(","):
        key, _, value = chunk.partition("=")
        parts[key.strip()] = value.strip()
    return parts.get("ts"), parts.get("v1")


def verify_webhook_signature(*, x_signature: str, x_request_id: str, data_id: str, secret: str | None = None) -> bool:
    """HMAC-SHA256 de 'id:{data.id};request-id:{x-request-id};ts:{ts};' comparado em tempo constante."""
    secret = secret if secret is not None else get_settings().mp_webhook_secret
    ts, v1 = parse_signature_header(x_signature or "")
    if not (secret and ts and v1 and x_request_id and data_id):
        return False
    data_id = data_id.lower() if data_id.isalnum() else data_id
    manifest = f"id:{data_id};request-id:{x_request_id};ts:{ts};"
    expected = hmac.new(secret.encode(), manifest.encode(), hashlib.sha256).hexdigest()
    return hmac.compare_digest(expected, v1)
