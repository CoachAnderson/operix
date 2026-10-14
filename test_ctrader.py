"""cTrader: conversões, e um servidor WebSocket local que imita o protocolo JSON do Open API."""
import asyncio
import json
from datetime import UTC, datetime
from decimal import Decimal

import pytest
import websockets

from app.models import PosSide, Side
from app.services.brokers.ctrader import (
    PT,
    CTraderBroker,
    CTraderConnection,
    CTraderError,
    close_detail_pnl,
    symbol_to_rules,
    trendbar_to_candle,
)

EURUSD = {
    "symbolId": 1,
    "digits": 5,
    "pipPosition": 4,
    "enableShortSelling": True,
    "minVolume": "100000",  # 1.000 unidades
    "maxVolume": "10000000000",
    "stepVolume": "100000",
    "lotSize": "10000000",  # 100.000 unidades
    "scheduleTimeZone": "UTC",
    # segunda 00:00 a sexta 22:00 (segundos desde domingo 00:00)
    "schedule": [{"startSecond": 86400, "endSecond": 5 * 86400 + 22 * 3600}],
}


def test_trendbar_conversion():
    c = trendbar_to_candle({"low": 108000, "deltaOpen": 50, "deltaHigh": 120, "deltaClose": 80, "utcTimestampInMinutes": 29_000_000, "volume": 12}, "5m")
    assert c.low == pytest.approx(1.08)
    assert c.open == pytest.approx(1.0805) and c.high == pytest.approx(1.0812) and c.close == pytest.approx(1.0808)
    assert c.open_time == 29_000_000 * 60_000 and c.close_time == c.open_time + 300_000 - 1


def test_symbol_rules_and_market_hours():
    r = symbol_to_rules("EURUSD", EURUSD)
    assert r.lot_size == Decimal("100000") and r.min_qty == Decimal("1000") and r.step_size == Decimal("1000")
    assert r.is_open(datetime(2026, 10, 14, 12, 0, tzinfo=UTC))  # quarta
    assert not r.is_open(datetime(2026, 10, 17, 12, 0, tzinfo=UTC))  # sábado
    assert not r.is_open(datetime(2026, 10, 16, 23, 0, tzinfo=UTC))  # sexta após 22h


def test_close_detail_pnl_signs():
    deal = {"closePositionDetail": {"grossProfit": "1250", "swap": "-30", "commission": "-120", "pnlConversionFee": "0", "moneyDigits": 2}}
    assert close_detail_pnl(deal) == Decimal("11.00")  # 12,50 - 0,30 - 1,20


