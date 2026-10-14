import os
import secrets
import tempfile

_db = os.path.join(tempfile.mkdtemp(), "test.db")
os.environ.update(
    ENVIRONMENT="test",
    DATABASE_URL=f"sqlite+aiosqlite:///{_db}",
    REDIS_URL="memory://",
    # Valores aleatórios gerados a cada execução: nenhum segredo fica no código.
    MP_ACCESS_TOKEN=secrets.token_hex(16),
    MP_WEBHOOK_SECRET=secrets.token_hex(16),
    MP_API_BASE="https://mp.test",
)

from collections.abc import AsyncIterator  # noqa: E402
from decimal import Decimal  # noqa: E402

import httpx  # noqa: E402
import pytest  # noqa: E402
import pytest_asyncio  # noqa: E402

from app.core.redis import MemoryRedis, set_redis  # noqa: E402
from app.db import Base, SessionLocal, engine  # noqa: E402
from app.main import app  # noqa: E402
from app.models import Plan  # noqa: E402
from app.services.brokers.base import Candle, SymbolRules  # noqa: E402


@pytest_asyncio.fixture(autouse=True)
async def fresh_db() -> AsyncIterator[None]:
    set_redis(MemoryRedis())
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
        await conn.run_sync(Base.metadata.create_all)
    yield


@pytest_asyncio.fixture
async def db():
    async with SessionLocal() as session:
        yield session


@pytest_asyncio.fixture
async def client() -> AsyncIterator[httpx.AsyncClient]:
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as c:
        yield c


@pytest_asyncio.fixture
async def plans(db):
    basic = Plan(code="sinais", name="Sinais", price_monthly=Decimal("49.90"), max_bots=1, allow_auto=False, allow_live=False)
    pro = Plan(code="pro", name="Pro", price_monthly=Decimal("99.90"), max_bots=3, allow_auto=True, allow_live=True)
    db.add_all([basic, pro])
    await db.commit()
    return {"sinais": basic, "pro": pro}


RULES = SymbolRules(
    symbol="BTCUSDT",
    base_asset="BTC",
    quote_asset="USDT",
    step_size=Decimal("0.00001"),
    min_qty=Decimal("0.00001"),
    max_qty=Decimal("9000"),
    min_notional=Decimal("5"),
    quote_precision=8,
)


class FakeMarket:
    """Dados de mercado controlados pelo teste."""

    def __init__(self, closes: list[float], price: float | None = None):
        self.closes = closes
        self.price = Decimal(str(price if price is not None else closes[-1]))

    async def get_price(self, symbol):
        return self.price

    async def get_klines(self, symbol, interval, limit=200):
        step = 60_000
        return [
            Candle(open_time=i * step, open=c, high=c * 1.001, low=c * 0.999, close=c, volume=1, close_time=i * step + step - 1)
            for i, c in enumerate(self.closes[-limit:])
        ]

    async def get_rules(self, symbol):
        return RULES

    async def close(self):
        pass


@pytest.fixture
def fake_market():
    return FakeMarket
