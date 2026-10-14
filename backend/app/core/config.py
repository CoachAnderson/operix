from functools import lru_cache
from typing import Literal

from pydantic import Field, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

DEV_JWT_SECRET = "dev-only-secret-troque-em-producao-0000000000"


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    app_name: str = "OráculoInvest"
    environment: Literal["development", "production", "test"] = "development"
    public_url: str = "http://localhost:3000"  # URL do painel (Next.js)
    api_public_url: str = "http://localhost:8000"  # URL pública da API (webhooks)

    database_url: str = "postgresql+asyncpg://operix:operix@localhost:5432/operix"
    redis_url: str = "redis://localhost:6379/0"

    # Segurança
    jwt_secret: str = Field(default=DEV_JWT_SECRET)
    jwt_algorithm: str = "HS256"
    access_token_minutes: int = 15
    refresh_token_days: int = 7
    # Chaves AES-256 em base64 (32 bytes). Formato: "id1:base64,id2:base64". A primeira cifra; todas decifram.
    encryption_keys: str = ""
    cookie_domain: str | None = None
    allowed_origins: str = "http://localhost:3000"  # separadas por vírgula

    # Mercado Pago
    mp_access_token: str = ""
    mp_webhook_secret: str = ""
    mp_api_base: str = "https://api.mercadopago.com"

    # Binance
    binance_live_base: str = "https://api.binance.com"
    binance_testnet_base: str = "https://testnet.binance.vision"
    binance_market_data_base: str = "https://data-api.binance.vision"  # dados públicos

    # cTrader Open API — app da PLATAFORMA (opcional). Sem isso, cada cliente informa o app próprio.
    ctrader_client_id: str = ""
    ctrader_client_secret: str = ""
    ctrader_redirect_uri: str = ""  # padrão: {API_PUBLIC_URL}/api/v1/ctrader/callback
    ctrader_token_url: str = "https://openapi.ctrader.com/apps/token"
    ctrader_auth_url: str = "https://id.ctrader.com/my/settings/openapi/grantingaccess/"
    ctrader_live_host: str = "live.ctraderapi.com"
    ctrader_demo_host: str = "demo.ctraderapi.com"
    ctrader_json_port: int = 5036

    # Motor
    worker_interval_seconds: int = 20
    paper_fee_rate: float = 0.001  # 0,1% (taxa padrão spot)
    paper_slippage_bps: float = 5  # 0,05%
    signal_ttl_minutes: int = 15

    # Admin inicial (seed)
    admin_email: str = "admin@example.com"
    admin_password: str = ""

    @field_validator("jwt_secret")
    @classmethod
    def strong_secret(cls, v: str) -> str:
        if len(v) < 32:
            raise ValueError("JWT_SECRET precisa de pelo menos 32 caracteres")
        return v

    @model_validator(mode="after")
    def production_guards(self) -> "Settings":
        if self.environment == "production":
            missing = []
            if self.jwt_secret == DEV_JWT_SECRET:
                missing.append("JWT_SECRET")
            if not self.encryption_keys:
                missing.append("ENCRYPTION_KEYS")
            if not self.mp_access_token or not self.mp_webhook_secret:
                missing.append("MP_ACCESS_TOKEN/MP_WEBHOOK_SECRET")
            if missing:
                raise ValueError(f"Configuração obrigatória em produção ausente: {', '.join(missing)}")
        return self

    @property
    def origins(self) -> list[str]:
        return [o.strip() for o in self.allowed_origins.split(",") if o.strip()]

    @property
    def is_production(self) -> bool:
        return self.environment == "production"


@lru_cache
def get_settings() -> Settings:
    return Settings()
