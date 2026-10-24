from __future__ import annotations

import time
import uuid
from datetime import UTC, datetime
from zoneinfo import ZoneInfo
from decimal import Decimal

from fastapi import APIRouter, HTTPException, Query, Request, status
from pydantic import ValidationError
from sqlalchemy import func, select

from app.api.deps import DB, ActivePlan, CurrentUser, active_subscription
from app.core.ratelimit import client_ip, hit
from app.engine import executor
from app.engine.guards import permission_problem
from app.engine import journal
from app.engine.risk import daily_stats, kill_switch_state
from app.engine.sizing import SizingBlocked
from app.models import (
    Bot,
    BotStatus,
    ExchangeCredential,
    ExecMode,
    Market,
    Order,
    PosSide,
    OrderStatus,
    Side,
    Signal,
    SignalStatus,
    Venue,
)
from app.schemas import BotIn, BotOut, BotSummary, BotUpdate, OrderOut, PositionOut, SignalOut, StrategyInfo
from app.services.audit import audit
from app.services.brokers.base import BrokerError
from app.services.brokers.factory import broker_for_bot
from app.strategies import filters as flt
from app.strategies.filters import STRATEGY_FAMILY, TF_MS, BotFilters
from app.strategies.library import STRATEGIES, get_strategy

TZ_BR = ZoneInfo("America/Sao_Paulo")
router = APIRouter(tags=["robôs"])


def _validate_params(strategy_code: str, params: dict) -> dict:
    try:
        strategy = get_strategy(strategy_code)
    except ValueError as exc:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(exc)) from exc
    try:
        return strategy.parse_params(params).model_dump(exclude_none=True)
    except ValidationError as exc:
        msgs = "; ".join(f"{'.'.join(map(str, e['loc']))}: {e['msg']}" for e in exc.errors())
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, f"Parâmetros inválidos — {msgs}") from exc


async def _get_bot(db, user, bot_id: uuid.UUID) -> Bot:
    bot = await db.get(Bot, bot_id)
    if not bot or bot.user_id != user.id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Robô não encontrado")
    return bot


EXCHANGE_FOR = {Market.crypto: "binance", Market.forex: "ctrader", Market.b3: "mt5"}
MISSING_CRED = {
    Market.crypto: "Escolha uma credencial da Binance para este ambiente",
    Market.forex: "Escolha uma conta cTrader (também usada para as cotações na simulação)",
    Market.b3: "Escolha uma conexão do MetaTrader 5 (também usada para as cotações na simulação)",
}


async def _check_credential(db, user, credential_id: uuid.UUID | None, venue: Venue, market: Market = Market.crypto) -> None:
    if venue == Venue.paper and market == Market.crypto:
        return  # simulação de cripto usa dados públicos da Binance
    if not credential_id:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, MISSING_CRED[market])
    cred = await db.get(ExchangeCredential, credential_id)
    if not cred or cred.user_id != user.id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Credencial não encontrada")
    if cred.exchange != EXCHANGE_FOR[market]:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            "Use a conexão certa para o mercado: Binance para cripto, cTrader para forex e MetaTrader 5 para a B3",
        )
    if venue != Venue.paper and cred.venue != venue:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "A credencial é de outro ambiente (demo/testnet × real)")


def _check_filters(filters: BotFilters, strategy_code: str, params: dict) -> dict:
    try:
        filters.validate_for(get_strategy(strategy_code).parse_params(params).timeframe)
    except ValueError as exc:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, f"Filtros: {exc}") from exc
    return filters.model_dump(exclude_defaults=True)


def _check_plan(plan, exec_mode: ExecMode, venue: Venue) -> None:
    if exec_mode == ExecMode.auto and not plan.allow_auto:
        raise HTTPException(status.HTTP_403_FORBIDDEN, f"O plano {plan.name} não inclui execução automática")
    if venue == Venue.live and not plan.allow_live:
        raise HTTPException(status.HTTP_403_FORBIDDEN, f"O plano {plan.name} não inclui operação em conta real")


async def _has_open_activity(db, bot_id: uuid.UUID) -> bool:
    pos = await executor.get_position(db, bot_id)
    pending = await db.scalar(
        select(func.count(Order.id)).where(Order.bot_id == bot_id, Order.status.in_([OrderStatus.new, OrderStatus.unknown]))
    )
    return pos is not None or bool(pending)


