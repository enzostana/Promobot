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


def _card(title, item_link, thumbs_src, original, current):
    prev = (
        f'<s class="andes-money-amount polylabel-price andes-money-amount--previous '
        f'andes-money-amount--cents-comma" role="img" aria-label="Antes: {original}">'
        f'<span class="andes-money-amount__fraction">{original.split(" reais")[0]}</span></s>'
        if original
        else ""
    )
    return (
        '<div class="andes-card poly-card poly-card--grid-card" data-testid="card">'
        '<img class="poly-component__picture" src="' + thumbs_src + '" alt="' + title + '"/>'
        '<h3 class="poly-component__title-wrapper">'
        '<a href="' + item_link + '" target="_self" class="poly-component__title">' + title + "</a>"
        "</h3>"
        '<div class="poly-component__price">'
        f'<span class="poly-price__label"><span style="color:#757575">{prev}</span></span>'
        '<span class="andes-money-amount poly-price__amount andes-money-amount--cents-superscript" '
        'role="img" aria-label="' + current + '">'
        '<span class="andes-money-amount__fraction">1</span></span>'
        "</div></div>"
    )


def _offers_page_html():
    cards = [
        # 100 → 200 (50% off), tema ok, dentro do max → passa
        _card(
            "Fone bluetooth TWS Pro",
            "https://produto.mercadolivre.com.br/MLB-1001-fone-bluetooth-tws-pro-_JM",
            "https://http2.mlstatic.com/D_NQ_NP_2x_fone-I.jpg",
            "200 reais com 0 centavos",
            "100 reais",
        ),
        # sem preço anterior → sem desconto real → cai
        _card(
            "Fone sem promo",
            "https://produto.mercadolivre.com.br/MLB-1002-fone-sem-promo-_JM",
            "https://http2.mlstatic.com/D_NQ_NP_2x_1A-I.jpg",
            None,
            "90 reais",
        ),
        # desconto abaixo do mínimo (5%) → cai
        _card(
            "Fone 5%",
            "https://produto.mercadolivre.com.br/MLB-1003-fone-5-_JM",
            "https://http2.mlstatic.com/D_NQ_NP_2x_1A-I.jpg",
            "200 reais",
            "190 reais",
        ),
        # acima do preço máximo → cai
        _card(
            "Smart TV caríssima",
            "https://produto.mercadolivre.com.br/MLB-1004-smart-tv-cara-_JM",
            "https://http2.mlstatic.com/D_NQ_NP_2x_1A-I.jpg",
            "2000 reais",
            "900 reais",
        ),
        # oferta ótima mas fora do tema (sem keyword) → cai
        _card(
            "Gloss Bella",
            "https://produto.mercadolivre.com.br/MLB-1005-gloss-bella-_JM",
            "https://http2.mlstatic.com/D_NQ_NP_2x_1A-I.jpg",
            "40 reais",
            "15 reais",
        ),
    ]
    return '<div id="results"><div class="items-list">' + "".join(cards) + "</div></div>"


def _mock_client_for(html):
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.rstrip("/").endswith("ofertas"):
            return httpx.Response(200, text=html)
        return httpx.Response(404, json={"message": "not found"})

    return httpx.AsyncClient(transport=httpx.MockTransport(handler))


@pytest.mark.asyncio
async def test_parse_offers_extracts_and_filters_html():
    finder = MercadoLivreFinder(_finder_settings(), client=_mock_client_for(_offers_page_html()))
    offers = MercadoLivreFinder._parse_offers(_offers_page_html())
    assert len(offers) == 5
    offer = next(o for o in offers if o["item_id"] == "1001")
    assert offer["discount_percentage"] == pytest.approx(50.0)
    assert offer["original_price"] == pytest.approx(200.0)
    assert offer["price"] == pytest.approx(100.0)
    assert offer["product_name"] == "Fone bluetooth TWS Pro"

    picked = [o for o in offers if finder._passes(o)]
    assert [o["item_id"] for o in picked] == ["1001"]


@pytest.mark.asyncio
async def test_scan_fetches_page_and_enqueues():
    finder = MercadoLivreFinder(
        _finder_settings(MEL_FINDER_KEYWORDS="smart watch"),
        client=_mock_client_for(_offers_page_html()),
    )

    class RecordingQueue:
        def __init__(self):
            self.items = []

        async def enqueue(self, raw):
            self.items.append(raw)

    queue = RecordingQueue()
    # Nenhuma oferta contém "smart watch" no título além da que foi bloqueada por preço
    found = await finder.scan(queue)
    assert found == 0
    assert queue.items == []


@pytest.mark.asyncio
async def test_scan_enqueues_matching_offer():
    html = _offers_page_html() + _card(
        "Smart watch Fit Pro",
        "https://produto.mercadolivre.com.br/MLB-2001-smart-watch-fit-pro-_JM",
        "https://http2.mlstatic.com/D_NQ_NP_2x_smart-I.jpg",
        "180 reais",
        "90 reais",
    )
    finder = MercadoLivreFinder(
        _finder_settings(MEL_FINDER_KEYWORDS="smart watch,smart tv"),
        client=_mock_client_for(html),
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
    assert raw.source_message_id == "mel-scrape-2001"
    assert "50.0% OFF" in raw.text or "50% OFF" in raw.text
    assert "MLB-2001" in raw.text
    assert raw.media_url.endswith("smart-I.jpg")


@pytest.mark.asyncio
async def test_credentials_not_required_for_scraping():
    finder = MercadoLivreFinder(_finder_settings(MEL_API_CLIENT_ID=""))
    assert finder.credentials_ok() is True
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