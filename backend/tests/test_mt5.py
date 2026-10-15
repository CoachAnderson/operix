"""Futuros da B3 via MetaTrader 5: conector (com MT5 simulado), ponte pelo servidor e motor dos robôs."""
import asyncio
import sys
import threading
import time
import uuid
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path
from zoneinfo import ZoneInfo

import httpx
import pytest
from sqlalchemy import select

AGENT_DIR = Path(__file__).resolve().parents[2] / "conector-mt5"
if not AGENT_DIR.exists():
    pytest.skip("pasta do conector não está disponível", allow_module_level=True)
sys.path.insert(0, str(AGENT_DIR))

import oraculo_conector as oc  # noqa: E402

from app.core.redis import get_redis  # noqa: E402
from app.engine import executor  # noqa: E402
from app.engine.runner import run_tick  # noqa: E402
from app.main import app  # noqa: E402
from app.models import Bot, BotStatus, ExchangeCredential, ExecMode, Market, Order, Position, PosSide, Side, SubStatus, Subscription, Venue  # noqa: E402
from app.services import b3, mt5_bridge  # noqa: E402
from app.services.brokers.base import BrokerError  # noqa: E402
from app.services.brokers.factory import broker_for_bot  # noqa: E402
from tests.fake_mt5 import FakeMT5  # noqa: E402
from tests.test_api import csrf, register  # noqa: E402

COID = "tb" + "1" * 30
BRT = ZoneInfo("America/Sao_Paulo")


# ---------------- conector sozinho ----------------
def test_handlers_contract_offset_candles_and_limits():
    fake = FakeMT5()
    h = oc.Handlers(fake, oc.Limits(["WIN", "WDO"], 3))
    assert h.offset() == -10800  # servidor em Brasília, medido pela cotação

    r = h.rules({"root": "WIN"})
    assert r["contract"] == "WINZ26"  # WINV26 vence amanhã: já rolou para o próximo
    assert r["tick_size"] == 5.0 and r["tick_value"] == 1.0 and r["volume_max"] == 3
    assert r["expiration"] == fake.symbols["WINZ26"].expiration_time + 10800  # devolvido em UTC real

    bars = h.candles({"root": "WIN", "timeframe": "5m", "count": 10})
    assert len(bars) == 10 and time.time() - 600 < bars[-1]["t"] <= time.time()

    with pytest.raises(oc.CommandError, match="não liberado"):
        h.open({"root": "PETR4", "side": "buy", "volume": 1, "coid": COID})
    with pytest.raises(oc.CommandError, match="acima do limite"):
        h.open({"root": "WIN", "side": "buy", "volume": 4, "coid": COID})

    d = h.open({"root": "WIN", "side": "buy", "volume": 2, "coid": COID, "sl": 130_002, "tp": None})
    assert d["contract"] == "WINZ26" and d["volume"] == 2 and d["commission"] == -0.5 and d["protection"] is True
    assert fake.positions[d["position"]].sl == 130_000  # stop arredondado para o tick de 5 pontos
    assert fake.sent[0]["type_filling"] == fake.ORDER_FILLING_RETURN  # execução de bolsa

    assert h.open({"root": "WIN", "side": "buy", "volume": 2, "coid": COID})["position"] == d["position"]  # reenvio idempotente
    assert len(fake.positions) == 1
    with pytest.raises(oc.CommandError, match="Já existe posição"):
        h.open({"root": "WIN", "side": "buy", "volume": 1, "coid": "tb" + "2" * 30})

    fake.set_price("WINZ26", 131_500)
    c = h.close({"contract": "WINZ26", "position": d["position"], "side": "sell", "volume": 2, "coid": "tb" + "3" * 30})
    assert c["profit"] == 200.0  # 500 pontos × R$ 0,20 × 2 contratos
    assert h.position_status({"position": d["position"]})["closing"]["profit"] == 200.0

    # Posição aberta à mão pelo cliente: o conector não fecha
    manual = fake.order_send({"action": 1, "symbol": "WDOX26", "volume": 1.0, "type": 0, "magic": 0, "comment": "manual"})
    with pytest.raises(oc.CommandError, match="não foi aberta pelo OráculoInvest"):
        h.close({"contract": "WDOX26", "position": manual.order, "side": "sell", "volume": 1, "coid": "tb" + "4" * 30})


# ---------------- ponte HTTP do conector para a API (em processo) ----------------
class _Resp:
    def __init__(self, r: httpx.Response):
        self.status_code, self.text, self._r = r.status_code, r.text, r

    def json(self):
        return self._r.json()


