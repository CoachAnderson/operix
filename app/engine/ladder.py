"""Robô ao vivo de grade (Grid) e de compra programada (DCA) na Binance à vista (conta do próprio cliente).

A cada ciclo (fechamento de candle, preço em tempo real cruzando um nível, ou conferência periódica):
1. resolve a ordem pendente do ciclo anterior (se a corretora não respondeu, espera; nunca envia em dobro);
2. compara o preço com os níveis (app/strategies/ladder.py) e envia ordens a mercado de lotes;
3. guarda no robô (bot.state) os lotes comprados, os níveis e o lucro acumulado.

A ordem pendente é gravada no MESMO commit que registra a intenção da ordem: se o processo cair no meio, o próximo
ciclo descobre pela ordem (preenchida, recusada ou ainda sem resposta) o que aconteceu.
"""
from __future__ import annotations

import logging
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.engine import executor
from app.models import Bot, BotStatus, ExecMode, Order, OrderStatus, Side
from app.services.audit import audit
from app.services.brokers.base import Broker, BrokerError, Fill
from app.services.brokers.paper import PaperBroker
from app.strategies import ladder as L
from app.strategies.library import get_strategy

log = logging.getLogger(__name__)
RETRY_AFTER = timedelta(minutes=5)  # depois de uma recusa (ex.: saldo insuficiente), espera antes de tentar de novo


class Result:
    def __init__(self, action: str, detail: str = ""):
        self.action, self.detail = action, detail


def _ms(dt: datetime) -> int:
    return int(dt.timestamp() * 1000)


def _d(v: Any) -> Decimal:
    return Decimal(str(v or 0))


def _save(bot: Bot, state: dict[str, Any]) -> None:
    bot.state = dict(state)  # novo objeto: o SQLAlchemy só percebe a mudança do JSON assim


def lots_qty(state: dict[str, Any], slots: list[int]) -> tuple[Decimal, Decimal, Decimal]:
    lots = state.get("lots") or {}
    qty = sum((_d(lots[str(i)]["qty"]) for i in slots if str(i) in lots), Decimal("0"))
    cost = sum((_d(lots[str(i)]["cost"]) for i in slots if str(i) in lots), Decimal("0"))
    fee = sum((_d(lots[str(i)]["fee"]) for i in slots if str(i) in lots), Decimal("0"))
    return qty, cost, fee


def _filled(order: Order, fill: Fill | None) -> tuple[Decimal, Decimal, Decimal, Decimal]:
    """(quantidade líquida, valor, taxa, preço) de uma ordem executada."""
    if fill is not None:
        return fill.net_base_qty, fill.quote_qty, fill.fee_quote, fill.avg_price
    price = order.price or Decimal("0")
    fee = order.fee_quote or Decimal("0")
    net = order.qty - (fee / price if order.side == Side.buy and price else Decimal("0"))
    return net, order.quote_qty or order.qty * price, fee, price


def apply_to_state(strategy, params, state: dict[str, Any], pend: dict[str, Any], order: Order, fill: Fill | None,
                   now: datetime) -> dict[str, Any]:
    """Atualiza os lotes e o ciclo com o resultado de uma ordem executada."""
    s = dict(state)
    op = pend.get("op")
    net, quote, fee, price = _filled(order, fill)
    if op in ("grid_buy", "grid_initial"):
        slots = pend.get("slots") or []
        lots = dict(s.get("lots") or {})
        n = Decimal(len(slots) or 1)
        for i in slots:
            lots[str(i)] = {"qty": str(net / n), "cost": str(quote / n), "fee": str(fee / n), "price": float(price), "at": now.isoformat()}
        s["lots"] = lots
        s["armed"] = [i for i in (s.get("armed") or []) if str(i) not in lots]
        if op == "grid_initial":
            s["started"] = True
    elif op in ("grid_sell", "grid_stop"):
        lots = dict(s.get("lots") or {})
        slots = pend.get("slots") or list(map(int, lots))
        for i in slots:
            lots.pop(str(i), None)
        s["lots"] = lots
        # Sobra do arredondamento da quantidade (a corretora vende em múltiplos do passo do par): fica para a próxima venda.
        total_q, total_c = _d(pend.get("total_q")), _d(pend.get("total_c"))
        sold = fill.executed_qty if fill is not None else order.qty
        if op == "grid_sell" and total_q > sold > 0:
            s["spare"] = {"qty": str(total_q - sold), "cost": str(total_c - total_c * sold / total_q)}
        else:
            s.pop("spare", None)
        s["profit"] = float(s.get("profit") or 0) + float(order.realized_pnl or 0)
        if op == "grid_sell":
            s["rounds"] = int(s.get("rounds") or 0) + len(slots)
            s["armed"] = L.grid_rearm(s, float(price))
    elif op == "dca_buy":
        s = L.dca_after_buy(s, float(net), float(quote), float(fee), float(price), _ms(now))
    elif op == "dca_sell":
        s = L.dca_after_sell(params, s, float(order.realized_pnl or 0), _ms(now))
        if str(pend.get("reason", "")).startswith("Stop"):
            s["done"] = True
    s.pop("pending", None)
    s.pop("retry_at", None)
    s.pop("last_error", None)
    return s


