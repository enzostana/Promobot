import pytest
from httpx import ASGITransport, AsyncClient
from app.main import create_app
from app.database.session import get_db
from app.core.models import Promotion, PromotionStatus
from app.database.repositories.promotion_repo import PromotionRepository
from app.database.repositories.source_repo import SourceRepository
from app.database.repositories.publication_repo import PublicationRepository


@pytest.mark.asyncio
async def test_api_endpoints(async_db_session):
    app = create_app()

    # Override get_db dependency to use test in-memory SQLite session
    async def override_get_db():
        yield async_db_session

    app.dependency_overrides[get_db] = override_get_db

    # Seed some test data in DB
    source_repo = SourceRepository(async_db_session)
    await source_repo.get_or_create(chat_id="@promo_deals", platform="telegram", name="Promo Deals")

    promo_repo = PromotionRepository(async_db_session)
    promo = Promotion(
        source="telegram",
        source_message_id="101",
        source_chat_id="@promo_deals",
        original_text="Smart TV Samsung 50 4K",
        product_name="Smart TV Samsung 50 4K",
        original_price=2499.0,
        sale_price=1899.0,
        discount_percentage=24.0,
        store="amazon",
        original_url="https://amazon.com.br/dp/B08N5WRWNW",
        affiliate_url="https://amazon.com.br/dp/B08N5WRWNW?tag=tag-20",
        status=PromotionStatus.PUBLISHED
    )
    saved_promo = await promo_repo.create(promo)

    pub_repo = PublicationRepository(async_db_session)
    await pub_repo.create(
        promotion_id=saved_promo.id,
        target_chat_id="@meu_canal",
        formatted_content="Post de oferta",
        target_message_id="555"
    )

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        # 1. Test /health
        res_health = await client.get("/health")
        assert res_health.status_code == 200
        health_data = res_health.json()
        assert "status" in health_data

        # 2. Test /promotions list (paginated)
        res_promos = await client.get("/promotions")
        assert res_promos.status_code == 200
        promos_data = res_promos.json()
        assert "items" in promos_data
        assert len(promos_data["items"]) == 1
        assert promos_data["items"][0]["product_name"] == "Smart TV Samsung 50 4K"
        assert promos_data["items"][0]["store"] == "amazon"
        assert promos_data["total"] == 1
        assert promos_data["page"] == 1

        # 3. Test /promotions/{id} detail
        res_detail = await client.get(f"/promotions/{saved_promo.id}")
        assert res_detail.status_code == 200
        detail_data = res_detail.json()
        assert detail_data["id"] == saved_promo.id
        assert len(detail_data["sources"]) == 1
        assert len(detail_data["publications"]) == 1

        # 4. Test /sources (paginated)
        res_sources = await client.get("/sources")
        assert res_sources.status_code == 200
        sources_data = res_sources.json()
        assert "items" in sources_data
        assert len(sources_data["items"]) == 1
        assert sources_data["items"][0]["chat_id"] == "@promo_deals"
        assert sources_data["total"] == 1

        # 5. Test /publications (paginated)
        res_pubs = await client.get("/publications")
        assert res_pubs.status_code == 200
        pubs_data = res_pubs.json()
        assert "items" in pubs_data
        assert len(pubs_data["items"]) == 1
        assert pubs_data["items"][0]["target_chat_id"] == "@meu_canal"
        assert pubs_data["total"] == 1
