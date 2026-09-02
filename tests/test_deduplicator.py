import pytest
from app.core.models import Promotion, PromotionStatus
from app.core.deduplicator import Deduplicator
from app.config.settings import Settings


@pytest.fixture
def dedup():
    settings = Settings(DEDUP_WINDOW_HOURS=24)
    return Deduplicator(settings=settings)


def test_url_normalization(dedup):
    url_a = "https://www.amazon.com.br/dp/B08N5WRWNW?utm_source=canalA&ref=promo1"
    url_b = "https://www.amazon.com.br/dp/B08N5WRWNW?utm_source=canalB&ref=promo2&fbclid=xyz"

    norm_a = dedup.normalize_url(url_a)
    norm_b = dedup.normalize_url(url_b)

    assert norm_a == norm_b
    assert "https://www.amazon.com.br/dp/B08N5WRWNW" in norm_a
    assert "utm_source" not in norm_a
    assert "fbclid" not in norm_b


@pytest.mark.asyncio
async def test_duplicate_detection_by_product_id(dedup):
    promo1 = Promotion(
        source="telegram",
        source_message_id="101",
        source_chat_id="@canal_a",
        original_text="Smart TV Samsung 50",
        product_name="Smart TV Samsung 50",
        sale_price=1899.0,
        store="amazon",
        product_id="B08N5WRWNW",
        original_url="https://www.amazon.com.br/dp/B08N5WRWNW?src=a",
    )

    # First time -> not duplicate
    is_dup, _ = await dedup.is_duplicate(promo1)
    assert is_dup is False

    # Record seen
    await dedup.record_seen(promotion_id=1, promotion=promo1)

    # Second time from different chat and message ID -> must be duplicate!
    promo2 = Promotion(
        source="telegram",
        source_message_id="505",
        source_chat_id="@canal_b",
        original_text="TV Samsung 50 4K",
        product_name="TV Samsung 50 4K",
        sale_price=1899.0,
        store="amazon",
        product_id="B08N5WRWNW",
        original_url="https://www.amazon.com.br/dp/B08N5WRWNW?src=b",
    )
    is_dup2, _ = await dedup.is_duplicate(promo2)
    assert is_dup2 is True


@pytest.mark.asyncio
async def test_duplicate_detection_by_normalized_url(dedup):
    promo1 = Promotion(
        source="telegram",
        source_message_id="201",
        source_chat_id="@canal_x",
        original_text="Cadeira Gamer",
        product_name="Cadeira Gamer Confort",
        sale_price=599.0,
        store="loja_gamer",
        original_url="https://lojadogamer.com/cadeira?utm_source=canal_x",
    )

    is_dup, _ = await dedup.is_duplicate(promo1)
    assert is_dup is False

    await dedup.record_seen(promotion_id=2, promotion=promo1)

    # Same URL with different utm query parameters
    promo2 = Promotion(
        source="telegram",
        source_message_id="302",
        source_chat_id="@canal_y",
        original_text="Oferta Cadeira Gamer",
        product_name="Cadeira Gamer Confort",
        sale_price=599.0,
        store="loja_gamer",
        original_url="https://lojadogamer.com/cadeira?utm_source=canal_y&ref=123",
    )
    is_dup2, _ = await dedup.is_duplicate(promo2)
    assert is_dup2 is True


@pytest.mark.asyncio
async def test_different_products_not_duplicate(dedup):
    promo_tv = Promotion(
        source="telegram",
        source_message_id="1",
        source_chat_id="@canal",
        original_text="TV",
        product_name="TV 55",
        sale_price=2500.0,
        store="amazon",
        product_id="B000000001",
        original_url="https://amazon.com.br/dp/B000000001",
    )
    await dedup.record_seen(10, promo_tv)

    promo_phone = Promotion(
        source="telegram",
        source_message_id="2",
        source_chat_id="@canal",
        original_text="Celular",
        product_name="Smartphone X",
        sale_price=1200.0,
        store="amazon",
        product_id="B000000002",
        original_url="https://amazon.com.br/dp/B000000002",
    )

    is_dup, _ = await dedup.is_duplicate(promo_phone)
    assert is_dup is False