# ---------------- Estratégias ----------------
@router.get("/strategies", response_model=list[StrategyInfo])
async def list_strategies() -> list[StrategyInfo]:
    return [
        StrategyInfo(
            code=s.code,
            name=s.name,
            style=s.style,
            description=s.description,
            timeframe=s.Params.model_fields["timeframe"].default,
            family=STRATEGY_FAMILY.get(s.code, "trend"),
            params_schema=s.Params.model_json_schema(),
            trade_bars=s.trade_bars,
            suggested_max_trades_per_day=s.suggested_max_trades_per_day,
            notes=list(s.notes),
        )
        for s in STRATEGIES.values()
    ]


# ---------------- Robôs ----------------
@router.get("/bots", response_model=list[BotOut])
async def list_bots(user: CurrentUser, db: DB) -> list[Bot]:
    return list(await db.scalars(select(Bot).where(Bot.user_id == user.id).order_by(Bot.created_at)))


@router.post("/bots", response_model=BotOut, status_code=201)
async def create_bot(body: BotIn, user: CurrentUser, plan: ActivePlan, request: Request, db: DB) -> Bot:
    count = await db.scalar(select(func.count(Bot.id)).where(Bot.user_id == user.id))
    if (count or 0) >= plan.max_bots:
        raise HTTPException(status.HTTP_403_FORBIDDEN, f"Seu plano permite até {plan.max_bots} robô(s)")
    _check_plan(plan, body.exec_mode, body.venue)
    await _check_credential(db, user, body.credential_id, body.venue, body.market)
    params = _validate_params(body.strategy, body.params)
    filters = _check_filters(body.filters, body.strategy, params)

    bot = Bot(
        user_id=user.id,
        name=body.name,
        market=body.market,
        symbol=body.symbol,
        strategy=body.strategy,
        allow_short=body.allow_short,
        params=params,
        filters=filters,
        exec_mode=body.exec_mode,
        venue=body.venue,
        credential_id=body.credential_id if (body.venue != Venue.paper or body.market != Market.crypto) else None,
        order_size_quote=body.order_size_quote,
        order_lots=body.order_lots,
        sizing_mode=body.sizing_mode,
        risk_pct=body.risk_pct,
        max_leverage=body.max_leverage,
        stop_loss_pct=body.stop_loss_pct,
        take_profit_pct=body.take_profit_pct,
        max_daily_loss_quote=body.max_daily_loss_quote,
        max_trades_per_day=body.max_trades_per_day,
        paper_quote_balance=body.paper_quote_balance,
        paper_base_balance=Decimal("0"),
    )
    db.add(bot)
    await db.flush()
    await audit(db, "bot.created", user.id, target=str(bot.id), ip=client_ip(request), venue=body.venue.value)
    await db.commit()
    return bot


@router.get("/bots/{bot_id}", response_model=BotSummary)
async def bot_summary(bot_id: uuid.UUID, user: CurrentUser, db: DB) -> BotSummary:
    bot = await _get_bot(db, user, bot_id)
    pos = await executor.get_position(db, bot.id)
    stats = await daily_stats(db, bot.id)
    total = await db.scalar(select(func.coalesce(func.sum(Order.realized_pnl), 0)).where(Order.bot_id == bot.id))
    return BotSummary(
        bot=BotOut.model_validate(bot),
        position=PositionOut.model_validate(pos) if pos else None,
        realized_pnl_today=stats.realized_pnl,
        realized_pnl_total=Decimal(str(total or 0)),
        trades_today=stats.trades,
    )


