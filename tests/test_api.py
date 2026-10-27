import hashlib
import hmac
import os

import respx
from httpx import Response
from sqlalchemy import select

from app.models import SubStatus, Subscription


async def register(client, email="joao@example.com"):
    r = await client.post(
        "/api/v1/auth/register",
        json={"name": "João", "email": email, "password": "senhaForte123", "accept_terms": True},
    )
    assert r.status_code == 201, r.text
    return r


def csrf(client) -> dict:
    return {"X-CSRF-Token": client.cookies.get("csrf_token")}


async def test_register_login_me(client):
    await register(client)
    assert (await client.get("/api/v1/me")).json()["email"] == "joao@example.com"
    await client.post("/api/v1/auth/logout", headers=csrf(client))
    client.cookies.clear()
    assert (await client.get("/api/v1/me")).status_code == 401

    bad = await client.post("/api/v1/auth/login", json={"email": "joao@example.com", "password": "errada"})
    assert bad.status_code == 401
    ok = await client.post("/api/v1/auth/login", json={"email": "joao@example.com", "password": "senhaForte123"})
    assert ok.status_code == 200


async def test_csrf_required_for_cookie_sessions(client, plans):
    await register(client)
    body = {"name": "x", "symbol": "BTCUSDT", "strategy": "ema_cross_day", "order_size_quote": "50"}
    assert (await client.post("/api/v1/bots", json=body)).status_code == 403


async def test_bot_requires_subscription_and_respects_plan(client, db, plans):
    await register(client)
    body = {"name": "Meu robô", "symbol": "BTCUSDT", "strategy": "ema_cross_day", "order_size_quote": "50", "exec_mode": "auto"}
    r = await client.post("/api/v1/bots", json=body, headers=csrf(client))
    assert r.status_code == 402

    me = (await client.get("/api/v1/me")).json()
    import uuid

    db.add(Subscription(user_id=uuid.UUID(me["id"]), plan_id=plans["sinais"].id, status=SubStatus.active))
    await db.commit()

    r = await client.post("/api/v1/bots", json=body, headers=csrf(client))
    assert r.status_code == 403  # plano Sinais não permite automático

    body["exec_mode"] = "signals"
    r = await client.post("/api/v1/bots", json=body, headers=csrf(client))
    assert r.status_code == 201, r.text
    assert r.json()["venue"] == "paper"

    r = await client.post("/api/v1/bots", json=body, headers=csrf(client))
    assert r.status_code == 403  # limite de 1 robô


async def test_admin_requires_2fa(client, db):
    await register(client, "chefe@example.com")
    from app.models import Role, User

    user = await db.scalar(select(User).where(User.email == "chefe@example.com"))
    user.role = Role.admin
    await db.commit()
    assert (await client.get("/api/v1/admin/stats")).status_code == 403


@respx.mock
async def test_checkout_and_webhook_activate_subscription(client, db, plans):
    await register(client)
    respx.post("https://mp.test/preapproval").mock(
        return_value=Response(201, json={"id": "pre123", "init_point": "https://mp.test/checkout/pre123", "status": "pending"})
    )
    r = await client.post("/api/v1/billing/checkout", json={"plan_id": str(plans["pro"].id)}, headers=csrf(client))
    assert r.status_code == 200, r.text
    assert r.json()["checkout_url"].endswith("pre123")

    respx.get("https://mp.test/preapproval/pre123").mock(
        return_value=Response(200, json={"id": "pre123", "status": "authorized", "next_payment_date": "2026-11-12T10:00:00.000-03:00"})
    )
    secret = os.environ["MP_WEBHOOK_SECRET"]
    ts, rid = "1760000000", "req-abc"
    v1 = hmac.new(secret.encode(), f"id:pre123;request-id:{rid};ts:{ts};".encode(), hashlib.sha256).hexdigest()
    payload = {"type": "subscription_preapproval", "data": {"id": "pre123"}}

    bad = await client.post("/api/v1/billing/webhook/mercadopago", json=payload, headers={"x-signature": f"ts={ts},v1=00", "x-request-id": rid})
    assert bad.status_code == 401

    ok = await client.post(
        "/api/v1/billing/webhook/mercadopago?data.id=pre123&type=subscription_preapproval",
        json=payload,
        headers={"x-signature": f"ts={ts},v1={v1}", "x-request-id": rid},
    )
    assert ok.status_code == 200 and ok.json()["status"] == "accepted"

    dup = await client.post(
        "/api/v1/billing/webhook/mercadopago?data.id=pre123",
        json=payload,
        headers={"x-signature": f"ts={ts},v1={v1}", "x-request-id": rid},
    )
    assert dup.json()["status"] == "duplicate"

    db.expire_all()
    sub = await db.scalar(select(Subscription).where(Subscription.mp_preapproval_id == "pre123"))
    assert sub.status == SubStatus.active
    assert sub.next_payment_at is not None


async def test_ctrader_own_app_and_forex_bot(client, db, plans, monkeypatch):
    import uuid as _uuid

    from app.api.routes import ctrader as route
    from app.models import ExchangeCredential

    async def fake_list(client_id, secret, token):
        assert client_id == "meu-app" and token == "token-da-conta-123"
        return [{"ctidTraderAccountId": "111", "isLive": False, "traderLogin": "5001", "brokerTitleShort": "Corretora X"},
                {"ctidTraderAccountId": "222", "isLive": True, "traderLogin": "9001", "brokerTitleShort": "Corretora X"}], True

    monkeypatch.setattr(route, "list_accounts", fake_list)
    r = await register(client, "fx@example.com")
    db.add(Subscription(user_id=_uuid.UUID(r.json()["id"]), plan_id=plans["pro"].id, status=SubStatus.active))
    await db.commit()

    body = {"label": "Minha", "client_id": "meu-app", "client_secret": "segredo-do-app", "access_token": "token-da-conta-123", "refresh_token": "refresh-da-conta-456"}
    res = await client.post("/api/v1/ctrader/credentials", json=body, headers=csrf(client))
    assert res.status_code == 201, res.text
    creds = res.json()
    assert {c["venue"] for c in creds} == {"testnet", "live"} and all(c["exchange"] == "ctrader" for c in creds)
    stored = await db.scalar(select(ExchangeCredential).where(ExchangeCredential.external_account_id == "111"))
    assert "token-da-conta" not in stored.api_key_enc and "meu-app" not in (stored.client_id_enc or "")  # cifrado

    again = await client.post("/api/v1/ctrader/credentials", json=body, headers=csrf(client))
    assert again.status_code == 409

    demo = next(c for c in creds if c["venue"] == "testnet")
    bot = {"name": "EURUSD", "market": "forex", "symbol": "EURUSD", "strategy": "ema_cross_swing", "allow_short": True,
           "order_lots": "0.05", "exec_mode": "auto", "venue": "paper", "credential_id": demo["id"]}
    res = await client.post("/api/v1/bots", json=bot, headers=csrf(client))
    assert res.status_code == 201, res.text
    assert res.json()["allow_short"] is True and res.json()["order_lots"] in ("0.05", "0.0500000000", 0.05)

    crypto_short = {"name": "x", "symbol": "BTCUSDT", "strategy": "ema_cross_day", "order_size_quote": "50", "allow_short": True}
    assert (await client.post("/api/v1/bots", json=crypto_short, headers=csrf(client))).status_code == 422
