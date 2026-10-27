"""Regras dos futuros da B3 operados pelos robôs.

O contrato em negociação (ex.: WINZ26), o valor do ponto, o lote mínimo e o vencimento vêm do MetaTrader 5
do cliente, que é a fonte oficial da corretora. Aqui ficam só os ativos liberados e o horário de operação.
"""
from __future__ import annotations

from dataclasses import dataclass

TZ = "America/Sao_Paulo"


@dataclass(frozen=True)
class FutureInfo:
    root: str
    name: str
    point_value: float  # R$ por ponto por contrato (só para exibir; o valor usado nas ordens vem do MT5)
    # Janela em que o robô pode ABRIR posição (minutos desde 00:00, horário de Brasília).
    # Começa depois do leilão de abertura e termina antes do fim do pregão; fechar é sempre permitido.
    entry_start: int
    entry_end: int
    # Robôs de day trade zeram a posição quando faltar isso para entry_end.
    flat_before_min: int = 10
    # Custos e escorregamento para simulação e backtest (estimativas; cada corretora cobra diferente).
    fee_rate: float = 0.000015  # emolumentos + registro, ~R$ 0,40 por contrato de WIN a 130 mil pontos
    slippage_bps: float = 0.6  # cerca de 1 tick


FUTURES: dict[str, FutureInfo] = {
    "WIN": FutureInfo("WIN", "Mini Ibovespa", 0.2, entry_start=9 * 60 + 5, entry_end=18 * 60 + 20),
    "WDO": FutureInfo("WDO", "Mini dólar", 10.0, entry_start=9 * 60 + 5, entry_end=18 * 60 + 20, fee_rate=0.00002, slippage_bps=0.9),
}


def info(root: str) -> FutureInfo:
    root = root.upper()
    if root not in FUTURES:
        raise ValueError(f"Ativo {root} não liberado. Disponíveis: {', '.join(FUTURES)}")
    return FUTURES[root]


def schedule(root: str) -> tuple[tuple[int, int], ...]:
    """Segunda a sexta, no formato de SymbolRules.schedule (segundos desde domingo 00:00)."""
    f = info(root)
    return tuple((day * 86400 + f.entry_start * 60, day * 86400 + f.entry_end * 60) for day in range(1, 6))
