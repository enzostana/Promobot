import json

import httpx
import pytest

from app.config.settings import Settings
from app.core.models import PromotionStatus, RawMessage
from app.core.processor import PromotionProcessor
from app.finder.amazon import AmazonFinder, _matched_keyword


def _finder_settings(**overrides) -> Settings:
    base = dict(
        APP_ENV="test",
        AMAZON_FINDER_ENABLED=True,
        AMAZON_FINDER_KEYWORDS="fone bluetooth,smart tv",
        AMAZON_FINDER_MIN_DISCOUNT=20.0,
        AMAZON_FINDER_MAX_PRICE=500.0,
        AMAZON_FINDER_INTERVAL_MIN=30,
    )
    base.update(overrides)
    return Settings(**base)


def _product(asin, title, price, original, discount_text="20% off", image="41iFGla9E5L"):
    price_obj = {"priceToPay": {"label": "Preço da Oferta:", "price": str(price), "strikethrough": False}}
    if original:
        price_obj["basisPrice"] = {"label": "De:", "price": str(original), "strikethrough": True}
    return {
        "asin": asin,
        "title": title,
        "link": f"/{title.replace(' ', '-')}/dp/{asin}",
        "linkV3Params": {},
        "image": {
            "hiRes": {"baseUrl": f"https://m.media-amazon.com/images/I/{image}", "extension": "jpg"},
            "lowRes": {"baseUrl": f"https://m.media-amazon.com/images/I/{image}", "extension": "jpg"},
            "physicalId": image,
            "variant": "MAIN",
        },
        "price": price_obj,
        "dealBadge": {
            "label": {"content": {"fragments": [{"text": discount_text}]}},
            "messaging": {"content": {"fragments": [{"text": "Oferta"}]}},
        },
        "dealDetails": {"state": "AVAILABLE", "type": "BEST_DEAL", "id": "abc123"},
    }


def _deals_html(*products):
    payload = {
        "productSearchResponse": {
            "nextIndex": 30,
            "startIndex": 0,
            "products": list(products),
        }
    }
    # Simula o JSON embutido no HTML do storefront de deals da Amazon.
    return '<!doctype html><html><body><script type="application/json">{}</script></body></html>'.format(
        json.dumps(payload)
    )


def _mock_client_for(html: str) -> httpx.AsyncClient:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, text=html)

    return httpx.AsyncClient(transport=httpx.MockTransport(handler))


class RecordingQueue:
    def __init__(self):
        self.items = []

    async def enqueue(self, raw):
        self.items.append(raw)


def test_defaults():
    st = _finder_settings()
    assert st.get_amazon_finder_keywords() == ["fone bluetooth", "smart tv"]
    assert st.AMAZON_FINDER_MIN_DISCOUNT == 20.0
    assert st.AMAZON_FINDER_MAX_PRICE == 500.0
    assert st.AMAZON_FINDER_INTERVAL_MIN == 30
    assert st.AMAZON_FINDER_ENABLED is True


def test_matched_keyword_helper():
    assert _matched_keyword("Fone bluetooth TWS Pro", ["fone bluetooth", "smart tv"]) == "fone bluetooth"
    assert _matched_keyword("Camêra de segurança", ["camera"]) == "camera"
    assert _matched_keyword("Smart TV 50", ["fone bluetooth"]) is None
    assert _matched_keyword("Smart TV 50", []) is None


def test_parse_products_embeds_json_and_dedupes():
    html = _deals_html(
        _product("B0F4ZTT2MM", "Fone bluetooth TWS Pro", 100.0, 200.0),
        # mesma asin duas vezes -> dedup por permalink
        _product("B0F4ZTT2MM", "Fone bluetooth TWS Pro", 100.0, 200.0),
        _product("B012345678", "Smart TV 50 4K", 1800.0, 4000.0),
    )
    offers = AmazonFinder._parse_offers(html)
    assert len(offers) == 2
    by_asin = {o["item_id"]: o for o in offers}
    assert by_asin["B0F4ZTT2MM"]["discount_percentage"] == 50.0
    assert by_asin["B012345678"]["price"] == 1800.0
    assert (
        by_asin["B0F4ZTT2MM"]["permalink"]
        == "https://www.amazon.com.br/dp/B0F4ZTT2MM"
    )
    assert by_asin["B0F4ZTT2MM"]["thumbnail"] == "https://m.media-amazon.com/images/I/41iFGla9E5L.jpg"


