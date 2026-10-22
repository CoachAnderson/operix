from __future__ import annotations

import uuid
from datetime import UTC, datetime

from fastapi import APIRouter, HTTPException, Request, Response, status
from sqlalchemy import select, update

from app.api.deps import ACCESS_COOKIE, CSRF_COOKIE, DB, REFRESH_COOKIE, CurrentUser
from app.core import crypto
from app.core.config import get_settings
from app.core.ratelimit import client_ip, hit
from app.core.security import (
    DUMMY_HASH,
    create_token,
    decode_token,
    hash_password,
    new_csrf_token,
    new_totp_secret,
    password_needs_rehash,
    totp_uri,
    verify_password,
    verify_totp,
)
from app.models import Bot, BotStatus, ExchangeCredential, User, UserStatus
from app.schemas import (
    AcceptRiskIn,
    AppearanceIn,
    ChangePasswordIn,
    LoginIn,
    RegisterIn,
    TotpCodeIn,
    TotpSetupOut,
    UserOut,
)
from app.services.audit import audit

router = APIRouter(prefix="/auth", tags=["auth"])
me_router = APIRouter(prefix="/me", tags=["me"])

RISK_TERMS_VERSION = "2026-10"


def _set_session_cookies(response: Response, user: User) -> None:
    s = get_settings()
    common = {"secure": s.is_production, "samesite": "lax", "domain": s.cookie_domain}
    response.set_cookie(
        ACCESS_COOKIE,
        create_token(user.id, user.token_version, "access"),
        max_age=s.access_token_minutes * 60,
        httponly=True,
        path="/",
        **common,
    )
    response.set_cookie(
        REFRESH_COOKIE,
        create_token(user.id, user.token_version, "refresh"),
        max_age=s.refresh_token_days * 86400,
        httponly=True,
        path="/api/v1/auth",
        **common,
    )
    # Cookie legível pelo front para o double-submit de CSRF.
    response.set_cookie(CSRF_COOKIE, new_csrf_token(), max_age=s.refresh_token_days * 86400, httponly=False, path="/", **common)


def _clear_session_cookies(response: Response) -> None:
    s = get_settings()
    response.delete_cookie(ACCESS_COOKIE, path="/", domain=s.cookie_domain)
    response.delete_cookie(REFRESH_COOKIE, path="/api/v1/auth", domain=s.cookie_domain)
    response.delete_cookie(CSRF_COOKIE, path="/", domain=s.cookie_domain)


@router.post("/register", response_model=UserOut, status_code=201)
async def register(body: RegisterIn, request: Request, response: Response, db: DB) -> User:
    ip = client_ip(request)
    await hit(f"register:{ip}", limit=5, window_seconds=3600)
    email = body.email.lower()
    exists = await db.scalar(select(User.id).where(User.email == email))
    if exists:
        # Mensagem genérica para não confirmar quais e-mails existem.
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Não foi possível concluir o cadastro com esses dados")
    user = User(email=email, name=body.name.strip(), password_hash=hash_password(body.password))
    db.add(user)
    await db.flush()
    await audit(db, "user.register", user.id, ip=ip)
    await db.commit()
    _set_session_cookies(response, user)
    return user


@router.post("/login", response_model=UserOut)
async def login(body: LoginIn, request: Request, response: Response, db: DB) -> User:
    ip = client_ip(request)
    email = body.email.lower()
    await hit(f"login:ip:{ip}", limit=20, window_seconds=900)
    await hit(f"login:email:{email}", limit=8, window_seconds=900)

    user = await db.scalar(select(User).where(User.email == email))
    ok = verify_password(body.password, user.password_hash if user else DUMMY_HASH)
    if not user or not ok or user.status != UserStatus.active:
        await audit(db, "auth.login_failed", user.id if user else None, ip=ip, email=email)
        await db.commit()
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "E-mail ou senha inválidos")

    if user.totp_enabled:
        if not body.totp_code:
            raise HTTPException(status.HTTP_401_UNAUTHORIZED, {"totp_required": True, "message": "Informe o código 2FA"})
        await hit(f"totp:{user.id}", limit=6, window_seconds=300)
        secret = crypto.decrypt(user.totp_secret_enc or "", aad=str(user.id))
        if not verify_totp(secret, body.totp_code):
            await audit(db, "auth.totp_failed", user.id, ip=ip)
            await db.commit()
            raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Código 2FA inválido")

    if password_needs_rehash(user.password_hash):
        user.password_hash = hash_password(body.password)
    user.last_login_at = datetime.now(UTC)
    await audit(db, "auth.login", user.id, ip=ip)
    await db.commit()
    _set_session_cookies(response, user)
    return user


@router.post("/refresh", status_code=204, response_model=None)
async def refresh(request: Request, response: Response, db: DB) -> None:
    token = request.cookies.get(REFRESH_COOKIE)
    data = decode_token(token, "refresh") if token else None
    user = await db.get(User, uuid.UUID(data["sub"])) if data else None
    if not user or user.status != UserStatus.active or user.token_version != data.get("ver"):
        _clear_session_cookies(response)
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Sessão expirada")
    _set_session_cookies(response, user)


