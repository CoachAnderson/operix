"""Carteira consolidada: lê saldos de cada conta (só leitura), converte para dólar/real e isola falhas."""
import uuid
from datetime import UTC, datetime
from decimal import Decimal

import pytest
import respx
from httpx import Response

from app.core import crypto
from app.models import Bot, BotStatus, ExchangeCredential, ExecMode, Market, Position, PosSide, Venue
from app.services import market_scan, wallet
from app.services.brokers.base import BrokerError
from app.services.brokers.mt5 import MT5Broker
from app.services.brokers.factory import credential_aad
from tests.test_engine import make_user_with_plan

T24 = [
    {"symbol": "BTCUSDT", "lastPrice": "100000"},
    {"symbol": "ETHBTC", "lastPrice": "0.04"},
    {"symbol": "USDTBRL", "lastPrice": "5.5"},
    {"symbol": "EURUSDT", "lastPrice": "1.1"},
]


@pytest.fixture(autouse=True)
def limpa():
    market_scan.clear_cache()
    wallet._clear()
    yield
    market_scan.clear_cache()
    wallet._clear()


def binance_cred(user) -> ExchangeCredential:
    c = ExchangeCredential(id=uuid.uuid4(), user_id=user.id, label="Minha Binance", exchange="binance", venue=Venue.live,
                           api_key_enc="", api_secret_enc="", key_last4="abcd", verified_at=datetime.now(UTC))
    aad = credential_aad(c)
    c.api_key_enc, c.api_secret_enc = crypto.encrypt("chave", aad), crypto.encrypt("segredo", aad)
    return c


@respx.mock
async def test_carteira_consolida_contas(db, plans, monkeypatch):
    user = await make_user_with_plan(db, plans["pro"])
    bn = binance_cred(user)
    mt5 = ExchangeCredential(user_id=user.id, label="MT5 demo", exchange="mt5", venue=Venue.testnet, api_key_enc="-", api_secret_enc="-",
                             key_last4="0000", verified_at=datetime.now(UTC))
    ct = ExchangeCredential(user_id=user.id, label="cTrader real", exchange="ctrader", venue=Venue.live, api_key_enc="-", api_secret_enc="-",
                            key_last4="1111", verified_at=datetime.now(UTC))
    pend = ExchangeCredential(user_id=user.id, label="não verificada", exchange="binance", venue=Venue.live, api_key_enc="-",
                              api_secret_enc="-", key_last4="2222")
    db.add_all([bn, mt5, ct, pend])
    bot = Bot(user_id=user.id, name="Sim BTC", symbol="BTCUSDT", strategy="ema_cross_day", params={"timeframe": "5m"}, exec_mode=ExecMode.auto,
              venue=Venue.paper, status=BotStatus.running, order_size_quote=Decimal("100"), paper_quote_balance=Decimal("900"),
              paper_base_balance=Decimal("0.001"), market=Market.crypto)
    db.add(bot)
    await db.flush()
    db.add(Position(bot_id=bot.id, side=PosSide.long, qty=Decimal("0.001"), avg_price=Decimal("90000")))
    await db.commit()

    respx.get("https://data-api.binance.vision/api/v3/ticker/24hr").mock(return_value=Response(200, json=T24))
    respx.get("https://data-api.binance.vision/api/v3/time").mock(return_value=Response(200, json={"serverTime": 1}))
    acc = respx.get("https://api.binance.com/api/v3/account").mock(return_value=Response(200, json={"balances": [
        {"asset": "USDT", "free": "1000", "locked": "100"},
        {"asset": "BTC", "free": "0.01", "locked": "0"},
        {"asset": "ETH", "free": "1", "locked": "0"},
        {"asset": "NOVA", "free": "50", "locked": "0"},
    ]}))

    async def mt5_summary(self):
        return {"balance": Decimal("10000"), "equity": Decimal("10550"), "margin_free": Decimal("9000"), "currency": "BRL", "leverage": 1}

    async def ct_broker(db_, cred):
        raise BrokerError("Token do cTrader expirado: reconecte a conta")

    monkeypatch.setattr(MT5Broker, "account_summary", mt5_summary)
    monkeypatch.setattr(wallet, "ctrader_broker", ct_broker)

    out = await wallet.build(db, user)
    by = {a["label"]: a for a in out["accounts"]}
    assert set(by) == {"Minha Binance", "MT5 demo", "cTrader real"}  # a não verificada fica de fora
    b = by["Minha Binance"]
    assert b["ok"], b.get("message")
    assert b["real"] and [h["asset"] for h in b["holdings"]][:3] == ["ETH", "USDT", "BTC"]  # por valor em dólar
    assert b["total_usd"] == pytest.approx(1100 + 1000 + 4000)  # ETH via ETHBTC × BTCUSDT
    assert b["unpriced"] == ["NOVA"]
    assert b["total_brl"] == pytest.approx(6100 * 5.5)
    m = by["MT5 demo"]
    assert m["ok"] and not m["real"] and m["equity"] == 10550 and m["total_usd"] == pytest.approx(10550 / 5.5)
    c = by["cTrader real"]
    assert not c["ok"] and "expirado" in c["message"]
    t = out["totals"]
    assert t["real_usd"] == pytest.approx(6100) and t["incomplete"]  # cTrader real falhou
    assert t["test_usd"] == pytest.approx(10550 / 5.5)
    pos = out["positions"][0]
    assert pos["bot"] == "Sim BTC" and pos["pnl"] == pytest.approx(10.0) and pos["pnl_currency"] == "USDT"
    assert out["simulated"][0]["value"] == pytest.approx(900 + 0.001 * 100000)

    await wallet.build(db, user)  # cache curto: não consulta a corretora de novo
    assert acc.call_count == 1
    await wallet.build(db, user, fresh=True)
    assert acc.call_count == 2


async def test_rota_carteira_exige_login(client):
    assert (await client.get("/api/v1/wallet")).status_code == 401
