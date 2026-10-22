"""Reversão AMS dentro do sistema: decisão, backtest de 1 candle, robô ao vivo e conferência com o backtester avulso."""
import importlib.util
import random
import sys
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path

import pytest
from sqlalchemy import select

from app.engine.backtest import BacktestConfig, binom_p_two_sided, run_backtest
from app.engine.runner import run_tick, trade_finished
from app.models import Bot, BotStatus, ExecMode, Order, Position, Signal, Venue
from app.services.brokers.base import Candle
from app.services.brokers.paper import PaperAccount, PaperBroker
from app.strategies.library import get_strategy
from tests.test_engine import make_user_with_plan

AMS = get_strategy("reversao_ams")
P = AMS.parse_params({"timeframe": "1m"})
STEP = 60_000
UP, DOWN, DOJI = (10.0, 11.0), (11.0, 10.0), (10.0, 10.0)


def mk(pares, start_ms=0, gaps=()):
    out, t = [], start_ms
    for k, (o, c) in enumerate(pares):
        if k in gaps:
            t += STEP
        out.append(Candle(t, o, max(o, c) + 0.5, min(o, c) - 0.5, c, 1.0, t + STEP - 1))
        t += STEP
    return out


# ---------------------------------------------------------------- decisão
def test_decide_regras():
    d = AMS.decide(mk([UP, DOWN, UP, DOWN, UP]), "flat", P, allow_short=True)
    assert d.target == "short" and d.tag == "3x2" and "A B A B A" in d.reason
    d = AMS.decide(mk([DOWN] * 5), "flat", P, allow_short=True)
    assert d.target == "long" and d.tag == "5x0"
    d = AMS.decide(mk([UP, UP, DOWN, DOWN, DOJI]), "flat", P, allow_short=True)
    assert d.target == "flat"  # 2 x 2 + doji: sem sinal
    d = AMS.decide(mk([UP, DOJI, UP, DOWN, UP]), "flat", P, allow_short=True)
    assert d.target == "short" and d.tag == "3x2"  # doji não conta


def test_decide_sem_venda_a_descoberto_e_lacuna():
    d = AMS.decide(mk([UP] * 4 + [DOWN]), "flat", P, allow_short=False)
    assert d.target == "flat" and "não opera vendido" in d.reason
    d = AMS.decide(mk([DOWN] * 5, gaps=(3,)), "flat", P, allow_short=True)
    assert d.target == "flat" and "Falta candle" in d.reason
    p4 = AMS.parse_params({"timeframe": "1m", "min_majority": 4})
    assert AMS.decide(mk([DOWN, DOWN, DOWN, UP, UP]), "flat", p4, True).target == "flat"
    assert AMS.decide(mk([DOWN, DOWN, DOWN, DOWN, UP]), "flat", p4, True).target == "long"
    with pytest.raises(ValueError):
        AMS.parse_params({"timeframe": "5m"})


# ---------------------------------------------------------------- backtest
def cfg(**kw):
    base = dict(initial_balance=100_000, order_units=1.0, allow_short=True, fee_rate=0.0, slippage_bps=0.0,
                max_trades_per_day=3000, timeframe="1m", family="reversion")
    return BacktestConfig(**{**base, **kw})


def test_backtest_uma_operacao_por_candle():
    pares = [DOWN] * 6 + [(20.0, 21.0), (21.0, 20.5), (20.5, 20.5), (20.5, 22.0)]
    r = run_backtest(AMS, P, mk(pares), cfg())
    # decisões nos fechamentos dos candles de índice 5..8 -> entradas nos candles 6..9
    assert [t.tag for t in r.trades] == ["5x0", "4x1", "4x1", "3x2"]
    for t, (o, c) in zip(r.trades, pares[6:10]):
        assert t.side == "long" and t.entry_price == o and t.exit_price == c  # entra na abertura, sai no fechamento
        assert t.exit_time - t.entry_time == STEP - 1
        assert t.exit_reason.startswith("Fim da operação")
    assert [round(t.move_pct, 6) for t in r.trades] == [5.0, round(-0.5 / 21 * 100, 6), 0.0, round(1.5 / 20.5 * 100, 6)]
    a = r.analysis
    assert (a["wins"], a["losses"], a["ties"]) == (2, 1, 1)
    assert [x["tag"] for x in a["by_tag"]] == ["3x2", "4x1", "5x0"]


