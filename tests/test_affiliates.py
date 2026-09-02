import pytest
from app.affiliates.amazon import AmazonProvider
from app.affiliates.mercadolivre import MercadoLivreProvider
from app.affiliates.shopee import ShopeeProvider
from app.affiliates.registry import AffiliateRegistry
from app.config.settings import Settings


def test_amazon_provider_asin_and_tag():
    provider = AmazonProvider(tag="minhatag-20")
    url = "https://www.amazon.com.br/dp/B08N5WRWNW?tag=outratag-20&ref_=as_li_ss_tl&linkCode=as2"

    assert provider.can_handle(url) is True
    assert provider.extract_product_id(url) == "B08N5WRWNW"

    affiliate_url = provider.convert(url)
    assert "https://www.amazon.com.br/dp/B08N5WRWNW?tag=minhatag-20" in affiliate_url
    assert "outratag" not in affiliate_url
    assert "ref_" not in affiliate_url


def test_amazon_provider_short_url():
    provider = AmazonProvider(tag="minhatag-20")
    short_url = "https://amzn.to/3xyz123"

    assert provider.can_handle(short_url) is True
    converted = provider.convert(short_url)
    assert "tag=minhatag-20" in converted


def test_mercadolivre_provider():
    provider = MercadoLivreProvider(tag="meu_afiliado_meli")
    url = "https://produto.mercadolivre.com.br/MLB-987654321-smartphone-x/_JM?matt_tool=outro&utm_source=telegram"

    assert provider.can_handle(url) is True
    assert provider.extract_product_id(url) == "MLB987654321"

    converted = provider.convert(url)
    assert "matt_tool=meu_afiliado_meli" in converted
    assert "utm_source" not in converted


def test_shopee_provider():
    provider = ShopeeProvider(tag="shopee_promo_tag", app_id="app_999")
    url = "https://shopee.com.br/product/12345/67890?aff_trace_key=oldtag&utm_source=other"

    assert provider.can_handle(url) is True
    assert provider.extract_product_id(url) == "12345:67890"

    converted = provider.convert(url)
    assert "aff_trace_key=shopee_promo_tag" in converted
    assert "app_id=app_999" in converted
    assert "oldtag" not in converted


def test_affiliate_registry_routing(test_settings):
    registry = AffiliateRegistry(test_settings)

    # 1. Amazon
    amz_url, amz_store, amz_pid = registry.convert("https://www.amazon.com.br/dp/B012345678")
    assert amz_store == "amazon"
    assert amz_pid == "B012345678"
    assert "tag=testtag-20" in amz_url

    # 2. Mercado Livre
    meli_url, meli_store, meli_pid = registry.convert("https://produto.mercadolivre.com.br/MLB-555444333-tv")
    assert meli_store == "mercadolivre"
    assert meli_pid == "MLB555444333"
    assert "matt_tool=meli_test_tag" in meli_url

    # 3. Shopee
    shp_url, shp_store, shp_pid = registry.convert("https://shopee.com.br/product/111/222")
    assert shp_store == "shopee"
    assert shp_pid == "111:222"
    assert "aff_trace_key=shopee_test_tag" in shp_url


def test_affiliate_unknown_link(test_settings):
    registry = AffiliateRegistry(test_settings)
    raw_url = "https://www.lojaaleatoria.com.br/produto-x?utm_source=facebook&utm_campaign=blackfriday&id=123"

    converted_url, store_name, pid = registry.convert(raw_url)
    assert store_name == "lojaaleatoria"
    assert pid is None
    # Strips marketing tracking
    assert "utm_source" not in converted_url
    assert "id=123" in converted_url


def test_affiliate_invalid_url(test_settings):
    registry = AffiliateRegistry(test_settings)
    converted, store, pid = registry.convert("")
    assert converted == ""
    assert store == "unknown"
    assert pid is None
