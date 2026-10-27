from decimal import Decimal

import pytest

from app.models import Side
from app.services.brokers.base import Candle
from app.services.brokers.paper import PaperAccount, PaperBroker
from app.strategies.indicators import ema, rsi, sma
from app.strategies.library import STRATEGIES, get_strategy


def candles(closes):
    return [Candle(i, c, c, c, c, 1, i + 1) for i, c in enumerate(closes)]


def test_sma_ema_basic():
    assert sma([1, 2, 3, 4], 2)[-1] == 3.5
    e = ema([1.0] * 10, 3)
    assert e[-1] == pytest.approx(1.0)


def test_rsi_extremes():
    up = [float(i) for i in range(1, 40)]
    assert rsi(up, 14)[-1] == 100.0
    down = list(reversed(up))
    assert rsi(down, 14)[-1] < 1


def test_ema_cross_buy_then_sell():
    s = get_strategy("ema_cross_day")
    p = s.parse_params({"fast": 3, "slow": 8})
    falling = [100 - i for i in range(30)]
    rising = falling + [falling[-1] + 9]  # salto que cruza a rápida acima da lenta
    assert s.decide(candles(rising), "flat", p).target == "long"
    dropping = [70 + i for i in range(30)] + [60]
    assert s.decide(candles(dropping), "long", p).target == "flat"
    assert s.decide(candles(dropping), "long", p, allow_short=True).target == "short"  # inverte se puder vender
    assert s.decide(candles(dropping), "flat", p).target is None  # sem posição e sem venda a descoberto: nada


def test_params_validation():
    s = get_strategy("ema_cross_swing")
    with pytest.raises(ValueError):
        s.parse_params({"fast": 50, "slow": 20})
    with pytest.raises(ValueError):
        s.parse_params({"campo_inexistente": 1})


def test_all_strategies_have_day_and_swing():
    styles = {s.style for s in STRATEGIES.values()}
    assert styles == {"day", "swing"}


async def test_paper_broker_buy_sell(fake_market):
    market = fake_market([100.0] * 5, price=100)
    acc = PaperAccount(quote=Decimal("1000"), base=Decimal("0"))
    broker = PaperBroker(market, acc, fee_rate=0.001, slippage_bps=0)

    buy = await broker.market_buy_quote("BTCUSDT", Decimal("100"), "c1")
    assert buy.side == Side.buy
    assert acc.quote == Decimal("900")
    assert buy.net_base_qty == pytest.approx(Decimal("0.999"), rel=Decimal("0.001"))

    market.price = Decimal("110")
    sell = await broker.market_sell_qty("BTCUSDT", acc.base, "c2")
    assert sell.quote_qty > Decimal("109")
    assert acc.base < Decimal("0.00001")
    assert acc.quote > Decimal("1009")
