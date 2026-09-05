import pytest
from app.core.models import Promotion
from app.core.filters import PromotionFilter
from app.config.settings import Settings


@pytest.fixture
def promo_filter(test_settings):
    return PromotionFilter(settings=test_settings)


def test_filter_pass_valid_promotion(promo_filter):
    promo = Promotion(
        source="telegram",
        source_message_id="1",
        source_chat_id="@c",
        original_text="Smart TV Samsung 50 4K",
        product_name="Smart TV Samsung 50 4K",
        original_price=2500.0,
        sale_price=1800.0,
        discount_percentage=28.0,
        store="amazon",
        original_url="https://amazon.com.br/dp/B08N5WRWNW",
        category="eletronicos",
    )
    res = promo_filter.evaluate(promo)
    assert res.passed is True
    assert res.reason is None


def test_filter_discount_below_minimum(promo_filter):
    # Minimum discount in test_settings is 10.0%
    promo = Promotion(
        source="telegram",
        source_message_id="2",
        source_chat_id="@c",
        original_text="Teclado sem fio",
        product_name="Teclado sem fio",
        original_price=100.0,
        sale_price=95.0,
        discount_percentage=5.0,
        store="amazon",
        original_url="https://amazon.com.br/dp/B000000002",
    )
    res = promo_filter.evaluate(promo)
    assert res.passed is False
    assert "abaixo do mínimo" in res.reason


def test_filter_price_above_maximum(promo_filter):
    # Maximum price in test_settings is 3000.0
    promo = Promotion(
        source="telegram",
        source_message_id="3",
        source_chat_id="@c",
        original_text="MacBook Pro M3",
        product_name="MacBook Pro M3",
        sale_price=12000.0,
        discount_percentage=15.0,
        store="amazon",
        original_url="https://amazon.com.br/dp/B000000003",
    )
    res = promo_filter.evaluate(promo)
    assert res.passed is False
    assert "acima do teto" in res.reason


def test_filter_price_below_minimum(promo_filter):
    # Minimum price in test_settings is 10.0
    promo = Promotion(
        source="telegram",
        source_message_id="4",
        source_chat_id="@c",
        original_text="Bala de goma",
        product_name="Bala de goma",
        sale_price=2.50,
        discount_percentage=20.0,
        store="amazon",
        original_url="https://amazon.com.br/dp/B000000004",
    )
    res = promo_filter.evaluate(promo)
    assert res.passed is False
    assert "abaixo do piso" in res.reason


def test_filter_blocked_amazon():
    settings = Settings(
        APP_ENV="test",
        BLOCKED_STORES="amazon",
    )
    promo_filter = PromotionFilter(settings=settings)
    promo = Promotion(
        source="telegram",
        source_message_id="5b",
        source_chat_id="@c",
        original_text="Kindle 11ª geração",
        product_name="Kindle 11ª geração",
        sale_price=299.0,
        discount_percentage=15.0,
        store="amazon",
        original_url="https://amazon.com.br/dp/B08N5WRWNW",
    )
    res = promo_filter.evaluate(promo)
    assert res.passed is False
    assert "Loja bloqueada" in res.reason


def test_filter_blocked_store(promo_filter):
    # Blocked store in test_settings is "aliexpress"
    promo = Promotion(
        source="telegram",
        source_message_id="5",
        source_chat_id="@c",
        original_text="Cabo USB",
        product_name="Cabo USB Tipo C",
        sale_price=15.0,
        discount_percentage=20.0,
        store="aliexpress",
        original_url="https://aliexpress.com/item/123",
    )
    res = promo_filter.evaluate(promo)
    assert res.passed is False
    assert "Loja bloqueada" in res.reason


def test_filter_blocked_category(promo_filter):
    # Blocked category in test_settings is "moda"
    promo = Promotion(
        source="telegram",
        source_message_id="6",
        source_chat_id="@c",
        original_text="Camiseta básica preta",
        product_name="Camiseta básica preta",
        sale_price=39.90,
        discount_percentage=30.0,
        store="shopee",
        category="moda",
        original_url="https://shopee.com.br/item/1",
    )
    res = promo_filter.evaluate(promo)
    assert res.passed is False
    assert "Categoria bloqueada" in res.reason


def test_filter_blocked_keyword(promo_filter):
    # Blocked keywords: "esgotado,sorteio,rifa,fake"
    promo = Promotion(
        source="telegram",
        source_message_id="7",
        source_chat_id="@c",
        original_text="Produto já esgotado, mas fiquem de olho!",
        product_name="Fone de Ouvido",
        sale_price=50.0,
        discount_percentage=25.0,
        store="amazon",
        original_url="https://amazon.com.br/dp/B000000007",
    )
    res = promo_filter.evaluate(promo)
    assert res.passed is False
    assert "Palavra-chave bloqueada" in res.reason
