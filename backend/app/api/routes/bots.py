from __future__ import annotations

import uuid
from datetime import UTC, datetime
from decimal import Decimal

from fastapi import APIRouter, HTTPException, Query, Request, status
from pydantic import ValidationError
from sqlalchemy import func, select

from app.api.deps import DB, ActivePlan, CurrentUser, active_subscription
from app.core.ratelimit import client_ip
from app.engine import executor
from app.engine.guards import permission_problem
from app.engine.risk import daily_stats
from app.models import (
    Bot,
    BotStatus,
    ExchangeCredential,
    ExecMode,
    Market,
    Order,
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
from app.strategies.library import STRATEGIES, get_strategy

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


async def _check_credential(db, user, credential_id: uuid.UUID | None, venue: Venue, market: Market = Market.crypto) -> None:
    forex = market == Market.forex
    if venue == Venue.paper and not forex:
        return  # simulação de cripto usa dados públicos da Binance
    if not credential_id:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            "Escolha uma conta cTrader (também usada para as cotações na simulação)" if forex else "Escolha uma credencial da Binance para este ambiente",
        )
    cred = await db.get(ExchangeCredential, credential_id)
    if not cred or cred.user_id != user.id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Credencial não encontrada")
    if cred.exchange != ("ctrader" if forex else "binance"):
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Para forex use uma conta cTrader; para cripto, uma chave da Binance")
    if venue != Venue.paper and cred.venue != venue:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "A credencial é de outro ambiente (demo/testnet × real)")


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
            params_schema=s.Params.model_json_schema(),
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

    bot = Bot(
        user_id=user.id,
        name=body.name,
        market=body.market,
        symbol=body.symbol,
        strategy=body.strategy,
        allow_short=body.allow_short,
        params=params,
        exec_mode=body.exec_mode,
        venue=body.venue,
        credential_id=body.credential_id if (body.venue != Venue.paper or body.market == Market.forex) else None,
        order_size_quote=body.order_size_quote,
        order_lots=body.order_lots,
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
    if venue == Venue.paper and bot.market == Market.crypto:
        data["credential_id"] = None
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
