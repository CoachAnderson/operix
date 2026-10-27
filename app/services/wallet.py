"""Carteira consolidada: o que o cliente tem em cada conta conectada, só leitura.

Nada sai da corretora: a plataforma consulta os saldos com as chaves que o próprio cliente cadastrou (Binance) ou
pela conexão que ele autorizou (cTrader, MetaTrader 5) e converte para dólar e real com as cotações públicas da
Binance. Não há depósito, saque nem guarda de valores pela plataforma.

- Contas reais entram no "patrimônio"; testnet e contas demo aparecem à parte.
- A simulação (saldo fictício dos robôs) também aparece à parte.
- Cada conta é consultada em paralelo e com tempo limite: uma corretora fora do ar não trava as outras.
"""
from __future__ import annotations

import asyncio
import logging
import time
import uuid
from decimal import Decimal
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Bot, ExchangeCredential, Market, Position, PosSide, User, Venue
from app.services import b3, market_scan
from app.services.brokers.base import BrokerError
from app.services.brokers.binance import BinanceClient
from app.services.brokers.factory import ctrader_broker, decrypt_credential
from app.services.brokers.mt5 import MT5Broker

log = logging.getLogger(__name__)
STABLE_USD = {"USDT", "USDC", "FDUSD", "BUSD", "TUSD", "USDP", "DAI", "USD"}
ACCOUNT_TIMEOUT = 15
MAX_HOLDINGS = 60
_cache: dict[uuid.UUID, tuple[float, dict]] = {}
CACHE_SECONDS = 20


class Prices:
    """Conversão para dólar e real com as cotações públicas da Binance (último preço de 24 h, em cache)."""

    def __init__(self, tickers: dict[str, dict]):
        self.t = tickers

    def last(self, symbol: str) -> float | None:
        v = self.t.get(symbol, {}).get("lastPrice")
        try:
            f = float(v)
        except (TypeError, ValueError):
            return None
        return f if f > 0 else None

    @property
    def usd_brl(self) -> float | None:
        return self.last("USDTBRL")

    def usd(self, asset: str, amount: float) -> float | None:
        asset = asset.upper()
        if amount == 0:
            return 0.0
        if asset in STABLE_USD:
            return amount
        if asset == "BRL":
            return amount / self.usd_brl if self.usd_brl else None
        for quote in ("USDT", "USDC", "FDUSD"):
            p = self.last(asset + quote)
            if p:
                return amount * p
        btc = self.last(asset + "BTC")
        if btc and self.last("BTCUSDT"):
            return amount * btc * self.last("BTCUSDT")  # type: ignore[operator]
        return None

    def brl(self, usd: float | None) -> float | None:
        return usd * self.usd_brl if usd is not None and self.usd_brl else None


def _f(v: Any) -> float:
    try:
        return float(v)
    except (TypeError, ValueError):
        return 0.0


async def _binance(cred: ExchangeCredential, prices: Prices) -> dict:
    key, secret = decrypt_credential(cred)
    client = BinanceClient(cred.venue.value, key, secret)
    try:
        await client.sync_time()
        data = await client.account()
    finally:
        await client.close()
    holdings = []
    for b in data.get("balances", []):
        free, locked = _f(b.get("free")), _f(b.get("locked"))
        total = free + locked
        if total <= 0:
            continue
        usd = prices.usd(b.get("asset", ""), total)
        holdings.append({"asset": b.get("asset"), "free": free, "locked": locked, "total": total, "usd": usd, "brl": prices.brl(usd)})
    holdings.sort(key=lambda h: h["usd"] if h["usd"] is not None else -1, reverse=True)
    total_usd = sum(h["usd"] for h in holdings if h["usd"] is not None)
    others = holdings[MAX_HOLDINGS:]
    return {
        "kind": "assets",
        "holdings": holdings[:MAX_HOLDINGS],
        "hidden_holdings": len(others),
        "unpriced": [h["asset"] for h in holdings if h["usd"] is None][:20],
        "total_usd": total_usd,
    }


async def _margin_account(summary: dict, prices: Prices) -> dict:
    cur = (summary.get("currency") or "").upper()
    equity = _f(summary.get("equity", summary.get("balance")))
    usd = prices.usd(cur, equity) if cur else None
    if usd is None and cur == "EUR":
        eur = prices.last("EURUSDT")
        usd = equity * eur if eur else None
    return {
        "kind": "margin",
        "currency": cur or None,
        "balance": _f(summary.get("balance")),
        "equity": equity if "equity" in summary else None,
        "margin_free": _f(summary["margin_free"]) if "margin_free" in summary else None,
        "leverage": summary.get("leverage"),
        "total_usd": usd,
    }