@router.patch("/bots/{bot_id}", response_model=BotOut)
async def update_bot(bot_id: uuid.UUID, body: BotUpdate, user: CurrentUser, plan: ActivePlan, request: Request, db: DB) -> Bot:
    bot = await _get_bot(db, user, bot_id)
    data = body.model_dump(exclude_unset=True)

    venue = data.get("venue", bot.venue)
    exec_mode = data.get("exec_mode", bot.exec_mode)
    credential_id = data.get("credential_id", bot.credential_id)
    if venue != bot.venue or credential_id != bot.credential_id:
        if bot.status == BotStatus.running:
            raise HTTPException(status.HTTP_409_CONFLICT, "Pare o robô antes de trocar o ambiente ou a credencial")
        if await _has_open_activity(db, bot.id):
            raise HTTPException(status.HTTP_409_CONFLICT, "Encerre a posição aberta antes de trocar o ambiente")
    _check_plan(plan, exec_mode, venue)
    await _check_credential(db, user, credential_id, venue, bot.market)

    if "params" in data:
        data["params"] = _validate_params(bot.strategy, data["params"])
    if "filters" in data:
        data["filters"] = _check_filters(body.filters or BotFilters(), bot.strategy, data.get("params", bot.params))
    if venue == Venue.paper and bot.market == Market.crypto:
        data["credential_id"] = None
    if bot.market == Market.b3 and data.get("order_lots") is not None and data["order_lots"] != data["order_lots"].to_integral_value():
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Na B3 o tamanho é em contratos inteiros")
    if bot.market == Market.crypto:
        if data.get("allow_short"):
            raise HTTPException(status.HTTP_400_BAD_REQUEST, "Cripto à vista não opera vendido")
        data.pop("order_lots", None)
    else:
        data.pop("order_size_quote", None)
    if "allow_short" in data and data["allow_short"] != bot.allow_short and await _has_open_activity(db, bot.id):
        raise HTTPException(status.HTTP_409_CONFLICT, "Encerre a posição antes de mudar a direção do robô")
    for key, value in data.items():
        setattr(bot, key, value)
    if bot.sizing_mode == "risk":
        if not bot.risk_pct:
            raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "Informe quanto do saldo arriscar por operação (ex.: 1%)")
        if not (bot.stop_loss_pct or (bot.filters or {}).get("stop_atr")):
            raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "O tamanho pelo risco precisa de um stop (em % ou pelo ATR)")
    elif bot.market == Market.crypto and not bot.order_size_quote:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "Informe o valor por ordem")
    elif bot.market != Market.crypto and not bot.order_lots:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "Informe o tamanho em lotes ou contratos")
    await audit(db, "bot.updated", user.id, target=str(bot.id), ip=client_ip(request), fields=sorted(data.keys()))
    await db.commit()
    return bot


@router.post("/bots/{bot_id}/start", response_model=BotOut)
async def start_bot(bot_id: uuid.UUID, user: CurrentUser, request: Request, db: DB) -> Bot:
    bot = await _get_bot(db, user, bot_id)
    sub = await active_subscription(db, user.id)
    problem = permission_problem(user, sub.plan if sub else None, bot)
    if problem:
        raise HTTPException(status.HTTP_403_FORBIDDEN, problem.message)
    bot.status = BotStatus.running
    bot.status_reason = None
    await audit(db, "bot.started", user.id, target=str(bot.id), ip=client_ip(request), venue=bot.venue.value, mode=bot.exec_mode.value)
    await db.commit()
    return bot


@router.post("/bots/{bot_id}/stop", response_model=BotOut)
async def stop_bot(bot_id: uuid.UUID, user: CurrentUser, request: Request, db: DB) -> Bot:
    bot = await _get_bot(db, user, bot_id)
    bot.status = BotStatus.stopped
    bot.status_reason = "Parado pelo usuário"
    await audit(db, "bot.stopped", user.id, target=str(bot.id), ip=client_ip(request))
    await db.commit()
    return bot


@router.post("/bots/{bot_id}/close-position", response_model=OrderOut)
async def close_position(bot_id: uuid.UUID, user: CurrentUser, request: Request, db: DB) -> Order:
    """Botão de pânico: encerra a posição a mercado (comprada ou vendida), mesmo com o robô parado."""
    bot = await _get_bot(db, user, bot_id)
    pos = await executor.get_position(db, bot.id)
    if not pos:
        raise HTTPException(status.HTTP_409_CONFLICT, "Não há posição aberta")
    broker = await _broker_or_400(db, bot)
    try:
        return await executor.execute(db, bot, broker, executor.closing_side(pos.side), "Encerramento manual", actor_id=user.id)
    except executor.ExecutionBlocked as exc:
        raise HTTPException(status.HTTP_409_CONFLICT, str(exc)) from exc
    except BrokerError as exc:
        raise HTTPException(status.HTTP_502_BAD_GATEWAY, f"Corretora recusou: {exc}") from exc
    finally:
        await broker.close()


