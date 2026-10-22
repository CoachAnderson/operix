from __future__ import annotations

import asyncio
import uuid
from collections import OrderedDict
from datetime import UTC, date, datetime, time, timedelta
from decimal import Decimal
from typing import Any

from fastapi import APIRouter, HTTPException, status
from pydantic import BaseModel, Field, ValidationError, model_validator

from app.api.deps import DB, ActivePlan, CurrentUser
from app.core.ratelimit import hit
from app.engine.backtest import BacktestConfig, filter_warmup, run_backtest
from app.models import Bot, ExchangeCredential, Market
from app.services.brokers.base import BrokerError, Candle
from app.services.brokers.binance import BinanceClient
from app.services import b3
from app.services.brokers.factory import ctrader_broker
from app.services.brokers.mt5 import MT5Broker
from app.strategies.filters import STRATEGY_FAMILY, BotFilters
from app.strategies.library import get_strategy

router = APIRouter(prefix="/backtest", tags=["backtest"])

INTERVAL_MS = {"1m": 60_000, "5m": 300_000, "15m": 900_000, "30m": 1_800_000, "1h": 3_600_000, "4h": 14_400_000, "1d": 86_400_000}
MAX_CANDLES = 30_000
MAX_CANDLES_1M = 46_080  # 32 dias de candles de 1 minuto (estratégias de 1 candle precisam de muitas operações)
MAX_CHART_CANDLES = 15_000
BINANCE_FIRST_DAY = date(2017, 8, 17)


class BacktestIn(BaseModel):
    strategy: str
    params: dict[str, Any] = Field(default_factory=dict)
    market: Market = Market.crypto
    credential_id: uuid.UUID | None = None  # forex: conta cTrader · B3: conexão MetaTrader 5 (fonte do histórico)
    order_lots: float | None = Field(None, gt=0, le=100)
    allow_short: bool = False
    symbol: str = Field(pattern=r"^[A-Z0-9]{3,20}$")
    start: date
    end: date
    initial_balance: float = Field(1000, gt=0, le=10_000_000)
    order_size_quote: float = Field(100, gt=0, le=10_000_000)
    stop_loss_pct: float | None = Field(None, gt=0, le=50)
    take_profit_pct: float | None = Field(None, gt=0, le=500)
    max_daily_loss_quote: float | None = Field(None, gt=0)
    max_trades_per_day: int | None = Field(None, ge=1, le=3000)  # vazio: 3000 em operações de 1 candle, 50 nas demais
    fee_rate: float = Field(0.001, ge=0, le=0.01)
    slippage_bps: float = Field(5, ge=0, le=200)
    filters: BotFilters = Field(default_factory=BotFilters)
    # Últimos X% do período ficam como "confirmação" (fora da amostra). 0 desliga.
    oos_pct: int = Field(30, ge=0, le=50)
    risk_pct: float | None = Field(None, gt=0, le=10)
    max_leverage: float | None = Field(None, gt=0, le=500)

    @model_validator(mode="after")
    def check_dates(self) -> BacktestIn:
        today = datetime.now(UTC).date()
        if self.end <= self.start:
            raise ValueError("A data final precisa ser depois da inicial")
        if self.start < BINANCE_FIRST_DAY and self.market == Market.crypto:
            raise ValueError("A Binance tem histórico a partir de 17/08/2017")
        if self.end > today:
            self.end = today
        if self.market == Market.forex and not (self.credential_id and self.order_lots):
            raise ValueError("Para forex informe a conta cTrader e o tamanho em lotes")
        if self.market == Market.b3:
            if not (self.credential_id and self.order_lots):
                raise ValueError("Para a B3 informe a conexão do MetaTrader 5 e o número de contratos")
            b3.info(self.symbol)
            # Custos padrão da B3, a não ser que o usuário tenha informado outros.
            f = b3.FUTURES[self.symbol.upper()]
            if "fee_rate" not in self.model_fields_set:
                self.fee_rate = f.fee_rate
            if "slippage_bps" not in self.model_fields_set:
                self.slippage_bps = f.slippage_bps
        if self.market == Market.crypto and self.allow_short:
            raise ValueError("Cripto à vista não opera vendido")
        if self.risk_pct and not (self.stop_loss_pct or self.filters.stop_atr):
            raise ValueError("O tamanho pelo risco precisa de um stop (em % ou pelo ATR)")
        return self


