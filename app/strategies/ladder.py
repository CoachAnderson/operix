"""Robôs de grade (Grid à vista) e de compra programada (DCA à vista).

Diferente das outras estratégias, que estão "comprado" ou "fora", estes robôs compram e vendem em PARTES (lotes).
Este módulo só tem a lógica pura — quais níveis disparam e quanto comprar —, usada igualmente pelo robô ao vivo
(app/engine/ladder.py) e pelo backtest (app/engine/ladder_backtest.py). Dinheiro e ordens ficam com quem chama.

Grid à vista
------------
A faixa [piso, teto] é dividida em N grades. Cada grade i vai do nível L[i] ao L[i+1] e tem no máximo um lote:
- vazia: compra um lote quando o preço DESCE até L[i] (a compra só fica "armada" depois que o preço esteve acima
  de L[i], como uma ordem de compra posicionada abaixo do preço);
- com lote: vende o lote quando o preço chega a L[i+1] ou acima (lucro de uma grade, menos as taxas).
Na partida, as grades inteiras ACIMA do preço recebem um lote comprado a mercado (como na Binance), para que o
robô também tenha o que vender se o preço subir. Abaixo do piso o robô fica com todos os lotes e só espera
(perda aberta); acima do teto fica só com dinheiro. Stop opcional: abaixo do piso menos X%, vende tudo e para.

DCA à vista (compra programada)
-------------------------------
Um ciclo começa com uma compra base. Depois compra de novo a cada queda (desvio a partir da 1ª compra) ou a cada
N horas, até o número máximo de compras. Quando o preço chega ao alvo acima do custo médio, vende tudo e (se
escolhido) começa outro ciclo. Stop opcional abaixo do custo médio.
"""
from __future__ import annotations

from typing import Any, ClassVar, Literal

from pydantic import Field, model_validator
from pydantic.json_schema import SkipJsonSchema

from app.services.brokers.base import Candle
from app.strategies.base import Decision, Strategy, StrategyParams, Target

# Custo de ida e volta padrão da Binance à vista (taxa 0,1% por lado), para os avisos.
ROUND_TRIP_FEE_PCT = 0.2


# ================================================================ Grid à vista
class GridSpot(Strategy):
    code = "grade_spot"
    name = "Grid à vista (grade)"
    style = "swing"
    kind: ClassVar[str] = "ladder"
    description = (
        "Divide uma faixa de preço em várias grades: compra um pedaço cada vez que o preço desce um degrau e vende esse "
        "pedaço quando sobe o degrau seguinte. Ganha com o vai e vem do preço dentro da faixa; perde se o preço cair "
        "abaixo da faixa e não voltar."
    )
    suggested_max_trades_per_day = None
    notes = (
        "Funciona melhor com o preço andando de lado. Em queda forte o robô termina com todos os lotes comprados e perda aberta; "
        "em alta forte vende tudo cedo e fica só com dinheiro.",
        "Cada grade precisa render bem mais que o custo de ida e volta (0,2% com a taxa padrão da Binance, mais o escorregamento). "
        "Use grades de 0,6% ou mais.",
        "O valor por ordem é o valor de CADA lote. Dinheiro necessário: número de grades × valor por ordem.",
        "As ordens são a mercado, disparadas quando o preço cruza o nível: pode haver pequeno escorregamento além do nível.",
        "Só opera no modo automático (seriam dezenas de confirmações por dia no modo sinais).",
    )

    class Params(StrategyParams):
        timeframe: Literal["1m", "5m", "15m", "1h"] = "5m"
        range_mode: Literal["auto", "manual"] = Field("auto", description="Faixa em % do preço na partida, ou preços fixos")
        lower_pct: float = Field(10.0, ge=0.5, le=80, description="Faixa automática: % abaixo do preço de partida")
        upper_pct: float = Field(10.0, ge=0.5, le=300, description="Faixa automática: % acima do preço de partida")
        lower_price: float | None = Field(None, gt=0, description="Faixa manual: preço do piso")
        upper_price: float | None = Field(None, gt=0, description="Faixa manual: preço do teto")
        grids: int = Field(20, ge=2, le=150, description="Número de grades (lotes)")
        spacing: Literal["geometric", "arithmetic"] = Field("geometric", description="Degraus em % iguais ou em preço igual")
        initial_buy: bool = Field(True, description="Na partida, compra os lotes das grades acima do preço")
        stop_below_pct: float | None = Field(None, ge=0.1, le=80, description="Vende tudo e para se cair X% abaixo do piso")
        max_hold_minutes: SkipJsonSchema[int | None] = None

        @model_validator(mode="after")
        def _check(self) -> GridSpot.Params:
            if self.range_mode == "manual":
                if not self.lower_price or not self.upper_price:
                    raise ValueError("Na faixa manual, informe o preço do piso e do teto")
                if self.lower_price >= self.upper_price:
                    raise ValueError("O piso precisa ser menor que o teto")
            return self

    def required_candles(self, params) -> int:  # type: ignore[override]
        return 3

    def decide(self, candles: list[Candle], position: Target, params, allow_short: bool = False) -> Decision:  # type: ignore[override]
        return Decision.hold("Robô de grade: decide pelos níveis de preço, não por candle")


