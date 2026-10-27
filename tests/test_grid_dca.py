"""Grid à vista e Compra programada (DCA): lógica, robô ao vivo na simulação, backtest e API."""
import math
from datetime import UTC, datetime, timedelta
from decimal import Decimal

from sqlalchemy import func, select

from app.engine.backtest import BacktestConfig, run_backtest
from app.engine.runner import run_risk_tick, run_tick
from app.engine.scheduler import Scheduler
from app.models import Bot, BotStatus, ExecMode, Order, OrderStatus, Position, Venue
from app.services.brokers.base import Candle
from app.strategies import ladder as L
from app.strategies.library import STRATEGIES
from tests.test_api import csrf, register
from tests.test_engine import factory_for, make_user_with_plan

GRID = STRATEGIES["grade_spot"]
DCA = STRATEGIES["dca_spot"]
NOW = datetime(2026, 10, 27, 12, 0, tzinfo=UTC)


# ------------------------------------------------------------------ lógica pura
def test_grid_levels_and_initial_lots():
    p = GRID.parse_params({"lower_pct": 10, "upper_pct": 10, "grids": 20})
    st = L.grid_new_state(p, 100.0)
    lv = st["levels"]
    assert len(lv) == 21 and math.isclose(lv[0], 90) and math.isclose(lv[-1], 110)
    lo, hi = L.grid_step_pct(lv)
    assert math.isclose(lo, hi) and 1.0 < lo < 1.02  # geométrica: degraus iguais em %
    assert st["initial"] == [i for i in range(20) if lv[i] >= 100]  # lotes só nas grades inteiras acima do preço
    assert all(lv[i] < 100 for i in st["armed"])

    a = L.grid_levels(90, 110, 4, "arithmetic")
    assert [round(x, 6) for x in a] == [90, 95, 100, 105, 110]


def test_grid_buys_only_when_price_comes_down_to_an_armed_level():
    p = GRID.parse_params({"grids": 10, "initial_buy": False})
    st = L.grid_new_state(p, 100.0)
    sells, buys = L.grid_triggers(st, 100.0)
    assert sells == [] and buys == []
    # Sem compra inicial, as grades acima do preço não compram ao subir de volta: só depois que o preço passar acima delas.
    _, buys = L.grid_triggers(st, 98.9)
    assert buys and all(st["levels"][i] >= 98.9 for i in buys) and all(st["levels"][i] < 100 for i in buys)
    st["lots"] = {str(i): {"qty": "1", "cost": "1", "fee": "0"} for i in buys}
    sells, _ = L.grid_triggers(st, 100.5)
    assert sells == [i for i in buys if st["levels"][i + 1] <= 100.5]


def test_manual_range_validation():
    try:
        GRID.parse_params({"range_mode": "manual", "lower_price": 120, "upper_price": 100})
    except ValueError as exc:
        assert "piso" in str(exc)
    else:
        raise AssertionError("faixa invertida deveria ser recusada")


def test_dca_ladder_of_buys_take_and_restart():
    p = DCA.parse_params({"deviation_pct": 2, "step_mult": 1.5, "max_orders": 4, "volume_mult": 2, "take_profit_pct": 3})
    assert [round(L.dca_drop_pct(p, k), 3) for k in (1, 2, 3)] == [2, 5, 9.5]
    assert L.dca_capital(p, 10) == 10 + 20 + 40 + 80
    st = L.dca_new_state()
    assert L.dca_action(p, st, 100, 0)[0] == "buy"
    st = L.dca_after_buy(st, 1.0, 100.0, 0.1, 100.0, 0)
    assert L.dca_action(p, st, 98.5, 1) is None
    act = L.dca_action(p, st, 97.9, 2)
    assert act[0] == "buy" and math.isclose(act[2], 98)
    st = L.dca_after_buy(st, 2.0, 196.0, 0.2, 98.0, 2)
    lv = L.dca_levels(p, st)
    assert math.isclose(lv["avg"], 296 / 3) and math.isclose(lv["take"], 296 / 3 * 1.03)
    act = L.dca_action(p, st, lv["take"] + 0.01, 3)
    assert act[0] == "sell" and "Alvo" in act[1]
    st = L.dca_after_sell(p, st, 8.0, 3)
    assert st["orders"] == 0 and st["rounds"] == 1 and st["profit"] == 8.0 and not st["done"]


