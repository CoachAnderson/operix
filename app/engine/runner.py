"""Um ciclo (tick) de um robô: permissões → reconciliação → saídas de risco → estratégia → execução ou sinal."""
from __future__ import annotations

import asyncio
import logging
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from decimal import Decimal

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import effective_plan
from app.core.config import get_settings
from app.core.redis import get_redis
from app.engine import executor, ladder
from app.engine.guards import Problem, permission_problem
from app.engine.risk import daily_stats, entry_block_reason, exit_reason, kill_switch_state
from app.models import Bot, BotStatus, ExecMode, Market, Side, Signal, SignalStatus, User
from app.services import b3
from app.strategies import filters as flt
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


def trade_finished(opened_at: datetime, last_closed_open_ms: int, timeframe: str, bars: int) -> bool:
    """Operação de duração fixa: True quando o último candle fechado é o N-ésimo desde o candle da entrada."""
    step = flt.TF_MS[timeframe]
    opened = opened_at if opened_at.tzinfo else opened_at.replace(tzinfo=UTC)
    entry_candle = int(opened.timestamp() * 1000) // step * step
    return last_closed_open_ms >= entry_candle + (bars - 1) * step


async def _emit_signal(db: AsyncSession, bot: Bot, side: Side, price: Decimal, reason: str, now: datetime,
                       expires_at: datetime | None = None) -> TickResult:
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
            expires_at=expires_at or now + timedelta(minutes=get_settings().signal_ttl_minutes),
        )
    )
    await db.commit()
    return TickResult("signal", f"{side.value}: {reason}")


async def _act(db: AsyncSession, bot: Bot, broker: Broker, side: Side, price: Decimal, reason: str, now: datetime,
               expires_at: datetime | None = None, signal_at: datetime | None = None, ref_price: Decimal | None = None) -> TickResult:
    if bot.exec_mode == ExecMode.signals:
        return await _emit_signal(db, bot, side, price, reason, now, expires_at)
    try:
        # Preço e momento do sinal ficam na ordem para medir atraso e escorregamento depois.
        order = await executor.execute(db, bot, broker, side, reason, ref_price=ref_price or price, signal_at=signal_at or now)
    except executor.ExecutionBlocked as exc:
        return TickResult("blocked", str(exc))
    return TickResult("executed", f"{side.value} {order.status.value}: {reason}")


