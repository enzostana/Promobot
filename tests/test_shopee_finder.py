import hashlib

import httpx
import pytest

from app.config.settings import Settings
from app.core.models import (PromotionStatus, RawMessage)
from app.finder.shopee import ShopeeFinder
from app.core.processor import PromotionProcessor


def _finder_settings(**overrides) -> Settings:
    base = dict(
        APP_ENV="test",
        SHOPEE_API_APP_ID="123456",
        SHOPEE_API_SECRET="sec-abc",
        SHOPEE_FINDER_ENABLED=True,
        SHOPEE_FINDER_KEYWORDS="fone bluetooth,smart tv",
        SHOPEE_FINDER_MIN_DISCOUNT=20.0,
        SHOPEE_FINDER_MIN_SALES=50,
        SHOPEE_FINDER_MIN_RATING=4.0,
        SHOPEE_FINDER_MAX_PRICE=500.0,
        SHOPEE_FINDER_INTERVAL_MIN=30,
    )
    base.update(overrides)
    return Settings(**base)


def test_defaults():
    st = _finder_settings()
    assert st.get_shopee_finder_keywords() == ["fone bluetooth", "smart tv"]
    assert st.SHOPEE_FINDER_MIN_DISCOUNT == 20.0
    assert st.SHOPEE_FINDER_MIN_SALES == 50
    assert st.SHOPEE_FINDER_MIN_RATING == 4.0
    assert st.SHOPEE_FINDER_MAX_PRICE == 500.0
    assert st.SHOPEE_FINDER_INTERVAL_MIN == 30


class TestSignature:
    def test_build_signature_vector(self):
        app_id = "123456"
        secret = "sec-abc"
        timestamp = "1704067200"
        payload = '{"query":"{ ping }"}'
        expected = hashlib.sha256(
            (app_id + timestamp + payload + secret).encode("utf-8")
        ).hexdigest()
        assert ShopeeFinder.build_signature(app_id, secret, timestamp, payload) == expected

    def test_headers_format(self):
        finder = ShopeeFinder(_finder_settings())
        payload = '{"query":"x"}'
        headers = finder._build_headers(payload)
        auth = headers["Authorization"]
        assert auth.startswith("SHA256 Credential=123456, Timestamp=")
        assert ", Signature=" in auth
        assert len(hashlib.sha256(b"x").hexdigest()) == 64


def _mock_client_for(nodes):
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"data": {"productOfferV2": {"nodes": nodes, "pageInfo": {}}}})
    return httpx.AsyncClient(transport=httpx.MockTransport(handler))


@pytest.mark.asyncio
async def test_search_maps_and_filters():
    nodes = [
        {
            "itemId": 1001, "shopId": 7, "productName": "Fone bluetooth TWS",
            "productLink": "https://shopee.com.br/product/7/1001", "offerLink": "",
            "imageUrl": "https://cf.shopee.com.br/img/1001.jpg", "priceMin": "159.0",
            "priceMax": "159.0", "priceDiscountRate": "0.5", "sales": 1200,
            "ratingStar": "4.8", "commission": "8.0", "shopName": "Loja X",
        },
        {
            "itemId": 1002, "shopId": 8, "productName": "Cabo barato",
            "productLink": "https://shopee.com.br/product/8/1002", "offerLink": "",
            "imageUrl": "", "priceMin": "5.0", "priceMax": "9.0",
            "priceDiscountRate": "0.05", "sales": 3, "ratingStar": "2.1",
            "commission": "1.0", "shopName": "Loja Y",
        },
    ]
    finder = ShopeeFinder(_finder_settings(), client=_mock_client_for(nodes))
    offers = await finder.search("fone bluetooth")
    assert len(offers) == 1
    offer = offers[0]
    assert offer["item_id"] == 1001
    assert offer["discount_percentage"] == 50
    assert offer["original_price"] == pytest.approx(318.0, rel=1e-6)
    raw = finder.build_message(offer)
    assert raw.source == "shopee_finder"
    assert raw.source_message_id == "shopee-1001"
    assert raw.media_url == "https://cf.shopee.com.br/img/1001.jpg"
    assert "50% OFF" in raw.text
    assert "shopee.com.br/product/7/1001" in raw.text


@pytest.mark.asyncio
async def test_scan_enqueues_matching_offers():
    nodes = [
        {
            "itemId": 2001, "shopId": 9, "productName": "Smart watch barato",
            "productLink": "https://shopee.com.br/product/9/2001", "offerLink": "",
            "imageUrl": "", "priceMin": "299.0", "priceMax": "299.0",
            "priceDiscountRate": "0.4", "sales": 800, "ratingStar": "4.6",
            "commission": "2.0", "shopName": "Loja Z",
        }
    ]

    class RecordingQueue:
        def __init__(self):
            self.items = []

        async def enqueue(self, raw):
            self.items.append(raw)

    finder = ShopeeFinder(_finder_settings(SHOPEE_FINDER_KEYWORDS="fone bluetooth"),
                          client=_mock_client_for(nodes))
    queue = RecordingQueue()
    found = await finder.scan(queue)
    assert found == 1
    assert len(queue.items) == 1
    assert queue.items[0].source_message_id == "shopee-2001"


@pytest.mark.asyncio
async def test_credentials_required():
    finder = ShopeeFinder(_finder_settings(SHOPEE_API_SECRET=""))
    assert finder.credentials_ok() is False
    assert finder.enabled() is True


@pytest.mark.asyncio
async def test_pipeline_publishes_finder_message(
    async_db_session, test_settings, mock_publisher
):
    """Finder messages pass the full pipeline and publish; dedup holds repeats."""
    product_link = "https://shopee.com.br/product/7/1001"
    raw = RawMessage(
        id="shopee-xx-1001",
        source="shopee_finder",
        source_message_id="shopee-1001",
        source_chat_id="caçador:shopee",
        text=(
            "🔥 Fone bluetooth TWS\n"
            "💰 De: R$ 318,00\n"
            "🔥 Por: R$ 159,00\n"
            "📉 50% OFF\n\n"
            f"{product_link}"
        ),
        urls=[product_link],
    )
    processor = PromotionProcessor(publisher=mock_publisher, settings=test_settings)
    promo = await processor.process(raw, db_session=async_db_session)
    assert promo is not None
    assert promo.status == PromotionStatus.PUBLISHED
    assert promo.store == "shopee"
    assert len(mock_publisher.published_promotions) == 1

    # Same product scanned again -> duplicate, no re-publish
    raw2 = RawMessage(
        id="shopee-yy-1001",
        source="shopee_finder",
        source_message_id="shopee-1001",
        source_chat_id="caçador:shopee",
        text=raw.text,
        urls=[product_link],
    )
    promo2 = await processor.process(raw2, db_session=async_db_session)
    assert promo2.status == PromotionStatus.DUPLICATE
    assert len(mock_publisher.published_promotions) == 1