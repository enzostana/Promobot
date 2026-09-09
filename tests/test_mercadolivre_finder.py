import httpx
import pytest

from app.config.settings import Settings
from app.core.models import PromotionStatus, RawMessage
from app.core.processor import PromotionProcessor
from app.finder.mercadolivre import MercadoLivreFinder, _enlarge_thumbnail


def _finder_settings(**overrides) -> Settings:
    base = dict(
        APP_ENV="test",
        MEL_API_CLIENT_ID="123456789",
        MEL_API_CLIENT_SECRET="sec-mel",
        MEL_FINDER_ENABLED=True,
        MEL_FINDER_KEYWORDS="fone bluetooth,smart tv",
        MEL_FINDER_MIN_DISCOUNT=20.0,
        MEL_FINDER_MAX_PRICE=500.0,
        MEL_FINDER_INTERVAL_MIN=30,
    )
    base.update(overrides)
    return Settings(**base)


def test_defaults():
    st = _finder_settings()
    assert st.get_mel_finder_keywords() == ["fone bluetooth", "smart tv"]
    assert st.MEL_FINDER_MIN_DISCOUNT == 20.0
    assert st.MEL_FINDER_MAX_PRICE == 500.0
    assert st.MEL_FINDER_INTERVAL_MIN == 30
    assert st.MEL_API_CLIENT_ID == "123456789"


def test_enlarge_thumbnail():
    assert _enlarge_thumbnail("https://http2.mlstatic.com/D_NQ_NP_2x_1A-I.jpg") == (
        "https://http2.mlstatic.com/D_NQ_NP_2x_1A-O.jpg"
    )
    assert _enlarge_thumbnail("https://http2.mlstatic.com/D_NQ_NP_2x_1A.jpg") == (
        "https://http2.mlstatic.com/D_NQ_NP_2x_1A.jpg"
    )


def _mock_client_for(results):
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/oauth/token":
            return httpx.Response(200, json={"access_token": "tok-abc", "token_type": "bearer", "expires_in": 21600})
        if request.url.path == "/sites/MLB/search":
            return httpx.Response(200, json={"results": results, "paging": {"total": len(results)}})
        return httpx.Response(404, json={"message": "not found"})

    return httpx.AsyncClient(transport=httpx.MockTransport(handler))


def _result(item_id, price, original_price, title="Fone bluetooth", permalink=None):
    return {
        "id": item_id,
        "title": title,
        "price": price,
        "original_price": original_price,
        "permalink": permalink or f"https://produto.mercadolivre.com.br/_JM#id={item_id}",
        "thumbnail": "https://http2.mlstatic.com/D_NQ_NP_2x_1A-I.jpg",
        "sold_quantity": 500,
        "condition": "new",
        "seller": {"nickname": "LOJA_TESTE"},
    }


@pytest.mark.asyncio
async def test_search_fetches_token_and_filters():
    results = [
        # 50% de desconto, dentro do max_price -> passa
        _result("MLB1001", 100.0, 200.0, title="Fone bluetooth TWS"),
        # Sem original_price -> sem desconto real -> cai
        _result("MLB1002", 90.0, None, title="Fone sem promo"),
        # Desconto abaixo do mínimo -> cai
        _result("MLB1003", 190.0, 200.0, title="Fone 5% off"),
        # Acima do preço máximo -> cai
        _result("MLB1004", 900.0, 1800.0, title="Fone caro"),
    ]
    finder = MercadoLivreFinder(_finder_settings(), client=_mock_client_for(results))
    offers = await finder.search("fone bluetooth", token="tok-abc")
    assert len(offers) == 1
    offer = offers[0]
    assert offer["item_id"] == "MLB1001"
    assert offer["discount_percentage"] == pytest.approx(50.0)
    assert offer["original_price"] == pytest.approx(200.0)
    assert offer["price"] == pytest.approx(100.0)
    assert offer["thumbnail"].endswith("-O.jpg")


@pytest.mark.asyncio
async def test_scan_gets_token_and_enqueues():
    results = [_result("MLB2001", 150.0, 300.0, title="Smart watch barato")]
    finder = MercadoLivreFinder(
        _finder_settings(MEL_FINDER_KEYWORDS="smart watch"),
        client=_mock_client_for(results),
    )

    class RecordingQueue:
        def __init__(self):
            self.items = []

        async def enqueue(self, raw):
            self.items.append(raw)

    queue = RecordingQueue()
    found = await finder.scan(queue)
    assert found == 1
    raw = queue.items[0]
    assert raw.source == "mel_finder"
    assert raw.source_message_id == "mel-MLB2001"
    assert "50.0% OFF" in raw.text or "50% OFF" in raw.text
    assert "#id=MLB2001" in raw.text
    assert raw.media_url.endswith("-O.jpg")


def test_credentials_required():
    finder = MercadoLivreFinder(_finder_settings(MEL_API_CLIENT_ID=""))
    assert finder.credentials_ok() is False
    assert finder.enabled() is True
    assert finder.label == "Mercado Livre"
    assert finder.interval_min == 30


@pytest.mark.asyncio
async def test_pipeline_publishes_finder_message(
    async_db_session, test_settings, mock_publisher
):
    """Finder MEL passa pelo pipeline e ganha matt_tool; dedup segura repetição."""
    product_link = "https://produto.mercadolivre.com.br/_JM#id=MLB3001"
    raw = RawMessage(
        id="mel-wx-MLB3001",
        source="mel_finder",
        source_message_id="mel-MLB3001",
        source_chat_id="caçador:mercadolivre",
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
    assert promo.store == "mercadolivre"
    assert "matt_tool=meli_test_tag" in promo.affiliate_url
    assert len(mock_publisher.published_promotions) == 1

    raw2 = RawMessage(
        id="mel-yz-MLB3001",
        source="mel_finder",
        source_message_id="mel-MLB3001",
        source_chat_id="caçador:mercadolivre",
        text=raw.text,
        urls=[product_link],
    )
    promo2 = await processor.process(raw2, db_session=async_db_session)
    assert promo2.status == PromotionStatus.DUPLICATE
    assert len(mock_publisher.published_promotions) == 1