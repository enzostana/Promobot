import httpx
import pytest
from app.affiliates.amazon import AmazonProvider
from app.affiliates.mercadolivre import MercadoLivreProvider
from app.affiliates.meli_mint import (
    MeliLinkMinter,
    MeliMintError,
    MeliRateLimited,
    MeliSessionExpired,
    MeliUrlNotAllowed,
)
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


def test_amazon_provider_link_amazon_bare_asin():
    provider = AmazonProvider(tag="minhatag-20")
    url = "https://link.amazon/B0hJNGE2k"

    assert provider.can_handle(url) is True

    converted = provider.convert(url)
    assert "https://link.amazon/B0hJNGE2k" in converted
    assert "tag=minhatag-20" in converted


def test_amazon_provider_no_tag_keeps_canonical_link():
    provider = AmazonProvider(tag=None)

    with_tag = "https://link.amazon/B0hJNGE2k?tag=oldtag"
    stripped = provider.convert(with_tag)
    assert "tag=" not in stripped
    assert "https://link.amazon/B0hJNGE2k" in stripped

    # Without a tag, short links just lose tracking params (no canonicalization)
    bare = provider.convert("https://link.amazon/B0hJNGE2k?tag=something")
    assert "tag=" not in bare
    assert "https://link.amazon/B0hJNGE2k" in bare

    # Valid 10-char ASIN is canonicalized even without a tag
    canonical = provider.convert("https://www.amazon.com.br/dp/B08N5WRWNW?ref=old")
    assert "https://www.amazon.com.br/dp/B08N5WRWNW" in canonical
    assert "ref=" not in canonical


def test_mercadolivre_provider():
    provider = MercadoLivreProvider(tag="meu_afiliado_meli")
    url = "https://produto.mercadolivre.com.br/MLB-987654321-smartphone-x/_JM?matt_tool=outro&utm_source=telegram"

    assert provider.can_handle(url) is True
    assert provider.extract_product_id(url) == "MLB987654321"

    converted = provider.convert(url)
    assert "matt_tool=meu_afiliado_meli" in converted
    assert "matt_word" not in converted
    assert "utm_source" not in converted


def test_mercadolivre_provider_injects_user_matt_word():
    provider = MercadoLivreProvider(tag="12520971", word="rufinobr")
    url = "https://www.mercadolivre.com.br/smart-tv-semp-43/p/MLB54075534?matt_word=canal&matt_tool=73920577&utm_source=telegram"

    converted = provider.convert(url)

    assert "matt_tool=12520971" in converted
    assert "matt_word=rufinobr" in converted
    assert "matt_tool=73920577" not in converted
    assert "matt_word=canal" not in converted
    assert "utm_source" not in converted


def test_mercadolivre_provider_convert_single_product_with_tag():
    provider = MercadoLivreProvider(tag="12520971", word="rufinobr", route="profile")

    converted = provider.convert("https://www.mercadolivre.com.br/some-product/p/MLB54075534")

    # Posts must link the single product — never the affiliate's /social/ list.
    assert converted.startswith("https://www.mercadolivre.com.br/some-product/p/MLB54075534")
    assert "social/rufinobr" not in converted
    assert "matt_tool=12520971" in converted
    assert "matt_word=rufinobr" in converted
    assert "forceInApp" not in converted


def test_mercadolivre_provider_single_product_shortlink_fallback():
    provider = MercadoLivreProvider(tag="12520971", word="rufinobr", route="profile")
    provider._resolver = lambda url: "https://www.mercadolivre.com.br/social/thautec?ref=SIGNED"
    provider._page_fetcher = lambda url: "<html><body>sem produto</body></html>"

    converted = provider.convert("https://meli.la/25aHuyj")

    assert "social/rufinobr" not in converted
    assert converted.startswith("https://www.mercadolivre.com.br/social/thautec?")
    assert "matt_tool=12520971" in converted
    assert "matt_word=rufinobr" in converted
    assert "ref=" not in converted


def test_mercadolivre_provider_without_word_single_product():
    provider = MercadoLivreProvider(tag="12520971", route="profile")
    provider._resolver = lambda url: "https://www.mercadolivre.com.br/social/thautec"
    provider._page_fetcher = lambda url: "<html><body>sem produto</body></html>"

    converted = provider.convert("https://meli.la/25aHuyj")

    # No matt_word: still a single product (or resolved) link, never the list.
    assert "social/rufinobr" not in converted
    assert "matt_tool=12520971" in converted


