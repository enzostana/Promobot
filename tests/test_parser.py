import pytest
from app.core.models import RawMessage
from app.core.parser import PromotionParser


@pytest.fixture
def parser():
    return PromotionParser()


def test_parse_message_with_prices(parser):
    text = (
        "🔥 SMART TV SAMSUNG 50” 4K\n\n"
        "💰 De: R$ 2.499,00\n"
        "🔥 Por: R$ 1.899,00\n\n"
        "📉 24% OFF\n\n"
        "🛒 COMPRAR AGORA\n"
        "https://www.amazon.com.br/dp/B08N5WRWNW"
    )
    raw = RawMessage(
        id="1",
        source="telegram",
        source_message_id="101",
        source_chat_id="@promo_deals",
        text=text
    )
    parsed = parser.parse(raw)

    assert parsed.product_name == "SMART TV SAMSUNG 50” 4K"
    assert parsed.original_price == 2499.0
    assert parsed.sale_price == 1899.0
    assert parsed.discount_percentage == 24.0
    assert parsed.store == "amazon"
    assert parsed.original_url == "https://www.amazon.com.br/dp/B08N5WRWNW"
    assert parsed.category == "eletronicos"


def test_parse_message_without_price(parser):
    text = (
        "Confira este produto imperdível!\n"
        "Acesse: https://www.amazon.com.br/dp/B08N5WRWNW"
    )
    raw = RawMessage(
        id="2",
        source="telegram",
        source_message_id="102",
        source_chat_id="@promo_deals",
        text=text
    )
    parsed = parser.parse(raw)

    assert "Confira" in parsed.product_name or "produto" in parsed.product_name.lower()
    assert parsed.sale_price is None
    assert parsed.original_price is None
    assert parsed.discount_percentage is None
    assert parsed.store == "amazon"
    assert parsed.original_url == "https://www.amazon.com.br/dp/B08N5WRWNW"


def test_parse_message_with_multiple_links(parser):
    text = (
        "Visite nosso blog em https://meublog.com e compre a TV em "
        "https://www.mercadolivre.com.br/p/MLB12345678 com desconto especial! "
        "Confira também https://outrosite.com.br"
    )
    raw = RawMessage(
        id="3",
        source="telegram",
        source_message_id="103",
        source_chat_id="@promo_deals",
        text=text
    )
    parsed = parser.parse(raw)

    assert len(parsed.all_urls) == 3
    # Must prioritize the recognized ecommerce store
    assert parsed.store == "mercadolivre"
    assert "mercadolivre.com.br" in parsed.original_url


def test_parse_message_messy_text(parser):
    text = (
        "💥💥🚨🚨 [MEGA OFERTA] 🚨🚨💥💥\n\n\n"
        "👉👉  Fone de Ouvido Bluetooth TWS Pro  👈👈\n"
        "#promocao #achadinhos #oferta\n\n"
        "Preço original: R$ 299,90\n"
        "Apenas: R$ 99,90 no Pix!! 😱\n\n"
        "👉 Pegue o seu aqui: https://shopee.com.br/product/123456/78901234\n"
        "Corre que acaba rápido!!!"
    )
    raw = RawMessage(
        id="4",
        source="telegram",
        source_message_id="104",
        source_chat_id="@promo_deals",
        text=text
    )
    parsed = parser.parse(raw)

    assert "Fone de Ouvido Bluetooth TWS Pro" in parsed.product_name
    assert parsed.original_price == 299.90
    assert parsed.sale_price == 99.90
    assert parsed.store == "shopee"
    assert parsed.category == "eletronicos"
    assert parsed.discount_percentage is not None
    assert parsed.discount_percentage > 60.0


def test_product_name_strips_embedded_url(parser):
    text = (
        "🔥 Fone Bluetooth JBL por apenas R$ 199,90! "
        "https://www.mercadolivre.com.br/p/MLB1002003001"
    )
    raw = RawMessage(
        id="7",
        source="telegram",
        source_message_id="107",
        source_chat_id="@promo_deals",
        text=text
    )
    parsed = parser.parse(raw)

    assert "http" not in parsed.product_name
    assert "Fone Bluetooth JBL" in parsed.product_name
    assert parsed.original_url == "https://www.mercadolivre.com.br/p/MLB1002003001"


def test_parse_number_currency_formats(parser):
    # Brazilian format with dot thousand and comma decimal
    assert parser.parse_number("1.899,90") == 1899.90
    assert parser.parse_number("2.499,00") == 2499.0
    # Comma decimal only
    assert parser.parse_number("99,90") == 99.90
    assert parser.parse_number("12,50") == 12.50
    # Dot thousand format
    assert parser.parse_number("1.499") == 1499.0
    # Integer
    assert parser.parse_number("250") == 250.0
    # Empty or invalid
    assert parser.parse_number("") is None
    assert parser.parse_number("abc") is None


def test_discount_calculation(parser):
    # Computed discount
    disc = parser.extract_discount("Promoção sem % no texto", orig_price=200.0, sale_price=150.0)
    assert disc == 25.0

    # Explicit discount in text overrides calculation
    disc_explicit = parser.extract_discount("Super desconto de 40% OFF no carrinho!", orig_price=200.0, sale_price=150.0)
    assert disc_explicit == 40.0
