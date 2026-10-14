"""Um ciclo (tick) de um robô: permissões → reconciliação → saídas de risco → estratégia → execução ou sinal."""
from __future__ import annotations

import logging
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from decimal import Decimal

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import active_subscription
from app.core.config import get_settings
from app.core.redis import get_redis
from app.engine import executor
from app.engine.guards import Problem, permission_problem
from app.engine.risk import daily_stats, entry_block_reason, exit_reason, kill_switch_state
from app.models import Bot, BotStatus, ExecMode, Side, Signal, SignalStatus, User
from app.services.audit import audit
from app.services.brokers.base import Broker, BrokerError
from app.services.brokers.factory import broker_for_bot
from app.strategies.library import get_strategy

log = logging.getLogger(__name__)

BrokerFactory = Callable[[AsyncSession, Bot], Awaitable[Broker]]


@dataclass
class TickResult:
    action: str  # skipped | hold | executed | signal | blocked | error
    detail: str = ""


async def _emit_signal(db: AsyncSession, bot: Bot, side: Side, price: Decimal, reason: str, now: datetime) -> TickResult:
    existing = await db.scalar(
        select(Signal.id).where(Signal.bot_id == bot.id, Signal.status == SignalStatus.pending, Signal.side == side)
    )
    if existing:
        return TickResult("hold", "Sinal pendente já existe")
    db.add(
        Signal(
            bot_id=bot.id,
            user_id=bot.user_id,
            symbol=bot.symbol,
            side=side,
            ref_price=price,
            reason=reason[:255],
            expires_at=now + timedelta(minutes=get_settings().signal_ttl_minutes),
        )
    )
    await db.commit()
    return TickResult("signal", f"{side.value}: {reason}")


async def _act(db: AsyncSession, bot: Bot, broker: Broker, side: Side, price: Decimal, reason: str, now: datetime) -> TickResult:
    if bot.exec_mode == ExecMode.signals:
        return await _emit_signal(db, bot, side, price, reason, now)
    try:
        order = await executor.execute(db, bot, broker, side, reason)
    except executor.ExecutionBlocked as exc:
        return TickResult("blocked", str(exc))
    return TickResult("executed", f"{side.value} {order.status.value}: {reason}")


async def run_tick(db: AsyncSession, bot: Bot, factory: BrokerFactory = broker_for_bot, now: datetime | None = None) -> TickResult:
    now = now or datetime.now(UTC)

    # 1) Permissões, assinatura e plano
    user = await db.get(User, bot.user_id)
    sub = await active_subscription(db, bot.user_id)
    problem = permission_problem(user, sub.plan if sub else None, bot) if user else Problem("billing", "Usuário inexistente")
    if problem:
        bot.status = BotStatus.paused_billing if problem.kind == "billing" else BotStatus.error
        bot.status_reason = problem.message
        await audit(db, "bot.paused", None, target=str(bot.id), reason=problem.message)
        await db.commit()
        return TickResult("skipped", problem.message)
    if bot.status == BotStatus.paused_billing:
        # Assinatura regularizada: retoma automaticamente.
        bot.status = BotStatus.running
        bot.status_reason = None
        await audit(db, "bot.resumed", None, target=str(bot.id))
        await db.commit()

    # 2) Kill switch global
    ks = await kill_switch_state(db)
    if ks.get("enabled"):
        return TickResult("skipped", "Kill switch global ativo")

    strategy = get_strategy(bot.strategy)
    params = strategy.parse_params(bot.params)

    broker = await factory(db, bot)
    try:
        # 3) Reconciliação: ordens sem resposta e posições encerradas pela própria corretora
        await executor.reconcile_unknown(db, bot, broker, now)
        await executor.sync_broker_closes(db, bot, broker)

        candles = strategy.closed_only(
            await broker.get_klines(bot.symbol, params.timeframe, strategy.required_candles(params) + 2),
            int(now.timestamp() * 1000),
        )
        if len(candles) < 3:
            return TickResult("hold", "Sem candles suficientes")
        price = await broker.get_price(bot.symbol)
        position = await executor.get_position(db, bot.id)
        bot.last_tick_at = now

        # 4) Saídas por risco (avaliadas a cada ciclo, com o preço atual)
        if position:
            reason = exit_reason(bot, position, price, strategy.max_hold_minutes(params), now)
            if reason:
                return await _act(db, bot, broker, executor.closing_side(position.side), price, reason, now)

        # 5) Estratégia: só decide uma vez por candle fechado (evita sinais repetidos)
        last_open = str(candles[-1].open_time)
        r = get_redis()
        seen_key = f"bot:{bot.id}:last_candle"
        if await r.get(seen_key) == last_open:
            await db.commit()
            return TickResult("hold", "Candle já avaliado")
        current = position.side.value if position else "flat"
        decision = strategy.decide(candles, current, params, bot.allow_short and broker.supports_short)
        await r.set(seen_key, last_open, ex=7 * 86400)

        target = decision.target
        if target is None or target == current:
            await db.commit()
            return TickResult("hold", decision.reason)

        # Primeiro encerra a posição atual (se houver); a nova entrada acontece no mesmo ciclo
        # no modo automático, ou vira o próximo sinal no modo sinais.
        if position:
            result = await _act(db, bot, broker, executor.closing_side(position.side), price, decision.reason, now)
            if target == "flat" or bot.exec_mode == ExecMode.signals or result.action != "executed":
                return result
            await db.refresh(bot)
            if await executor.get_position(db, bot.id):
                return result  # fechamento ainda não confirmado

        stats = await daily_stats(db, bot.id, now)
        block, pause = entry_block_reason(bot, stats)
        if block:
            if pause:
                bot.status = BotStatus.paused_risk
                bot.status_reason = block
                await audit(db, "bot.paused_risk", None, target=str(bot.id), reason=block)
            await db.commit()
            return TickResult("blocked", block)
        side = Side.buy if target == "long" else Side.sell
        return await _act(db, bot, broker, side, price, decision.reason, now)
    finally:
        await broker.close()


async def expire_signals(db: AsyncSession, now: datetime | None = None) -> int:
    now = now or datetime.now(UTC)
    res = await db.execute(
        update(Signal)
        .where(Signal.status == SignalStatus.pending, Signal.expires_at < now)
        .values(status=SignalStatus.expired)
    )
    await db.commit()
    return res.rowcount or 0


async def mark_error(db: AsyncSession, bot: Bot, exc: Exception) -> None:
    """Erro não recuperável (ex.: chave revogada): para o robô e registra o motivo."""
    retryable = isinstance(exc, BrokerError) and exc.retryable
    if retryable:
        log.warning("Erro temporário no robô %s: %s", bot.id, exc)
        return
    bot.status = BotStatus.error
    bot.status_reason = str(exc)[:255]
    await audit(db, "bot.error", None, target=str(bot.id), error=str(exc)[:200])
    await db.commit()