class BotBacktestIn(BaseModel):
    start: date
    end: date
    initial_balance: float = Field(1000, gt=0, le=10_000_000)
    oos_pct: int = Field(30, ge=0, le=50)


# Cache em memória dos últimos históricos baixados (evita rebaixar ao ajustar parâmetros).
_CACHE: OrderedDict[tuple, list[Candle]] = OrderedDict()
_CACHE_SIZE = 8


def max_candles(interval: str) -> int:
    return MAX_CANDLES_1M if interval == "1m" else MAX_CANDLES


async def load_candles(symbol: str, interval: str, start_ms: int, end_ms: int, source: Any = None) -> list[Candle]:
    """Histórico da Binance (cripto) ou da conta cTrader do cliente (forex, via `source`)."""
    key = (id(source) if source else "binance", symbol, interval, start_ms, end_ms)
    if key in _CACHE:
        _CACHE.move_to_end(key)
        return _CACHE[key]
    client = source or BinanceClient("live")
    try:
        candles = await client.get_klines_range(symbol, interval, start_ms, end_ms, max_candles(interval))
    finally:
        await client.close()
    if source is not None:
        return candles  # não guarda no cache: depende da conta
    _CACHE[key] = candles
    if len(_CACHE) > _CACHE_SIZE:
        _CACHE.popitem(last=False)
    return candles


async def execute(body: BacktestIn, db=None, user=None) -> dict:
    try:
        strategy = get_strategy(body.strategy)
        params = strategy.parse_params(body.params)
    except ValidationError as exc:
        msgs = "; ".join(f"{'.'.join(map(str, e['loc']))}: {e['msg']}" for e in exc.errors())
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, f"Parâmetros inválidos — {msgs}") from exc
    except ValueError as exc:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(exc)) from exc

    try:
        body.filters.validate_for(params.timeframe)
    except ValueError as exc:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, f"Filtros: {exc}") from exc

    step = INTERVAL_MS[params.timeframe]
    warmup = max(strategy.required_candles(params), filter_warmup(body.filters, params.timeframe)) + 2
    start_ms = int(datetime.combine(body.start, time.min, UTC).timestamp() * 1000)
    end_ms = int(datetime.combine(body.end + timedelta(days=1), time.min, UTC).timestamp() * 1000) - 1
    estimated = (end_ms - start_ms) // step + warmup
    limit = max_candles(params.timeframe)
    if estimated > limit:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            f"Período longo demais para o tempo gráfico {params.timeframe} (~{estimated:,} candles; limite {limit:,}). "
            "Encurte o período ou use um tempo gráfico maior.".replace(",", "."),
        )

    source, units, unit_step = None, None, None
    if body.market == Market.forex:
        cred = await db.get(ExchangeCredential, body.credential_id) if db else None
        if not cred or cred.user_id != user.id or cred.exchange != "ctrader":
            raise HTTPException(status.HTTP_404_NOT_FOUND, "Conta cTrader não encontrada")
        try:
            source = await ctrader_broker(db, cred)
            rules = await source.get_rules(body.symbol)
            units = float(Decimal(str(body.order_lots)) * rules.lot_size)
            unit_step = float(rules.step_size) or None
        except BrokerError as exc:
            raise HTTPException(status.HTTP_502_BAD_GATEWAY, f"cTrader: {exc}") from exc
    if body.market == Market.b3:
        cred = await db.get(ExchangeCredential, body.credential_id) if db else None
        if not cred or cred.user_id != user.id or cred.exchange != "mt5":
            raise HTTPException(status.HTTP_404_NOT_FOUND, "Conexão do MetaTrader 5 não encontrada")
        source = MT5Broker(cred.id, cred.venue.value)
        try:
            rules = await source.get_rules(body.symbol)
            units = float(Decimal(str(body.order_lots)) * rules.lot_size)
            unit_step = float(rules.step_size) or None
        except BrokerError as exc:
            raise HTTPException(status.HTTP_502_BAD_GATEWAY, str(exc)) from exc
    try:
        # Busca candles extras antes do início para "aquecer" os indicadores.
        candles = await load_candles(body.symbol, params.timeframe, start_ms - warmup * step, end_ms, source)
    except BrokerError as exc:
        origin = {Market.forex: "do cTrader", Market.b3: "do MetaTrader 5"}.get(body.market, "da Binance")
        raise HTTPException(status.HTTP_502_BAD_GATEWAY, f"Não foi possível baixar o histórico {origin}: {exc}") from exc

    split = start_ms + int((end_ms - start_ms) * (1 - body.oos_pct / 100)) if body.oos_pct else None
    cfg = BacktestConfig(
        filters=body.filters if body.filters.active else None,
        family=STRATEGY_FAMILY.get(strategy.code, "trend"),
        timeframe=params.timeframe,
        split_time=split,
        risk_pct=body.risk_pct,
        max_leverage=body.max_leverage,
        unit_step=unit_step,
        initial_balance=body.initial_balance,
        order_size_quote=body.order_size_quote,
        order_units=units,
        allow_short=body.allow_short,
        stop_loss_pct=body.stop_loss_pct,
        take_profit_pct=body.take_profit_pct,
        max_daily_loss_quote=body.max_daily_loss_quote,
        # Vazio: sem limite prático para operações de 1 candle (o teste mede a regra inteira); 50 nas demais.
        max_trades_per_day=body.max_trades_per_day or (3000 if strategy.trade_bars else 50),
        fee_rate=body.fee_rate,
        slippage_bps=body.slippage_bps,
    )
    try:
        # CPU: roda fora do loop de eventos para não travar a API.
        result = await asyncio.to_thread(run_backtest, strategy, params, candles, cfg)
        # Mesma configuração SEM filtros e sem ATR, para mostrar o que os filtros mudaram.
        baseline = None
        if cfg.filters is not None:
            plain = BacktestConfig(**{**cfg.__dict__, "filters": None})
            baseline = await asyncio.to_thread(run_backtest, strategy, params, candles, plain)
    except ValueError as exc:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(exc)) from exc

    out = result.to_dict()
    if baseline is not None:
        b = baseline.to_dict()
        out["baseline"] = {"metrics": b["metrics"], "segments": b["segments"]}
    out["trades"] = out["trades"][-500:]  # as mais recentes; as métricas usam todas
    # Candles para o gráfico (TradingView Lightweight Charts). Limite para manter a resposta leve.
    out["ohlc"] = [[t, *(float(f"{v:.8g}") for v in ohlc)] for t, *ohlc in out["ohlc"][-MAX_CHART_CANDLES:]]
    out["symbol"] = body.symbol
    out["strategy"] = strategy.code
    out["market"] = body.market.value
    out["timeframe"] = params.timeframe
    out["config"] = {k: v for k, v in body.model_dump(mode="json").items() if k not in ("params",)}
    return out