class BridgeSession:
    """Sessão no estilo `requests` que o conector usa, chamando a API ASGI no loop de eventos do teste."""

    def __init__(self, loop: asyncio.AbstractEventLoop, client: httpx.AsyncClient):
        self.loop, self.client, self.headers = loop, client, {}

    def _run(self, coro):
        return _Resp(asyncio.run_coroutine_threadsafe(coro, self.loop).result(timeout=60))

    def get(self, url, params=None, timeout=None):
        return self._run(self.client.get(url, params=params, headers=self.headers))

    def post(self, url, json=None, timeout=None):
        return self._run(self.client.post(url, json=json, headers=self.headers))


async def _subscribe(db, plans, client) -> uuid.UUID:
    me = (await client.get("/api/v1/me")).json()
    uid = uuid.UUID(me["id"])
    db.add(Subscription(user_id=uid, plan_id=plans["pro"].id, status=SubStatus.active))
    await db.commit()
    return uid


class Agent:
    def __init__(self, token: str, fake: FakeMT5):
        self.fake = fake
        self.http = httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test")
        self.api = oc.Api("http://test", token, session=BridgeSession(asyncio.get_running_loop(), self.http))
        self.stop = threading.Event()
        cfg = oc.Config("http://test", token, None, None, oc.Limits(["WIN", "WDO"], 5))
        self.thread = threading.Thread(target=oc.run, args=(cfg, fake, self.api), kwargs={"stop": self.stop.is_set, "poll_wait": 1}, daemon=True)

    async def __aenter__(self):
        self.thread.start()
        return self

    async def __aexit__(self, *exc):
        self.stop.set()
        while self.thread.is_alive():
            await asyncio.sleep(0.05)
        await self.http.aclose()


async def _wait_online(client, n=0) -> dict:
    for _ in range(200):
        st = (await client.get("/api/v1/mt5/status")).json()
        if st[n]["online"]:
            return st[n]
        await asyncio.sleep(0.05)
    raise AssertionError("conector não ficou online")


def _next_weekday(hour: int, minute: int) -> datetime:
    d = datetime.now(BRT) + timedelta(days=1)
    while d.weekday() >= 5:
        d += timedelta(days=1)
    return d.replace(hour=hour, minute=minute, second=0, microsecond=0).astimezone(UTC)


async def test_connector_auth_and_demo_real_guard(client, db, plans):
    await register(client)
    await _subscribe(db, plans, client)
    r = await client.post("/api/v1/mt5/connections", json={"label": "XP demo", "venue": "testnet"}, headers=csrf(client))
    assert r.status_code == 201, r.text
    token = r.json()["token"]
    assert token.startswith("oimt5_") and r.json()["credential"]["verified_at"] is None

    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as agent:
        bad = await agent.get("/api/v1/mt5/agent/poll", headers={"Authorization": "Bearer oimt5_x_y"})
        assert bad.status_code == 401
        hello = oc.hello_payload(FakeMT5(trade_mode=2), oc.Limits())  # MT5 numa conta REAL
        r = await agent.post("/api/v1/mt5/agent/hello", json=hello, headers={"Authorization": f"Bearer {token}"})
        assert r.status_code == 409 and "CONTA DEMO" in r.json()["detail"] and "conta REAL" in r.json()["detail"]
        r = await agent.get("/api/v1/mt5/agent/poll", params={"wait": 0}, headers={"Authorization": f"Bearer {token}"})
        assert r.status_code == 428  # sem hello aceito, nada é entregue

        # Token novo invalida o anterior
        cred_id = (await client.get("/api/v1/credentials")).json()[0]["id"]
        new = await client.post(f"/api/v1/mt5/connections/{cred_id}/token", headers=csrf(client))
        assert new.status_code == 200 and new.json()["token"] != token
        r = await agent.get("/api/v1/mt5/agent/poll", headers={"Authorization": f"Bearer {token}"})
        assert r.status_code == 401