def test_backtest_lacuna_antes_da_entrada():
    pares = [DOWN] * 6 + [(20.0, 21.0)] + [DOWN] * 3
    r = run_backtest(AMS, P, mk(pares, gaps=(6,)), cfg())  # falta um minuto antes do candle de índice 6
    assert r.trades == []


def test_binomial_exato():
    assert binom_p_two_sided(60, 100) == pytest.approx(0.05689, abs=1e-4)
    assert binom_p_two_sided(50, 100) == 1.0
    assert binom_p_two_sided(5000, 9000) < 1e-20


def _ferramenta():
    caminho = Path(__file__).resolve().parents[2] / "ferramentas" / "reversao_ams" / "reversao_ams.py"
    spec = importlib.util.spec_from_file_location("reversao_ams_tool", caminho)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = mod  # dataclasses do módulo precisam dele registrado
    spec.loader.exec_module(mod)
    return mod


def test_bate_com_o_backtester_avulso():
    """Mesmos candles: o sistema e o backtester avulso contam os mesmos WIN, LOSS e empates."""
    pd = pytest.importorskip("pandas")
    tool = _ferramenta()
    rng = random.Random(5)
    price, pares = 100.0, []
    for _ in range(3000):
        o = price
        c = round(o + rng.choice([-0.2, -0.1, 0.0, 0.1, 0.2]), 1)
        pares.append((o, c))
        price = c
    candles = mk(pares, start_ms=int(datetime(2026, 3, 2, tzinfo=UTC).timestamp() * 1000))
    r = run_backtest(AMS, P, candles, cfg())

    df = pd.DataFrame({"ts": pd.to_datetime([c.open_time for c in candles], unit="ms", utc=True),
                       "open": [c.open for c in candles], "high": [c.high for c in candles],
                       "low": [c.low for c in candles], "close": [c.close for c in candles], "volume": 1.0})
    tcfg = tool.Config(fuso_relatorio="UTC")
    ops, _ = tool.gerar_operacoes(tool.preparar(df, tcfg), tcfg, "reversao")
    primeiro = pd.Timestamp(r.trades[0].entry_time, unit="ms", tz="UTC")
    ops = ops[ops["data_hora"] >= primeiro]
    assert len(ops) == len(r.trades)
    assert (ops["resultado"] == "WIN").sum() == r.analysis["wins"]
    assert (ops["resultado"] == "LOSS").sum() == r.analysis["losses"]
    assert (ops["resultado"] == "EMPATE").sum() == r.analysis["ties"]
    assert list(ops["sinal"].map({"CALL": "long", "PUT": "short"})) == [t.side for t in r.trades]


# ---------------------------------------------------------------- robô ao vivo
T0 = datetime(2026, 10, 12, 12, 0, tzinfo=UTC)  # fechamento do 5º candle = abertura do 6º


class AmsMarket:
    """Candles de 1 minuto que terminam no minuto de `now`: todos fechados, menos o último (em formação)."""

    def __init__(self, pares):
        self.pares = pares
        self.price = Decimal("0")

    def at(self, now: datetime, pares):
        self.pares = pares
        self.now = now
        self.price = Decimal(str(pares[-1][0]))
        return self

    async def get_klines(self, symbol, interval, limit=200):
        base = int(self.now.timestamp() * 1000) // STEP * STEP - (len(self.pares) - 1) * STEP
        return mk(self.pares, start_ms=base)

    async def get_price(self, symbol):
        return self.price

    async def get_rules(self, symbol):
        from tests.conftest import RULES
        return RULES

    async def close(self):
        pass


def factory_for(market):
    async def factory(db, bot):
        return PaperBroker(market, PaperAccount(bot.paper_quote_balance, bot.paper_base_balance), fee_rate=0.001, slippage_bps=0)
    return factory