def grid_bounds(p: GridSpot.Params, anchor: float) -> tuple[float, float]:
    if p.range_mode == "manual":
        return float(p.lower_price), float(p.upper_price)  # type: ignore[arg-type]
    return anchor * (1 - p.lower_pct / 100), anchor * (1 + p.upper_pct / 100)


def grid_levels(lower: float, upper: float, grids: int, spacing: str) -> list[float]:
    if spacing == "arithmetic":
        step = (upper - lower) / grids
        return [lower + step * i for i in range(grids + 1)]
    ratio = (upper / lower) ** (1 / grids)
    return [lower * ratio**i for i in range(grids + 1)]


def grid_step_pct(levels: list[float]) -> tuple[float, float]:
    """Menor e maior degrau da grade, em % (na geométrica são iguais)."""
    steps = [(levels[i + 1] / levels[i] - 1) * 100 for i in range(len(levels) - 1)]
    return min(steps), max(steps)


def grid_new_state(p: GridSpot.Params, price: float) -> dict[str, Any]:
    """Estado inicial: níveis e quais grades recebem lote na partida (as inteiras acima do preço)."""
    lower, upper = grid_bounds(p, price)
    levels = grid_levels(lower, upper, p.grids, p.spacing)
    initial = [i for i in range(p.grids) if levels[i] >= price] if (p.initial_buy and price >= lower) else []
    armed = [i for i in range(p.grids) if levels[i] < price]  # compras posicionadas abaixo do preço
    return {"kind": "grid", "anchor": price, "levels": levels, "lots": {}, "armed": armed, "initial": initial,
            "started": False, "profit": 0.0, "rounds": 0}


def grid_triggers(state: dict[str, Any], price: float) -> tuple[list[int], list[int]]:
    """(grades para vender, grades para comprar) com o preço atual."""
    levels: list[float] = state["levels"]
    lots: dict[str, Any] = state["lots"]
    armed = set(state.get("armed") or [])
    n = len(levels) - 1
    sells = [i for i in range(n) if str(i) in lots and price >= levels[i + 1]]
    buys = [i for i in range(n) if str(i) not in lots and i in armed and price <= levels[i]]
    return sells, buys


def grid_rearm(state: dict[str, Any], price: float) -> list[int]:
    """Grades vazias com o preço acima do nível de compra passam a ter a compra armada."""
    levels: list[float] = state["levels"]
    lots = state["lots"]
    armed = set(state.get("armed") or [])
    armed |= {i for i in range(len(levels) - 1) if str(i) not in lots and price > levels[i]}
    return sorted(i for i in armed if str(i) not in lots)


def grid_stop_price(p: GridSpot.Params, state: dict[str, Any]) -> float | None:
    if not p.stop_below_pct:
        return None
    return state["levels"][0] * (1 - p.stop_below_pct / 100)


