"""Execução de ordens com idempotência, persistência antes do envio e atualização de posição.

Uma ordem de COMPRA ou VENDA é interpretada contra a posição atual do robô:
- sem posição: compra abre comprado; venda abre vendido (se o robô e a corretora permitirem);
- com posição: a ordem no sentido contrário encerra a posição.
"""
from __future__ import annotations

import asyncio
import logging
import uuid
from datetime import UTC, datetime, timedelta
from decimal import Decimal

from sqlalchemy import and_, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.redis import get_redis
from app.engine.risk import kill_switch_state
from app.models import Bot, Market, Order, OrderStatus, Position, PosSide, Side, Venue
from app.services.audit import audit
from app.services.brokers.base import Broker, BrokerError, Fill, OrderUnknownError
from app.services.brokers.paper import PaperBroker
from app.engine import sizing
from app.strategies import filters as flt
from app.strategies.base import Strategy
from app.strategies.library import get_strategy

log = logging.getLogger(__name__)


class ExecutionBlocked(Exception):
    pass


def new_client_order_id() -> str:
    # Binance aceita até 36 caracteres [.A-Za-z0-9:/_-]; cTrader até 50.
    return f"tb{uuid.uuid4().hex[:30]}"


def closing_side(pos_side: PosSide) -> Side:
    return Side.sell if pos_side == PosSide.long else Side.buy


class BotLock:
    """Lock distribuído por robô: impede que worker e confirmação manual enviem ordens ao mesmo tempo."""

    def __init__(self, bot_id: uuid.UUID, ttl: int = 60):
        self.key = f"lock:exec:{bot_id}"
        self.token = uuid.uuid4().hex
        self.ttl = ttl

    async def __aenter__(self) -> BotLock:
        if not await get_redis().set(self.key, self.token, ex=self.ttl, nx=True):
            raise ExecutionBlocked("Outra operação deste robô está em andamento")
        return self

    async def __aexit__(self, *exc: object) -> None:
        r = get_redis()
        if await r.get(self.key) == self.token:
            await r.delete(self.key)


async def get_position(db: AsyncSession, bot_id: uuid.UUID) -> Position | None:
    return await db.scalar(select(Position).where(Position.bot_id == bot_id))


def _sync_paper(bot: Bot, broker: Broker) -> None:
    if isinstance(broker, PaperBroker):
        bot.paper_quote_balance = broker.account.quote
        bot.paper_base_balance = broker.account.base


async def apply_fill(db: AsyncSession, bot: Bot, order: Order, fill: Fill, broker: Broker) -> None:
    """Atualiza ordem e posição a partir da execução. Usado no envio, na reconciliação e em fechamentos da corretora."""
    order.exchange_order_id = fill.exchange_order_id
    order.qty = fill.executed_qty
    order.price = fill.avg_price or None
    order.quote_qty = fill.quote_qty
    order.fee_quote = fill.fee_quote
    order.status = {
        "FILLED": OrderStatus.filled,
        "PARTIALLY_FILLED": OrderStatus.partially_filled,
        "NEW": OrderStatus.new,
        "CANCELED": OrderStatus.canceled,
        "EXPIRED": OrderStatus.canceled,
        "REJECTED": OrderStatus.rejected,
    }.get(fill.status, OrderStatus.unknown)
    if fill.executed_qty <= 0:
        return

    position = await get_position(db, bot.id)
    if position is None or fill.side != closing_side(position.side):
        # ---- abertura
        side = PosSide.long if fill.side == Side.buy else PosSide.short
        spot = bot.market == Market.crypto
        if position:  # reforço no mesmo sentido (não usado pelas estratégias atuais)
            total = position.qty + fill.net_base_qty
            position.avg_price = (position.avg_price * position.qty + fill.avg_price * fill.net_base_qty) / total
            position.qty = total
            position.entry_fee += fill.fee_quote
            if position.cost_basis is not None:
                position.cost_basis += fill.quote_qty
        else:
            db.add(
                Position(
                    bot_id=bot.id,
                    side=side,
                    qty=fill.net_base_qty,
                    avg_price=fill.avg_price,
                    cost_basis=fill.quote_qty if spot else None,
                    entry_fee=fill.fee_quote,
                    external_id=fill.external_position_id,
                )
            )
    else:
        # ---- fechamento (total ou parcial)
        sold = min(fill.executed_qty, position.qty)
        share = sold / position.qty if position.qty else Decimal("1")
        entry_fee_part = position.entry_fee * share
        if fill.realized_pnl is not None:  # a corretora informou o resultado (já com swap e comissão de saída)
            pnl = fill.realized_pnl - entry_fee_part
        elif position.cost_basis is not None:  # à vista: recebido líquido menos o custo pago
            pnl = (fill.quote_qty - fill.fee_quote) - position.cost_basis * share
            position.cost_basis -= position.cost_basis * share
        else:  # margem simulada
            sign = 1 if position.side == PosSide.long else -1
            gross = sign * (fill.avg_price - position.avg_price) * sold
            if isinstance(broker, PaperBroker):
                broker.settle(gross)
            pnl = gross - fill.fee_quote - entry_fee_part
        order.realized_pnl = pnl
        order.trade_fees = entry_fee_part + fill.fee_quote  # para separar "resultado do preço" de "taxas"
        position.entry_fee -= entry_fee_part
        position.qty -= sold
        rules = await broker.get_rules(bot.symbol)
        if position.qty <= 0 or rules.floor_qty(position.qty) < rules.min_qty:
            await db.delete(position)  # sobra abaixo do mínimo negociável ("poeira")

    _sync_paper(bot, broker)