# ------------------------------------------------------------------ backtest
def _candles(prices: list[float], step: int = 300_000) -> list[Candle]:
    out, t = [], 1_700_000_000_000
    for i in range(1, len(prices)):
        o, c = prices[i - 1], prices[i]
        out.append(Candle(t, o, max(o, c) * 1.001, min(o, c) * 0.999, c, 1.0, t + step - 1))
        t += step
    return out


def test_grid_backtest_profits_sideways_and_suffers_in_a_crash():
    side = _candles([100 * (1 + 0.06 * math.sin(i / 40)) for i in range(3000)])
    crash = _candles([100 * (1 - 0.3 * i / 3000) for i in range(3000)])
    cfg = BacktestConfig(initial_balance=3000, order_size_quote=100)
    p = GRID.parse_params({})
    r = run_backtest(GRID, p, side, cfg)
    assert r.ladder["kind"] == "grid" and r.ladder["rounds"] > 50
    assert r.metrics.return_pct > 0 and r.metrics.win_rate_pct > 90
    r2 = run_backtest(GRID, p, crash, cfg)
    assert r2.metrics.return_pct < -10 and r2.ladder["below_range_pct"] > 25
    assert any("abaixo da faixa" in w for w in r2.warnings)
    # Stop abaixo do piso limita a perda e para o robô
    r3 = run_backtest(GRID, GRID.parse_params({"stop_below_pct": 2}), crash, cfg)
    assert r3.ladder["stopped_at"] is not None and r3.metrics.return_pct > r2.metrics.return_pct


def test_dca_backtest_cycles_and_insufficient_balance_warning():
    side = _candles([100 * (1 + 0.08 * math.sin(i / 30)) for i in range(3000)])
    p = DCA.parse_params({"max_orders": 5, "volume_mult": 2})
    r = run_backtest(DCA, p, side, BacktestConfig(initial_balance=300, order_size_quote=50))
    assert r.ladder["cycles"] >= 2 and r.ladder["skipped_buys"] > 0
    assert r.ladder["capital"] == 50 * (1 + 2 + 4 + 8 + 16)
    assert any("menor que o dinheiro necessário" in w for w in r.warnings)


# ------------------------------------------------------------------ robô ao vivo (simulação)
class Market:
    def __init__(self, price: float):
        self.price = Decimal(str(price))

    async def get_price(self, symbol):
        return self.price

    async def get_klines(self, symbol, interval, limit=200):
        return []

    async def get_rules(self, symbol):
        from tests.conftest import RULES

        return RULES

    async def close(self):
        pass


async def _ladder_bot(db, user, strategy: str, params: dict, size="50", balance="2000") -> Bot:
    bot = Bot(user_id=user.id, name="Lotes", symbol="BTCUSDT", strategy=strategy, params=params, exec_mode=ExecMode.auto,
              venue=Venue.paper, status=BotStatus.running, order_size_quote=Decimal(size), max_trades_per_day=10,
              paper_quote_balance=Decimal(balance), paper_base_balance=Decimal("0"), state={})
    db.add(bot)
    await db.commit()
    return bot