@router.post("/bots/{bot_id}/paper-reset", response_model=BotOut)
async def paper_reset(bot_id: uuid.UUID, user: CurrentUser, db: DB, balance: Decimal = Query(Decimal("1000"), gt=0, le=10_000_000)) -> Bot:
    bot = await _get_bot(db, user, bot_id)
    if bot.venue != Venue.paper:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Disponível só na simulação")
    if await _has_open_activity(db, bot.id):
        raise HTTPException(status.HTTP_409_CONFLICT, "Encerre a posição simulada antes de reiniciar o saldo")
    bot.paper_quote_balance = balance
    bot.paper_base_balance = Decimal("0")
    await db.commit()
    return bot


@router.delete("/bots/{bot_id}", status_code=204, response_model=None)
async def delete_bot(bot_id: uuid.UUID, user: CurrentUser, request: Request, db: DB) -> None:
    bot = await _get_bot(db, user, bot_id)
    if bot.status == BotStatus.running:
        raise HTTPException(status.HTTP_409_CONFLICT, "Pare o robô antes de excluir")
    if await _has_open_activity(db, bot.id):
        raise HTTPException(status.HTTP_409_CONFLICT, "Encerre a posição antes de excluir o robô")
    await audit(db, "bot.deleted", user.id, target=str(bot.id), ip=client_ip(request))
    await db.delete(bot)
    await db.commit()


@router.get("/orders", response_model=list[OrderOut])
async def list_orders(
    user: CurrentUser, db: DB, bot_id: uuid.UUID | None = None, limit: int = Query(100, ge=1, le=500)
) -> list[Order]:
    q = select(Order).where(Order.user_id == user.id)
    if bot_id:
        q = q.where(Order.bot_id == bot_id)
    return list(await db.scalars(q.order_by(Order.created_at.desc()).limit(limit)))


# ---------------- Prévia do tamanho e da alavancagem ----------------
class SizingPreviewIn(BotIn):
    name: str = "Prévia"


async def _preview(db, bot: Bot) -> dict:
    """Calcula o tamanho da próxima entrada com o saldo e o preço de agora, sem enviar nada."""
    try:
        broker = await broker_for_bot(db, bot)
    except BrokerError as exc:
        return {"ok": False, "message": str(exc)}
    try:
        rules = await broker.get_rules(bot.symbol)
        plan, *_ = await executor.plan_entry(bot, broker, rules, PosSide.long, always_balance=True)
    except SizingBlocked as exc:
        return {"ok": False, "message": str(exc)}
    except (BrokerError, ValueError) as exc:
        return {"ok": False, "message": f"Não foi possível consultar a corretora: {exc}"}
    finally:
        await broker.close()
    unit = {Market.b3: "contratos", Market.forex: "lotes"}.get(bot.market)
    return {
        "ok": True,
        "currency": rules.currency or rules.quote_asset,
        "unit": unit,
        **plan.as_dict(),
    }


@router.post("/bots/sizing-preview")
async def sizing_preview(body: SizingPreviewIn, user: CurrentUser, db: DB) -> dict:
    await hit(f"preview:{user.id}", 60, 60)
    await _check_credential(db, user, body.credential_id, body.venue, body.market)
    params = _validate_params(body.strategy, body.params)
    filters = _check_filters(body.filters, body.strategy, params)
    bot = Bot(  # objeto temporário: não é salvo
        user_id=user.id, name=body.name, market=body.market, symbol=body.symbol, strategy=body.strategy, params=params, filters=filters,
        allow_short=body.allow_short, exec_mode=body.exec_mode, venue=body.venue,
        credential_id=body.credential_id if (body.venue != Venue.paper or body.market != Market.crypto) else None,
        order_size_quote=body.order_size_quote, order_lots=body.order_lots, sizing_mode=body.sizing_mode, risk_pct=body.risk_pct,
        max_leverage=body.max_leverage, stop_loss_pct=body.stop_loss_pct, take_profit_pct=body.take_profit_pct,
        paper_quote_balance=body.paper_quote_balance, paper_base_balance=Decimal("0"),
    )
    return await _preview(db, bot)


@router.get("/bots/{bot_id}/sizing-preview")
async def bot_sizing_preview(bot_id: uuid.UUID, user: CurrentUser, db: DB) -> dict:
    await hit(f"preview:{user.id}", 60, 60)
    return await _preview(db, await _get_bot(db, user, bot_id))