async def _resolve_pending(db: AsyncSession, bot: Bot, strategy, params, state: dict[str, Any], now: datetime) -> tuple[dict, str | None]:
    pend = state.get("pending")
    if not pend:
        return state, None
    order = await db.scalar(select(Order).where(Order.client_order_id == pend.get("coid")))
    if order is None or order.status in (OrderStatus.rejected, OrderStatus.canceled):
        state = {k: v for k, v in state.items() if k != "pending"}
        return state, None
    if order.status in (OrderStatus.new, OrderStatus.unknown):
        return state, "Aguardando a corretora confirmar a ordem anterior"
    return apply_to_state(strategy, params, state, pend, order, None, now), None


async def _send(db: AsyncSession, bot: Bot, broker: Broker, state: dict[str, Any], strategy, params, pend: dict[str, Any],
                side: Side, reason: str, now: datetime, price: Decimal, *, quote: Decimal | None = None, qty: Decimal | None = None,
                lot_cost: Decimal | None = None, lot_fee: Decimal | None = None, lot_qty: Decimal | None = None) -> tuple[dict[str, Any], Result]:
    def register(order: Order) -> None:
        _save(bot, {**state, "pending": {**pend, "coid": order.client_order_id}})

    try:
        if side == Side.buy and isinstance(broker, PaperBroker) and quote is not None and broker.account.quote < quote:
            # Na conta real a Binance recusa; a simulação compraria só o que sobrou, desfigurando o lote.
            raise BrokerError(f"Saldo simulado insuficiente: livre {broker.account.quote:.2f}, compra de {quote:.2f}")
        order, fill = await executor.ladder_order(db, bot, broker, side, reason, quote_amount=quote, qty=qty, ref_price=price,
                                                  signal_at=now, lot_cost=lot_cost, lot_fee=lot_fee, lot_qty=lot_qty,
                                                  on_registered=register)
    except executor.ExecutionBlocked as exc:
        return state, Result("blocked", str(exc))
    except BrokerError as exc:
        if exc.retryable:
            raise
        # Recusa definitiva (saldo, mínimo do par...): registra e espera antes de tentar de novo, sem parar o robô.
        new = {k: v for k, v in state.items() if k != "pending"}
        new["last_error"] = str(exc)[:200]
        new["retry_at"] = (now + RETRY_AFTER).isoformat()
        _save(bot, new)
        await db.commit()
        return new, Result("blocked", f"Corretora recusou: {exc}")
    if fill is None:
        await db.commit()
        return {**state, "pending": {**pend, "coid": order.client_order_id}}, Result("executed", f"{reason} (aguardando confirmação)")
    new = apply_to_state(strategy, params, state, pend, order, fill, now)
    _save(bot, new)
    await db.commit()
    return new, Result("executed", f"{side.value} {fill.executed_qty} a {fill.avg_price}: {reason}")