def test_mercadolivre_provider_shortlink_resolved_with_user_tag():
    provider = MercadoLivreProvider(tag="12520971")
    resolved_url = "https://www.mercadolivre.com.br/social/guru?ref=ABC123"
    html = """
    <meta property="og:title" content="Serra Tico Tico Profissional 500w 3000 Gpm Bst500 The Black Tools" />
    <a href="https://www.mercadolivre.com.br/serra-tico-tico-profissional-500w-3000-gpm-bst500-the-black-tools/p/MLB26715512?matt_event_ts=1788911218266&matt_tool=73920577">x</a>
    <a href="https://www.mercadolivre.com.br/serra-eletrica-tico-tico-einhell/p/MLB25804364?matt_tool=73920577">y</a>
    """
    provider._resolver = lambda url: resolved_url
    provider._page_fetcher = lambda url: html

    converted = provider.convert("https://meli.la/2PLK2PN")

    assert converted.startswith("https://www.mercadolivre.com.br/serra-tico-tico-profissional-500w-3000-gpm-bst500-the-black-tools/p/MLB26715512")
    assert "matt_tool=12520971" in converted
    assert "matt_tool=73920577" not in converted
    assert "matt_event_ts" not in converted
    assert "matt_word" not in converted


def test_mercadolivre_provider_shortlink_unresolved_fallback():
    provider = MercadoLivreProvider(tag="12520971")
    provider._resolver = lambda url: ""

    converted = provider.convert("https://meli.la/2PLK2PN")

    assert converted.startswith("https://meli.la/2PLK2PN")
    assert "matt_tool=12520971" in converted


def test_mercadolivre_provider_shortlink_page_without_product_keeps_resolved_url():
    provider = MercadoLivreProvider(tag="12520971")
    provider._resolver = lambda url: "https://www.mercadolivre.com.br/social/guru?ref=XYZ&matt_tool=73920577"
    provider._page_fetcher = lambda url: "<html><body>no products</body></html>"

    converted = provider.convert("https://meli.la/2PLK2PN")

    assert converted.startswith("https://www.mercadolivre.com.br/social/guru?")
    assert "matt_tool=12520971" in converted
    assert "matt_tool=73920577" not in converted
    assert "ref=" not in converted


def test_mercadolivre_provider_keeps_own_official_link():
    provider = MercadoLivreProvider(tag="12520971", word="rufinobr")
    provider._resolver = lambda url: "https://www.mercadolivre.com.br/social/rufinobr?ref=SIGNEDX"

    converted = provider.convert("https://meli.la/27AVDj7")

    # Official /sec link of the own affiliate is kept untouched (headline preserved).
    assert converted == "https://meli.la/27AVDj7"


def test_mercadolivre_provider_foreign_shortlink_is_rebound_not_kept():
    provider = MercadoLivreProvider(tag="12520971", word="rufinobr")
    provider._resolver = lambda url: "https://www.mercadolivre.com.br/social/thautec?ref=SIGNED"
    provider._page_fetcher = lambda url: "<html><body>sem produto</body></html>"

    converted = provider.convert("https://meli.la/1BftLww")

    assert converted != "https://meli.la/1BftLww"
    assert "social/rufinobr" not in converted
    assert "matt_tool=12520971" in converted


def test_mercadolivre_resolver_follows_redirect():
    provider = MercadoLivreProvider(tag="12520971")
    converted = provider.convert("https://meli.la/28DwKXE")

    assert converted.startswith("https://www.mercadolivre.com.br/")
    assert "matt_tool=12520971" in converted
    assert "matt_tool=30765415" not in converted
    assert "/p/MLB" in converted or "/social/" in converted


def test_shopee_provider():
    provider = ShopeeProvider(tag="shopee_promo_tag", app_id="app_999")
    url = "https://shopee.com.br/product/12345/67890?aff_trace_key=oldtag&utm_source=other"

    assert provider.can_handle(url) is True
    assert provider.extract_product_id(url) == "12345:67890"

    converted = provider.convert(url)
    assert "aff_trace_key=shopee_promo_tag" in converted
    assert "app_id=app_999" in converted
    assert "oldtag" not in converted


def test_shopee_shortlink_can_handle():
    provider = ShopeeProvider(tag="shopee_promo_tag")

    assert provider.can_handle("https://br.shp.ee/SkFaqsyb") is True
    assert provider.can_handle("https://shp.ee/abc123") is True
    assert provider._is_shortlink("https://br.shp.ee/SkFaqsyb") is True
    assert provider._is_shortlink("https://shp.ee/abc123") is True
    assert provider._is_shortlink("https://shopee.com.br/product/1/2") is False