async def run_tick(db: AsyncSession, bot: Bot, factory: BrokerFactory = broker_for_bot, now: datetime | None = None,
                   price: Decimal | None = None) -> TickResult:
    now = now or datetime.now(UTC)

    # 1) Permissões, assinatura e plano
    user = await db.get(User, bot.user_id)
    plan = await effective_plan(db, user)
    problem = permission_problem(user, plan, bot) if user else Problem("billing", "Usuário inexistente")
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
    filters = flt.parse(bot.filters)

    broker = await factory(db, bot)
    try:
        # 3) Reconciliação: ordens sem resposta e posições encerradas pela própria corretora
        await executor.reconcile_unknown(db, bot, broker, now)
        await executor.sync_broker_closes(db, bot, broker)

        if strategy.kind == "ladder":  # Grid e DCA: compram e vendem lotes por nível de preço
            res = await ladder.tick(db, bot, broker, price, now)
            return TickResult(res.action, res.detail)

        # Candles e preço ao mesmo tempo: menos espera entre o fechamento do candle e a ordem.
        raw, price = await asyncio.gather(
            broker.get_klines(bot.symbol, params.timeframe, max(strategy.required_candles(params), filters.lookback()) + 2),
            broker.get_price(bot.symbol),
        )
        candles = strategy.closed_only(raw, int(now.timestamp() * 1000))
        if len(candles) < 3:
            return TickResult("hold", "Sem candles suficientes")
        position = await executor.get_position(db, bot.id)
        bot.last_tick_at = now

        # 4a) Futuros da B3: zera o day trade antes do fim do pregão e rola o contrato perto do vencimento
        if bot.market == Market.b3:
            rules = await broker.get_rules(bot.symbol)
            info = b3.info(bot.symbol)
            left = rules.minutes_to_close(now)
            day = strategy.style == "day"
            if position:
                if position.external_id is None and rules.contract:
                    position.external_id = f"{rules.contract}:0"  # simulação: guarda o contrato da entrada
                held = (position.external_id or "").split(":")[0]
                if day and left is not None and left <= info.flat_before_min:
                    return await _act(db, bot, broker, executor.closing_side(position.side), price, "Encerramento do day trade antes do fim do pregão", now)
                if held and rules.contract and held != rules.contract:
                    reason = f"Rolagem: {held} perto do vencimento; o robô passa a operar {rules.contract}"
                    return await _act(db, bot, broker, executor.closing_side(position.side), price, reason, now)
            elif day and (left is None or left <= info.flat_before_min + 5):
                await db.commit()
                return TickResult("hold", "Fora do horário de entrada do day trade")

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
        # Duração fixa (ex.: Reversão AMS, 1 candle): a operação termina no fechamento do seu último candle,
        # mesmo que o próximo sinal seja na mesma direção (aí fecha e abre de novo, como no backtest).
        bars = strategy.trade_bars
        finished = bool(position and bars and trade_finished(position.opened_at, candles[-1].open_time, params.timeframe, bars))
        current = "flat" if finished else (position.side.value if position else "flat")
        decision = strategy.decide(candles, current, params, bot.allow_short and broker.supports_short)
        await r.set(seen_key, last_open, ex=7 * 86400)

        target = decision.target
        candle_close_at = datetime.fromtimestamp((candles[-1].close_time + 1) / 1000, UTC)
        candle_close_px = Decimal(str(candles[-1].close))  # referência do sinal (é o preço que o backtest usa)
        if finished and target is None:
            target = "flat"
        entry_note = decision.reason
        signal_expiry: datetime | None = None
        if bars and target in ("long", "short"):
            # Entrada só vale perto da abertura do candle; atrasada, a operação não teria a duração da regra.
            candle_open_ms = candles[-1].close_time + 1
            delay = (now.timestamp() * 1000 - candle_open_ms) / 1000
            if delay > strategy.max_entry_delay_s:
                entry_note = f"Entrada descartada: {delay:.0f}s de atraso desde a abertura do candle ({decision.reason})"
                target = "flat"
            signal_expiry = datetime.fromtimestamp((candle_open_ms + flt.TF_MS[params.timeframe] * bars) / 1000, UTC)
        if not finished and (target is None or target == current):
            await db.commit()
            return TickResult("hold", entry_note)

        # Primeiro encerra a posição atual (se houver); a nova entrada acontece no mesmo ciclo
        # no modo automático, ou vira o próximo sinal no modo sinais.
        closed: TickResult | None = None
        if position:
            close_reason = f"Fim da operação de {bars} candle(s) de {params.timeframe}" if finished else decision.reason
            result = await _act(db, bot, broker, executor.closing_side(position.side), price, close_reason, now, signal_at=candle_close_at, ref_price=candle_close_px)
            if finished and target == "flat" and entry_note != decision.reason:
                result = TickResult(result.action, f"{result.detail} · {entry_note}")
            if bot.exec_mode == ExecMode.signals and finished and target != "flat" and result.action == "signal":
                closed = result  # sinal de saída emitido; o sinal da nova operação vem em seguida
            elif target == "flat" or bot.exec_mode == ExecMode.signals or result.action != "executed":
                return result
            else:
                await db.refresh(bot)
                if await executor.get_position(db, bot.id):
                    return result  # fechamento ainda não confirmado
                closed = result

        # Filtros de entrada: barram só a abertura de posição, nunca a saída.
        if filters.any_entry_filter:
            htf = None
            if filters.htf:
                htf = strategy.closed_only(await broker.get_klines(bot.symbol, filters.htf, filters.htf_lookback() + 2), int(now.timestamp() * 1000))
            family = flt.STRATEGY_FAMILY.get(bot.strategy, "trend")
            why = flt.entry_block(filters, family, target, candles, htf, int(now.timestamp() * 1000))  # type: ignore[arg-type]
            if why:
                await db.commit()
                note = f"Entrada filtrada: {why}"
                return TickResult(closed.action, f"{closed.detail} · {note}") if closed else TickResult("hold", note)

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
        if closed:
            entry = await _act(db, bot, broker, side, price, decision.reason, now, signal_expiry, signal_at=candle_close_at, ref_price=candle_close_px)
            return TickResult(entry.action, f"{closed.detail} · {entry.detail}")
        return await _act(db, bot, broker, side, price, decision.reason, now, signal_expiry, signal_at=candle_close_at, ref_price=candle_close_px)
    finally:
        await broker.close()


async def run_risk_tick(
    db: AsyncSession, bot: Bot, factory: BrokerFactory = broker_for_bot, price: Decimal | None = None, now: datetime | None = None
) -> TickResult:
    """Conferência rápida de uma posição aberta: stop, alvo e tempo máximo, sem baixar candles.

    Chamada pelo agendador quando o preço em tempo real cruza um nível, ou a cada poucos segundos.
    Saídas não dependem de assinatura nem de filtros: proteger a posição vem sempre primeiro.
    """
    now = now or datetime.now(UTC)
    if get_strategy(bot.strategy).kind == "ladder":
        # Grid e DCA: o preço cruzou um nível (ou é a conferência periódica); o ciclo completo é leve (sem candles).
        return await run_tick(db, bot, factory, now, price)
    position = await executor.get_position(db, bot.id)
    if not position:
        return TickResult("skipped", "Sem posição aberta")
    strategy = get_strategy(bot.strategy)
    params = strategy.parse_params(bot.params)
    broker = await factory(db, bot)
    try:
        if position.external_id:  # stop/alvo guardados na corretora (cTrader, MT5)
            if await executor.sync_broker_closes(db, bot, broker):
                return TickResult("executed", "Encerrada pela corretora")
        if price is None:
            price = await broker.get_price(bot.symbol)
        reason = exit_reason(bot, position, price, strategy.max_hold_minutes(params), now)
        if not reason:
            return TickResult("hold")
        return await _act(db, bot, broker, executor.closing_side(position.side), price, reason, now)
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