async def _protection(bot: Bot, broker: Broker, side: PosSide) -> tuple[Decimal | None, Decimal | None, float | None, Decimal | None]:
    """Stop e alvo em preço absoluto (para corretoras que guardam a proteção no servidor).

    Com stop/alvo pelo ATR, mede o ATR nos candles fechados do tempo gráfico da estratégia; as pernas sem
    ATR continuam pelos percentuais do robô. Devolve também o ATR usado (None no modo percentual).
    """
    f = flt.parse(bot.filters)
    atr_now: float | None = None
    sl_atr = tp_atr = None
    if f.atr_exits:
        timeframe = get_strategy(bot.strategy).parse_params(bot.params).timeframe
        candles = Strategy.closed_only(await broker.get_klines(bot.symbol, timeframe, f.lookback() + 2))
        atr_now = flt.atr_value(candles, f.atr_period)
        if atr_now != atr_now or atr_now <= 0:  # NaN: histórico curto; cai para os percentuais
            atr_now = None
    if not (bot.stop_loss_pct or bot.take_profit_pct or atr_now):
        return None, None, None, None
    ref = await broker.get_price(bot.symbol)
    sign = 1 if side == PosSide.long else -1
    if atr_now:
        s_, t_ = flt.atr_levels(f, side.value, float(ref), atr_now)  # type: ignore[arg-type]
        sl_atr = Decimal(str(s_)) if s_ is not None else None
        tp_atr = Decimal(str(t_)) if t_ is not None else None
    sl = sl_atr or (ref * (1 - sign * bot.stop_loss_pct / 100) if bot.stop_loss_pct else None)
    tp = tp_atr or (ref * (1 + sign * bot.take_profit_pct / 100) if bot.take_profit_pct else None)
    return sl, tp, atr_now, ref


async def plan_entry(bot: Bot, broker: Broker, rules, side: PosSide, always_balance: bool = False) -> tuple[sizing.SizePlan, Decimal | None, Decimal | None, float | None]:
    """Stop/alvo e tamanho da próxima entrada. Usado na execução e na prévia da tela do robô.

    Na execução, o saldo só é consultado quando a regra precisa dele; na prévia, sempre (para mostrar a alavancagem).
    """
    getter = getattr(broker, "account_balance", None)
    required = sizing.needs_balance(bot)
    if required and getter is None:
        raise sizing.SizingBlocked("Esta corretora não informa o saldo; use tamanho fixo e sem limite de alavancagem")

    async def read_balance() -> Decimal | None:
        if getter is None or not (required or always_balance):
            return None
        try:
            return await getter(bot.symbol)
        except BrokerError:
            if required:
                raise
            return None

    # Proteção (preço, candles do ATR) e saldo em paralelo: menos tempo entre o sinal e a ordem.
    (sl, tp, atr_now, ref), balance = await asyncio.gather(_protection(bot, broker, side), read_balance())
    price = ref if ref is not None else await broker.get_price(bot.symbol)
    plan = sizing.compute(bot, rules, price, sl, balance)
    return plan, sl, tp, atr_now