@router.post("")
async def backtest(body: BacktestIn, user: CurrentUser, _: ActivePlan, db: DB) -> dict:
    await hit(f"backtest:{user.id}", limit=40, window_seconds=3600)
    return await execute(body, db, user)


@router.post("/bot/{bot_id}")
async def backtest_bot(bot_id: uuid.UUID, body: BotBacktestIn, user: CurrentUser, _: ActivePlan, db: DB) -> dict:
    """Testa no histórico exatamente a configuração de um robô existente."""
    bot = await db.get(Bot, bot_id)
    if not bot or bot.user_id != user.id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Robô não encontrado")
    await hit(f"backtest:{user.id}", limit=40, window_seconds=3600)

    def f(v: Decimal | None) -> float | None:
        return float(v) if v is not None else None

    return await execute(
        BacktestIn(
            strategy=bot.strategy,
            params=bot.params,
            market=bot.market,
            credential_id=bot.credential_id,
            order_lots=f(bot.order_lots),
            allow_short=bot.allow_short,
            symbol=bot.symbol,
            start=body.start,
            end=body.end,
            initial_balance=body.initial_balance,
            order_size_quote=float(bot.order_size_quote or 100),
            stop_loss_pct=f(bot.stop_loss_pct),
            take_profit_pct=f(bot.take_profit_pct),
            max_daily_loss_quote=f(bot.max_daily_loss_quote),
            max_trades_per_day=bot.max_trades_per_day,
            filters=BotFilters(**(bot.filters or {})),
            oos_pct=body.oos_pct,
            risk_pct=f(bot.risk_pct) if bot.sizing_mode == "risk" else None,
            max_leverage=f(bot.max_leverage),
        ),
        db,
        user,
    )
