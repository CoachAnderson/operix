"""Mercados: pares disponíveis agora na Binance, com status, volume e última hora; cache compartilhado."""
import json
from urllib.parse import parse_qs, urlsplit

import pytest
import respx
from httpx import Response

from app.services import market_scan
from tests.test_api import register

BASE = "https://data-api.binance.vision"
INFO = {"symbols": [
    {"symbol": "BTCUSDT", "baseAsset": "BTC", "quoteAsset": "USDT", "status": "TRADING", "orderTypes": ["LIMIT", "MARKET"], "isSpotTradingAllowed": True},
    {"symbol": "ETHUSDT", "baseAsset": "ETH", "quoteAsset": "USDT", "status": "TRADING", "orderTypes": ["LIMIT", "MARKET"], "isSpotTradingAllowed": True},
    {"symbol": "XYZUSDT", "baseAsset": "XYZ", "quoteAsset": "USDT", "status": "BREAK", "orderTypes": ["LIMIT", "MARKET"], "isSpotTradingAllowed": True},
    {"symbol": "BTCBRL", "baseAsset": "BTC", "quoteAsset": "BRL", "status": "TRADING", "orderTypes": ["LIMIT", "MARKET"], "isSpotTradingAllowed": True},
]}
T24 = [
    {"symbol": "BTCUSDT", "openPrice": "100000", "highPrice": "103000", "lowPrice": "99000", "lastPrice": "102000", "quoteVolume": "5000000000", "count": 900000},
    {"symbol": "ETHUSDT", "openPrice": "4000", "highPrice": "4100", "lowPrice": "3900", "lastPrice": "3960", "quoteVolume": "2000000000", "count": 500000},
    {"symbol": "XYZUSDT", "openPrice": "1", "highPrice": "1", "lowPrice": "1", "lastPrice": "1", "quoteVolume": "0", "count": 0},
    {"symbol": "BTCBRL", "openPrice": "550000", "highPrice": "560000", "lowPrice": "540000", "lastPrice": "555000", "quoteVolume": "90000000", "count": 30000},
]


@pytest.fixture(autouse=True)
def limpa_cache():
    market_scan.clear_cache()
    yield
    market_scan.clear_cache()


@respx.mock
async def test_pares_disponiveis_agora():
    info = respx.get(f"{BASE}/api/v3/exchangeInfo").mock(return_value=Response(200, json=INFO))
    t24 = respx.get(f"{BASE}/api/v3/ticker/24hr").mock(return_value=Response(200, json=T24))
    seen = {}

    def hour(request):
        q = parse_qs(urlsplit(str(request.url)).query)
        seen.update(q)
        syms = json.loads(q["symbols"][0])
        return Response(200, json=[{"symbol": s, "openPrice": "100", "highPrice": "102", "lowPrice": "100", "lastPrice": "101"} for s in syms])

    t1h = respx.get(f"{BASE}/api/v3/ticker").mock(side_effect=hour)
    d = await market_scan.scan("USDT")
    assert [r["symbol"] for r in d["rows"]] == ["BTCUSDT", "ETHUSDT", "XYZUSDT"]  # por volume
    btc, eth, xyz = d["rows"]
    assert btc["tradable"] and btc["change_24h_pct"] == pytest.approx(2.0) and btc["range_24h_pct"] == pytest.approx(4000 / 99000 * 100)
    assert eth["change_24h_pct"] == pytest.approx(-1.0)
    assert not xyz["tradable"] and xyz["status_label"] == "Pausado" and xyz["change_1h_pct"] is None  # pausado fica fora da última hora
    assert btc["change_1h_pct"] == pytest.approx(1.0) and btc["range_1h_pct"] == pytest.approx(2.0)
    assert seen["windowSize"] == ["1h"] and json.loads(seen["symbols"][0]) == ["BTCUSDT", "ETHUSDT"]
    assert d["quotes"][0] == {"quote": "USDT", "count": 2}

    # Segunda consulta usa o cache (nada novo na Binance)
    await market_scan.scan("USDT")
    assert info.call_count == 1 and t24.call_count == 1 and t1h.call_count == 1
    brl = await market_scan.scan("BRL")
    assert [r["symbol"] for r in brl["rows"]] == ["BTCBRL"]


@respx.mock
async def test_ultima_hora_falha_nao_derruba_a_lista():
    respx.get(f"{BASE}/api/v3/exchangeInfo").mock(return_value=Response(200, json=INFO))
    respx.get(f"{BASE}/api/v3/ticker/24hr").mock(return_value=Response(200, json=T24))
    respx.get(f"{BASE}/api/v3/ticker").mock(return_value=Response(429, json={"code": -1003}))
    d = await market_scan.scan("USDT")
    assert len(d["rows"]) == 3 and d["hour_top"] == 0 and d["rows"][0]["change_1h_pct"] is None


@respx.mock
async def test_rota_exige_login_e_valida_moeda(client):
    respx.get(f"{BASE}/api/v3/exchangeInfo").mock(return_value=Response(200, json=INFO))
    respx.get(f"{BASE}/api/v3/ticker/24hr").mock(return_value=Response(200, json=T24))
    respx.get(f"{BASE}/api/v3/ticker").mock(return_value=Response(200, json=[]))
    respx.route(host="test").pass_through()
    assert (await client.get("/api/v1/market/binance")).status_code == 401
    await register(client)
    r = await client.get("/api/v1/market/binance?quote=USDT")
    assert r.status_code == 200 and r.json()["rows"][0]["symbol"] == "BTCUSDT"
    assert (await client.get("/api/v1/market/binance?quote=usd;x")).status_code == 422
