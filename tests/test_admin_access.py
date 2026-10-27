"""Admin com acesso ilimitado; admin libera (com ou sem prazo) e cancela o acesso de clientes."""
import uuid
from datetime import UTC, datetime, timedelta

import respx
from httpx import Response
from sqlalchemy import select

from app.models import Bot, BotStatus, Role, SubStatus, Subscription, User
from tests.test_api import csrf, register

BOT = {"name": "Robô", "symbol": "BTCUSDT", "strategy": "ema_cross_day", "order_size_quote": "50", "exec_mode": "auto"}


def _ids(plans) -> dict:
    return {k: str(p.id) for k, p in plans.items()}


async def _user(db, email) -> User:
    db.expire_all()
    return await db.scalar(select(User).where(User.email == email))


async def _make_admin(client, db, email="chefe@example.com") -> User:
    await register(client, email)
    u = await _user(db, email)
    u.role = Role.admin
    u.totp_enabled = True  # o painel admin exige 2FA
    await db.commit()
    return u


async def test_admin_has_unlimited_access_without_subscription(client, db, plans):
    pid = _ids(plans)
    await _make_admin(client, db)
    sub = (await client.get("/api/v1/billing/subscription")).json()
    assert sub["source"] == "admin" and sub["status"] == "active"
    assert sub["plan"]["allow_auto"] and sub["plan"]["allow_live"] and sub["plan"]["max_bots"] >= 1000

    for i in range(5):  # nenhum plano normal do teste permite 5 robôs automáticos
        r = await client.post("/api/v1/bots", json={**BOT, "name": f"R{i}"}, headers=csrf(client))
        assert r.status_code == 201, r.text
    bot_id = r.json()["id"]
    r = await client.post(f"/api/v1/bots/{bot_id}/start", headers=csrf(client))
    assert r.status_code == 200, r.text
    assert r.json()["status"] == "running"

    # Admin não precisa (nem consegue) assinar.
    r = await client.post("/api/v1/billing/checkout", json={"plan_id": pid["pro"]}, headers=csrf(client))
    assert r.status_code == 400


async def test_admin_grants_access_with_expiry_and_revokes(client, db, plans):
    pid = _ids(plans)
    await register(client, "cliente@example.com")
    cid = (await _user(db, "cliente@example.com")).id
    client.cookies.clear()
    await _make_admin(client, db)

    users = (await client.get("/api/v1/admin/users")).json()
    row = next(u for u in users if u["email"] == "cliente@example.com")
    assert row["access"]["source"] == "none"
    assert next(u for u in users if u["email"] == "chefe@example.com")["access"]["source"] == "admin"

    r = await client.post(f"/api/v1/admin/users/{cid}/grant-plan", json={"plan_id": pid["pro"], "days": 30, "note": "parceria"}, headers=csrf(client))
    assert r.status_code == 201, r.text
    row = next(u for u in (await client.get("/api/v1/admin/users")).json() if u["email"] == "cliente@example.com")
    assert row["access"]["source"] == "manual" and row["access"]["plan_name"] == "Pro"
    exp = datetime.fromisoformat(row["access"]["expires_at"])
    assert timedelta(days=29) < exp.replace(tzinfo=exp.tzinfo or UTC) - datetime.now(UTC) <= timedelta(days=30)

    # Um robô do cliente rodando
    bot = Bot(user_id=cid, name="x", symbol="BTCUSDT", strategy="ema_cross_day", params={}, order_size_quote=50, status=BotStatus.running)
    db.add(bot)
    await db.commit()
    bot_id = bot.id

    r = await client.post(f"/api/v1/admin/users/{cid}/revoke-access", json={"note": "fim da parceria"}, headers=csrf(client))
    assert r.status_code == 200, r.text
    assert r.json() == {"cancelled": 1, "paid_cancelled": 0, "bots_paused": 1}
    db.expire_all()
    assert (await db.get(Bot, bot_id)).status == BotStatus.paused_billing
    row = next(u for u in (await client.get("/api/v1/admin/users")).json() if u["email"] == "cliente@example.com")
    assert row["access"]["source"] == "none"
    assert row["status"] == "active"  # o login continua; só os robôs param

    # Liberar de novo (sem prazo)
    r = await client.post(f"/api/v1/admin/users/{cid}/grant-plan", json={"plan_id": pid["sinais"]}, headers=csrf(client))
    assert r.status_code == 201 and r.json()["expires_at"] is None

    # Admin não pode cancelar acesso de outro admin
    admin_id = (await _user(db, "chefe@example.com")).id
    r = await client.post(f"/api/v1/admin/users/{admin_id}/revoke-access", json={}, headers=csrf(client))
    assert r.status_code == 400


async def test_expired_grant_no_longer_counts(client, db, plans):
    pid = _ids(plans)
    await register(client)
    u = await _user(db, "joao@example.com")
    db.add(Subscription(user_id=u.id, plan_id=uuid.UUID(pid["pro"]), status=SubStatus.active, expires_at=datetime.now(UTC) - timedelta(minutes=1)))
    await db.commit()
    r = await client.post("/api/v1/bots", json=BOT, headers=csrf(client))
    assert r.status_code == 402  # liberação vencida = sem acesso


@respx.mock
async def test_revoke_also_cancels_paid_subscription(client, db, plans):
    pid = _ids(plans)
    await register(client, "pagante@example.com")
    pid_user = (await _user(db, "pagante@example.com")).id
    db.add(Subscription(user_id=pid_user, plan_id=uuid.UUID(pid["pro"]), status=SubStatus.active, mp_preapproval_id="pre999"))
    await db.commit()
    client.cookies.clear()
    await _make_admin(client, db)

    r = await client.post(f"/api/v1/admin/users/{pid_user}/revoke-access", json={"cancel_billing": False}, headers=csrf(client))
    assert r.status_code == 409  # não corta o acesso deixando a cobrança rodando

    route = respx.put("https://mp.test/preapproval/pre999").mock(return_value=Response(200, json={"id": "pre999", "status": "cancelled"}))
    r = await client.post(f"/api/v1/admin/users/{pid_user}/revoke-access", json={}, headers=csrf(client))
    assert r.status_code == 200, r.text
    assert route.called and r.json()["paid_cancelled"] == 1
    db.expire_all()
    sub = await db.scalar(select(Subscription).where(Subscription.user_id == pid_user))
    assert sub.status == SubStatus.cancelled
