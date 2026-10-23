"""Mercados: pares da Binance à vista disponíveis agora (dados públicos, sem chave)."""
from __future__ import annotations

from fastapi import APIRouter, HTTPException, Query, status

from app.api.deps import DB, CurrentUser
from app.core.ratelimit import hit
from app.services import market_scan
from app.services import wallet as wallet_service
from app.services.brokers.base import BrokerError

router = APIRouter(prefix="/market", tags=["mercados"])


@router.get("/binance")
async def binance_pairs(user: CurrentUser, quote: str = Query("USDT", pattern=r"^[A-Z0-9]{2,10}$")) -> dict:
    await hit(f"market:{user.id}", limit=60, window_seconds=60)
    try:
        return await market_scan.scan(quote)
    except BrokerError as exc:
        raise HTTPException(status.HTTP_502_BAD_GATEWAY, f"Não foi possível consultar a Binance agora: {exc}") from exc


# ---------------- Carteira ----------------
wallet_router = APIRouter(prefix="/wallet", tags=["carteira"])


@wallet_router.get("")
async def wallet(user: CurrentUser, db: DB, atualizar: bool = False) -> dict:
    """Saldos de todas as contas conectadas do cliente (só leitura), em dólar e real."""
    await hit(f"wallet:{user.id}", limit=20, window_seconds=60)
    return await wallet_service.build(db, user, fresh=atualizar)