def grid_next_levels(state: dict[str, Any]) -> tuple[float | None, float | None]:
    """Próximo nível de compra (o mais alto entre as grades vazias) e de venda (o mais baixo entre as com lote)."""
    levels: list[float] = state.get("levels") or []
    lots = state.get("lots") or {}
    armed = set(state.get("armed") or [])
    n = len(levels) - 1
    buys = [levels[i] for i in range(n) if str(i) not in lots and i in armed]
    sells = [levels[i + 1] for i in range(n) if str(i) in lots]
    return (max(buys) if buys else None), (min(sells) if sells else None)


def grid_capital(p: GridSpot.Params, order_size: float) -> float:
    return p.grids * order_size


# ================================================================ DCA à vista
class DcaSpot(Strategy):
    code = "dca_spot"
    name = "Compra programada (DCA à vista)"
    style = "swing"
    kind: ClassVar[str] = "ladder"
    description = (
        "Compra em partes: uma compra inicial e novas compras a cada queda (ou a cada intervalo de tempo), baixando o "
        "preço médio. Quando o preço sobe até o alvo acima do custo médio, vende tudo e recomeça."
    )
    suggested_max_trades_per_day = None
    notes = (
        "O alvo é medido sobre o custo médio de todas as compras do ciclo; a taxa da venda (0,1%) sai do lucro.",
        "Em queda longa o robô usa todas as compras e fica esperando a volta, com perda aberta. Defina um stop se não quiser esperar.",
        "Multiplicador de volume acima de 1 aumenta cada nova compra (como um martingale): o ciclo fica mais caro rápido. "
        "Confira o dinheiro necessário antes de ligar.",
        "Só opera no modo automático.",
    )

    class Params(StrategyParams):
        timeframe: Literal["5m", "15m", "1h", "4h"] = "15m"
        trigger: Literal["drop", "time"] = Field("drop", description="Novas compras a cada queda ou a cada intervalo de tempo")
        deviation_pct: float = Field(1.5, ge=0.2, le=30, description="Queda (a partir da 1ª compra) para a 2ª compra, em %")
        step_mult: float = Field(1.2, ge=1.0, le=3.0, description="Cada nova queda exigida é multiplicada por este valor")
        interval_hours: float = Field(24, ge=1, le=720, description="Modo tempo: horas entre as compras")
        max_orders: int = Field(6, ge=1, le=30, description="Número máximo de compras por ciclo (inclui a primeira)")
        volume_mult: float = Field(1.0, ge=1.0, le=3.0, description="Cada nova compra é multiplicada por este valor")
        take_profit_pct: float = Field(2.0, ge=0.3, le=100, description="Alvo acima do custo médio, em %")
        stop_loss_pct: float | None = Field(None, ge=0.5, le=90, description="Stop abaixo do custo médio, em %")
        restart: bool = Field(True, description="Depois do alvo, começa um novo ciclo")
        cooldown_minutes: int = Field(0, ge=0, le=10_080, description="Espera entre um ciclo e o próximo")
        max_hold_minutes: SkipJsonSchema[int | None] = None

    def required_candles(self, params) -> int:  # type: ignore[override]
        return 3

    def decide(self, candles: list[Candle], position: Target, params, allow_short: bool = False) -> Decision:  # type: ignore[override]
        return Decision.hold("Compra programada: decide pelo preço e pelo relógio, não por candle")


def dca_order_quote(p: DcaSpot.Params, base_quote: float, k: int) -> float:
    """Valor da k-ésima compra do ciclo (k = 0 é a compra inicial)."""
    return base_quote * p.volume_mult**k


def dca_capital(p: DcaSpot.Params, base_quote: float) -> float:
    return sum(dca_order_quote(p, base_quote, k) for k in range(p.max_orders))


def dca_drop_pct(p: DcaSpot.Params, k: int) -> float:
    """Queda acumulada, a partir da 1ª compra, que dispara a k-ésima compra (k >= 1)."""
    return p.deviation_pct * sum(p.step_mult**j for j in range(k))


def dca_new_state() -> dict[str, Any]:
    return {"kind": "dca", "cycle": 0, "orders": 0, "qty": 0.0, "cost": 0.0, "fees": 0.0, "first_price": None,
            "last_at": None, "cycle_started_at": None, "cooldown_until": None, "done": False, "profit": 0.0, "rounds": 0}


