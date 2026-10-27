"""Tamanho da posição: fixo ou pela regra de risco, com limite de alavancagem.

Regra de risco: o cliente escolhe quanto do saldo aceita perder se o stop for atingido (ex.: 1%).
    tamanho = saldo × risco% ÷ distância até o stop
Assim, um stop longe vira posição pequena e um stop perto vira posição maior, mas a perda no stop é sempre
a mesma fração do saldo. O limite de alavancagem corta o tamanho quando o valor movimentado passa de
X vezes o saldo.

Unidades: forex e B3 usam "unidades" (lotes × tamanho do lote; na B3, contratos × valor do ponto), então
unidades × variação de preço = resultado na moeda da conta. Cripto à vista usa valor em moeda de cotação.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass
from decimal import ROUND_DOWN, Decimal

from app.models import Bot, Market
from app.services.brokers.base import SymbolRules


class SizingBlocked(Exception):
    """Não dá para abrir posição com essas regras (saldo pequeno, sem stop, sem saldo...)."""


@dataclass
class SizePlan:
    units: Decimal | None  # forex/B3
    quote_amount: Decimal | None  # cripto à vista
    price: Decimal
    notional: Decimal  # valor movimentado pela ordem
    balance: Decimal | None
    leverage: Decimal | None  # notional ÷ saldo
    stop: Decimal | None
    risk_money: Decimal | None  # perda estimada se o stop for atingido (sem custos)
    risk_pct: Decimal | None  # risk_money ÷ saldo
    lots: Decimal | None  # forex: lotes · B3: contratos
    capped: bool = False  # tamanho reduzido pelo limite de alavancagem
    note: str = ""

    def as_dict(self) -> dict:
        return {k: (str(v) if isinstance(v, Decimal) else v) for k, v in asdict(self).items()}


def needs_balance(bot: Bot) -> bool:
    return bot.sizing_mode == "risk" or bot.max_leverage is not None


def _fmt(v: Decimal, digits: int = 2) -> str:
    return f"{v:,.{digits}f}".replace(",", "§").replace(".", ",").replace("§", ".")


def compute(bot: Bot, rules: SymbolRules, price: Decimal, stop: Decimal | None, balance: Decimal | None) -> SizePlan:
    """Calcula o tamanho da próxima entrada. Lança SizingBlocked quando não há tamanho possível."""
    spot = bot.market == Market.crypto
    risk_mode = bot.sizing_mode == "risk"
    if price <= 0:
        raise SizingBlocked("Sem preço para calcular o tamanho")
    if (risk_mode or bot.max_leverage) and (balance is None or balance <= 0):
        raise SizingBlocked("Saldo da conta zerado ou indisponível: não dá para calcular o tamanho")
    per_unit = abs(price - stop) if stop is not None else None
    if risk_mode and not per_unit:
        raise SizingBlocked("O tamanho pelo risco precisa de um stop (em % ou pelo ATR)")

    capped = False
    note = ""
    if spot:
        if risk_mode:
            amount = balance * bot.risk_pct / 100 / per_unit * price  # type: ignore[operator]
        else:
            amount = bot.order_size_quote or Decimal("0")
        limit = None
        if bot.max_leverage is not None and balance:
            limit = balance * bot.max_leverage
        if balance is not None:  # à vista não gasta mais do que tem
            limit = min(limit, balance) if limit is not None else balance
        if limit is not None and amount > limit:
            amount, capped = limit, True
            note = "Reduzido ao saldo disponível" if limit == balance else "Reduzido pelo limite de alavancagem"
        amount = rules.floor_quote(amount)
        if amount <= 0 or amount < rules.min_notional:
            raise SizingBlocked(f"Ordem de {_fmt(amount)} abaixo do mínimo da corretora ({_fmt(rules.min_notional)} {rules.quote_asset})")
        units = None
        notional = amount
        qty = amount / price
    else:
        if risk_mode:
            raw = balance * bot.risk_pct / 100 / per_unit  # type: ignore[operator]
        else:
            raw = (bot.order_lots or Decimal("0")) * rules.lot_size
        if bot.max_leverage is not None and balance:
            limit = balance * bot.max_leverage / price
            if raw > limit:
                raw, capped, note = limit, True, f"Reduzido pelo limite de alavancagem ({_fmt(bot.max_leverage, 1)}×)"
        units = rules.floor_qty(raw)
        if units < rules.min_qty or units <= 0:
            unit_name = "contrato" if bot.market == Market.b3 else "lote mínimo"
            if risk_mode and per_unit:
                min_risk = rules.min_qty * per_unit
                raise SizingBlocked(
                    f"Saldo pequeno para arriscar {_fmt(bot.risk_pct, 2)}% com esse stop: 1 {unit_name} já arrisca {_fmt(min_risk)} "
                    f"({_fmt(min_risk / balance * 100, 1)}% do saldo). Aumente o risco, aproxime o stop ou deposite mais."  # type: ignore[operator]
                )
            raise SizingBlocked(f"Tamanho abaixo do {unit_name} permitido pela corretora (o limite de alavancagem cortou demais)")
        amount = None
        notional = units * price
        qty = units

    risk_money = qty * per_unit if per_unit else None
    lots = (units / rules.lot_size).quantize(Decimal("0.01"), rounding=ROUND_DOWN) if units is not None and rules.lot_size else None
    return SizePlan(
        units=units,
        quote_amount=amount,
        price=price,
        notional=notional,
        balance=balance,
        leverage=(notional / balance) if balance else None,
        stop=stop,
        risk_money=risk_money,
        risk_pct=(risk_money / balance * 100) if (risk_money is not None and balance) else None,
        lots=lots,
        capped=capped,
        note=note,
    )
