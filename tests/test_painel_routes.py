import base64

import pytest
from httpx import ASGITransport, AsyncClient

from app.main import create_app
from app.config.settings import Settings, get_settings
from app.database.session import get_db
from app.database.repositories.setting_repo import SettingRepository


class FakeClientCounter:
    def __init__(self):
        self.enqueued = []

    async def enqueue(self, raw_msg) -> None:
        self.enqueued.append(raw_msg)


@pytest.mark.asyncio
async def test_painel_routes(async_db_session, monkeypatch):
    import app.api.routes.painel as painel

    settings = get_settings()
    expected_user = settings.DASHBOARD_USERNAME or "admin"
    expected_pass = settings.DASHBOARD_PASSWORD or "admin"
    auth_header = "Basic " + base64.b64encode(f"{expected_user}:{expected_pass}".encode()).decode()

    # Fake redis-dependent bits so tests stay hermetic
    async def fake_worker_status():
        return {
            "queue_length": 0, "dead_letter_length": 0,
            "last_processed_at": None, "last_processed_seconds_ago": None,
            "status": "unknown",
        }
    monkeypatch.setattr(painel, "_get_worker_status", fake_worker_status)
    fake_queue = FakeClientCounter()
    monkeypatch.setattr(painel, "RedisQueue", lambda settings: fake_queue)

    app = create_app()

    async def override_get_db():
        yield async_db_session

    app.dependency_overrides[get_db] = override_get_db

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        # Page renders
        res_page = await client.get("/painel")
        assert res_page.status_code == 401  # auth required
        res_page = await client.get("/painel", headers={"Authorization": auth_header})
        assert res_page.status_code == 200
        assert "Painel de Controle" in res_page.text

        # Initial values (no overrides yet)
        res_values = await client.get("/painel/values", headers={"Authorization": auth_header})
        assert res_values.status_code == 200
        data = res_values.json()
        assert data["paused"] is False
        assert data["settings"]["amazon_tag"]["configured_in_db"] is False

        # Update afiliados section
        res_save = await client.put(
            "/painel/section/afiliados",
            headers={"Authorization": auth_header},
            json={"values": {"amazon_tag": "nova-tag", "mercadolivre_tag": ""}},
        )
        assert res_save.status_code == 200
        saved = res_save.json()
        assert saved["settings"]["amazon_tag"]["value"] == "nova-tag"
        assert saved["settings"]["amazon_tag"]["configured_in_db"] is True

        # Persisted in DB
        repo = SettingRepository(async_db_session)
        assert await repo.get("amazon_tag") == "nova-tag"

        # Values now reflect override
        res_values = await client.get("/painel/values", headers={"Authorization": auth_header})
        assert res_values.json()["settings"]["amazon_tag"]["value"] == "nova-tag"

        # Invalid section
        res_bad = await client.put(
            "/painel/section/filtros",
            headers={"Authorization": auth_header},
            json={"values": {"min_discount_percent": "abc"}},
        )
        assert res_bad.status_code == 422

        # Unknown section
        res_unknown = await client.put(
            "/painel/section/nao-existe",
            headers={"Authorization": auth_header},
            json={"values": {}},
        )
        assert res_unknown.status_code == 404

        # Pause / resume
        res_pause = await client.post(
            "/painel/pause", headers={"Authorization": auth_header}, json={"paused": True}
        )
        assert res_pause.status_code == 200
        assert res_pause.json()["paused"] is True
        res_values = await client.get("/painel/values", headers={"Authorization": auth_header})
        assert res_values.json()["paused"] is True
        await client.post("/painel/pause", headers={"Authorization": auth_header}, json={"paused": False})

        # Test enqueue
        res_test = await client.post("/painel/test", headers={"Authorization": auth_header})
        assert res_test.status_code == 200
        assert res_test.json()["ok"] is True
        assert len(fake_queue.enqueued) == 1
        assert fake_queue.enqueued[0].source == "painel"