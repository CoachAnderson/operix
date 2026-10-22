"""Aparência do painel: salva por conta, valida tudo (vira CSS no navegador) e pode voltar ao padrão."""
from tests.test_api import csrf, register


async def test_salva_e_le_aparencia(client):
    await register(client)
    me = (await client.get("/api/v1/me")).json()
    assert me["appearance"] is None
    body = {"theme": "dark", "palette": "oceano", "accent": "#2563eb", "font": "atkinson", "scale": 110, "radius": "round",
            "pnl": "blue-orange", "custom": {"dark": {"ink": "#f0f0f0"}}}
    r = await client.put("/api/v1/me/appearance", json=body, headers=csrf(client))
    assert r.status_code == 200, r.text
    saved = (await client.get("/api/v1/me")).json()["appearance"]
    assert saved["theme"] == "dark" and saved["custom"]["dark"]["ink"] == "#f0f0f0" and saved["custom"]["light"] == {}
    r = await client.delete("/api/v1/me/appearance", headers=csrf(client))
    assert r.json()["appearance"] is None


async def test_recusa_valores_que_virariam_css_arbitrario(client):
    await register(client)
    ruins = [
        {"accent": "red;}body{display:none"},
        {"accent": "#12345"},
        {"custom": {"light": {"ink": "url(x)"}}},
        {"custom": {"light": {"rule": "#000000"}}},  # chave fora da lista
        {"font": "Comic Sans"},
        {"scale": 300},
        {"extra": 1},
    ]
    for b in ruins:
        r = await client.put("/api/v1/me/appearance", json=b, headers=csrf(client))
        assert r.status_code == 422, (b, r.text)


async def test_exige_csrf(client):
    await register(client)
    r = await client.put("/api/v1/me/appearance", json={"theme": "dark"})
    assert r.status_code == 403
