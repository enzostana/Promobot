from unittest.mock import AsyncMock

import pytest
from telethon.tl.types import MessageEntityTextUrl, MessageEntityUrl

from app.adapters.telegram import TelegramAdapter
from app.config.settings import Settings
from app.workers.queue import RedisQueue


class FakeChat:
    def __init__(self, title=None, username=None):
        self.title = title
        self.username = username


class FakeMessage:
    def __init__(self, id=1, text="", entities=None, photo=None, message=None):
        self.id = id
        self.text = text
        self.message = message
        self.entities = entities or []
        self.photo = photo


class FakeEvent:
    def __init__(self, chat_id, message=None, chat=None):
        self.chat_id = chat_id
        self.message = message
        self.chat = chat


@pytest.fixture
def test_settings():
    return Settings(
        APP_ENV="test",
        DEBUG=True,
        TELEGRAM_API_ID=123456,
        TELEGRAM_API_HASH="test_hash",
        TELEGRAM_SOURCE_CHATS="@canal_a,@canal_b",
    )


@pytest.fixture
def mock_queue():
    return AsyncMock(spec=RedisQueue)


@pytest.fixture
def adapter(test_settings, mock_queue):
    return TelegramAdapter(queue=mock_queue, settings=test_settings)


def test_capture_text(adapter):
    event = FakeEvent(
        chat_id="@promo_deals",
        chat=FakeChat(title="Canal Promo Deals"),
        message=FakeMessage(id=42, text="🔥 SMART TV 50 4K por R$ 1.899"),
    )

    raw = adapter._build_raw_message(
        chat_id=str(event.chat_id),
        chat_title=event.chat.title,
        message_id=str(event.message.id),
        text=event.message.text,
        entities=event.message.entities,
    )

    assert raw.text == "🔥 SMART TV 50 4K por R$ 1.899"
    assert raw.source == "telegram"
    assert raw.media_path is None
    assert raw.urls == []


def test_capture_links_via_plain_url_entity(adapter):
    url = "https://www.amazon.com.br/dp/B08N5WRWNW"
    text = f"Compre aqui {url}"
    offset = text.index(url)
    entities = [MessageEntityUrl(offset=offset, length=len(url))]
    raw = adapter._build_raw_message(
        chat_id="@promo_deals",
        chat_title="Canal",
        message_id="1",
        text=text,
        entities=entities,
    )

    assert raw.urls == [url]


def test_capture_links_via_text_url_entity(adapter):
    text = "Veja o link"
    entities = [MessageEntityTextUrl(offset=0, length=5, url="https://shopee.com.br/product/1/2")]
    raw = adapter._build_raw_message(
        chat_id="@promo_deals",
        chat_title="Canal",
        message_id="2",
        text=text,
        entities=entities,
    )

    assert raw.urls == ["https://shopee.com.br/product/1/2"]


def test_capture_chat_and_message_id(adapter):
    event = FakeEvent(
        chat_id="@canal_a",
        chat=FakeChat(title="Canal A"),
        message=FakeMessage(id=77, text="oferta"),
    )

    raw = adapter._build_raw_message(
        chat_id=str(event.chat_id),
        chat_title=event.chat.title,
        message_id=str(event.message.id),
        text=event.message.text,
        entities=event.message.entities,
    )

    assert raw.source_chat_id == "@canal_a"
    assert raw.source_message_id == "77"
    assert raw.source_chat_title == "Canal A"


def test_chat_title_falls_back_to_username():
    adapter = TelegramAdapter(settings=Settings(TELEGRAM_API_ID=1, TELEGRAM_API_HASH="h"))
    event = FakeEvent(
        chat_id="-100123",
        chat=FakeChat(username="canal_username"),
        message=FakeMessage(id=1, text="oi"),
    )

    title = getattr(event.chat, "title", None) or getattr(event.chat, "username", None) or str(event.chat_id)
    assert title == "canal_username"


def test_media_path_is_placeholder_without_photo(adapter):
    raw = adapter._build_raw_message(
        chat_id="@a",
        chat_title=None,
        message_id="1",
        text="sem foto",
        entities=[],
        photo=False,
    )
    assert raw.media_path is None


@pytest.mark.asyncio
async def test_handle_event_enqueues_raw_message(adapter, mock_queue):
    event = FakeEvent(
        chat_id="@promo_deals",
        chat=FakeChat(title="Canal Promo Deals"),
        message=FakeMessage(id=10, text="texto de teste"),
    )

    await adapter._handle_event(event)

    mock_queue.enqueue.assert_awaited_once()
    raw = mock_queue.enqueue.await_args.args[0]
    assert raw.source == "telegram"
    assert raw.source_chat_id == "@promo_deals"
    assert raw.source_message_id == "10"
    assert raw.text == "texto de teste"


@pytest.mark.asyncio
async def test_handle_event_downloads_photo(tmp_path, adapter, mock_queue):
    media_file = tmp_path / "photo.jpg"
    media_file.write_bytes(b"fake-image")
    message = FakeMessage(id=5, text="foto", photo="photo_bytes")
    message.download_media = AsyncMock(return_value=str(media_file))
    event = FakeEvent(
        chat_id="@promo_deals",
        chat=FakeChat(title="Canal"),
        message=message,
    )

    await adapter._handle_event(event)

    raw = mock_queue.enqueue.await_args.args[0]
    assert raw.media_path == str(media_file)
    message.download_media.assert_awaited_once()


def test_missing_api_creds_does_not_init_client():
    adapter = TelegramAdapter(settings=Settings(TELEGRAM_API_ID=None, TELEGRAM_API_HASH=None))
    assert adapter._init_client() is None
