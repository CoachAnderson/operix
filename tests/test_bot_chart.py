"""Gráfico do robô: candles da corretora + ordens do robô + níveis da posição; só o dono vê."""
import uuid
from datetime import UTC, datetime
from decimal import Decimal

from app.api.routes import bots as bots_route
from app.models import Order, OrderStatus, Position, PosSide, Side, SubStatus, Subscription, Venue
from app.services.brokers.base import Candle
from app.services.brokers.paper import PaperAccount, PaperBroker
from tests.test_api import csrf, register

T0 = int(datetime(2026, 10, 22, 12, 0, tzinfo=UTC).timestamp() * 1000)


class Market:
    async def get_klines(self, symbol, interval, limit=200):
        return [Candle(T0 + i * 3_600_000, 100 + i, 101 + i, 99 + i, 100.5 + i, 1, T0 + (i + 1) * 3_600_000 - 1) for i in range(min(limit, 60))]

    async def get_price(self, symbol):
        return Decimal("150")

    async def get_rules(self, symbol):
        from tests.conftest import RULES
        return RULES

    async def close(self):
        pass


async def test_grafico_com_ordens_e_posicao(client, db, plans, monkeypatch):
    await register(client)
    me = (await client.get("/api/v1/me")).json()
    db.add(Subscription(user_id=uuid.UUID(me["id"]), plan_id=plans["pro"].id, status=SubStatus.active))
    await db.commit()
    body = {"name": "R", "symbol": "BTCUSDT", "strategy": "ema_cross_swing", "order_size_quote": "50", "exec_mode": "auto",
            "stop_loss_pct": "2", "take_profit_pct": "4"}
    bot = (await client.post("/api/v1/bots", json=body, headers=csrf(client))).json()

    async def fake_broker(db_, b):
        return PaperBroker(Market(), PaperAccount(Decimal("1000"), Decimal("0")))

    monkeypatch.setattr(bots_route, "broker_for_bot", fake_broker)
    bid = uuid.UUID(bot["id"])
    at = lambda h: datetime.fromtimestamp((T0 + h * 3_600_000 + 60_000) / 1000, UTC)  # noqa: E731
    db.add_all([
        Order(bot_id=bid, user_id=uuid.UUID(me["id"]), venue=Venue.paper, symbol="BTCUSDT", side=Side.buy, qty=Decimal("0.5"),
              price=Decimal("110"), status=OrderStatus.filled, reason="EMA cruzou acima", client_order_id="t0", created_at=at(10)),
        Order(bot_id=bid, user_id=uuid.UUID(me["id"]), venue=Venue.paper, symbol="BTCUSDT", side=Side.sell, qty=Decimal("0.5"),
              price=Decimal("120"), realized_pnl=Decimal("5"), status=OrderStatus.filled, reason="EMA cruzou abaixo", client_order_id="t1", created_at=at(20)),
        Order(bot_id=bid, user_id=uuid.UUID(me["id"]), venue=Venue.paper, symbol="BTCUSDT", side=Side.buy, qty=Decimal("0.5"),
              price=None, status=OrderStatus.rejected, reason="recusada", client_order_id="t2", created_at=at(21)),
        Position(bot_id=bid, side=PosSide.long, qty=Decimal("0.4"), avg_price=Decimal("150"), opened_at=at(50)),
    ])
    await db.commit()

    r = await client.get(f"/api/v1/bots/{bot['id']}/chart")
    assert r.status_code == 200, r.text
    d = r.json()
    assert d["timeframe"] == "4h" and len(d["ohlc"]) == 60
    assert [(o["side"], o["exit"], o["pnl"]) for o in d["orders"]] == [("BUY", False, None), ("SELL", True, 5.0)]  # sem a recusada
    p = d["position"]
    assert p["side"] == "long" and p["avg_price"] == 150 and abs(p["stop"] - 147) < 1e-9 and abs(p["take"] - 156) < 1e-9

    # outro usuário não vê
    client.cookies.clear()
    await register(client, "outra@example.com")
    assert (await client.get(f"/api/v1/bots/{bot['id']}/chart")).status_code == 404