async def test_live_grid_initial_buy_then_sell_and_rebuy(db, plans):
    user = await make_user_with_plan(db, plans["pro"])
    bot = await _ladder_bot(db, user, "grade_spot", {"grids": 10, "lower_pct": 5, "upper_pct": 5})
    m = Market(100)
    f = factory_for(m)

    r = await run_tick(db, bot, f, NOW)
    assert r.action == "executed" and "Grade montada" in r.detail
    st = bot.state
    n = len(st["initial"])
    assert st["started"] and n >= 4 and len(st["lots"]) == n
    pos = await db.scalar(select(Position).where(Position.bot_id == bot.id))
    assert pos is not None and pos.cost_basis == Decimal(50 * n)
    assert bot.paper_quote_balance == Decimal(2000 - 50 * n)

    # Sobe um degrau: vende o lote da primeira grade comprada
    lv = st["levels"]
    h = min(st["initial"])
    m.price = Decimal(str(lv[h + 1] * 1.0005))
    r = await run_risk_tick(db, bot, f, m.price, NOW + timedelta(seconds=5))
    assert r.action == "executed" and "venda de 1 lote" in r.detail
    sell = await db.scalar(select(Order).where(Order.bot_id == bot.id, Order.side == "SELL"))
    assert sell.realized_pnl > 0  # resultado pelo custo DO LOTE, não pela média
    assert bot.state["rounds"] == 1 and len(bot.state["lots"]) == n - 1 and str(h) not in bot.state["lots"]

    # Volta a cair até o nível de compra daquela grade: recompra o lote
    m.price = Decimal(str(lv[h] * 0.9995))
    r = await run_risk_tick(db, bot, f, m.price, NOW + timedelta(seconds=10))
    assert r.action == "executed" and "compra" in r.detail
    assert str(h) in bot.state["lots"]


async def test_live_grid_stop_sells_everything_and_stops(db, plans):
    user = await make_user_with_plan(db, plans["pro"])
    bot = await _ladder_bot(db, user, "grade_spot", {"grids": 4, "lower_pct": 4, "upper_pct": 4, "stop_below_pct": 1})
    m = Market(100)
    f = factory_for(m)
    await run_tick(db, bot, f, NOW)
    m.price = Decimal("94")  # abaixo de 96 × 0,99
    r = await run_risk_tick(db, bot, f, m.price, NOW + timedelta(minutes=1))
    assert r.action == "executed"
    assert bot.status == BotStatus.stopped and "Stop da grade" in (bot.status_reason or "")
    assert await db.scalar(select(Position).where(Position.bot_id == bot.id)) is None
    assert bot.state["lots"] == {}


async def test_live_dca_buys_on_drop_and_sells_at_target(db, plans):
    user = await make_user_with_plan(db, plans["pro"])
    bot = await _ladder_bot(db, user, "dca_spot", {"deviation_pct": 2, "max_orders": 3, "take_profit_pct": 2, "restart": False})
    m = Market(100)
    f = factory_for(m)
    r = await run_tick(db, bot, f, NOW)
    assert r.action == "executed" and bot.state["orders"] == 1
    r = await run_tick(db, bot, f, NOW + timedelta(minutes=15))
    assert r.action == "hold" and "próxima compra em 98" in r.detail
    m.price = Decimal("97.9")
    r = await run_risk_tick(db, bot, f, m.price, NOW + timedelta(minutes=16))
    assert r.action == "executed" and bot.state["orders"] == 2
    take = L.dca_levels(DCA.parse_params(bot.params), bot.state)["take"]
    m.price = Decimal(str(take * 1.001))
    r = await run_risk_tick(db, bot, f, m.price, NOW + timedelta(minutes=30))
    assert r.action == "executed" and "Alvo" in r.detail
    assert bot.state["rounds"] == 1 and bot.state["profit"] > 0
    assert bot.status == BotStatus.stopped  # sem recomeçar: para depois do alvo
    assert await db.scalar(select(Position).where(Position.bot_id == bot.id)) is None