def test_shopee_shortlink_resolved_and_rewritten():
    resolved = "https://shopee.com.br/product/1338519571/22797731885?d_id=10ca4&uls_trackid=abc&utm_content=1111"
    provider = ShopeeProvider(tag="shopee_promo_tag", app_id="app_999",
                              resolver=lambda u: resolved)

    converted = provider.convert("https://br.shp.ee/SkFaqsyb")

    assert converted.startswith("https://shopee.com.br/product/1338519571/22797731885")
    assert "aff_trace_key=shopee_promo_tag" in converted
    assert "app_id=app_999" in converted
    assert "d_id" not in converted
    assert "uls_trackid" not in converted
    assert "utm_content" not in converted


def test_shopee_shortlink_discard_on_resolution_failure():
    provider = ShopeeProvider(tag="shopee_promo_tag",
                              resolver=lambda u: "")

    assert provider.convert("https://br.shp.ee/SkFaqsyb") == ""


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


# ---------------------------------------------------------------------------
# Mercado Livre: mintagem oficial (mercadolivre.com/sec) via sessão ssid
# ---------------------------------------------------------------------------

def _mint_transport(create_links_handler):
    """Builds an httpx transport that bootstraps _csrf then proxies createLink."""
    def handler(request: httpx.Request) -> httpx.Response:
        path = request.url.path
        if path == "/afiliados/linkbuilder":
            return httpx.Response(
                200,
                headers=httpx.Headers([
                    ("set-cookie", "_csrf=csrf-token-abc; Path=/; HttpOnly"),
                    ("set-cookie", "_d2id=d2id-1; Path=/; HttpOnly"),
                ]),
            )
        if path == "/affiliate-program/api/v2/stripe/user/tags":
            return httpx.Response(200, json=[
                {"name": "rufinobr", "in_use": True},
            ])
        if path == "/affiliate-program/api/v2/affiliates/createLink":
            return create_links_handler(request)
        return httpx.Response(404, json={"message": "not found"})

    return httpx.MockTransport(handler)


def _ok_create_handler(request):
    origin = request.content.decode()
    return httpx.Response(200, json={
        "total_success": 1,
        "total_error": 0,
        "urls": [{
            "origin_url": "https://www.mercadolivre.com.br/produto/p/MLB54075534",
            "short_url": "https://mercadolivre.com/sec/1AbCdEf",
            "long_url": "https://www.mercadolivre.com.br/produto/p/MLB54075534",
        }],
    })


def test_meli_minter_mints_official_short_link():
    minter = MeliLinkMinter(ssid="ssid-secreto", word="rufinobr",
                            transport=_mint_transport(_ok_create_handler))

    result = minter.create_links(["https://www.mercadolivre.com.br/produto/p/MLB54075534?matt_tool=x"])

    assert result == {
        "https://www.mercadolivre.com.br/produto/p/MLB54075534":
            "https://mercadolivre.com/sec/1AbCdEf",
    }
    assert minter._temp_cookies.get("_csrf") == "csrf-token-abc"


def test_meli_provider_convert_uses_official_link():
    provider = MercadoLivreProvider(
        tag="12520971", word="rufinobr", route="profile",
        mint=True, session="ssid-secreto",
    )
    provider._minter._transport = _mint_transport(_ok_create_handler)

    converted = provider.convert("https://www.mercadolivre.com.br/produto/p/MLB54075534?matt_tool=outra")

    assert converted == "https://mercadolivre.com/sec/1AbCdEf"


def test_meli_provider_mint_disabled_returns_single_product():
    provider = MercadoLivreProvider(
        tag="12520971", word="rufinobr", route="profile",
        mint=False, session="ssid-secreto",
    )

    converted = provider.convert("https://www.mercadolivre.com.br/produto/p/MLB54075534")

    assert converted.startswith("https://www.mercadolivre.com.br/produto/p/MLB54075534")
    assert "social/rufinobr" not in converted
    assert "matt_tool=12520971" in converted