def test_offer_without_strikethrough_uses_deal_badge():
    html = _deals_html(_product("B0F4ZTT2MM", "Fone bluetooth", 80.0, None, discount_text="15% off"))
    offers = AmazonFinder._parse_offers(html)
    assert len(offers) == 1
    assert offers[0]["discount_percentage"] == 15.0


def test_passes_records_matched_keyword():
    finder = AmazonFinder(_finder_settings())
    offer = {
        "item_id": "B0F4ZTT2MM",
        "product_name": "Fone bluetooth TWS Pro",
        "price": 100.0,
        "original_price": 200.0,
        "discount_percentage": 50.0,
        "permalink": "https://www.amazon.com.br/dp/B0F4ZTT2MM",
    }
    assert finder._passes(offer) is True
    assert offer["matched_keyword"] == "fone bluetooth"


def test_passes_fails_on_conditions():
    finder = AmazonFinder(_finder_settings())
    base = {
        "item_id": "B0F4ZTT2MM",
        "product_name": "Fone bluetooth TWS Pro",
        "price": 100.0,
        "original_price": 100.0,
        "discount_percentage": 0.0,
        "permalink": "https://www.amazon.com.br/dp/B0F4ZTT2MM",
    }
    assert finder._passes({**base, "price": 600.0}) is False  # acima do teto
    assert finder._passes({**base, "discount_percentage": 10.0}) is False  # abaixo do mín
    assert finder._passes({**base, "product_name": "Smart TV 50"}) is False  # sem keyword


def test_build_message_carries_matched_keyword():
    finder = AmazonFinder(_finder_settings())
    raw = finder.build_message({
        "item_id": "B0F4ZTT2MM",
        "product_name": "Fone bluetooth TWS Pro",
        "price": 100.0,
        "original_price": 200.0,
        "discount_percentage": 50.0,
        "permalink": "https://www.amazon.com.br/dp/B0F4ZTT2MM",
        "thumbnail": "https://m.media-amazon.com/images/I/41iFGla9E5L.jpg",
        "matched_keyword": "fone bluetooth",
    })
    assert raw.source == "amazon_finder"
    assert raw.source_chat_id == "caçador:amazon"
    assert raw.matched_keyword == "fone bluetooth"
    assert raw.urls == ["https://www.amazon.com.br/dp/B0F4ZTT2MM"]
    assert "https://www.amazon.com.br/dp/B0F4ZTT2MM" in raw.text
    assert "50.0% OFF" in raw.text


@pytest.mark.asyncio
async def test_scan_enqueues_matching_offers():
    html = _deals_html(
        _product("B0F4ZTT2MM", "Fone bluetooth TWS Pro", 100.0, 200.0),
        _product("B012345678", "Smart TV 50 4K", 1800.0, 4000.0),
        _product("B034567890", "Smartphone 128GB", 1200.0, 2000.0),
    )
    finder = AmazonFinder(
        _finder_settings(AMAZON_FINDER_MAX_PRICE=500),
        client=_mock_client_for(html),
    )
    queue = RecordingQueue()
    found = await finder.scan(queue)
    # Fone passa (desconto 50%, 100 <= 500); Smart TV passa pelo DESCONTO mas excede teto
    # (1800 > 500) -> cai; Smartphone excede teto -> cai.
    assert found == 1
    assert queue.items[0].source_message_id == "amazon-scrape-B0F4ZTT2MM"
    assert queue.items[0].matched_keyword == "fone bluetooth"


