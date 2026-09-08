import base64
import pytest
import httpx

from app.adapters.whatsapp import WhatsAppPublisher
from app.config.settings import Settings
from app.core.models import Promotion


def _make_promotion(**overrides):
    attrs = {
        "source": "telegram",
        "source_message_id": "1",
        "source_chat_id": "@promo_deals",
        "original_text": "Texto",
        "product_name": "SMART TV SAMSUNG 50” 4K",
        "original_price": 2499.0,
        "sale_price": 1899.0,
        "discount_percentage": 24.0,
        "store": "amazon",
        "original_url": "https://amazon.com.br/dp/B08N5WRWNW",
        "affiliate_url": "https://www.amazon.com.br/dp/B08N5WRWNW?tag=tag-20",
    }
    attrs.update(overrides)
    return Promotion(**attrs)


def _settings(with_creds=True):
    kwargs = {"APP_ENV": "test", "DEBUG": True}
    if with_creds:
        kwargs.update(
            EVOLUTION_URL="http://evolution:8080",
            EVOLUTION_INSTANCE="promobot",
            EVOLUTION_API_KEY="test-api-key",
            WHATSAPP_TARGET_CHAT="120363410512355040@g.us",
        )
    return Settings(**kwargs)


def _http_client(handler):
    transport = httpx.MockTransport(handler)
    return httpx.AsyncClient(transport=transport)


def _make_client_and_publisher(handler, with_creds=True):
    client = _http_client(handler)
    publisher = WhatsAppPublisher(settings=_settings(with_creds), client=client)
    return client, publisher


def _success_handler(request: httpx.Request) -> httpx.Response:
    if "/sendText" in request.url.path:
        return httpx.Response(200, json={"key": {"id": "WA-101", "remoteJid": "120363410512355040@g.us", "fromMe": True}})
    if "/sendMedia" in request.url.path:
        return httpx.Response(200, json={"key": {"id": "WA-202", "remoteJid": "120363410512355040@g.us", "fromMe": True}})
    return httpx.Response(400, json={"message": "unknown"})


@pytest.mark.asyncio
async def test_publish_plain_text_success():
    requests = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return _success_handler(request)

    client, publisher = _make_client_and_publisher(handler)
    try:
        result = await publisher.publish(_make_promotion(image_url=None), "Mensagem formatada")
    finally:
        await client.aclose()

    assert result.success is True
    assert result.platform == "whatsapp"
    assert result.target_chat_id == "120363410512355040@g.us"
    assert result.target_message_id == "WA-101"
    assert result.error_message is None

    assert len(requests) == 1
    assert requests[0].url.path == "/message/sendText/promobot"
    assert requests[0].headers.get("apikey") == "test-api-key"
    body = requests[0].read()
    assert "120363410512355040@g.us" in body.decode()
    assert "Mensagem formatada" in body.decode()


@pytest.mark.asyncio
async def test_publish_local_image_uses_send_media(tmp_path):
    image = tmp_path / "promo.jpg"
    image.write_bytes(b"\xff\xd8fake-jpeg")
    requests = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return _success_handler(request)

    client, publisher = _make_client_and_publisher(handler)
    try:
        result = await publisher.publish(_make_promotion(image_url=str(image)), "Mensagem com foto")
    finally:
        await client.aclose()

    assert result.success is True
    assert result.target_message_id == "WA-202"
    assert len(requests) == 1
    assert requests[0].url.path == "/message/sendMedia/promobot"
    body = requests[0].read().decode()
    # Evolution API requires raw base64 (no data: prefix)
    assert "data:image" not in body
    assert base64.b64encode(b"\xff\xd8fake-jpeg").decode() in body
    assert "mediatype" in body


@pytest.mark.asyncio
async def test_publish_image_by_url_uses_send_media():
    requests = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return _success_handler(request)

    client, publisher = _make_client_and_publisher(handler)
    try:
        result = await publisher.publish(_make_promotion(image_url="https://cdn.example.com/promo.jpg"), "Mensagem")
    finally:
        await client.aclose()

    assert result.success is True
    assert len(requests) == 1
    assert requests[0].url.path == "/message/sendMedia/promobot"
    body = requests[0].read().decode()
    assert "https://cdn.example.com/promo.jpg" in body


@pytest.mark.asyncio
async def test_publish_with_image_disabled_uses_send_text(tmp_path):
    image = tmp_path / "promo.jpg"
    image.write_bytes(b"\xff\xd8fake-jpeg")
    requests = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return _success_handler(request)

    client = _http_client(handler)
    publisher = WhatsAppPublisher(
        settings=Settings(
            APP_ENV="test",
            DEBUG=True,
            EVOLUTION_URL="http://evolution:8080",
            EVOLUTION_INSTANCE="promobot",
            EVOLUTION_API_KEY="test-api-key",
            WHATSAPP_TARGET_CHAT="120363410512355040@g.us",
            WHATSAPP_WITH_IMAGE=False,
        ),
        client=client,
    )
    try:
        result = await publisher.publish(_make_promotion(image_url=str(image)), "Mensagem")
    finally:
        await client.aclose()

    assert result.success is True
    assert requests[0].url.path == "/message/sendText/promobot"


@pytest.mark.asyncio
async def test_publish_api_error_returns_failure():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(400, json={"message": "session not connected"})

    client, publisher = _make_client_and_publisher(handler)
    try:
        result = await publisher.publish(_make_promotion(), "Mensagem")
    finally:
        await client.aclose()

    assert result.success is False
    assert result.platform == "whatsapp"
    assert "Evolution API error" in result.error_message


@pytest.mark.asyncio
async def test_publish_raises_network_error_returns_failure():
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("connection refused")

    client, publisher = _make_client_and_publisher(handler)
    try:
        result = await publisher.publish(_make_promotion(), "Mensagem")
    finally:
        await client.aclose()

    assert result.success is False
    assert result.error_message


@pytest.mark.asyncio
async def test_publish_missing_credentials_returns_failure_without_http():
    client, publisher = _make_client_and_publisher(_success_handler, with_creds=False)
    try:
        result = await publisher.publish(_make_promotion(), "Mensagem")
    finally:
        await client.aclose()

    assert result.success is False
    assert "não configurados" in result.error_message


@pytest.mark.asyncio
async def test_enabled_respects_settings():
    publisher = WhatsAppPublisher(settings=_settings())
    assert publisher.enabled is True

    disabled = WhatsAppPublisher(
        settings=Settings(APP_ENV="test", DEBUG=True, EVOLUTION_API_KEY="k", WHATSAPP_ENABLED=False)
    )
    assert disabled.enabled is False

    no_target = WhatsAppPublisher(settings=_settings(with_creds=False))
    assert no_target.enabled is False


@pytest.mark.asyncio
async def test_publish_retries_on_429_then_succeeds():
    calls = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request)
        if len(calls) == 1:
            return httpx.Response(429, json={"message": "Too Many Requests"}, headers={"Retry-After": "0"})
        return _success_handler(request)

    client, publisher = _make_client_and_publisher(handler)
    try:
        result = await publisher.publish(_make_promotion(image_url=None), "Mensagem teste")
    finally:
        await client.aclose()

    assert result.success is True
    assert len(calls) == 2, f"Expected 2 calls, got {len(calls)}"