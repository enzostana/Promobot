import pytest
from app.core.models import RawMessage, PromotionStatus
from app.core.processor import PromotionProcessor
from app.database.repositories.promotion_repo import PromotionRepository
from app.database.repositories.publication_repo import PublicationRepository


@pytest.mark.asyncio
async def test_full_pipeline_success(async_db_session, test_settings, mock_publisher):
    processor = PromotionProcessor(
        publisher=mock_publisher,
        settings=test_settings
    )

    raw_msg = RawMessage(
        id="msg-1",
        source="telegram",
        source_message_id="1001",
        source_chat_id="@promo_deals",
        source_chat_title="Canal Promo Deals",
        text=(
            "🔥 SMART TV SAMSUNG 50” 4K\n\n"
            "💰 De: R$ 2.499,00\n"
            "🔥 Por: R$ 1.899,00\n\n"
            "📉 24% OFF\n\n"
            "https://www.amazon.com.br/dp/B08N5WRWNW"
        )
    )

    promo = await processor.process(raw_msg, db_session=async_db_session)

    assert promo is not None
    assert promo.status == PromotionStatus.PUBLISHED
    assert promo.store == "amazon"
    assert "tag=testtag-20" in promo.affiliate_url
    assert len(mock_publisher.published_promotions) == 1

    # Verify DB persistence
    repo = PromotionRepository(async_db_session)
    db_promo = await repo.get_by_id(promo.id)
    assert db_promo is not None
    assert db_promo.product_name == "SMART TV SAMSUNG 50” 4K"
    assert float(db_promo.sale_price) == 1899.0
    assert len(db_promo.sources) == 1
    assert db_promo.sources[0].source_chat_id == "@promo_deals"

    pub_repo = PublicationRepository(async_db_session)
    pubs = await pub_repo.list_publications()
    assert len(pubs) == 1
    assert pubs[0].status == "published"


@pytest.mark.asyncio
async def test_pipeline_deduplication_multi_source(async_db_session, test_settings, mock_publisher):
    processor = PromotionProcessor(
        publisher=mock_publisher,
        settings=test_settings
    )

    # First source posts deal
    msg1 = RawMessage(
        id="msg-1",
        source="telegram",
        source_message_id="101",
        source_chat_id="@canal_a",
        text="🔥 TV 50 4K\nPor: R$ 1.899\nhttps://www.amazon.com.br/dp/B08N5WRWNW?ref=a"
    )
    promo1 = await processor.process(msg1, db_session=async_db_session)
    assert promo1.status == PromotionStatus.PUBLISHED
    assert len(mock_publisher.published_promotions) == 1

    # Second source posts the same deal
    msg2 = RawMessage(
        id="msg-2",
        source="telegram",
        source_message_id="202",
        source_chat_id="@canal_b",
        text="Super TV 50\nPor: R$ 1.899\nhttps://www.amazon.com.br/dp/B08N5WRWNW?ref=b"
    )
    promo2 = await processor.process(msg2, db_session=async_db_session)

    # Must be marked DUPLICATE and NOT published again!
    assert promo2.status == PromotionStatus.DUPLICATE
    assert len(mock_publisher.published_promotions) == 1

    # But second source must be recorded on the original promotion in DB!
    repo = PromotionRepository(async_db_session)
    db_promo = await repo.get_by_id(promo1.id)
    assert len(db_promo.sources) == 2
    chat_ids = {s.source_chat_id for s in db_promo.sources}
    assert "@canal_a" in chat_ids
    assert "@canal_b" in chat_ids