async def tick(db: AsyncSession, bot: Bot, broker: Broker, price: Decimal | None, now: datetime) -> Result:
    strategy = get_strategy(bot.strategy)
    params = strategy.parse_params(bot.params)
    if bot.exec_mode != ExecMode.auto:
        return Result("blocked", f"{strategy.name} só funciona no modo automático. Mude o modo do robô.")
    state = dict(bot.state or {})
    state, wait = await _resolve_pending(db, bot, strategy, params, state, now)
    _save(bot, state)
    if wait:
        await db.commit()
        return Result("hold", wait)
    if state.get("retry_at") and now < datetime.fromisoformat(state["retry_at"]):
        await db.commit()
        return Result("hold", f"Esperando para tentar de novo depois da recusa: {state.get('last_error', '')}")
    price = price if price is not None else await broker.get_price(bot.symbol)
    bot.last_tick_at = now
    if isinstance(strategy, L.GridSpot):
        return await _grid(db, bot, broker, strategy, params, state, price, now)
    return await _dca(db, bot, broker, strategy, params, state, price, now)


async def _stop_bot(db: AsyncSession, bot: Bot, reason: str) -> None:
    bot.status = BotStatus.stopped
    bot.status_reason = reason[:255]
    await audit(db, "bot.stopped", None, target=str(bot.id), reason=reason[:200])
    await db.commit()


# ------------------------------------------------------------------ Grid
async def _grid(db, bot, broker, strategy, params, state, price: Decimal, now) -> Result:
    p = float(price)
    size = _d(bot.order_size_quote)
    if state.get("kind") != "grid" or not state.get("levels"):
        lower, _upper = L.grid_bounds(params, p)
        if p < lower:
            await db.commit()
            return Result("hold", f"Preço {p:.8g} abaixo do piso da grade ({lower:.8g}): aguardando entrar na faixa")
        state = L.grid_new_state(params, p)
        _save(bot, state)
        await db.commit()
    if not state.get("started"):
        initial = state.get("initial") or []
        if not initial:
            state["started"] = True
            _save(bot, state)
            await db.commit()
        else:
            state, res = await _send(db, bot, broker, state, strategy, params, {"op": "grid_initial", "slots": initial}, Side.buy,
                                     f"Grade montada: compra dos {len(initial)} lotes acima do preço", now, price,
                                     quote=size * len(initial))
            return res

    stop = L.grid_stop_price(params, state)
    if stop is not None and p <= stop and state.get("lots"):
        slots = sorted(map(int, state["lots"]))
        qty, cost, fee = lots_qty(state, slots)
        pos = await executor.get_position(db, bot.id)
        cost = pos.cost_basis if pos is not None and pos.cost_basis is not None else cost  # vende tudo: custo de tudo
        state, res = await _send(db, bot, broker, state, strategy, params, {"op": "grid_stop", "slots": slots}, Side.sell,
                                 f"Stop: preço abaixo de {stop:.8g} ({params.stop_below_pct:g}% abaixo do piso)", now, price,
                                 qty=None, lot_cost=cost, lot_fee=fee)
        if res.action == "executed" and "pending" not in state:
            await _stop_bot(db, bot, f"Stop da grade atingido em {p:.8g}: lotes vendidos, robô parado")
        return res

    sells, buys = L.grid_triggers(state, p)
    results: list[str] = []
    if sells:
        qty, cost, fee = lots_qty(state, sells)
        pos = await executor.get_position(db, bot.id)
        spare = state.get("spare") or {}
        if pos is not None and spare:
            qty += _d(spare.get("qty"))
            cost += _d(spare.get("cost"))
        if pos is None or qty <= 0:
            state = {**state, "lots": {k: v for k, v in state["lots"].items() if int(k) not in sells}}
            _save(bot, state)
            await db.commit()
            results.append("Lotes sem saldo correspondente foram descartados")
        else:
            levels = state["levels"]
            label = ", ".join(f"{levels[i + 1]:.8g}" for i in sells[:4]) + ("…" if len(sells) > 4 else "")
            state, res = await _send(db, bot, broker, state, strategy, params,
                                     {"op": "grid_sell", "slots": sells, "total_q": str(qty), "total_c": str(cost)}, Side.sell,
                                     f"Grade: venda de {len(sells)} lote(s) no(s) nível(is) {label}", now, price,
                                     qty=min(qty, pos.qty), lot_cost=cost, lot_fee=fee, lot_qty=qty)
            if res.action != "executed" or "pending" in state:
                return res
            if state.get("spare") and await executor.get_position(db, bot.id) is None:
                state = {k: v for k, v in state.items() if k != "spare"}  # sobra abaixo do mínimo: a posição foi zerada
                _save(bot, state)
            results.append(res.detail)
    if buys:
        levels = state["levels"]
        label = ", ".join(f"{levels[i]:.8g}" for i in buys[:4]) + ("…" if len(buys) > 4 else "")
        state, res = await _send(db, bot, broker, state, strategy, params, {"op": "grid_buy", "slots": buys}, Side.buy,
                                 f"Grade: compra de {len(buys)} lote(s) no(s) nível(is) {label}", now, price, quote=size * len(buys))
        if res.action != "executed":
            return Result(res.action, " · ".join([*results, res.detail]))
        results.append(res.detail)
    armed = L.grid_rearm(state, p)
    if armed != state.get("armed"):
        state = {**state, "armed": armed}
        _save(bot, state)
    await db.commit()
    if results:
        return Result("executed", " · ".join(results))
    nb, ns = L.grid_next_levels(state)
    parts = [f"próxima compra em {nb:.8g}" if nb else "nenhuma compra armada", f"próxima venda em {ns:.8g}" if ns else "nenhum lote para vender"]
    return Result("hold", "Grade: " + ", ".join(parts))