@router.post("/logout", status_code=204, response_model=None)
async def logout(response: Response) -> None:
    _clear_session_cookies(response)


@router.post("/logout-all", status_code=204, response_model=None)
async def logout_all(user: CurrentUser, request: Request, response: Response, db: DB) -> None:
    user.token_version += 1
    await audit(db, "auth.logout_all", user.id, ip=client_ip(request))
    await db.commit()
    _clear_session_cookies(response)


# ---------- Conta do usuário ----------
@me_router.get("", response_model=UserOut)
async def me(user: CurrentUser) -> User:
    return user


@me_router.put("/appearance", response_model=UserOut)
async def save_appearance(body: AppearanceIn, user: CurrentUser, db: DB) -> User:
    """Tema, cores, fonte e tamanho do texto do painel; vale em todos os aparelhos da conta."""
    await hit(f"appearance:{user.id}", limit=120, window_seconds=600)
    user.appearance = body.model_dump(mode="json")
    await db.commit()
    return user


@me_router.delete("/appearance", response_model=UserOut)
async def reset_appearance(user: CurrentUser, db: DB) -> User:
    user.appearance = None
    await db.commit()
    return user


@me_router.post("/password", status_code=204, response_model=None)
async def change_password(body: ChangePasswordIn, user: CurrentUser, request: Request, response: Response, db: DB) -> None:
    if not verify_password(body.current_password, user.password_hash):
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Senha atual incorreta")
    user.password_hash = hash_password(body.new_password)
    user.token_version += 1  # derruba outras sessões
    await audit(db, "user.password_changed", user.id, ip=client_ip(request))
    await db.commit()
    _set_session_cookies(response, user)


@me_router.post("/2fa/setup", response_model=TotpSetupOut)
async def totp_setup(user: CurrentUser, db: DB) -> TotpSetupOut:
    if user.totp_enabled:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "2FA já está ativo")
    secret = new_totp_secret()
    user.totp_secret_enc = crypto.encrypt(secret, aad=str(user.id))
    await db.commit()
    return TotpSetupOut(secret=secret, otpauth_uri=totp_uri(secret, user.email))


@me_router.post("/2fa/enable", status_code=204, response_model=None)
async def totp_enable(body: TotpCodeIn, user: CurrentUser, request: Request, db: DB) -> None:
    await hit(f"totp:{user.id}", limit=6, window_seconds=300)
    if not user.totp_secret_enc:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Gere o código QR primeiro")
    if not verify_totp(crypto.decrypt(user.totp_secret_enc, aad=str(user.id)), body.code):
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Código inválido")
    user.totp_enabled = True
    await audit(db, "user.2fa_enabled", user.id, ip=client_ip(request))
    await db.commit()


@me_router.post("/2fa/disable", status_code=204, response_model=None)
async def totp_disable(body: TotpCodeIn, user: CurrentUser, request: Request, db: DB) -> None:
    await hit(f"totp:{user.id}", limit=6, window_seconds=300)
    if not user.totp_enabled or not verify_totp(crypto.decrypt(user.totp_secret_enc or "", aad=str(user.id)), body.code):
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Código inválido")
    user.totp_enabled = False
    user.totp_secret_enc = None
    await audit(db, "user.2fa_disabled", user.id, ip=client_ip(request))
    await db.commit()


@me_router.post("/accept-risk", response_model=UserOut)
async def accept_risk(body: AcceptRiskIn, user: CurrentUser, request: Request, db: DB) -> User:
    if body.version != RISK_TERMS_VERSION:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Versão do termo desatualizada; recarregue a página")
    ip = client_ip(request)
    user.risk_terms_accepted_at = datetime.now(UTC)
    user.risk_terms_ip = ip
    user.risk_terms_version = body.version
    await audit(db, "user.risk_terms_accepted", user.id, ip=ip, version=body.version)
    await db.commit()
    return user


@me_router.delete("", status_code=204, response_model=None)
async def delete_account(user: CurrentUser, request: Request, response: Response, db: DB) -> None:
    """LGPD: anonimiza o usuário, apaga credenciais de corretora e encerra sessões.
    A assinatura no Mercado Pago deve ser cancelada antes (rota /billing/cancel)."""
    creds = (await db.scalars(select(ExchangeCredential).where(ExchangeCredential.user_id == user.id))).all()
    for c in creds:
        await db.delete(c)
    await db.execute(update(Bot).where(Bot.user_id == user.id).values(status=BotStatus.stopped, credential_id=None))
    await audit(db, "user.deleted", user.id, ip=client_ip(request))
    user.email = f"removido-{user.id}@invalid"
    user.name = "Conta removida"
    user.password_hash = DUMMY_HASH
    user.totp_secret_enc = None
    user.totp_enabled = False
    user.status = UserStatus.deleted
    user.token_version += 1
    await db.commit()
    _clear_session_cookies(response)
