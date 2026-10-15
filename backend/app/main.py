from __future__ import annotations

import hmac
import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from sqlalchemy import text

from app.api.deps import ACCESS_COOKIE, CSRF_COOKIE, CSRF_HEADER
from app.api.routes import admin, auth, backtest, billing, bots, credentials, ctrader, mt5, reports
from app.core.config import get_settings
from app.core.redis import get_redis
from app.db import SessionLocal, create_all

settings = get_settings()
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")

API = "/api/v1"
CSRF_EXEMPT = {
    f"{API}/auth/login",
    f"{API}/auth/register",
    f"{API}/billing/webhook/mercadopago",
}
UNSAFE = {"POST", "PUT", "PATCH", "DELETE"}


@asynccontextmanager
async def lifespan(app: FastAPI):
    if settings.environment != "production":
        await create_all()  # produção: use `alembic upgrade head`
    yield


app = FastAPI(
    title=settings.app_name,
    version="0.1.0",
    lifespan=lifespan,
    docs_url=None if settings.is_production else "/docs",
    redoc_url=None,
    openapi_url=None if settings.is_production else "/openapi.json",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.origins,
    allow_credentials=True,
    allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE"],
    allow_headers=["Content-Type", "X-CSRF-Token", "Authorization"],
)


@app.middleware("http")
async def csrf_and_headers(request: Request, call_next):
    path = request.url.path
    if request.method in UNSAFE and path.startswith(API) and path not in CSRF_EXEMPT:
        uses_cookie = ACCESS_COOKIE in request.cookies or "refresh_token" in request.cookies
        if uses_cookie:
            cookie = request.cookies.get(CSRF_COOKIE, "")
            header = request.headers.get(CSRF_HEADER, "")
            if not cookie or not hmac.compare_digest(cookie, header):
                return JSONResponse({"detail": "Falha na verificação CSRF. Recarregue a página."}, status_code=403)

    response = await call_next(request)
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["X-Frame-Options"] = "DENY"
    response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
    response.headers["Permissions-Policy"] = "camera=(), microphone=(), geolocation=()"
    response.headers["Cache-Control"] = "no-store"
    if settings.is_production:
        response.headers["Strict-Transport-Security"] = "max-age=63072000; includeSubDomains; preload"
    if not path.startswith(("/docs", "/openapi")):
        response.headers["Content-Security-Policy"] = "default-src 'none'; frame-ancestors 'none'"
    return response


for r in (auth.router, auth.me_router, billing.router, credentials.router, ctrader.router, mt5.router, bots.router, backtest.router, reports.router, admin.router):
    app.include_router(r, prefix=API)


@app.get("/health")
async def health() -> dict:
    status = {"api": "ok"}
    try:
        async with SessionLocal() as db:
            await db.execute(text("SELECT 1"))
        status["db"] = "ok"
    except Exception:  # noqa: BLE001
        status["db"] = "erro"
    try:
        await get_redis().ping()
        status["redis"] = "ok"
    except Exception:  # noqa: BLE001
        status["redis"] = "erro"
    return status
