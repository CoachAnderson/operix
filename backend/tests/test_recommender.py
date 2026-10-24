"""Qual estratégia usar? Testa todas as combinações, separa ajuste × confirmação, ranqueia e guarda em cache."""
import asyncio
import math
import random
import uuid
from types import SimpleNamespace

from app.api.routes import backtest as bt_route
from app.models import SubStatus, Subscription
from app.services import recommender
from app.services.brokers.base import BrokerError, Candle
from app.strategies.filters import TF_MS
from tests.test_api import csrf, register

calls = {"n": 0}


async def fake_load(symbol, tf, start_ms, end_ms, source=None):
    """Histórico FICTÍCIO determinístico: tendência de alta com ondas e ruído."""
    calls["n"] += 1
    if symbol == "XXXYYY":
        raise BrokerError("Binance 400: Invalid symbol. (-1121)")
    step = TF_MS[tf]
    rng = random.Random(hash(tf) & 0xFFFF)
    out, p, t = [], 100.0, start_ms // step * step
    i = 0
    while t <= end_ms:
        o = p
        p = max(1.0, p * (1 + 0.00002 * (step / 60_000) ** 0.5 + 0.004 * math.sin(i / 37) / 10 + rng.gauss(0, 0.002)))
        out.append(Candle(t, o, max(o, p) * 1.0005, min(o, p) * 0.9995, p, 1, t + step - 1))
        t += step
        i += 1
    return out


def test_selo_da_combinacao():
    seg = lambda label, trades, pf, net: SimpleNamespace(label=label, trades=trades, profit_factor=pf, net_pnl=net, win_rate_pct=55,  # noqa: E731
                                                         return_pct=net / 10, buy_hold_pct=1.0)
    def res(fit, conf, trades=40):
        m = SimpleNamespace(trades=trades, win_rate_pct=55, breakeven_win_rate_pct=50, profit_factor=1.2, net_pnl=10, return_pct=1,
                            buy_hold_pct=2, max_drawdown_pct=3, fees_total=1)
        return SimpleNamespace(metrics=m, segments=[seg("Ajuste", *fit), seg("Confirmação", *conf)], start=0, end=1)
    assert recommender.evaluate(res((30, 1.4, 20), (10, 1.3, 5)))["verdict"] == "approved"
    assert recommender.evaluate(res((30, 1.4, 20), (10, 0.7, -5)))["verdict"] == "only_fit"
    assert recommender.evaluate(res((30, 1.05, 2), (10, 1.3, 5)))["verdict"] == "marginal"
    assert recommender.evaluate(res((30, 0.8, -20), (10, 1.5, 5)))["verdict"] == "rejected"
    assert recommender.evaluate(res((10, 1.4, 20), (4, 1.3, 5), trades=14))["verdict"] == "few_trades"


async def test_analise_completa_e_cache():
    calls["n"] = 0
    job = await recommender.start("SOLUSDT", 30, fake_load, owner="u1")
    await asyncio.wait_for(job["_task"], 120)
    assert job["status"] == "done" and job["done"] == job["total"] == len(recommender.combos())
    rows = job["results"]
    assert len(rows) == job["total"] and {r["verdict"] for r in rows} <= set(recommender.VERDICT_RANK)
    assert rows == sorted(rows, key=recommender.sort_key)  # aprovadas primeiro, depois pela confirmação
    assert all(r["confirm"] for r in rows if r["verdict"] != "error")
    first = calls["n"]
    again = await recommender.start("SOLUSDT", 30, fake_load, owner="u2")  # outra pessoa, mesma moeda e período
    assert again["status"] == "done" and again["cached"] and calls["n"] == first  # veio do cache
    assert recommender.public(again).get("_owner") is None


async def test_moeda_invalida():
    job = await recommender.start("XXXYYY", 30, fake_load, owner="u1")
    await asyncio.wait_for(job["_task"], 30)
    assert job["status"] == "error" and "XXXYYY" in job["error"]


async def test_rotas(client, db, plans, monkeypatch):
    monkeypatch.setattr(bt_route, "load_candles", fake_load)
    await register(client)
    me = (await client.get("/api/v1/me")).json()
    db.add(Subscription(user_id=uuid.UUID(me["id"]), plan_id=plans["pro"].id, status=SubStatus.active))
    await db.commit()
    assert (await client.post("/api/v1/backtest/recommend", json={"symbol": "eth;usdt"}, headers=csrf(client))).status_code == 422
    r = await client.post("/api/v1/backtest/recommend", json={"symbol": "ETHUSDT", "days": 30}, headers=csrf(client))
    assert r.status_code == 200, r.text
    jid = r.json()["id"]
    for _ in range(600):
        st = (await client.get(f"/api/v1/backtest/recommend/{jid}")).json()
        if st["status"] != "running":
            break
        await asyncio.sleep(0.05)
    assert st["status"] == "done" and len(st["results"]) == st["total"]
    client.cookies.clear()
    await register(client, "outro@example.com")
    assert (await client.get(f"/api/v1/backtest/recommend/{jid}")).status_code == 404  # análise de outra pessoa
