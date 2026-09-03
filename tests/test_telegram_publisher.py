import pytest
import httpx

from app.adapters.telegram import TelegramPublisher
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
            TELEGRAM_BOT_TOKEN="123:test-token",
            TELEGRAM_TARGET_CHAT="@target_channel",
        )
    return Settings(**kwargs)


def _http_client(handler):
    transport = httpx.MockTransport(handler)
    return httpx.AsyncClient(transport=transport)


def _make_client_and_publisher(handler, with_creds=True):
    client = _http_client(handler)
    publisher = TelegramPublisher(settings=_settings(with_creds), client=client)
    return client, publisher


def _success_handler(request: httpx.Request) -> httpx.Response:
    if "/sendMessage" in request.url.path:
        return httpx.Response(200, json={"ok": True, "result": {"message_id": 101}})
    if "/sendPhoto" in request.url.path:
        return httpx.Response(200, json={"ok": True, "result": {"message_id": 202}})
    return httpx.Response(400, json={"ok": False, "description": "unknown"})


@pytest.mark.asyncio
async def test_publish_plain_text_success():
    client, publisher = _make_client_and_publisher(_success_handler)
    try:
        result = await publisher.publish(_make_promotion(image_url=None), "Mensagem formatada")
    finally:
        await client.aclose()

    assert result.success is True
    assert result.platform == "telegram"
    assert result.target_chat_id == "@target_channel"
    assert result.target_message_id == "101"
    assert result.error_message is None


@pytest.mark.asyncio
async def test_publish_local_image_uses_send_photo(tmp_path):
    image = tmp_path / "promo.jpg"
    image.write_bytes(b"fake-image-content")
    requests = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(200, json={"ok": True, "result": {"message_id": 202}})

    client = _http_client(handler)
    publisher = TelegramPublisher(settings=_settings(), client=client)
    try:
        promo = _make_promotion(image_url=str(image))
        result = await publisher.publish(promo, "Mensagem com foto")
    finally:
        await client.aclose()

    assert result.success is True
    assert result.target_message_id == "202"
    assert len(requests) == 1
    assert requests[0].url.path == "/bot123:test-token/sendPhoto"


@pytest.mark.asyncio
async def test_publish_image_by_url_uses_send_photo():
    requests = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(200, json={"ok": True, "result": {"message_id": 303}})

    client = _http_client(handler)
    publisher = TelegramPublisher(settings=_settings(), client=client)
    try:
        promo = _make_promotion(image_url="https://cdn.example.com/promo.jpg")
        result = await publisher.publish(promo, "Mensagem com link de imagem")
    finally:
        await client.aclose()

    assert result.success is True
    assert result.target_message_id == "303"
    assert requests[0].url.path == "/bot123:test-token/sendPhoto"


@pytest.mark.asyncio
async def test_publish_api_error_returns_failure():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(400, json={"ok": False, "description": "chat not found"})

    client = _http_client(handler)
    publisher = TelegramPublisher(settings=_settings(), client=client)
    try:
        result = await publisher.publish(_make_promotion(), "Mensagem")
    finally:
        await client.aclose()

    assert result.success is False
    assert result.platform == "telegram"
    assert "Telegram API error" in result.error_message


@pytest.mark.asyncio
async def test_publish_raises_network_error_returns_failure():
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("connection refused")

    client = _http_client(handler)
    publisher = TelegramPublisher(settings=_settings(), client=client)
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
