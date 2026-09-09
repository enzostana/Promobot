from datetime import datetime, timedelta

import pytest
from httpx import ASGITransport, AsyncClient

from app.main import create_app
from app.database.session import get_db
from app.core.models import Promotion, PromotionStatus
from app.database.repositories.promotion_repo import PromotionRepository
from app.api.routes.site import _site_image_url


def make_promo(
    name: str,
    store: str = "amazon",
    category: str = "eletrodomesticos",
    price: float = 99.0,
    sale: float = 79.0,
    discount: float = 20.0,
    source: str = "telegram",
    status=PromotionStatus.PUBLISHED,
    image_url: str = "",
    created_at=None,
):
    return Promotion(
        source=source,
        source_message_id=name,
        source_chat_id="@test_chat",
        original_text=name,
        product_name=name,
        original_price=price,
        sale_price=sale,
        discount_percentage=discount,
        store=store,
        category=category,
        image_url=image_url,
        original_url="https://exemplo.com/x",
        affiliate_url="https://exemplo.com/x?tag=x",
        status=status,
        created_at=created_at or datetime.now(),
    )


@pytest.mark.asyncio
async def test_site_home_public(async_db_session):
    app = create_app()

    async def override_get_db():
        yield async_db_session

    app.dependency_overrides[get_db] = override_get_db

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        res = await client.get("/")
        assert res.status_code == 200
        assert "Rufino Promo" in res.text
        assert "Promoções" in res.text
        assert 'href="/hub"' in res.text


@pytest.mark.asyncio
async def test_site_home_hides_painel_and_draft(async_db_session):
    app = create_app()

    async def override_get_db():
        yield async_db_session

    app.dependency_overrides[get_db] = override_get_db
    repo = PromotionRepository(async_db_session)
    visivel = await repo.create(make_promo("Produto visível"))
    await repo.create(make_promo("Rascunho interno", status=PromotionStatus.PENDING))
    await repo.create(make_promo("Do painel", source="painel", status=PromotionStatus.PUBLISHED))

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        res = await client.get("/")
        assert "Produto visível" in res.text
        assert "Rascunho interno" not in res.text
        assert "Do painel" not in res.text

        feed = await client.get("/api/site/promotions")
        assert feed.status_code == 200
        data = feed.json()
        assert data["total"] == 1
        assert data["items"][0]["product_name"] == "Produto visível"
        assert data["items"][0]["url"] == f'/p/{visivel.id}'


@pytest.mark.asyncio
async def test_site_api_filters_and_ordering(async_db_session):
    app = create_app()

    async def override_get_db():
        yield async_db_session

    app.dependency_overrides[get_db] = override_get_db
    repo = PromotionRepository(async_db_session)
    now = datetime.now()
    await repo.create(make_promo("Fone Bluetooth", store="mercadolivre", discount=30.0, created_at=now))
    await repo.create(make_promo("Smart TV 50", store="amazon", discount=50.0, created_at=now - timedelta(hours=1)))
    await repo.create(make_promo("Aspirador Robô", store="shopee", discount=10.0, created_at=now - timedelta(hours=2)))

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        feed = await client.get("/api/site/promotions?order=discount")
        data = feed.json()
        assert [i["product_name"] for i in data["items"]] == ["Smart TV 50", "Fone Bluetooth", "Aspirador Robô"]

        search = await client.get("/api/site/promotions?q=tv")
        sdata = search.json()
        assert [i["product_name"] for i in sdata["items"]] == ["Smart TV 50"]

        store = await client.get("/api/site/promotions?store=shopee")
        assert store.json()["total"] == 1
        assert store.json()["items"][0]["store"] == "shopee"

        meta = await client.get("/api/site/meta")
        assert meta.status_code == 200
        m = meta.json()
        assert set(m["stores"]) == {"mercadolivre", "amazon", "shopee"}
        assert "eletrodomesticos" in m["categories"]


@pytest.mark.asyncio
async def test_site_pagination(async_db_session):
    app = create_app()

    async def override_get_db():
        yield async_db_session

    app.dependency_overrides[get_db] = override_get_db
    repo = PromotionRepository(async_db_session)
    now = datetime.now()
    for i in range(25):
        await repo.create(make_promo(f"Produto {i:02d}", created_at=now - timedelta(hours=i)))

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        p1 = await client.get("/promocoes")
        assert p1.status_code == 200
        assert "próxima" in p1.text
        assert "Produto 00" in p1.text

        p2 = await client.get("/promocoes?page=2")
        assert "Produto 24" in p2.text

        feed = await client.get("/api/site/promotions?page=2&limit=24")
        assert feed.json()["total"] == 25
        assert len(feed.json()["items"]) == 1


@pytest.mark.asyncio
async def test_site_detail_visibility(async_db_session):
    app = create_app()

    async def override_get_db():
        yield async_db_session

    app.dependency_overrides[get_db] = override_get_db
    repo = PromotionRepository(async_db_session)
    visivel = await repo.create(make_promo("Oferta da página", discount=45.0))
    painel = await repo.create(make_promo("Interna", source="painel", status=PromotionStatus.PUBLISHED))
    rascunho = await repo.create(make_promo("Rascunho", status=PromotionStatus.PENDING))

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        ok = await client.get(f"/p/{visivel.id}")
        assert ok.status_code == 200
        assert "Oferta da página" in ok.text
        assert "45% OFF" in ok.text
        assert "VER OFERTA NA LOJA" in ok.text

        assert (await client.get(f"/p/{painel.id}")).status_code == 404
        assert (await client.get(f"/p/{rascunho.id}")).status_code == 404
        assert (await client.get("/p/99999")).status_code == 404


def test_site_image_url_mapping():
    assert _site_image_url("") == ""
    assert _site_image_url(None) == ""
    assert _site_image_url("https://cdn.x.com/a.jpg") == "https://cdn.x.com/a.jpg"
    assert _site_image_url("media_cache/abc.jpg") == "/media/abc.jpg"
    assert _site_image_url("/app/media_cache/abc.jpg") == "/media/abc.jpg"
    assert _site_image_url("blob://foo") == ""