def dca_levels(p: DcaSpot.Params, state: dict[str, Any]) -> dict[str, float | None]:
    """Preço médio, alvo, stop e próxima compra (por queda) do ciclo atual."""
    qty, cost = float(state.get("qty") or 0), float(state.get("cost") or 0)
    if not state.get("orders") or qty <= 0:
        return {"avg": None, "take": None, "stop": None, "next_buy": None}
    avg = cost / qty
    nxt = None
    if p.trigger == "drop" and state["orders"] < p.max_orders and state.get("first_price"):
        nxt = float(state["first_price"]) * (1 - dca_drop_pct(p, state["orders"]) / 100)
    return {
        "avg": avg,
        "take": avg * (1 + p.take_profit_pct / 100),
        "stop": avg * (1 - p.stop_loss_pct / 100) if p.stop_loss_pct else None,
        "next_buy": nxt,
    }


def dca_action(p: DcaSpot.Params, state: dict[str, Any], price: float, now_ms: int) -> tuple[str, str, float | None] | None:
    """O que fazer agora: ("buy", motivo, preço de disparo) | ("sell", motivo, preço de disparo) | None.

    O preço de disparo serve ao backtest (execução no nível cruzado); ao vivo, a ordem é a mercado.
    """
    if state.get("done"):
        return None
    k = int(state.get("orders") or 0)
    if k == 0:
        if state.get("cooldown_until") and now_ms < state["cooldown_until"]:
            return None
        return ("buy", "Compra inicial do ciclo", None)
    lv = dca_levels(p, state)
    if lv["take"] is not None and price >= lv["take"]:
        return ("sell", f"Alvo de {p.take_profit_pct:g}% sobre o custo médio", lv["take"])
    if lv["stop"] is not None and price <= lv["stop"]:
        return ("sell", f"Stop de {p.stop_loss_pct:g}% abaixo do custo médio", lv["stop"])
    if k >= p.max_orders:
        return None
    if p.trigger == "drop":
        if lv["next_buy"] is not None and price <= lv["next_buy"]:
            return ("buy", f"Compra {k + 1} de {p.max_orders}: queda de {dca_drop_pct(p, k):.2f}% desde a 1ª compra", lv["next_buy"])
        return None
    if state.get("last_at") is not None and now_ms >= state["last_at"] + p.interval_hours * 3_600_000:
        return ("buy", f"Compra {k + 1} de {p.max_orders}: {p.interval_hours:g} h desde a anterior", None)
    return None


def dca_after_buy(state: dict[str, Any], qty: float, cost: float, fee: float, price: float, now_ms: int) -> dict[str, Any]:
    s = dict(state)
    if not s.get("orders"):
        s["cycle"] = int(s.get("cycle") or 0) + 1
        s["first_price"] = price
        s["cycle_started_at"] = now_ms
    s["orders"] = int(s.get("orders") or 0) + 1
    s["qty"] = float(s.get("qty") or 0) + qty
    s["cost"] = float(s.get("cost") or 0) + cost
    s["fees"] = float(s.get("fees") or 0) + fee
    s["last_at"] = now_ms
    return s


def dca_after_sell(p: DcaSpot.Params, state: dict[str, Any], pnl: float, now_ms: int) -> dict[str, Any]:
    s = dict(state)
    s.update(orders=0, qty=0.0, cost=0.0, fees=0.0, first_price=None, last_at=None, cycle_started_at=None)
    s["profit"] = float(s.get("profit") or 0) + pnl
    s["rounds"] = int(s.get("rounds") or 0) + 1
    if p.restart:
        s["cooldown_until"] = now_ms + p.cooldown_minutes * 60_000 if p.cooldown_minutes else None
    else:
        s["done"] = True
    return s


LADDER_STRATEGIES = (GridSpot, DcaSpot)


def is_ladder(strategy: Strategy) -> bool:
    return getattr(strategy, "kind", "signal") == "ladder"


def capital_needed(strategy: Strategy, params, order_size: float) -> float | None:
    if isinstance(strategy, GridSpot):
        return grid_capital(params, order_size)
    if isinstance(strategy, DcaSpot):
        return dca_capital(params, order_size)
    return None