@pytest.mark.asyncio
async def test_painel_test_bypasses_dedup(async_db_session, test_settings, mock_publisher):
    processor = PromotionProcessor(
        publisher=mock_publisher,
        settings=test_settings
    )

    # A real (telegram) message publishes the deal and registers it as seen
    msg_telegram = RawMessage(
        id="msg-tg",
        source="telegram",
        source_message_id="501",
        source_chat_id="@canal_a",
        text="TV 50 4K\nPor: R$ 1.899\nhttps://www.amazon.com.br/dp/B08N5WRWNW"
    )
    promo_tg = await processor.process(msg_telegram, db_session=async_db_session)
    assert promo_tg.status == PromotionStatus.PUBLISHED
    assert len(mock_publisher.published_promotions) == 1

    # The very same content via painel test must STILL publish (dedup bypassed)
    msg_painel = RawMessage(
        id="painel-test-abc123",
        source="painel",
        source_message_id="painel-test-abc123",
        source_chat_id="",
        text="TV 50 4K\nPor: R$ 1.899\nhttps://www.amazon.com.br/dp/B08N5WRWNW"
    )
    promo_painel = await processor.process(msg_painel, db_session=async_db_session)
    assert promo_painel is not None
    assert promo_painel.status == PromotionStatus.PUBLISHED
    assert len(mock_publisher.published_promotions) == 2

    # Dedup still guards real messages with the same content
    msg_dup = RawMessage(
        id="msg-dup",
        source="telegram",
        source_message_id="502",
        source_chat_id="@canal_b",
        text="TV 50 4K\nPor: R$ 1.899\nhttps://www.amazon.com.br/dp/B08N5WRWNW"
    )
    promo_dup = await processor.process(msg_dup, db_session=async_db_session)
    assert promo_dup.status == PromotionStatus.DUPLICATE
    assert len(mock_publisher.published_promotions) == 2


@pytest.mark.asyncio
async def test_pipeline_filtered_out(async_db_session, test_settings, mock_publisher):
    processor = PromotionProcessor(
        publisher=mock_publisher,
        settings=test_settings
    )

    # Discount below minimum (minimum is 10.0%)
    raw_msg = RawMessage(
        id="msg-filter",
        source="telegram",
        source_message_id="301",
        source_chat_id="@promo_deals",
        text=(
            "Smartphone Barato\n"
            "De: R$ 1000\n"
            "Por: R$ 980\n"
            "https://www.amazon.com.br/dp/B000000099"
        )
    )

    promo = await processor.process(raw_msg, db_session=async_db_session)
    assert promo is not None
    assert promo.status == PromotionStatus.FILTERED_OUT
    assert "abaixo do mínimo" in promo.filter_reason
    # Should not have published
    assert len(mock_publisher.published_promotions) == 0


@pytest.mark.asyncio
async def test_pipeline_handles_publisher_failure(async_db_session, test_settings):
    from tests.conftest import MockPublisher
    failing_publisher = MockPublisher(should_succeed=False)

    processor = PromotionProcessor(
        publisher=failing_publisher,
        settings=test_settings
    )

    raw_msg = RawMessage(
        id="msg-fail",
        source="telegram",
        source_message_id="401",
        source_chat_id="@promo_deals",
        text="TV Samsung\nPor: R$ 1500\nhttps://www.amazon.com.br/dp/B08N5WRWNW"
    )

    promo = await processor.process(raw_msg, db_session=async_db_session)
    assert promo is not None
    assert promo.status == PromotionStatus.FAILED
    assert "Simulated publication error" in promo.error_message


class RaisingPublisher:
    """Publisher that raises instead of returning a result."""

    async def publish(self, promotion, formatted_message):
        raise RuntimeError("boom do publisher")


@pytest.mark.asyncio
async def test_pipeline_survives_publisher_raising(async_db_session, test_settings):
    processor = PromotionProcessor(
        publisher=RaisingPublisher(),
        settings=test_settings
    )

    raw_msg = RawMessage(
        id="msg-raise",
        source="telegram",
        source_message_id="402",
        source_chat_id="@promo_deals",
        text="Notebook Dell\nPor: R$ 2500\nhttps://www.amazon.com.br/dp/B08N5WRWNW"
    )

    # process() must NOT raise; error is swallowed so the worker survives
    promo = await processor.process(raw_msg, db_session=async_db_session)
    assert promo is None