class FakeCTrader:
    """Servidor mínimo: autenticação, símbolos, ordem a mercado, fechamento, reconciliação."""

    def __init__(self):
        self.positions: dict[int, dict] = {}
        self.next_id = 500
        self.received: list[dict] = []

    async def handler(self, ws):
        async for raw in ws:
            m = json.loads(raw)
            self.received.append(m)
            pt, p, mid = m["payloadType"], m.get("payload", {}), m.get("clientMsgId")

            async def reply(t, payload, with_id=True):
                await ws.send(json.dumps({"payloadType": t, "payload": payload, **({"clientMsgId": mid} if with_id else {})}))

            acc = p.get("ctidTraderAccountId")
            if pt == PT.HEARTBEAT:
                continue
            if pt == PT.APP_AUTH_REQ:
                await reply(PT.APP_AUTH_RES, {})
            elif pt == PT.ACCOUNT_AUTH_REQ:
                if p["accessToken"] != "tok-ok":
                    await reply(PT.OA_ERROR_RES, {"errorCode": "CH_ACCESS_TOKEN_INVALID", "description": "token inválido"})
                else:
                    await reply(PT.ACCOUNT_AUTH_RES, {"ctidTraderAccountId": acc})
            elif pt == PT.SYMBOLS_LIST_REQ:
                await reply(PT.SYMBOLS_LIST_RES, {"ctidTraderAccountId": acc, "symbol": [{"symbolId": 1, "symbolName": "EURUSD"}]})
            elif pt == PT.SYMBOL_BY_ID_REQ:
                await reply(PT.SYMBOL_BY_ID_RES, {"ctidTraderAccountId": acc, "symbol": [EURUSD]})
            elif pt == PT.GET_TRENDBARS_REQ:
                bars = [{"low": 108000 + i, "deltaOpen": 1, "deltaHigh": 3, "deltaClose": 2, "utcTimestampInMinutes": 29_000_000 + i, "volume": 1} for i in range(3)]
                await reply(PT.GET_TRENDBARS_RES, {"ctidTraderAccountId": acc, "period": p["period"], "trendbar": bars})
            elif pt == PT.NEW_ORDER_REQ:
                pid = self.next_id = self.next_id + 1
                order = {"orderId": 9, "clientOrderId": p["clientOrderId"], "tradeData": {"symbolId": 1, "volume": p["volume"], "tradeSide": p["tradeSide"], "comment": p["comment"]}}
                position = {"positionId": pid, "price": 1.08002, "tradeData": order["tradeData"]}
                self.positions[pid] = position
                await reply(PT.EXECUTION_EVENT, {"ctidTraderAccountId": acc, "executionType": 2, "order": order})  # ACCEPTED
                await asyncio.sleep(0.01)
                deal = {"orderId": 9, "positionId": pid, "volume": p["volume"], "filledVolume": p["volume"], "executionPrice": 1.08002, "commission": "-300", "moneyDigits": 2}
                await reply(PT.EXECUTION_EVENT, {"ctidTraderAccountId": acc, "executionType": 3, "order": order, "position": position, "deal": deal}, with_id=False)
            elif pt == PT.CLOSE_POSITION_REQ:
                pid = p["positionId"]
                position = self.positions.pop(pid)
                await reply(PT.EXECUTION_EVENT, {"ctidTraderAccountId": acc, "executionType": 2, "position": position})
                deal = {"orderId": 10, "positionId": pid, "volume": p["volume"], "filledVolume": p["volume"], "executionPrice": 1.08502,
                        "closePositionDetail": {"entryPrice": 1.08002, "grossProfit": "5000", "swap": "-50", "commission": "-300", "moneyDigits": 2}}
                await reply(PT.EXECUTION_EVENT, {"ctidTraderAccountId": acc, "executionType": 3, "position": position, "deal": deal}, with_id=False)
            elif pt == PT.RECONCILE_REQ:
                await reply(PT.RECONCILE_RES, {"ctidTraderAccountId": acc, "position": list(self.positions.values())})
            else:
                await reply(PT.OA_ERROR_RES, {"errorCode": "UNSUPPORTED_MESSAGE"})


@pytest.fixture
async def fake_server():
    fake = FakeCTrader()
    server = await websockets.serve(fake.handler, "127.0.0.1", 0)
    port = server.sockets[0].getsockname()[1]
    yield fake, f"ws://127.0.0.1:{port}"
    server.close()
    await server.wait_closed()


async def test_full_cycle_against_fake_server(fake_server):
    fake, url = fake_server
    conn = CTraderConnection("x", "app-id", "app-secret", url=url)
    broker = CTraderBroker(conn, account_id=42, access_token="tok-ok", venue="testnet")

    rules = await broker.get_rules("EURUSD")
    assert rules.lot_size == Decimal("100000")
    candles = await broker.get_klines("EURUSD", "5m", 3)
    assert len(candles) == 3 and candles[0].open_time < candles[-1].open_time

    fill = await broker.open_position("EURUSD", PosSide.short, "tbabc", units=Decimal("10000"), sl_price=Decimal("1.0900"), tp_price=Decimal("1.0700"))
    assert fill.side == Side.sell and fill.executed_qty == Decimal("10000")
    assert fill.external_position_id == "501" and fill.fee_quote == Decimal("3.00")
    order_msg = next(m for m in fake.received if m["payloadType"] == PT.NEW_ORDER_REQ)["payload"]
    assert order_msg["volume"] == 1_000_000 and order_msg["tradeSide"] == 2
    assert order_msg["relativeStopLoss"] > 0 and order_msg["relativeTakeProfit"] > 0  # proteção enviada à corretora

    assert await broker.closed_by_broker("EURUSD", "501") is None  # ainda aberta
    close = await broker.close_position("EURUSD", PosSide.short, Decimal("10000"), "tbdef", "501")
    assert close.realized_pnl == Decimal("46.50")  # 50,00 - 0,50 swap - 3,00 comissão de saída
    await conn.close()


async def test_invalid_token_is_reported(fake_server):
    _, url = fake_server
    broker = CTraderBroker(CTraderConnection("x", "a", "b", url=url), account_id=1, access_token="vencido", venue="testnet")
    with pytest.raises(CTraderError, match="CH_ACCESS_TOKEN_INVALID"):
        await broker.get_rules("EURUSD")
    await broker.conn.close()
