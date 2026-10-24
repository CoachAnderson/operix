"""Painel "Por que não entrou?": diário das decisões, sinal de vida do worker e conferência das causas comuns."""
import asyncio
import uuid
from decimal import Decimal

from app.api.routes import bots as bots_route
from app.engine import journal, worker
from app.engine.scheduler import Scheduler
from app.models import SubStatus, Subscription
from app.services.brokers.paper import PaperAccount, PaperBroker
from tests.conftest import FakeMarket
from tests.test_api import csrf, register


async def test_diario_guarda_as_ultimas_decisoes():
    bid = uuid.uuid4()
    for i in range(105):
        await journal.record(bid, "decision", "hold", f"candle {i}")
    got = await journal.read(bid, 200)
    assert len(got) == 100 and got[0]["detail"] == "candle 104"  # mais recente primeiro, só as 100 últimas


async def test_sinal_de_vida_do_worker(monkeypatch):
    class FakeClient:
        def __init__(self, *a, **k):
            self._time_offset_ms = 3500

        async def sync_time(self):
            pass

        async def close(self):
            pass

    monkeypatch.setattr(worker, "BinanceClient", FakeClient)
    sch = Scheduler(worker.run_bot)
    sch.last_error = "ProgrammingError: column bots.filters does not exist"
    stop = asyncio.Event()
    task = asyncio.create_task(worker._heartbeat_loop(stop, sch, 0.0))
    await asyncio.sleep(0.1)
    stop.set()
    await asyncio.wait_for(task, 5)
    st = await journal.worker_state()
    assert st["clock_offset_ms"] == 3500 and "filters" in st["last_error"]


async def _bot(client, db, plans, **extra):
    await register(client)
    me = (await client.get("/api/v1/me")).json()
    db.add(Subscription(user_id=uuid.UUID(me["id"]), plan_id=plans["pro"].id, status=SubStatus.active))
    await db.commit()
    body = {"name": "R", "symbol": "BTCUSDT", "strategy": "ema_cross_day", "order_size_quote": "50", "stop_loss_pct": "2", **extra}
    r = await client.post("/api/v1/bots", json=body, headers=csrf(client))
    assert r.status_code == 201, r.text
    return r.json()


def _fake_broker(monkeypatch):
    async def fb(db_, b):
        return PaperBroker(FakeMarket([100.0] * 50), PaperAccount(Decimal("1000"), Decimal("0")))

    monkeypatch.setattr(bots_route, "broker_for_bot", fb)


async def test_diagnostico_aponta_worker_parado_e_modo_sinais(client, db, plans, monkeypatch):
    _fake_broker(monkeypatch)
    bot = await _bot(client, db, plans, exec_mode="signals")
    r = await client.get(f"/api/v1/bots/{bot['id']}/diagnostics")
    assert r.status_code == 200, r.text
    d = r.json()
    by = {c["title"]: c for c in d["checks"]}
    assert by["O motor de robôs (worker) não está rodando"]["level"] == "fail"
    assert by["Modo sinais: o robô não entra sozinho"]["level"] == "warn"
    assert by["Binance à vista: só entra comprado"]["level"] == "info"
    assert by["Saldo e tamanho da ordem conferidos"]["level"] == "ok"
    assert d["timeframe"] == "5m" and d["journal"] == []


async def test_diagnostico_com_worker_ok_e_diario(client, db, plans, monkeypatch):
    _fake_broker(monkeypatch)
    bot = await _bot(client, db, plans, exec_mode="auto")
    await journal.beat({"bots": 1, "last_error": None, "clock_offset_ms": 120})
    await journal.record(bot["id"], "decision", "hold", "")
    await journal.record(bot["id"], "decision", "blocked", "Limite de 10 operações no dia atingido")
    d = (await client.get(f"/api/v1/bots/{bot['id']}/diagnostics")).json()
    titles = [c["title"] for c in d["checks"]]
    assert "Motor de robôs rodando" in titles and "Modo automático" in titles
    assert not any(c["level"] == "fail" for c in d["checks"] if c["title"].startswith("Relógio"))
    assert [e["action"] for e in d["journal"]] == ["blocked", "hold"] and d["counts"] == {"blocked": 1, "hold": 1}


async def test_diagnostico_aponta_erro_de_migracao(client, db, plans, monkeypatch):
    _fake_broker(monkeypatch)
    bot = await _bot(client, db, plans, exec_mode="auto")
    await journal.beat({"bots": 0, "last_error": "ProgrammingError: column bots.filters does not exist"})
    d = (await client.get(f"/api/v1/bots/{bot['id']}/diagnostics")).json()
    fail = next(c for c in d["checks"] if c["title"] == "O motor não consegue ler os robôs do banco")
    assert "docker-compose.prod.yml" in fail["detail"]
    other = (await client.get(f"/api/v1/bots/{uuid.uuid4()}/diagnostics"))
    assert other.status_code == 404
