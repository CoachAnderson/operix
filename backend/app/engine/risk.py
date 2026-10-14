"""Gerenciador de risco: limites diários, stop loss/take profit, tempo máximo e kill switch."""
from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from decimal import Decimal

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.redis import get_redis
from app.models import Bot, Order, OrderStatus, Position, PosSide, SystemSetting

KILL_SWITCH_KEY = "kill_switch"


@dataclass
class DailyStats:
    realized_pnl: Decimal
    trades: int


def day_start(now: datetime | None = None) -> datetime:
    now = now or datetime.now(UTC)
    return now.replace(hour=0, minute=0, second=0, microsecond=0)


async def daily_stats(db: AsyncSession, bot_id, now: datetime | None = None) -> DailyStats:
    since = day_start(now)
    row = (
        await db.execute(
            select(func.coalesce(func.sum(Order.realized_pnl), 0), func.count(Order.id)).where(
                Order.bot_id == bot_id,
                Order.created_at >= since,
                Order.status.in_([OrderStatus.filled, OrderStatus.partially_filled]),
            )
        )
    ).one()
    return DailyStats(realized_pnl=Decimal(str(row[0])), trades=int(row[1]))


def entry_block_reason(bot: Bot, stats: DailyStats) -> tuple[str | None, bool]:
    """Retorna (motivo, pausar_robô). Motivo None = entrada liberada."""
    if stats.trades >= bot.max_trades_per_day:
        return f"Limite de {bot.max_trades_per_day} operações no dia atingido", False
    if bot.max_daily_loss_quote and stats.realized_pnl <= -bot.max_daily_loss_quote:
        return f"Perda diária máxima ({bot.max_daily_loss_quote}) atingida", True
    return None, False


def exit_reason(bot: Bot, position: Position, price: Decimal, max_hold_minutes: int | None, now: datetime | None = None) -> str | None:
    if position.avg_price <= 0:
        return None
    # Variação a favor da posição: alta para comprado, queda para vendido.
    sign = -1 if position.side == PosSide.short else 1
    change_pct = sign * (price - position.avg_price) / position.avg_price * 100
    if bot.stop_loss_pct and change_pct <= -bot.stop_loss_pct:
        return f"Stop loss: {change_pct:.2f}%"
    if bot.take_profit_pct and change_pct >= bot.take_profit_pct:
        return f"Take profit: {change_pct:.2f}%"
    if max_hold_minutes:
        now = now or datetime.now(UTC)
        opened = position.opened_at if position.opened_at.tzinfo else position.opened_at.replace(tzinfo=UTC)
        if now - opened >= timedelta(minutes=max_hold_minutes):
            return f"Tempo máximo de {max_hold_minutes} min atingido"
    return None


async def kill_switch_state(db: AsyncSession) -> dict:
    r = get_redis()
    cached = await r.get(KILL_SWITCH_KEY)
    if cached is not None:
        return json.loads(cached)
    row = await db.get(SystemSetting, KILL_SWITCH_KEY)
    state = row.value if row else {"enabled": False, "reason": ""}
    await r.set(KILL_SWITCH_KEY, json.dumps(state), ex=30)
    return state


async def set_kill_switch(db: AsyncSession, enabled: bool, reason: str) -> dict:
    state = {"enabled": enabled, "reason": reason, "at": datetime.now(UTC).isoformat()}
    row = await db.get(SystemSetting, KILL_SWITCH_KEY)
    if row:
        row.value = state
    else:
        db.add(SystemSetting(key=KILL_SWITCH_KEY, value=state))
    await get_redis().set(KILL_SWITCH_KEY, json.dumps(state), ex=30)
    return state