@pytest.mark.asyncio
async def test_keyword_match_ignores_accents():
    html = _deals_html(_product("B0GGGGGGGG", "Kit 2 Camêras de Segurança WiFi", 150.0, 300.0))
    finder = AmazonFinder(
        _finder_settings(AMAZON_FINDER_KEYWORDS="camera"),
        client=_mock_client_for(html),
    )
    queue = RecordingQueue()
    found = await finder.scan(queue)
    assert found == 1
    assert queue.items[0].source_message_id == "amazon-scrape-B0GGGGGGGG"


@pytest.mark.asyncio
async def test_scan_http_error_returns_zero():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(503, text="unavailable")

    finder = AmazonFinder(
        _finder_settings(),
        client=httpx.AsyncClient(transport=httpx.MockTransport(handler)),
    )
    finder.retry_attempts = 1
    assert await finder.scan(RecordingQueue()) == 0


@pytest.mark.asyncio
async def test_scan_retries_after_503_then_succeeds():
    calls = {"n": 0}
    html = _deals_html(_product("B0F4ZTT2MM", "Fone bluetooth TWS Pro", 100.0, 200.0))

    def handler(request: httpx.Request) -> httpx.Response:
        calls["n"] += 1
        if calls["n"] < 3:
            return httpx.Response(503, text="unavailable")
        return httpx.Response(200, text=html)

    finder = AmazonFinder(
        _finder_settings(),
        client=httpx.AsyncClient(transport=httpx.MockTransport(handler)),
    )
    finder.retry_backoff_s = 0.0
    queue = RecordingQueue()
    found = await finder.scan(queue)
    assert calls["n"] == 3
    assert found == 1
    assert queue.items[0].source_message_id == "amazon-scrape-B0F4ZTT2MM"


@pytest.mark.asyncio
async def test_scan_gives_up_after_all_retries():
    calls = {"n": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        calls["n"] += 1
        return httpx.Response(503, text="unavailable")

    finder = AmazonFinder(
        _finder_settings(),
        client=httpx.AsyncClient(transport=httpx.MockTransport(handler)),
    )
    finder.retry_backoff_s = 0.0
    assert await finder.scan(RecordingQueue()) == 0
    assert calls["n"] == 3


def test_credentials_not_required_for_scraping():
    finder = AmazonFinder(_finder_settings())
    assert finder.credentials_ok() is True
    assert finder.enabled() is True
    assert finder.label == "Amazon"
    assert finder.interval_min == 30


@pytest.mark.asyncio
async def test_pipeline_publishes_finder_message(
    async_db_session, test_settings, mock_publisher
):
    """Finder Amazon passa pelo pipeline e ganha a tag de afiliado; dedup segura repetição."""
    product_link = "https://www.amazon.com.br/dp/B0F4ZTT2MM"
    raw = RawMessage(
        id="amazon-wx-B0F4ZTT2MM",
        source="amazon_finder",
        source_message_id="amazon-scrape-B0F4ZTT2MM",
        source_chat_id="caçador:amazon",
        text=(
            "🔥 Fone bluetooth TWS\n"
            "💰 De: R$ 200,00\n"
            "🔥 Por: R$ 100,00\n"
            "📉 50% OFF\n\n"
            f"{product_link}"
        ),
        urls=[product_link],
    )
    processor = PromotionProcessor(publisher=mock_publisher, settings=test_settings)
    promo = await processor.process(raw, db_session=async_db_session)
    assert promo is not None
    assert promo.status == PromotionStatus.PUBLISHED
    assert promo.store == "amazon"
    assert promo.affiliate_url == "https://www.amazon.com.br/dp/B0F4ZTT2MM?tag=testtag-20"
    assert len(mock_publisher.published_promotions) == 1

    raw2 = RawMessage(
        id="amazon-yz-B0F4ZTT2MM",
        source="amazon_finder",
        source_message_id="amazon-scrape-B0F4ZTT2MM",
        source_chat_id="caçador:amazon",
        text=raw.text,
        urls=[product_link],
    )
    promo2 = await processor.process(raw2, db_session=async_db_session)
    assert promo2.status == PromotionStatus.DUPLICATE
    assert len(mock_publisher.published_promotions) == 1