async def test_b3_bot_end_to_end(client, db, plans, monkeypatch):
    # Pregão "aberto" o tempo todo neste teste (o horário real é testado abaixo)
    monkeypatch.setattr(b3, "schedule", lambda root: ((0, 7 * 86400),))
    await register(client)
    await _subscribe(db, plans, client)
    r = await client.post("/api/v1/mt5/connections", json={"label": "Clear demo", "venue": "testnet"}, headers=csrf(client))
    token, cred_id = r.json()["token"], r.json()["credential"]["id"]
    assert (await client.get("/api/v1/mt5/status")).json()[0]["online"] is False

    fake = FakeMT5()
    async with Agent(token, fake):
        st = await _wait_online(client)
        assert st["account"]["login"] == 5550123 and st["limits"]["roots"] == ["WIN", "WDO"]
        cred = await db.get(ExchangeCredential, uuid.UUID(cred_id))
        await db.refresh(cred)
        assert cred.verified_at and cred.can_trade and cred.external_account_id == "5550123"

        body = {"name": "WIN demo", "market": "b3", "symbol": "WIN", "strategy": "ema_cross_day", "exec_mode": "auto",
                "venue": "testnet", "credential_id": cred_id, "order_lots": "2", "allow_short": True}
        assert (await client.post("/api/v1/bots", json={**body, "order_lots": "1.5"}, headers=csrf(client))).status_code == 422
        assert (await client.post("/api/v1/bots", json={**body, "symbol": "PETR4"}, headers=csrf(client))).status_code == 422
        r = await client.post("/api/v1/bots", json=body, headers=csrf(client))
        assert r.status_code == 201, r.text
        bot = await db.get(Bot, uuid.UUID(r.json()["id"]))

        broker = await broker_for_bot(db, bot)
        rules = await broker.get_rules("WIN")
        assert rules.contract == "WINZ26" and rules.lot_size == Decimal("0.2")

        # Abre vendido 2 contratos e fecha com 500 pontos a favor
        o1 = await executor.execute(db, bot, broker, Side.sell, "teste: venda")
        pos = await executor.get_position(db, bot.id)
        assert o1.status.value == "FILLED" and pos.side == PosSide.short and pos.qty == Decimal("0.4")
        assert pos.external_id.startswith("WINZ26:") and pos.entry_fee == Decimal("0.5")
        fake.set_price("WINZ26", 130_500)
        o2 = await executor.execute(db, bot, broker, Side.buy, "teste: zerar")
        # 500 pts × R$0,20 × 2 = 200; menos corretagem de entrada e saída (0,50 + 0,50)
        assert o2.realized_pnl == Decimal("199.0")
        assert await executor.get_position(db, bot.id) is None

        # Stop executado pela corretora: o motor registra sozinho
        await executor.execute(db, bot, broker, Side.buy, "teste: compra")
        pos = await executor.get_position(db, bot.id)
        ticket = int(pos.external_id.split(":")[1])
        fake.broker_close(ticket, 130_000)
        closed = await executor.sync_broker_closes(db, bot, broker)
        assert closed and closed.realized_pnl == Decimal("-201")  # comprou a 130.500, stop a 130.000: −500 pts × 0,2 × 2 − 1,00
        assert "corretora" in closed.reason

    # Conector fechado (sem sinal): erro claro e temporário, o robô tenta de novo no próximo ciclo
    await get_redis().delete(mt5_bridge._seen(cred_id))
    with pytest.raises(BrokerError, match="desconectado") as err:
        await broker.get_price("WIN")
    assert err.value.retryable


async def test_runner_b3_session_end_and_roll(client, db, plans):
    await register(client)
    uid = await _subscribe(db, plans, client)
    r = await client.post("/api/v1/mt5/connections", json={"label": "demo", "venue": "testnet"}, headers=csrf(client))
    token, cred_id = r.json()["token"], uuid.UUID(r.json()["credential"]["id"])
    fake = FakeMT5()
    async with Agent(token, fake):
        await _wait_online(client)

        def mk(strategy: str) -> Bot:
            return Bot(user_id=uid, name=strategy, market=Market.b3, symbol="WIN", strategy=strategy, exec_mode=ExecMode.auto,
                       venue=Venue.paper, credential_id=cred_id, order_lots=Decimal("1"), status=BotStatus.running, paper_quote_balance=Decimal("10000"))

        day, swing = mk("ema_cross_day"), mk("ema_cross_swing")
        db.add_all([day, swing])
        await db.flush()
        db.add(Position(bot_id=day.id, side=PosSide.long, qty=Decimal("0.2"), avg_price=Decimal("131000")))
        db.add(Position(bot_id=swing.id, side=PosSide.long, qty=Decimal("0.2"), avg_price=Decimal("130500"), external_id="WINV26:0"))
        await db.commit()

        # 18h12 de um dia útil: day trade é zerado antes do fim do pregão
        res = await run_tick(db, day, now=_next_weekday(18, 12))
        assert res.action == "executed" and "fim do pregão" in res.detail
        assert await executor.get_position(db, day.id) is None
        # ... e não abre posição nova tão perto do fechamento
        res = await run_tick(db, day, now=_next_weekday(18, 12))
        assert res.action == "hold" and "horário de entrada" in res.detail

        # Swing comprado no contrato que está vencendo: rola (encerra para reabrir no WINZ26)
        res = await run_tick(db, swing, now=_next_weekday(11, 0))
        assert res.action == "executed" and "Rolagem: WINV26" in res.detail and "WINZ26" in res.detail
        last = (await db.scalars(select(Order).where(Order.bot_id == swing.id).order_by(Order.created_at.desc()))).first()
        assert last.realized_pnl is not None
