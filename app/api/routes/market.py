"""Mercados: pares da Binance à vista disponíveis agora (dados públicos, sem chave)."""
from __future__ import annotations

from fastapi import APIRouter, HTTPException, Query, status

from app.api.deps import DB, CurrentUser
from app.core.ratelimit import hit
from app.services import market_scan
from app.services import wallet as wallet_service
from app.services.brokers.base import BrokerError
from app.services.brokers.binance import BinanceClient

router = APIRouter(prefix="/market", tags=["mercados"])


@router.get("/binance")
async def binance_pairs(user: CurrentUser, quote: str = Query("USDT", pattern=r"^[A-Z0-9]{2,10}$")) -> dict:
    await hit(f"market:{user.id}", limit=60, window_seconds=60)
    try:
        return await market_scan.scan(quote)
    except BrokerError as exc:
        raise HTTPException(status.HTTP_502_BAD_GATEWAY, f"Não foi possível consultar a Binance agora: {exc}") from exc


@router.get("/price")
async def binance_price(user: CurrentUser, symbol: str = Query(pattern=r"^[A-Z0-9]{5,20}$")) -> dict:
    """Preço atual de um par da Binance à vista (público), para as prévias da grade e da DCA."""
    await hit(f"price:{user.id}", limit=120, window_seconds=60)
    client = BinanceClient("live")
    try:
        return {"symbol": symbol, "price": float(await client.get_price(symbol))}
    except BrokerError as exc:
        raise HTTPException(status.HTTP_502_BAD_GATEWAY, f"Par não encontrado ou Binance indisponível: {exc}") from exc
    finally:
        await client.close()


# ---------------- Carteira ----------------
wallet_router = APIRouter(prefix="/wallet", tags=["carteira"])


@wallet_router.get("")
async def wallet(user: CurrentUser, db: DB, atualizar: bool = False) -> dict:
    """Saldos de todas as contas conectadas do cliente (só leitura), em dólar e real."""
    await hit(f"wallet:{user.id}", limit=20, window_seconds=60)
    return await wallet_service.build(db, user, fresh=atualizar)