# ------------------------------------------------------------------ DCA
async def _dca(db, bot, broker, strategy, params, state, price: Decimal, now) -> Result:
    if state.get("kind") != "dca":
        state = L.dca_new_state()
        _save(bot, state)
    if state.get("done"):
        await _stop_bot(db, bot, "Ciclo encerrado (alvo sem recomeçar, ou stop). Ligue de novo para começar outro ciclo.")
        return Result("skipped", "Ciclo encerrado")
    p = float(price)
    act = L.dca_action(params, state, p, _ms(now))
    if not act:
        lv = L.dca_levels(params, state)
        await db.commit()
        if state.get("orders"):
            parts = [f"Ciclo {state.get('cycle')}: {state['orders']} de {params.max_orders} compras, médio {lv['avg']:.8g}, alvo {lv['take']:.8g}"]
            if lv["next_buy"]:
                parts.append(f"próxima compra em {lv['next_buy']:.8g}")
            return Result("hold", ", ".join(parts))
        return Result("hold", "Aguardando o próximo ciclo")
    kind, reason, _level = act
    if kind == "buy":
        k = int(state.get("orders") or 0)
        quote = _d(L.dca_order_quote(params, float(bot.order_size_quote or 0), k)).quantize(Decimal("0.00000001"))
        state, res = await _send(db, bot, broker, state, strategy, params, {"op": "dca_buy", "k": k}, Side.buy, reason, now, price, quote=quote)
        return res
    pos = await executor.get_position(db, bot.id)
    if pos is None:
        state = L.dca_after_sell(params, state, 0.0, _ms(now))
        _save(bot, state)
        await db.commit()
        return Result("hold", "Ciclo sem saldo correspondente; recomeçando")
    state, res = await _send(db, bot, broker, state, strategy, params, {"op": "dca_sell", "reason": reason}, Side.sell, reason, now, price,
                             qty=pos.qty)
    if res.action == "executed" and "pending" not in state and state.get("done"):
        await _stop_bot(db, bot, "Ciclo encerrado pelo stop" if reason.startswith("Stop") else "Ciclo concluído no alvo (sem recomeçar)")
    return res