async def _account(db: AsyncSession, cred: ExchangeCredential, prices: Prices) -> dict:
    base = {
        "id": str(cred.id),
        "label": cred.label,
        "exchange": cred.exchange,
        "venue": cred.venue.value,
        "real": cred.venue == Venue.live,
        "broker_name": cred.broker_name,
    }
    try:
        if cred.exchange == "binance":
            body = await asyncio.wait_for(_binance(cred, prices), ACCOUNT_TIMEOUT)
        elif cred.exchange == "ctrader":
            broker = await ctrader_broker(db, cred)
            body = await _margin_account(await asyncio.wait_for(broker.account_summary(), ACCOUNT_TIMEOUT), prices)
        elif cred.exchange == "mt5":
            body = await _margin_account(await asyncio.wait_for(MT5Broker(cred.id, cred.venue.value).account_summary(), ACCOUNT_TIMEOUT), prices)
        else:
            return {**base, "ok": False, "message": "Corretora não suportada na carteira"}
    except TimeoutError:
        return {**base, "ok": False, "message": "A corretora demorou para responder. Tente de novo em instantes."}
    except BrokerError as exc:
        return {**base, "ok": False, "message": str(exc)}
    except Exception:  # noqa: BLE001 - uma conta com problema não derruba a carteira
        log.exception("Carteira: falha ao ler a conta %s (%s)", cred.id, cred.exchange)
        return {**base, "ok": False, "message": "Não foi possível ler esta conta agora."}
    body["total_brl"] = prices.brl(body.get("total_usd"))
    return {**base, "ok": True, **body}


def _position_row(bot: Bot, pos: Position, prices: Prices) -> dict:
    qty, avg = float(pos.qty), float(pos.avg_price)
    sign = -1 if pos.side == PosSide.short else 1
    row: dict[str, Any] = {
        "bot_id": str(bot.id), "bot": bot.name, "symbol": bot.symbol, "market": bot.market.value, "venue": bot.venue.value,
        "side": pos.side.value, "qty": qty, "avg_price": avg, "price": None, "pnl": None, "pnl_currency": None, "value_usd": None,
    }
    if bot.market == Market.b3:
        row["qty"] = qty / float(b3.info(bot.symbol).point_value)  # contratos
        row["pnl_currency"] = "BRL"
    if bot.market == Market.crypto:
        price = prices.last(bot.symbol)
        if price:
            quote = bot.symbol[-4:] if bot.symbol.endswith(("USDT", "USDC")) else bot.symbol[-3:]
            row.update(price=price, pnl=sign * (price - avg) * qty, pnl_currency=quote, value_usd=prices.usd(quote, qty * price))
    return row


async def build(db: AsyncSession, user: User, fresh: bool = False) -> dict:
    hit = _cache.get(user.id)
    if hit and not fresh and time.monotonic() - hit[0] < CACHE_SECONDS:
        return hit[1]
    try:
        prices = Prices(await market_scan._tickers_24h())
        prices_ok = True
    except BrokerError:
        prices, prices_ok = Prices({}), False

    creds = list(await db.scalars(select(ExchangeCredential).where(ExchangeCredential.user_id == user.id, ExchangeCredential.verified_at.is_not(None))))
    accounts = list(await asyncio.gather(*(_account(db, c, prices) for c in creds)))
    accounts.sort(key=lambda a: (not a["real"], -(a.get("total_usd") or 0)))  # contas reais primeiro, maiores no topo
    bots = list(await db.scalars(select(Bot).where(Bot.user_id == user.id)))
    by_cred: dict[str, int] = {}
    for b in bots:
        if b.credential_id and b.venue != Venue.paper:
            by_cred[str(b.credential_id)] = by_cred.get(str(b.credential_id), 0) + 1
    for a in accounts:
        a["bots"] = by_cred.get(a["id"], 0)

    positions = {p.bot_id: p for p in await db.scalars(select(Position).where(Position.bot_id.in_([b.id for b in bots])))} if bots else {}
    open_rows = [_position_row(b, positions[b.id], prices) for b in bots if b.id in positions]

    simulated = []
    for b in bots:
        if b.venue != Venue.paper:
            continue
        cash = float(b.paper_quote_balance)
        held = float(b.paper_base_balance)
        value, currency = cash, ("BRL" if b.market == Market.b3 else None)
        if b.market == Market.crypto:
            quote = b.symbol[-4:] if b.symbol.endswith(("USDT", "USDC")) else b.symbol[-3:]
            currency = quote
            price = prices.last(b.symbol)
            if held and price:
                value = cash + held * price
        elif b.market == Market.forex:
            currency = b.symbol[3:6] if len(b.symbol) >= 6 else None
        simulated.append({"bot_id": str(b.id), "bot": b.name, "symbol": b.symbol, "market": b.market.value, "value": value, "currency": currency})

    real_usd = sum(a.get("total_usd") or 0 for a in accounts if a.get("ok") and a["real"])
    test_usd = sum(a.get("total_usd") or 0 for a in accounts if a.get("ok") and not a["real"])
    out = {
        "updated_at": int(time.time() * 1000),
        "usd_brl": prices.usd_brl,
        "prices_ok": prices_ok,
        "totals": {
            "real_usd": real_usd, "real_brl": prices.brl(real_usd),
            "test_usd": test_usd, "test_brl": prices.brl(test_usd),
            "incomplete": any(not a.get("ok") or a.get("total_usd") is None for a in accounts if a["real"]),
        },
        "accounts": accounts,
        "positions": open_rows,
        "simulated": simulated,
    }
    _cache[user.id] = (time.monotonic(), out)
    return out


def _clear() -> None:
    _cache.clear()


__all__ = ["build", "Prices", "Decimal"]
