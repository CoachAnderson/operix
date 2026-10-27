from fastapi import HTTPException, Request, status

from app.core.redis import get_redis


def client_ip(request: Request) -> str:
    # Atrás de proxy confiável, configure o uvicorn com --proxy-headers e --forwarded-allow-ips.
    return request.client.host if request.client else "unknown"


async def hit(key: str, limit: int, window_seconds: int) -> None:
    """Janela fixa. Lança 429 quando o limite é excedido."""
    r = get_redis()
    full = f"rl:{key}"
    count = await r.incr(full)
    if count == 1:
        await r.expire(full, window_seconds)
    if count > limit:
        raise HTTPException(
            status.HTTP_429_TOO_MANY_REQUESTS,
            "Muitas tentativas. Aguarde alguns minutos.",
            headers={"Retry-After": str(window_seconds)},
        )