# ------------------------------------------------------------------ para o agendador e as telas
def trigger_levels(bot: Bot) -> tuple[float | None, float | None, float | None, bool]:
    """(compra quando o preço CAIR até, vende quando SUBIR até, stop quando CAIR até, precisa agir já)."""
    try:
        strategy = get_strategy(bot.strategy)
        params = strategy.parse_params(bot.params)
    except Exception:  # noqa: BLE001
        return None, None, None, False
    state = bot.state or {}
    if state.get("pending"):
        return None, None, None, True
    if state.get("retry_at") and datetime.now(UTC) < datetime.fromisoformat(state["retry_at"]):
        return None, None, None, False  # recusada há pouco: a conferência periódica tenta de novo depois
    if isinstance(strategy, L.GridSpot):
        if not state.get("levels") or not state.get("started"):
            return None, None, None, True
        nb, ns = L.grid_next_levels(state)
        return nb, ns, L.grid_stop_price(params, state), False
    if not state.get("orders"):
        return None, None, None, True
    lv = L.dca_levels(params, state)
    return lv["next_buy"], lv["take"], lv["stop"], False


def summary(bot: Bot, price: float | None = None) -> dict[str, Any]:
    """Situação da grade ou do ciclo, para a tela do robô."""
    strategy = get_strategy(bot.strategy)
    params = strategy.parse_params(bot.params)
    state = bot.state or {}
    size = float(bot.order_size_quote or 0)
    out: dict[str, Any] = {"kind": "grid" if isinstance(strategy, L.GridSpot) else "dca",
                           "capital": L.capital_needed(strategy, params, size), "order_size": size,
                           "pending": bool(state.get("pending")), "last_error": state.get("last_error"),
                           "profit": float(state.get("profit") or 0), "rounds": int(state.get("rounds") or 0)}
    if out["kind"] == "grid":
        levels = state.get("levels") or []
        lots = state.get("lots") or {}
        armed = set(state.get("armed") or [])
        out.update(started=bool(state.get("started")), anchor=state.get("anchor"), levels=levels,
                   stop=L.grid_stop_price(params, state) if levels else None)
        if levels:
            lo, hi = L.grid_step_pct(levels)
            out.update(step_min_pct=lo, step_max_pct=hi, lower=levels[0], upper=levels[-1])
            out["slots"] = [
                {"i": i, "buy": levels[i], "sell": levels[i + 1],
                 "status": "holding" if str(i) in lots else ("armed" if i in armed else "idle"),
                 "qty": float(lots[str(i)]["qty"]) if str(i) in lots else None,
                 "cost": float(lots[str(i)]["cost"]) if str(i) in lots else None,
                 "bought_at": lots[str(i)]["price"] if str(i) in lots else None}
                for i in range(len(levels) - 1)
            ]
            held_qty = sum(float(v["qty"]) for v in lots.values())
            held_cost = sum(float(v["cost"]) for v in lots.values())
            out.update(lots=len(lots), held_cost=held_cost,
                       open_result=(held_qty * price - held_cost) if price is not None else None)
            nb, ns = L.grid_next_levels(state)
            out.update(next_buy=nb, next_sell=ns)
    else:
        lv = L.dca_levels(params, state)
        out.update(cycle=int(state.get("cycle") or 0), orders=int(state.get("orders") or 0), max_orders=params.max_orders,
                   trigger=params.trigger, avg=lv["avg"], take=lv["take"], stop=lv["stop"], next_buy=lv["next_buy"],
                   cost=float(state.get("cost") or 0), qty=float(state.get("qty") or 0), done=bool(state.get("done")),
                   first_price=state.get("first_price"),
                   next_time=(state["last_at"] + params.interval_hours * 3_600_000) if params.trigger == "time" and state.get("last_at") and state.get("orders", 0) < params.max_orders else None,
                   plan=[{"k": k, "quote": L.dca_order_quote(params, size, k),
                          "drop_pct": L.dca_drop_pct(params, k) if k else 0.0,
                          "price": (float(state["first_price"]) * (1 - L.dca_drop_pct(params, k) / 100)) if state.get("first_price") and params.trigger == "drop" else None,
                          "done": k < int(state.get("orders") or 0)} for k in range(params.max_orders)])
        if price is not None and out["qty"]:
            out["open_result"] = out["qty"] * price - out["cost"]
    return out
