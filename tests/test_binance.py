import hashlib
import hmac
from decimal import Decimal
from urllib.parse import parse_qs, urlsplit

import pytest
import respx
from httpx import Response

from app.services.brokers.base import OrderUnknownError
from app.services.brokers.binance import BinanceClient

EXCHANGE_INFO = {
    "symbols": [
        {
            "symbol": "ETHUSDT",
            "status": "TRADING",
            "baseAsset": "ETH",
            "quoteAsset": "USDT",
            "quoteAssetPrecision": 8,
            "filters": [
                {"filterType": "LOT_SIZE", "minQty": "0.0001", "maxQty": "9000", "stepSize": "0.0001"},
                {"filterType": "NOTIONAL", "minNotional": "5"},
            ],
        }
    ]
}


@respx.mock
async def test_signed_market_buy_with_fee_in_base():
    base = "https://testnet.binance.vision"
    respx.get(f"{base}/api/v3/exchangeInfo").mock(return_value=Response(200, json=EXCHANGE_INFO))
    route = respx.post(url__startswith=f"{base}/api/v3/order").mock(
        return_value=Response(
            200,
            json={
                "orderId": 42,
                "clientOrderId": "tbabc",
                "status": "FILLED",
                "executedQty": "0.0500",
                "cummulativeQuoteQty": "100.00",
                "fills": [{"price": "2000", "qty": "0.05", "commission": "0.00005", "commissionAsset": "ETH"}],
            },
        )
    )
    api_secret = "s" * 64
    client = BinanceClient("testnet", "k" * 64, api_secret)
    fill = await client.market_buy_quote("ETHUSDT", Decimal("100"), "tbabc")
    await client.close()

    assert fill.avg_price == Decimal("2000")
    assert fill.net_base_qty == Decimal("0.04995")
    assert fill.fee_quote == Decimal("0.10000")

    req = route.calls.last.request
    assert req.headers["X-MBX-APIKEY"] == "k" * 64
    query = urlsplit(str(req.url)).query
    unsigned, _, sig = query.rpartition("&signature=")
    assert sig == hmac.new(api_secret.encode(), unsigned.encode(), hashlib.sha256).hexdigest()
    assert parse_qs(unsigned)["quoteOrderQty"] == ["100.00000000"]


@respx.mock
async def test_5xx_on_order_means_unknown_state():
    base = "https://testnet.binance.vision"
    respx.get(f"{base}/api/v3/exchangeInfo").mock(return_value=Response(200, json=EXCHANGE_INFO))
    respx.post(url__startswith=f"{base}/api/v3/order").mock(return_value=Response(503, text="busy"))
    client = BinanceClient("testnet", "k" * 64, "s" * 64)
    with pytest.raises(OrderUnknownError):
        await client.market_sell_qty("ETHUSDT", Decimal("0.12345"), "tbx")
    await client.close()
