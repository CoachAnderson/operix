import uuid
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.models import AuditLog

SENSITIVE = {"password", "api_key", "api_secret", "secret", "token", "totp_code", "code"}


def _scrub(details: dict[str, Any]) -> dict[str, Any]:
    return {k: ("***" if k.lower() in SENSITIVE else v) for k, v in details.items()}


async def audit(
    db: AsyncSession,
    action: str,
    actor_id: uuid.UUID | None = None,
    target: str | None = None,
    ip: str | None = None,
    **details: Any,
) -> None:
    """Adiciona um registro de auditoria à sessão; o commit fica com quem chama."""
    db.add(AuditLog(actor_id=actor_id, action=action, target=target, ip=ip, details=_scrub(details)))