# ---------------- Gráfico do robô ----------------
def _ms(dt: datetime) -> int:
    return int((dt if dt.tzinfo else dt.replace(tzinfo=UTC)).timestamp() * 1000)


@router.get("/bots/{bot_id}/chart")
async def bot_chart(bot_id: uuid.UUID, user: CurrentUser, db: DB, limit: int = Query(300, ge=50, le=1000)) -> dict:
    """Candles do ativo (pela conexão do próprio cliente) com as ordens do robô e os níveis da posição aberta."""
    await hit(f"chart:{user.id}", 120, 60)
    bot = await _get_bot(db, user, bot_id)
    strategy = get_strategy(bot.strategy)
    tf = strategy.parse_params(bot.params).timeframe
    broker = await broker_for_bot(db, bot)
    try:
        candles = await broker.get_klines(bot.symbol, tf, limit)
    except (BrokerError, ValueError) as exc:
        raise HTTPException(status.HTTP_502_BAD_GATEWAY, f"Não foi possível buscar os candles na corretora: {exc}") from exc
    finally:
        await broker.close()
    if not candles:
        return {"timeframe": tf, "ohlc": [], "orders": [], "signals": [], "position": None}
    since = datetime.fromtimestamp(candles[0].open_time / 1000, UTC)

    orders = (
        await db.scalars(
            select(Order)
            .where(Order.bot_id == bot.id, Order.created_at >= since, Order.price.is_not(None),
                   Order.status.in_([OrderStatus.filled, OrderStatus.partially_filled]))
            .order_by(Order.created_at)
            .limit(2000)
        )
    ).all()
    signals = (
        await db.scalars(
            select(Signal).where(Signal.bot_id == bot.id, Signal.created_at >= since).order_by(Signal.created_at).limit(500)
        )
    ).all() if bot.exec_mode == ExecMode.signals else []

    pos = await executor.get_position(db, bot.id)
    position = None
    if pos:
        sign = -1 if pos.side == PosSide.short else 1
        avg = pos.avg_price
        stop = pos.stop_price if pos.stop_price is not None else (
            avg * (1 - sign * bot.stop_loss_pct / 100) if bot.stop_loss_pct else None)
        take = pos.take_price if pos.take_price is not None else (
            avg * (1 + sign * bot.take_profit_pct / 100) if bot.take_profit_pct else None)
        position = {"side": pos.side.value, "avg_price": float(avg), "stop": float(stop) if stop else None,
                    "take": float(take) if take else None, "opened_at": _ms(pos.opened_at)}

    return {
        "timeframe": tf,
        "ohlc": [[c.open_time, c.open, c.high, c.low, c.close] for c in candles],
        # Ordem com resultado realizado é saída; sem resultado é entrada.
        "orders": [
            {"time": _ms(o.created_at), "side": o.side.value, "price": float(o.price), "exit": o.realized_pnl is not None,
             "pnl": float(o.realized_pnl) if o.realized_pnl is not None else None, "reason": o.reason[:160]}
            for o in orders
        ],
        "signals": [
            {"time": _ms(x.created_at), "side": x.side.value, "price": float(x.ref_price), "status": x.status.value}
            for x in signals
        ],
        "position": position,
    }


# ---------------- Diagnóstico ----------------
STATUS_TEXT = {
    BotStatus.paused_billing: "Pausado pela assinatura",
    BotStatus.paused_risk: "Pausado pelo limite de perda do dia",
    BotStatus.error: "Parado por erro",
    BotStatus.stopped: "Parado",
}