def test_meli_provider_falls_back_on_111():
    def handler(request):
        return httpx.Response(200, json={
            "total_success": 0,
            "total_error": 1,
            "urls": [{
                "origin_url": "https://www.mercadolivre.com.br/produto/p/MLB54075534",
                "error_code": 111,
                "message": "URL not allowed in affiliates program",
            }],
        })

    provider = MercadoLivreProvider(
        tag="12520971", word="rufinobr", route="profile",
        mint=True, session="ssid-secreto",
    )
    provider._minter._transport = _mint_transport(handler)

    converted = provider.convert("https://www.mercadolivre.com.br/produto/p/MLB54075534")

    # Mint rejeitou o produto: cai na PÁGINA DO PRODUTO, nunca na lista do perfil.
    assert converted.startswith("https://www.mercadolivre.com.br/produto/p/MLB54075534")
    assert "social/rufinobr" not in converted
    assert "matt_tool=12520971" in converted


def test_meli_provider_falls_back_on_403():
    def handler(request):
        return httpx.Response(403, json={"message": "forbidden"})

    provider = MercadoLivreProvider(
        tag="12520971", word="rufinobr", route="profile",
        mint=True, session="ssid-secreto",
    )
    provider._minter._transport = _mint_transport(handler)

    converted = provider.convert("https://www.mercadolivre.com.br/produto/p/MLB54075534")

    assert converted.startswith("https://www.mercadolivre.com.br/produto/p/MLB54075534")
    assert "social/rufinobr" not in converted


def test_meli_provider_falls_back_on_429():
    def handler(request):
        return httpx.Response(429, json={"message": "too many"})

    provider = MercadoLivreProvider(
        tag="12520971", word="rufinobr", route="profile",
        mint=True, session="ssid-secreto",
    )
    provider._minter._transport = _mint_transport(handler)

    converted = provider.convert("https://www.mercadolivre.com.br/produto/p/MLB54075534")

    assert converted.startswith("https://www.mercadolivre.com.br/produto/p/MLB54075534")
    assert "sec/" not in converted
    assert "social/rufinobr" not in converted


def test_meli_provider_without_session_falls_back():
    provider = MercadoLivreProvider(
        tag="12520971", word="rufinobr", route="profile",
        mint=True, session=None,
    )

    converted = provider.convert("https://www.mercadolivre.com.br/produto/p/MLB54075534")

    assert converted.startswith("https://www.mercadolivre.com.br/produto/p/MLB54075534")
    assert "social/rufinobr" not in converted


def test_meli_provider_cannotize_rejects_non_product_urls():
    provider = MercadoLivreProvider(tag="12520971", mint=True, session="ssid")
    assert provider._minter.canonicalize("https://www.mercadolivre.com.br/ofertas") == ""
    assert provider._minter.canonicalize("") == ""


def test_meli_canonicalize_cleans_query_fragment_and_accepts_item_url():
    minter = MeliLinkMinter(ssid="ssid")

    catalog = minter.canonicalize(
        "https://www.mercadolivre.com.br/smartwatch-x/p/MLB46211942?pdp_filters=deal%3AMLB779362-1"
        "#polycard_client=offers&position=26&tracking_id=abc"
    )
    assert catalog == "https://www.mercadolivre.com.br/smartwatch-x/p/MLB46211942"

    item = minter.canonicalize(
        "https://produto.mercadolivre.com.br/MLB-5643170848-tnis-adidas-_JM?searchVariation=1#pos=1"
    )
    assert item == "https://produto.mercadolivre.com.br/MLB-5643170848-tnis-adidas-_JM"


def test_meli_rewrite_drops_offer_page_params_and_fragment():
    provider = MercadoLivreProvider(tag="12520971", word="rufinobr")

    converted = provider.convert(
        "https://www.mercadolivre.com.br/impressora-x/p/MLB62998911"
        "?pdp_filters=deal%3AMLB123-1&matt_tool=73920577"
        "#polycard_client=offers&deal_print_id=zzz&tracking_id=ttt&wid=MLB99&sid=offers"
    )

    assert converted.startswith("https://www.mercadolivre.com.br/impressora-x/p/MLB62998911?")
    assert "matt_tool=12520971" in converted
    assert "matt_tool=73920577" not in converted
    assert "pdp_filters" not in converted
    assert "wid=" not in converted
    assert "#" not in converted


def test_meli_minter_logs_non_111_error(caplog):
    def handler(request):
        return httpx.Response(200, json={
            "urls": [{
                "origin_url": "https://www.mercadolivre.com.br/produto/p/MLB55",
                "error_code": 5004,
                "message": "algum erro novo",
            }],
        })

    minter = MeliLinkMinter(ssid="ssid-secreto", transport=_mint_transport(handler))
    result = minter.create_links(["https://www.mercadolivre.com.br/produto/p/MLB55?x=1"])

    assert result == {}
    assert "error_code=5004" in caplog.text
    assert "origin_url" in caplog.text