async def test_ladder_waits_for_unconfirmed_order(db, plans):
    user = await make_user_with_plan(db, plans["pro"])
    bot = await _ladder_bot(db, user, "dca_spot", {})
    order = Order(bot_id=bot.id, user_id=user.id, venue=Venue.paper, client_order_id="tbpending", symbol="BTCUSDT", side="BUY",
                  qty=Decimal("0"), status=OrderStatus.unknown, reason="x")
    db.add(order)
    bot.state = {"kind": "dca", "orders": 0, "pending": {"op": "dca_buy", "k": 0, "coid": "tbpending"}}
    await db.commit()
    from app.engine import ladder as engine

    broker = await factory_for(Market(100))(db, bot)
    r = await engine.tick(db, bot, broker, None, NOW)  # direto no motor da grade (sem a reconciliação da simulação)
    assert r.action == "hold" and "confirmar" in r.detail
    assert await db.scalar(select(func.count(Order.id)).where(Order.bot_id == bot.id)) == 1  # nada enviado em dobro


async def test_insufficient_balance_does_not_kill_the_bot(db, plans):
    user = await make_user_with_plan(db, plans["pro"])
    bot = await _ladder_bot(db, user, "dca_spot", {}, size="50", balance="20")
    r = await run_tick(db, bot, factory_for(Market(100)), NOW)
    assert r.action == "blocked" and "recusou" in r.detail
    assert bot.status == BotStatus.running and bot.state.get("retry_at")
    r = await run_tick(db, bot, factory_for(Market(100)), NOW + timedelta(minutes=1))
    assert r.action == "hold" and "tentar de novo" in r.detail


def test_scheduler_triggers_ladder_on_level_cross():
    calls = []
    s = Scheduler(lambda *a: calls.append(a), clock=lambda: 1000.0)
    bot = Bot(id=__import__("uuid").uuid4(), symbol="BTCUSDT", strategy="dca_spot", params={}, market="crypto", venue=Venue.paper,
              state={"kind": "dca", "orders": 1, "qty": 1.0, "cost": 100.0, "first_price": 100.0})
    s.load([bot], {})
    w = s.watches[bot.id]
    assert w.ladder and math.isclose(w.buy_at, 98.5) and math.isclose(w.sell_at, 102.0)
    w.next_risk = w.due_decision = 9e9
    s.on_price("live", "BTCUSDT", 99.0, 99.1)
    assert bot.id not in s.triggered
    s.on_price("live", "BTCUSDT", 98.4, 98.45)
    assert s.triggered[bot.id] == Decimal("98.45") and w.next_risk == 0.0


# ------------------------------------------------------------------ API
async def test_api_rules_for_ladder_bots(client, db, plans):
    pro_id = plans["pro"].id
    await register(client)
    from tests.test_admin_access import _user
    from app.models import SubStatus, Subscription

    u = await _user(db, "joao@example.com")
    db.add(Subscription(user_id=u.id, plan_id=pro_id, status=SubStatus.active))
    await db.commit()
    base = {"name": "Grade", "symbol": "BTCUSDT", "strategy": "grade_spot", "order_size_quote": "50", "params": {"grids": 10},
            "paper_quote_balance": "1000"}
    r = await client.post("/api/v1/bots", json={**base, "exec_mode": "signals"}, headers=csrf(client))
    assert r.status_code == 400 and "automático" in r.text
    r = await client.post("/api/v1/bots", json={**base, "exec_mode": "auto", "paper_quote_balance": "300"}, headers=csrf(client))
    assert r.status_code == 422 and "dinheiro necessário" in r.text  # 10 lotes × 50 = 500
    r = await client.post("/api/v1/bots", json={**base, "exec_mode": "auto", "stop_loss_pct": "2"}, headers=csrf(client))
    assert r.status_code == 201, r.text
    bot = r.json()
    assert bot["stop_loss_pct"] is None  # a grade tem o próprio stop
    strategies = (await client.get("/api/v1/strategies")).json()
    assert {s["code"]: s["kind"] for s in strategies}["grade_spot"] == "ladder"
    r = await client.get(f"/api/v1/bots/{bot['id']}/ladder")
    assert r.status_code == 200 and r.json()["kind"] == "grid" and r.json()["capital"] == 500