@router.get("/bots/{bot_id}/diagnostics")
async def bot_diagnostics(bot_id: uuid.UUID, user: CurrentUser, db: DB) -> dict:
    """Por que o robô entrou ou não entrou: confere as causas comuns e devolve o diário das últimas decisões."""
    await hit(f"diag:{user.id}", 30, 60)
    bot = await _get_bot(db, user, bot_id)
    now = datetime.now(UTC)
    checks: list[dict] = []

    def add(level: str, title: str, detail: str = "") -> None:
        checks.append({"level": level, "title": title, "detail": detail})

    # 1) O motor (worker) está rodando?
    ws = await journal.worker_state()
    if not ws or time.time() - ws.get("at", 0) > 90:
        add("fail", "O motor de robôs (worker) não está rodando",
            "Sem sinal de vida do worker. No servidor, confira com `docker compose ps` e veja o erro com `docker compose logs --tail=100 worker`.")
    elif ws.get("last_error"):
        add("fail", "O motor não consegue ler os robôs do banco",
            f"Erro: {ws['last_error']}. Depois de atualizar o sistema, rode a atualização com o arquivo de produção "
            "(docker compose -f docker-compose.yml -f docker-compose.prod.yml up -d --build) para aplicar as migrações do banco.")
    else:
        add("ok", "Motor de robôs rodando", f"Vigiando {ws.get('bots', 0)} robô(s).")
    off = (ws or {}).get("clock_offset_ms")
    if off is not None and abs(off) > 2000:
        add("warn", f"Relógio do servidor {abs(off) / 1000:.1f} s diferente do da Binance",
            "Ative a sincronização de horário (NTP) no servidor. Em estratégias de 1 minuto isso atrasa ou descarta entradas.")

    # 2) Situação, assinatura e permissões
    sub = await active_subscription(db, user.id)
    problem = permission_problem(user, sub.plan if sub else None, bot)
    if bot.status == BotStatus.running:
        add("ok", "Robô ligado")
    else:
        reason = bot.status_reason or ""
        hint = "Depois de resolver, ligue o robô de novo." if bot.status != BotStatus.stopped else "Ligue o robô no botão Ligar."
        add("fail", STATUS_TEXT.get(bot.status, bot.status.value), f"{reason}. {hint}" if reason else hint)
    if problem and problem.message != bot.status_reason:
        add("fail", "Falta algo para o robô poder operar", problem.message)
    ks = await kill_switch_state(db)
    if ks.get("enabled"):
        add("fail", "Todos os robôs estão pausados pela administração", ks.get("reason") or "")

    # 3) Modo de execução
    if bot.exec_mode == ExecMode.signals:
        pending = await db.scalar(select(func.count(Signal.id)).where(Signal.bot_id == bot.id, Signal.status == SignalStatus.pending))
        add("warn", "Modo sinais: o robô não entra sozinho",
            f"Cada entrada vira um aviso na tela Sinais e só é executada quando você confirma. Sinais pendentes agora: {pending or 0}. "
            "Para entrar sozinho, mude o modo para Automático (plano com execução automática).")
    else:
        add("ok", "Modo automático", "As entradas são enviadas sozinhas.")

    # 4) Avaliações recentes
    strategy = get_strategy(bot.strategy)
    tf = strategy.parse_params(bot.params).timeframe
    step = TF_MS[tf] / 1000
    if bot.last_tick_at is None:
        add("warn", "O robô ainda não foi avaliado pelo motor", "Se o motor estiver rodando, a primeira avaliação acontece em até 1 minuto.")
    else:
        last = bot.last_tick_at if bot.last_tick_at.tzinfo else bot.last_tick_at.replace(tzinfo=UTC)
        age = (now - last).total_seconds()
        if bot.status != BotStatus.running:
            pass  # parado: o motor não avalia, e isso já aparece acima
        elif age > step + 120:
            ago = f"{int(age // 86400)} dia(s)" if age >= 86400 else f"{int(age // 3600)} h" if age >= 3600 else f"{int(age // 60)} min"
            add("warn", f"Última avaliação há {ago}", f"O esperado é a cada candle de {tf}. Confira se o motor está rodando.")
        else:
            add("ok", "Avaliando a cada candle", f"Tempo gráfico {tf}; última avaliação às {last.astimezone(TZ_BR):%H:%M:%S}.")

    # 5) Limites do dia
    stats = await daily_stats(db, bot.id, now)
    if stats.trades >= bot.max_trades_per_day:
        add("fail", "Limite de operações do dia atingido",
            f"{stats.trades} de {bot.max_trades_per_day} (entrada e saída contam separadas). Aumente o limite em Ajustar ou espere o dia virar (meia-noite UTC).")
    elif bot.max_daily_loss_quote and stats.realized_pnl <= -bot.max_daily_loss_quote:
        add("fail", "Perda máxima do dia atingida", f"Resultado de hoje: {stats.realized_pnl:.2f}.")
    else:
        add("ok", "Limites do dia livres", f"{stats.trades} de {bot.max_trades_per_day} operações hoje.")

    # 6) Filtros de entrada
    entries = await journal.read(bot.id, 50)
    f = flt.parse(bot.filters)
    if f.any_entry_filter:
        barred = sum(1 for e in entries if "Entrada filtrada" in (e.get("detail") or ""))
        add("warn" if barred else "info", "Filtros de entrada ligados",
            f"Eles barram entradas fora das condições escolhidas. Nas últimas {len(entries)} avaliações, {barred} entrada(s) foram barradas por filtro.")

    # 7) Venda a descoberto na Binance à vista
    if bot.market == Market.crypto:
        add("info", "Binance à vista: só entra comprado",
            "Sinais de venda sem posição aberta são ignorados (não existe venda a descoberto no mercado à vista).")

    # 8) Tamanho da próxima entrada (saldo, mínimo da corretora, conexão)
    preview = await _preview(db, bot)
    if preview.get("ok"):
        add("ok", "Saldo e tamanho da ordem conferidos", "A próxima entrada passa no saldo e no mínimo da corretora.")
    else:
        add("fail", "A próxima entrada seria recusada", preview.get("message") or "")

    # Resumo do diário
    counts: dict[str, int] = {}
    for e in entries:
        counts[e.get("action", "")] = counts.get(e.get("action", ""), 0) + 1
    next_close = (int(now.timestamp() // step) + 1) * step
    return {
        "checks": checks,
        "journal": entries,
        "counts": counts,
        "timeframe": tf,
        "strategy": strategy.name,
        "next_decision_at": int((next_close + 1.2) * 1000),
        "worker": ws,
    }


# ---------------- Sinais ----------------
@router.get("/signals", response_model=list[SignalOut])
async def list_signals(
    user: CurrentUser, db: DB, status_filter: SignalStatus | None = Query(None, alias="status"), limit: int = Query(50, le=200)
) -> list[Signal]:
    q = select(Signal).where(Signal.user_id == user.id)
    if status_filter:
        q = q.where(Signal.status == status_filter)
    return list(await db.scalars(q.order_by(Signal.created_at.desc()).limit(limit)))


async def _get_pending_signal(db, user, signal_id: uuid.UUID) -> Signal:
    sig = await db.get(Signal, signal_id)
    if not sig or sig.user_id != user.id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Sinal não encontrado")
    if sig.status != SignalStatus.pending:
        raise HTTPException(status.HTTP_409_CONFLICT, "Este sinal não está mais pendente")
    expires = sig.expires_at if sig.expires_at.tzinfo else sig.expires_at.replace(tzinfo=UTC)
    if expires < datetime.now(UTC):
        sig.status = SignalStatus.expired
        await db.commit()
        raise HTTPException(status.HTTP_409_CONFLICT, "Sinal expirado")
    return sig


async def _broker_or_400(db, bot: Bot):
    try:
        return await broker_for_bot(db, bot)
    except BrokerError as exc:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(exc)) from exc


@router.post("/signals/{signal_id}/execute", response_model=OrderOut)
async def execute_signal(signal_id: uuid.UUID, user: CurrentUser, request: Request, db: DB) -> Order:
    sig = await _get_pending_signal(db, user, signal_id)
    bot = await _get_bot(db, user, sig.bot_id)
    sub = await active_subscription(db, user.id)
    problem = permission_problem(user, sub.plan if sub else None, bot)
    if problem:
        raise HTTPException(status.HTTP_403_FORBIDDEN, problem.message)

    broker = await _broker_or_400(db, bot)
    try:
        order = await executor.execute(db, bot, broker, sig.side, f"Sinal confirmado: {sig.reason}", actor_id=user.id)
    except executor.ExecutionBlocked as exc:
        raise HTTPException(status.HTTP_409_CONFLICT, str(exc)) from exc
    except BrokerError as exc:
        sig.status = SignalStatus.failed
        await db.commit()
        raise HTTPException(status.HTTP_502_BAD_GATEWAY, f"Corretora recusou: {exc}") from exc
    finally:
        await broker.close()

    sig.status = SignalStatus.executed
    sig.order_id = order.id
    await audit(db, "signal.executed", user.id, target=str(sig.id), ip=client_ip(request))
    await db.commit()
    return order


@router.post("/signals/{signal_id}/dismiss", response_model=SignalOut)
async def dismiss_signal(signal_id: uuid.UUID, user: CurrentUser, db: DB) -> Signal:
    sig = await _get_pending_signal(db, user, signal_id)
    sig.status = SignalStatus.dismissed
    await db.commit()
    return sig