async def execute(db: AsyncSession, bot: Bot, broker: Broker, side: Side, reason: str, actor_id: uuid.UUID | None = None,
                  ref_price: Decimal | None = None, signal_at: datetime | None = None) -> Order:
    ks = await kill_switch_state(db)
    if ks.get("enabled"):
        raise ExecutionBlocked(f"Operações suspensas pela plataforma: {ks.get('reason') or 'manutenção'}")

    async with BotLock(bot.id):
        position = await get_position(db, bot.id)
        rules = await broker.get_rules(bot.symbol)
        if position:
            if side != closing_side(position.side):
                raise ExecutionBlocked(f"O robô já está {'comprado' if position.side == PosSide.long else 'vendido'}")
            opening = None
        else:
            opening = PosSide.long if side == Side.buy else PosSide.short
            if opening == PosSide.short and not (bot.allow_short and broker.supports_short and rules.allow_short):
                raise ExecutionBlocked("Não há posição para vender (este robô não opera vendido)")
            if not rules.is_open():
                raise ExecutionBlocked(f"Mercado de {bot.symbol} fechado agora")

        plan: sizing.SizePlan | None = None
        sl = tp = None
        atr_now: float | None = None
        if opening:
            # Stop, alvo e tamanho ANTES de registrar a ordem: sem tamanho possível, nada é enviado.
            try:
                plan, sl, tp, atr_now = await plan_entry(bot, broker, rules, opening)
            except sizing.SizingBlocked as exc:
                raise ExecutionBlocked(str(exc)) from exc
        note = f" [{plan.note}]" if plan and plan.note else ""
        order = Order(
            bot_id=bot.id,
            user_id=bot.user_id,
            venue=bot.venue,
            client_order_id=new_client_order_id(),
            symbol=bot.symbol,
            side=side,
            qty=position.qty if position else (plan.units or Decimal("0")),  # type: ignore[union-attr]
            quote_qty=plan.quote_amount if plan else None,
            status=OrderStatus.new,
            reason=(reason[: 255 - len(note)] + note),
            ref_price=ref_price,
            signal_at=signal_at,
        )
        db.add(order)
        await db.commit()  # registra a intenção ANTES de enviar: nada se perde se o processo cair

        try:
            if opening:
                fill = await broker.open_position(
                    bot.symbol,
                    opening,
                    order.client_order_id,
                    quote_amount=plan.quote_amount,  # type: ignore[union-attr]
                    units=plan.units,  # type: ignore[union-attr]
                    sl_price=sl,
                    tp_price=tp,
                )
            else:
                fill = await broker.close_position(bot.symbol, position.side, position.qty, order.client_order_id, position.external_id)  # type: ignore[union-attr]
        except OrderUnknownError as exc:
            order.status = OrderStatus.unknown
            order.error = str(exc)[:1000]
            await db.commit()
            log.warning("Ordem %s em estado desconhecido; será reconciliada", order.client_order_id)
            return order
        except BrokerError as exc:
            order.status = OrderStatus.rejected
            order.error = str(exc)[:1000]
            await audit(db, "order.rejected", actor_id or bot.user_id, target=str(bot.id), error=str(exc)[:200])
            await db.commit()
            raise

        await apply_fill(db, bot, order, fill, broker)
        order.filled_at = datetime.now(UTC)
        if opening and atr_now and fill.executed_qty > 0:
            # Guarda stop/alvo pelo ATR a partir do preço REAL de entrada; o motor confere a cada ciclo.
            await db.flush()
            pos = await get_position(db, bot.id)
            if pos is not None:
                f = flt.parse(bot.filters)
                s_, t_ = flt.atr_levels(f, opening.value, float(fill.avg_price), atr_now)  # type: ignore[arg-type]
                pos.stop_price = Decimal(str(round(s_, 10))) if s_ is not None else None
                pos.take_price = Decimal(str(round(t_, 10))) if t_ is not None else None
        await audit(
            db,
            "order.filled",
            actor_id or bot.user_id,
            target=str(bot.id),
            venue=bot.venue.value,
            side=side.value,
            effect="abertura" if opening else "fechamento",
            qty=str(fill.executed_qty),
            price=str(fill.avg_price),
        )
        await db.commit()
        return order


async def sync_broker_closes(db: AsyncSession, bot: Bot, broker: Broker) -> Order | None:
    """Registra fechamentos feitos pela própria corretora (stop/alvo no servidor, stop-out)."""
    position = await get_position(db, bot.id)
    if not position or not position.external_id:
        return None
    fill = await broker.closed_by_broker(bot.symbol, position.external_id)
    if not fill:
        return None
    order = Order(
        bot_id=bot.id,
        user_id=bot.user_id,
        venue=bot.venue,
        client_order_id=fill.client_order_id,
        symbol=bot.symbol,
        side=closing_side(position.side),
        qty=fill.executed_qty,
        status=OrderStatus.new,
        reason="Encerrada pela corretora (stop, alvo ou chamada de margem)",
    )
    db.add(order)
    await apply_fill(db, bot, order, fill, broker)
    await audit(db, "order.closed_by_broker", bot.user_id, target=str(bot.id), pnl=str(order.realized_pnl))
    await db.commit()
    return order


async def reconcile_unknown(db: AsyncSession, bot: Bot, broker: Broker, now: datetime | None = None) -> None:
    """Consulta na corretora ordens que ficaram em estado desconhecido (timeout/5xx)."""
    now = now or datetime.now(UTC)
    # Inclui ordens que ficaram em NEW (processo caiu entre gravar a intenção e receber a resposta).
    stale_new = now - timedelta(seconds=60)
    unknown = (
        await db.scalars(
            select(Order).where(
                Order.bot_id == bot.id,
                or_(Order.status == OrderStatus.unknown, and_(Order.status == OrderStatus.new, Order.created_at < stale_new)),
            )
        )
    ).all()
    for order in unknown:
        if bot.venue == Venue.paper or order.venue == Venue.paper:
            order.status = OrderStatus.rejected  # simulação: sem resposta = não executada
            order.error = "Simulação interrompida antes da execução"
            continue
        try:
            fill = await broker.query_order(bot.symbol, order.client_order_id)
        except BrokerError:
            continue
        if fill:
            await apply_fill(db, bot, order, fill, broker)
            await audit(db, "order.reconciled", bot.user_id, target=str(bot.id), status=fill.status)
        else:
            created = order.created_at if order.created_at.tzinfo else order.created_at.replace(tzinfo=UTC)
            if now - created > timedelta(minutes=2):
                order.status = OrderStatus.rejected
                order.error = (order.error or "") + " | não encontrada na corretora"
    await db.commit()
