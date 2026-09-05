import base64

import pytest
from httpx import ASGITransport, AsyncClient

from app.main import create_app
from app.config.settings import get_settings
from app.database.session import get_db


@pytest.mark.asyncio
async def test_hub_requires_auth(async_db_session):
    app = create_app()

    async def override_get_db():
        yield async_db_session

    app.dependency_overrides[get_db] = override_get_db

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        res = await client.get("/")
        assert res.status_code == 401


@pytest.mark.asyncio
async def test_hub_navigates_to_painel_and_dashboard(async_db_session):
    import app.api.routes.painel as painel
    from tests.test_painel_routes import FakeClientCounter

    app = create_app()

    async def override_get_db():
        yield async_db_session

    async def fake_worker_status():
        return {
            "queue_length": 0, "dead_letter_length": 0,
            "last_processed_at": None, "last_processed_seconds_ago": None,
            "status": "healthy",
        }

    app.dependency_overrides[get_db] = override_get_db
    painel._get_worker_status_backup = painel._get_worker_status
    painel._get_worker_status = fake_worker_status
    painel.RedisQueue_backup = painel.RedisQueue
    painel.RedisQueue = lambda settings: FakeClientCounter()

    settings = get_settings()
    auth = "Basic " + base64.b64encode(
        f"{settings.DASHBOARD_USERNAME or 'admin'}:{settings.DASHBOARD_PASSWORD or 'admin'}".encode()
    ).decode()

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        res = await client.get("/", headers={"Authorization": auth})
        assert res.status_code == 200
        assert 'href="/dashboard"' in res.text
        assert 'href="/painel"' in res.text
        assert "PromoBot" in res.text

    painel._get_worker_status = painel._get_worker_status_backup
    painel.RedisQueue = painel.RedisQueue_backup