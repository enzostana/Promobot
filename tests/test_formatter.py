import pytest
from app.core.models import Promotion
from app.core.formatter import PromotionFormatter


@pytest.fixture
def formatter():
    return PromotionFormatter()


def test_format_complete_promotion(formatter):
    promo = Promotion(
        source="telegram",
        source_message_id="1",
        source_chat_id="@test",
        original_text="Texto",
        product_name="SMART TV SAMSUNG 50” 4K",
        original_price=2499.0,
        sale_price=1899.0,
        discount_percentage=24.0,
        store="amazon",
        original_url="https://amazon.com.br/dp/B08N5WRWNW",
        affiliate_url="https://www.amazon.com.br/dp/B08N5WRWNW?tag=minhatag-20",
    )

    output = formatter.format(promo)

    expected = (
        "🔥 SMART TV SAMSUNG 50” 4K\n\n"
        "💰 De: R$ 2.499\n"
        "🔥 Por: R$ 1.899\n\n"
        "📉 24% OFF\n\n"
        "🛒 COMPRAR AGORA\n"
        "https://www.amazon.com.br/dp/B08N5WRWNW?tag=minhatag-20\n\n"
        "⚡ Oferta sujeita a alteração de preço/estoque."
    )
    assert output == expected


def test_format_without_original_price(formatter):
    promo = Promotion(
        source="telegram",
        source_message_id="2",
        source_chat_id="@test",
        original_text="Texto",
        product_name="Air Fryer Mondial 4L",
        original_price=None,
        sale_price=299.90,
        discount_percentage=None,
        store="shopee",
        original_url="https://shopee.com.br/item",
        affiliate_url="https://shopee.com.br/item?tag=shopee",
    )

    output = formatter.format(promo)

    assert "💰 De:" not in output
    assert "🔥 Por: R$ 299,90" in output
    assert "📉" not in output
    assert "🛒 COMPRAR AGORA" in output
    assert "https://shopee.com.br/item?tag=shopee" in output
    assert "⚡ Oferta sujeita a alteração de preço/estoque." in output


def test_format_currency_helper(formatter):
    assert formatter.format_currency(2499.0) == "2.499"
    assert formatter.format_currency(1899.0) == "1.899"
    assert formatter.format_currency(1899.90) == "1.899,90"
    assert formatter.format_currency(49.99) == "49,99"
    assert formatter.format_currency(0.0) == "0"
    assert formatter.format_currency(None) == ""
