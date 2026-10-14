"""Cria planos iniciais e o administrador. Executar:  python -m app.seed"""
from __future__ import annotations

import asyncio
from decimal import Decimal

from sqlalchemy import select

from app.core.config import get_settings
from app.core.security import hash_password
from app.db import SessionLocal, create_all
from app.models import Plan, Role, User

PLANS = [
    dict(code="sinais", name="Sinais", price_monthly=Decimal("49.90"), max_bots=2, allow_auto=False, allow_live=True, sort_order=1,
         description="Os robôs avisam as entradas e saídas, e você confirma cada ordem."),
    dict(code="pro", name="Pro", price_monthly=Decimal("99.90"), max_bots=3, allow_auto=True, allow_live=True, sort_order=2,
         description="Execução automática ou por sinais, até 3 robôs."),
    dict(code="elite", name="Elite", price_monthly=Decimal("199.90"), max_bots=10, allow_auto=True, allow_live=True, sort_order=3,
         description="Até 10 robôs, todas as estratégias e modalidades."),
]


async def main() -> None:
    s = get_settings()
    await create_all()
    async with SessionLocal() as db:
        for p in PLANS:
            if not await db.scalar(select(Plan.id).where(Plan.code == p["code"])):
                db.add(Plan(**p))
                print(f"Plano criado: {p['name']}")
        if s.admin_password:
            email = s.admin_email.lower()
            if not await db.scalar(select(User.id).where(User.email == email)):
                db.add(User(email=email, name="Administrador", password_hash=hash_password(s.admin_password), role=Role.admin))
                print(f"Admin criado: {email} (ative o 2FA no primeiro acesso para liberar o painel admin)")
        else:
            print("ADMIN_PASSWORD vazio: administrador não criado")
        await db.commit()


if __name__ == "__main__":
    asyncio.run(main())
