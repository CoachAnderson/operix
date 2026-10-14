"""Regras de permissão compartilhadas entre a API e o worker."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from app.models import Bot, ExecMode, Market, Plan, User, UserStatus, Venue


@dataclass(frozen=True)
class Problem:
    kind: Literal["billing", "config"]  # billing: assinatura/plano · config: ajuste do usuário
    message: str


def permission_problem(user: User, plan: Plan | None, bot: Bot) -> Problem | None:
    """Retorna o motivo pelo qual o robô não pode operar, ou None se estiver tudo certo."""
    if user.status != UserStatus.active:
        return Problem("billing", "Conta inativa")
    if plan is None:
        return Problem("billing", "Assinatura inativa")
    if bot.exec_mode == ExecMode.auto and not plan.allow_auto:
        return Problem("billing", f"O plano {plan.name} não inclui execução automática")
    if bot.venue == Venue.live:
        if not plan.allow_live:
            return Problem("billing", f"O plano {plan.name} não inclui operação em conta real")
        if not user.totp_enabled:
            return Problem("config", "Ative a verificação em duas etapas para operar em conta real")
        if not user.risk_terms_accepted_at:
            return Problem("config", "Aceite o termo de ciência de risco para operar em conta real")
    if (bot.venue != Venue.paper or bot.market == Market.forex) and not bot.credential_id:
        return Problem("config", "Conecte uma conta cTrader a este robô" if bot.market == Market.forex else "Conecte uma credencial da Binance a este robô")
    return None
