import io
import uuid
from datetime import UTC, datetime, timedelta
from decimal import Decimal

from pypdf import PdfReader

from app.models import Bot, Market, Order, OrderStatus, Position, PosSide, Side, User, Venue
from tests.test_api import register


async def _seed(db, user_id: uuid.UUID) -> None:
    now = datetime.now(UTC)
    btc = Bot(user_id=user_id, name="BTC dia", market=Market.crypto, symbol="BTCUSDT", strategy="ema_cross_day", venue=Venue.live)
    eth = Bot(user_id=user_id, name="ETH swing", market=Market.crypto, symbol="ETHUSDT", strategy="ema_cross_swing", venue=Venue.paper)
    eur = Bot(user_id=user_id, name="Euro rompimento", market=Market.forex, symbol="EURUSD", strategy="donchian_breakout", venue=Venue.testnet, allow_short=True)
    db.add_all([btc, eth, eur])
    await db.flush()

    def order(bot, side, q, p, pnl=None, fee="0.05", days=1, status=OrderStatus.filled, reason="Cruzamento de médias"):
        return Order(
            bot_id=bot.id, user_id=user_id, venue=bot.venue, client_order_id=str(uuid.uuid4()), symbol=bot.symbol,
            side=side, qty=Decimal(q), price=Decimal(p), quote_qty=Decimal(q) * Decimal(p), fee_quote=Decimal(fee),
            realized_pnl=Decimal(pnl) if pnl is not None else None, status=status, reason=reason,
            created_at=now - timedelta(days=days),
        )

    db.add_all(
        [
            order(btc, Side.buy, "0.001", "62000", days=5),
            order(btc, Side.sell, "0.001", "63500", pnl="1.40", days=4),
            order(btc, Side.buy, "0.001", "63000", days=3),
            order(btc, Side.sell, "0.001", "62500", pnl="-0.60", days=2, reason="Stop de 1,5% atingido"),
            order(btc, Side.buy, "0.001", "61000", days=1, status=OrderStatus.rejected),  # não entra
            order(eth, Side.buy, "0.02", "2400", days=40),  # fora do período
            order(eth, Side.sell, "0.02", "2450", pnl="0.90", days=2),
            order(eur, Side.sell, "10000", "1.0850", pnl=None, fee="0.30", days=1),
        ]
    )
    db.add(Position(bot_id=eur.id, side=PosSide.short, qty=Decimal("10000"), avg_price=Decimal("1.0850")))

    other = User(email="outra@example.com", name="Outra", password_hash="x")
    db.add(other)
    await db.flush()
    ob = Bot(user_id=other.id, name="Alheio", symbol="BTCUSDT", strategy="ema_cross_day", venue=Venue.live)
    db.add(ob)
    await db.flush()
    db.add(order(ob, Side.sell, "1", "60000", pnl="999", days=1, reason="NAO-DEVE-APARECER"))
    await db.commit()


def _text(pdf: bytes) -> str:
    return "\n".join(p.extract_text() for p in PdfReader(io.BytesIO(pdf)).pages)


async def test_symbols_open_first_and_pdf(client, db):
    await register(client)
    me = (await client.get("/api/v1/me")).json()
    await _seed(db, uuid.UUID(me["id"]))

    symbols = (await client.get("/api/v1/reports/symbols")).json()
    assert [s["symbol"] for s in symbols] == ["EURUSD", "BTCUSDT", "ETHUSDT"]
    assert symbols[0]["open"] is True and symbols[0]["open_sides"] == ["short"]
    assert not symbols[1]["open"]

    today = datetime.now(UTC).date()
    params = [("symbol", "BTCUSDT"), ("symbol", "EURUSD"), ("start", str(today - timedelta(days=30))), ("end", str(today))]
    r = await client.get("/api/v1/reports/pdf", params=params)
    assert r.status_code == 200, r.text
    assert r.headers["content-type"] == "application/pdf"
    assert "attachment" in r.headers["content-disposition"] and ".pdf" in r.headers["content-disposition"]
    text = _text(r.content)
    assert "Relatório de operações" in text
    assert "BTCUSDT" in text and "EURUSD" in text
    assert "ETHUSDT" not in text  # não escolhida
    assert "+0,80" in text  # 1,40 - 0,60 na conta real em USDT
    assert "50% de acerto em 2 operações" in text
    assert "Vendido" in text and "Conta demo" in text  # posição aberta no forex
    assert "Stop de 1,5% atingido" in text
    assert "NAO-DEVE-APARECER" not in text and "999" not in text  # dados de outro assinante

    # Só conta real: some o forex demo
    r = await client.get("/api/v1/reports/pdf", params=params + [("venue", "live")])
    text = _text(r.content)
    assert "Conta demo" not in text and "+0,80" in text


async def test_pdf_validation(client, db):
    await register(client)
    today = datetime.now(UTC).date()
    r = await client.get("/api/v1/reports/pdf", params={"start": str(today), "end": str(today)})
    assert r.status_code == 422  # sem moeda
    r = await client.get("/api/v1/reports/pdf", params={"symbol": "BTCUSDT", "start": str(today), "end": str(today - timedelta(days=1))})
    assert r.status_code == 400
    r = await client.get("/api/v1/reports/pdf", params={"symbol": "BTCUSDT", "start": str(today), "end": str(today)})
    assert r.status_code == 200
    assert "Nenhuma ordem executada" in _text(r.content)
    client.cookies.clear()
    assert (await client.get("/api/v1/reports/symbols")).status_code == 401
