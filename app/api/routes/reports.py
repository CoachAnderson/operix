"""Relatórios do assinante: lista de moedas (abertas primeiro) e download em PDF."""

from __future__ import annotations

import asyncio
import re
import unicodedata
from datetime import UTC, date, datetime, time, timedelta
from decimal import Decimal

from fastapi import APIRouter, HTTPException, Query, Request, Response, status
from pydantic import BaseModel
from sqlalchemy import select

from app.api.deps import DB, CurrentUser
from app.core.config import get_settings
from app.core.ratelimit import client_ip, hit
from app.models import Bot, Market, Order, OrderStatus, Position, PosSide, Venue
from app.services import b3
from app.services.audit import audit
from app.services.report_pdf import TZ, OpenRow, OrderRow, ReportData, render

router = APIRouter(prefix="/reports", tags=["relatórios"])

MAX_ORDERS = 5000
MAX_DAYS = 3 * 366
MAX_SYMBOLS = 60
EXECUTED = (OrderStatus.filled, OrderStatus.partially_filled)


class ReportSymbol(BaseModel):
    symbol: str
    market: Market
    open: bool  # há posição aberta nessa moeda
    open_sides: list[PosSide]
    bots: int


@router.get("/symbols", response_model=list[ReportSymbol])
async def report_symbols(user: CurrentUser, db: DB) -> list[ReportSymbol]:
    """Moedas dos robôs do assinante. As que têm posição aberta vêm primeiro (a tela já as deixa marcadas)."""
    bots = list(await db.scalars(select(Bot).where(Bot.user_id == user.id)))
    positions = {
        p.bot_id: p
        for p in await db.scalars(select(Position).join(Bot, Bot.id == Position.bot_id).where(Bot.user_id == user.id))
    }
    out: dict[str, ReportSymbol] = {}
    for b in bots:
        item = out.setdefault(b.symbol, ReportSymbol(symbol=b.symbol, market=b.market, open=False, open_sides=[], bots=0))
        item.bots += 1
        pos = positions.get(b.id)
        if pos:
            item.open = True
            if pos.side not in item.open_sides:
                item.open_sides.append(pos.side)
    return sorted(out.values(), key=lambda s: (not s.open, s.market.value, s.symbol))


def _slug(text: str) -> str:
    ascii_ = unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode()
    return re.sub(r"[^a-z0-9]+", "-", ascii_.lower()).strip("-") or "relatorio"


@router.get("/pdf", response_class=Response, responses={200: {"content": {"application/pdf": {}}}})
async def report_pdf(
    request: Request,
    user: CurrentUser,
    db: DB,
    symbols: list[str] = Query(..., min_length=1, max_length=MAX_SYMBOLS, alias="symbol"),
    start: date = Query(...),
    end: date = Query(...),
    venues: list[Venue] = Query([Venue.paper, Venue.testnet, Venue.live], alias="venue"),
) -> Response:
    if end < start:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "A data final é anterior à inicial")
    if (end - start).days > MAX_DAYS:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Escolha um período de até 3 anos")
    if not venues:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Escolha pelo menos um ambiente")
    await hit(f"report:{user.id}", 20, 600)  # gerar PDF custa CPU

    wanted = sorted({s.strip().upper() for s in symbols if s.strip()})
    if not wanted:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Escolha pelo menos uma moeda")

    # Datas do filtro no horário de Brasília, convertidas para UTC
    since = datetime.combine(start, time.min, TZ).astimezone(UTC)
    until = datetime.combine(end + timedelta(days=1), time.min, TZ).astimezone(UTC)

    q = (
        select(Order, Bot)
        .join(Bot, Bot.id == Order.bot_id)
        .where(
            Order.user_id == user.id,
            Bot.user_id == user.id,
            Order.symbol.in_(wanted),
            Order.venue.in_(venues),
            Order.status.in_(EXECUTED),
            Order.created_at >= since,
            Order.created_at < until,
        )
        .order_by(Order.created_at.desc())
        .limit(MAX_ORDERS + 1)
    )
    rows = (await db.execute(q)).all()
    truncated = len(rows) > MAX_ORDERS
    rows = list(reversed(rows[:MAX_ORDERS]))  # ordem cronológica no PDF
    def contracts(qty, bot: Bot):
        """Futuros da B3: converte a quantidade interna (pontos × valor do ponto) em contratos."""
        if bot.market == Market.b3 and bot.symbol.upper() in b3.FUTURES:
            return qty / Decimal(str(b3.FUTURES[bot.symbol.upper()].point_value))
        return qty

    orders = [
        OrderRow(
            created_at=o.created_at,
            bot_name=b.name,
            symbol=o.symbol,
            market=b.market.value,
            venue=o.venue.value,
            side=o.side.value,
            qty=contracts(o.qty, b),
            price=o.price,
            fee=o.fee_quote or 0,
            pnl=o.realized_pnl,
            reason=o.reason or "",
        )
        for o, b in rows
    ]

    pq = (
        select(Position, Bot)
        .join(Bot, Bot.id == Position.bot_id)
        .where(Bot.user_id == user.id, Bot.symbol.in_(wanted), Bot.venue.in_(venues))
        .order_by(Position.opened_at)
    )
    open_positions = [
        OpenRow(
            bot_name=b.name,
            symbol=b.symbol,
            market=b.market.value,
            venue=b.venue.value,
            side=p.side.value,
            qty=contracts(p.qty, b),
            avg_price=p.avg_price,
            opened_at=p.opened_at,
        )
        for p, b in (await db.execute(pq)).all()
    ]

    brand = get_settings().app_name
    data = ReportData(
        brand=brand,
        user_name=user.name,
        user_email=user.email,
        start=start,
        end=end,
        symbols=wanted,
        venues=[v.value for v in Venue if v in venues],
        orders=orders,
        open_positions=open_positions,
        generated_at=datetime.now(UTC),
        truncated=truncated,
    )
    pdf = await asyncio.to_thread(render, data)

    await audit(db, "report.downloaded", user.id, ip=client_ip(request), symbols=wanted, start=str(start), end=str(end))
    await db.commit()

    filename = f"{_slug(brand)}-relatorio-{start:%Y-%m-%d}-a-{end:%Y-%m-%d}.pdf"
    return Response(
        content=pdf,
        media_type="application/pdf",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )
