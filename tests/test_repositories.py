import pytest
from app.core.models import Promotion, PromotionStatus
from app.database.repositories.promotion_repo import PromotionRepository
from app.database.repositories.source_repo import SourceRepository
from app.database.repositories.publication_repo import PublicationRepository
from app.database.repositories.affiliate_link_repo import AffiliateLinkRepository


def _make_promotion(**overrides) -> Promotion:
    defaults = dict(
        source="telegram",
        source_message_id="1001",
        source_chat_id="@promo_deals",
        original_text="Smart TV Samsung 50 4K",
        product_name="Smart TV Samsung 50 4K",
        original_price=2499.0,
        sale_price=1899.0,
        discount_percentage=24.0,
        store="amazon",
        product_id="B08N5WRWNW",
        original_url="https://amazon.com.br/dp/B08N5WRWNW",
        affiliate_url="https://amazon.com.br/dp/B08N5WRWNW?tag=tag-20",
        status=PromotionStatus.PUBLISHED,
    )
    defaults.update(overrides)
    return Promotion(**defaults)


# --- SourceRepository ---


@pytest.mark.asyncio
async def test_source_repo_get_or_create(async_db_session):
    repo = SourceRepository(async_db_session)

    src = await repo.get_or_create(chat_id="@promo_deals", platform="telegram", name="Promo Deals")
    assert src.id is not None
    assert src.chat_id == "@promo_deals"
    assert src.name == "Promo Deals"
    assert src.is_active is True

    src_again = await repo.get_or_create(chat_id="@promo_deals", platform="telegram", name="Outro Nome")
    assert src_again.id == src.id

    other = await repo.get_or_create(chat_id="@canal_b", platform="telegram", name="Canal B")
    assert other.id != src.id

    sources = await repo.list_sources(active_only=True)
    assert len(sources) == 2


# --- PromotionRepository ---


@pytest.mark.asyncio
async def test_promotion_repo_crud(async_db_session):
    repo = PromotionRepository(async_db_session)

    promo = await repo.create(_make_promotion())
    assert promo.id is not None

    fetched = await repo.get_by_id(promo.id)
    assert fetched is not None
    assert fetched.product_name == "Smart TV Samsung 50 4K"
    assert len(fetched.sources) == 1
    assert fetched.sources[0].source_chat_id == "@promo_deals"

    updated = await repo.update_status(promo.id, PromotionStatus.FAILED, error_message="boom")
    assert updated.status == PromotionStatus.FAILED.value
    assert updated.error_message == "boom"

    listing = await repo.list_promotions(status="failed")
    assert len(listing) == 1
    listing_default = await repo.list_promotions()
    assert len(listing_default) == 1


@pytest.mark.asyncio
async def test_promotion_repo_find_duplicate(async_db_session):
    repo = PromotionRepository(async_db_session)

    promo = await repo.create(_make_promotion())

    dup_by_product = await repo.find_duplicate(
        store="amazon",
        product_id="B08N5WRWNW",
        normalized_url="",
        content_hash=None,
    )
    assert dup_by_product is not None
    assert dup_by_product.id == promo.id

    dup_by_url = await repo.find_duplicate(
        store=None,
        product_id=None,
        normalized_url="https://amazon.com.br/dp/B08N5WRWNW",
        content_hash=None,
    )
    assert dup_by_url is not None
    assert dup_by_url.id == promo.id

    dup_by_hash = await repo.find_duplicate(
        store=None,
        product_id=None,
        normalized_url="",
        content_hash="somenonsensehash123",
    )
    assert dup_by_hash is None


@pytest.mark.asyncio
async def test_promotion_repo_add_source_reference(async_db_session):
    repo = PromotionRepository(async_db_session)
    promo = await repo.create(_make_promotion())

    await repo.add_source_reference(promo.id, "@canal_b", "202")
    fetched = await repo.get_by_id(promo.id)
    chat_ids = {s.source_chat_id for s in fetched.sources}
    assert chat_ids == {"@promo_deals", "@canal_b"}


# --- PublicationRepository ---


@pytest.mark.asyncio
async def test_publication_repo(async_db_session):
    promo = await PromotionRepository(async_db_session).create(_make_promotion())
    repo = PublicationRepository(async_db_session)

    pub = await repo.create(
        promotion_id=promo.id,
        target_chat_id="@meu_canal",
        formatted_content="Post de oferta",
        target_message_id="555",
    )
    assert pub.id is not None
    assert pub.status == "published"

    pubs = await repo.list_publications()
    assert len(pubs) == 1
    assert pubs[0].target_chat_id == "@meu_canal"

    failed = await repo.create(
        promotion_id=promo.id,
        target_chat_id="@meu_canal",
        formatted_content="x",
        status="failed",
        error_message="erro",
    )
    assert failed.status == "failed"
    assert failed.error_message == "erro"
    assert len(await repo.list_publications()) == 2


# --- AffiliateLinkRepository ---


@pytest.mark.asyncio
async def test_affiliate_link_repo(async_db_session):
    promo = await PromotionRepository(async_db_session).create(_make_promotion())
    repo = AffiliateLinkRepository(async_db_session)

    link = await repo.create(
        promotion_id=promo.id,
        store="amazon",
        original_url="https://amazon.com.br/dp/B08N5WRWNW",
        affiliate_url="https://amazon.com.br/dp/B08N5WRWNW?tag=tag-20",
    )
    assert link.id is not None

    by_promo = await repo.list_by_promotion(promo.id)
    assert len(by_promo) == 1
    assert by_promo[0].store == "amazon"

    all_links = await repo.list_links()
    assert len(all_links) == 1

    found = await repo.find_by_original_url("https://amazon.com.br/dp/B08N5WRWNW")
    assert found is not None
    assert found.id == link.id

    not_found = await repo.find_by_original_url("https://shopee.com.br/nao-existe")
    assert not_found is None