async def make_ams_bot(db, user, mode=ExecMode.auto) -> Bot:
    bot = Bot(user_id=user.id, name="AMS", symbol="BTCUSDT", strategy="reversao_ams", params={"timeframe": "1m"},
              exec_mode=mode, venue=Venue.paper, status=BotStatus.running, order_size_quote=Decimal("100"),
              max_trades_per_day=120, paper_quote_balance=Decimal("1000"), paper_base_balance=Decimal("0"))
    db.add(bot)
    await db.commit()
    return bot


async def test_robo_ao_vivo_opera_um_candle(db, plans):
    user = await make_user_with_plan(db, plans["pro"])
    bot = await make_ams_bot(db, user)
    m = AmsMarket([])
    forming = (10.0, 10.0)

    # 1) 5 candles de baixa fechados; 1,2 s depois da abertura do 6º: compra
    now = T0 + timedelta(seconds=1.2)
    res = await run_tick(db, bot, factory_for(m.at(now, [DOWN] * 5 + [forming])), now)
    assert res.action == "executed" and "5x0" in res.detail, res
    pos = await db.scalar(select(Position).where(Position.bot_id == bot.id))
    pos.opened_at = now
    await db.commit()

    # 2) fechou o 6º; os 5 últimos (2º..6º) ainda pedem compra: fecha a operação e abre outra
    now2 = T0 + timedelta(seconds=61.2)
    res = await run_tick(db, bot, factory_for(m.at(now2, [DOWN] * 5 + [(10.0, 10.5), forming])), now2)
    assert res.action == "executed" and "Fim da operação" in res.detail and "4x1" in res.detail, res
    orders = (await db.scalars(select(Order).where(Order.bot_id == bot.id).order_by(Order.created_at))).all()
    assert [o.side.value for o in orders] == ["BUY", "SELL", "BUY"]
    pos = await db.scalar(select(Position).where(Position.bot_id == bot.id))
    assert pos is not None
    pos.opened_at = now2
    await db.commit()

    # 3) fechou o 7º; agora 3 de alta pedem venda, mas cripto à vista não vende a descoberto: só fecha
    now3 = T0 + timedelta(seconds=121.2)
    res = await run_tick(db, bot, factory_for(m.at(now3, [DOWN] * 4 + [UP, UP, UP, forming])), now3)
    assert res.action == "executed" and "Fim da operação" in res.detail, res
    assert await db.scalar(select(Position).where(Position.bot_id == bot.id)) is None


async def test_entrada_atrasada_e_descartada(db, plans):
    user = await make_user_with_plan(db, plans["pro"])
    bot = await make_ams_bot(db, user)
    now = T0 + timedelta(seconds=35)
    res = await run_tick(db, bot, factory_for(AmsMarket([]).at(now, [DOWN] * 5 + [(10.0, 10.0)])), now)
    assert res.action == "hold" and "Entrada descartada" in res.detail
    assert (await db.scalars(select(Order))).all() == []


async def test_sinal_vale_so_ate_o_fim_do_candle(db, plans):
    user = await make_user_with_plan(db, plans["sinais"])
    bot = await make_ams_bot(db, user, ExecMode.signals)
    now = T0 + timedelta(seconds=1.5)
    res = await run_tick(db, bot, factory_for(AmsMarket([]).at(now, [DOWN] * 5 + [(10.0, 10.0)])), now)
    assert res.action == "signal"
    sig = await db.scalar(select(Signal))
    exp = sig.expires_at if sig.expires_at.tzinfo else sig.expires_at.replace(tzinfo=UTC)
    assert exp == T0 + timedelta(minutes=1)


def test_trade_finished():
    opened = T0 + timedelta(seconds=1.4)
    t0_ms = int(T0.timestamp() * 1000)
    assert not trade_finished(opened, t0_ms - STEP, "1m", 1)  # último fechado ainda é o anterior à entrada
    assert trade_finished(opened, t0_ms, "1m", 1)  # o candle da entrada fechou
