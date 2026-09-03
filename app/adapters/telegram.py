import asyncio
import logging
import os
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import List, Optional
import httpx
from telethon import TelegramClient, events
from telethon.tl.types import MessageEntityTextUrl, MessageEntityUrl

from app.adapters.base import MessageSource
from app.core.publisher import Publisher
from app.core.models import Promotion, PublicationResult, RawMessage
from app.config.settings import Settings, get_settings
from app.workers.queue import RedisQueue
from app.workers.health_server import run_health_server

logger = logging.getLogger(__name__)


class TelegramAdapter(MessageSource):
    """
    Telegram input adapter using Telethon.

    Monitors the configured source channels/groups and captures:
    - text
    - links (from text and URL entities)
    - images (media)
    - chat_id
    - message_id

    Decoupled from the core: it only builds a RawMessage and enqueues it.
    """

    def __init__(self, queue: Optional[RedisQueue] = None, settings: Optional[Settings] = None):
        self.settings = settings or get_settings()
        self.queue = queue or RedisQueue(self.settings)
        self.client: Optional[TelegramClient] = None
        self.media_dir = Path("media_cache")
        self.media_dir.mkdir(parents=True, exist_ok=True)
        self._running = False

    def _init_client(self) -> Optional[TelegramClient]:
        api_id = self.settings.TELEGRAM_API_ID
        api_hash = self.settings.TELEGRAM_API_HASH
        if not api_id or not api_hash:
            logger.warning("[TELEGRAM] TELEGRAM_API_ID e TELEGRAM_API_HASH não configurados.")
            return None

        # Prefer session string if provided, otherwise file-based session
        from telethon.sessions import StringSession
        session = StringSession(self.settings.TELEGRAM_SESSION_STRING) if self.settings.TELEGRAM_SESSION_STRING else self.settings.TELEGRAM_SESSION_NAME
        return TelegramClient(session, api_id, api_hash)

    async def start(self) -> None:
        self.client = self._init_client()
        if not self.client:
            logger.error("[TELEGRAM] Não foi possível inicializar o cliente Telegram.")
            return

        await self.client.connect()

        # Check if authorized, if not and bot token is available, login as bot
        if not await self.client.is_user_authorized():
            if self.settings.TELEGRAM_BOT_TOKEN:
                logger.info("[TELEGRAM] Autenticando com TELEGRAM_BOT_TOKEN...")
                await self.client.start(bot_token=self.settings.TELEGRAM_BOT_TOKEN)
            else:
                logger.warning("[TELEGRAM] Cliente Telegram não autorizado. Configure TELEGRAM_SESSION_STRING ou TELEGRAM_BOT_TOKEN.")
                return

        logger.info("[TELEGRAM] Cliente Telegram conectado e autenticado com sucesso.")

        # Register event handlers for source chats
        source_chats = self.settings.get_telegram_source_chats()
        logger.info(f"[TELEGRAM] Monitorando canais/grupos: {source_chats or 'TODOS os canais acessíveis'}")

        chat_targets = []
        for chat in source_chats:
            try:
                # Convert numeric IDs if applicable
                chat_targets.append(int(chat) if chat.lstrip("-").isdigit() else chat)
            except Exception:
                chat_targets.append(chat)

        event_kwargs = {"chats": chat_targets} if chat_targets else {}

        @self.client.on(events.NewMessage(**event_kwargs))
        async def on_new_message(event):
            try:
                await self._handle_event(event)
            except Exception as e:
                logger.error(f"[TELEGRAM] Erro ao processar evento de mensagem: {e}", exc_info=True)

        self._running = True

    def _extract_urls(self, text: str, entities: Optional[list]) -> List[str]:
        """Extract URLs from message entities (text link or plain URL)."""
        urls: List[str] = []
        if not entities:
            return urls
        for ent in entities:
            if isinstance(ent, MessageEntityTextUrl):
                urls.append(ent.url)
            elif isinstance(ent, MessageEntityUrl):
                offset = ent.offset
                length = ent.length
                urls.append(text[offset:offset + length])
        return urls

    def _build_raw_message(
        self,
        *,
        chat_id: str,
        chat_title: Optional[str],
        message_id: str,
        text: str,
        entities: Optional[list],
        photo: bool = False,
    ) -> RawMessage:
        """Build a normalized RawMessage (pure, testable) from Telegram fields."""
        urls = self._extract_urls(text, entities)
        # Generate correlation ID for tracing this message through the pipeline
        correlation_id = uuid.uuid4().hex[:8]
        return RawMessage(
            id=str(uuid.uuid4()),
            source="telegram",
            source_message_id=message_id,
            source_chat_id=chat_id,
            source_chat_title=chat_title,
            text=text,
            media_path=None,
            urls=urls,
            correlation_id=correlation_id,
            received_at=datetime.now(timezone.utc)
        )

    async def _download_media(self, message, chat_id: str, message_id: str) -> Optional[str]:
        """Download image media from a message and return its local path."""
        try:
            filename = f"{chat_id}_{message_id}_{uuid.uuid4().hex[:8]}.jpg"
            dest_path = self.media_dir / filename
            downloaded = await message.download_media(file=dest_path)
            if downloaded and os.path.exists(downloaded):
                return str(downloaded)
        except Exception as e:
            logger.warning(f"[TELEGRAM] Erro ao baixar imagem da mensagem {message_id}: {e}")
        return None

    async def _handle_event(self, event) -> None:
        message = event.message
        if not message:
            return

        chat_id = str(event.chat_id)
        chat_title = getattr(event.chat, "title", None) or getattr(event.chat, "username", None) or chat_id
        message_id = str(message.id)
        text = message.text or message.message or ""

        raw_msg = self._build_raw_message(
            chat_id=chat_id,
            chat_title=chat_title,
            message_id=message_id,
            text=text,
            entities=message.entities,
        )

        # Handle image/media download if present
        if message.photo:
            media_path = await self._download_media(message, chat_id, message_id)
            if media_path:
                raw_msg.media_path = media_path

        logger.info(f"[TELEGRAM] mensagem recebida de {chat_id} (msg {message_id})")
        await self.queue.enqueue(raw_msg)

    async def listen(self) -> None:
        if not self._running:
            await self.start()
        if self.client and self.client.is_connected():
            logger.info("[TELEGRAM] Aguardando mensagens de canais configurados...")
            await self.client.run_until_disconnected()

    async def stop(self) -> None:
        self._running = False
        if self.client:
            await self.client.disconnect()
            logger.info("[TELEGRAM] Cliente Telegram desconectado.")


class TelegramPublisher(Publisher):
    """
    Telegram publisher implementation.
    Publishes formatted promotion posts with optional photo to TELEGRAM_TARGET_CHAT.
    Uses Telegram Bot API HTTP for direct, robust messaging with retry logic.
    """

    def __init__(self, settings: Optional[Settings] = None, client: Optional[httpx.AsyncClient] = None):
        self.settings = settings or get_settings()
        self._client = client

    def _create_retry_transport(self) -> httpx.AsyncClient:
        """Create an httpx client with retry logic for transient errors."""
        # Retry on 429 (rate limit), 5xx server errors, and network errors
        retry = httpx.Retry(
            total=3,
            backoff_factor=0.5,
            status_forcelist=[429, 500, 502, 503, 504],
            allowed_methods=["HEAD", "GET", "OPTIONS", "POST"],
        )
        transport = httpx.AsyncHTTPTransport(retries=retry)
        return httpx.AsyncClient(transport=transport, timeout=30.0)

    async def _http_client(self) -> httpx.AsyncClient:
        if self._client is not None:
            return self._client
        # Fallback: create a short-lived client with retry transport
        client = self._create_retry_transport()
        return await client.__aenter__()

    async def _http_close(self, client: httpx.AsyncClient) -> None:
        if self._client is None:
            await client.__aexit__(None, None, None)

    async def publish(self, promotion: Promotion, formatted_message: str) -> PublicationResult:
        bot_token = self.settings.TELEGRAM_BOT_TOKEN
        target_chat = self.settings.TELEGRAM_TARGET_CHAT

        if not bot_token or not target_chat:
            err = "TELEGRAM_BOT_TOKEN ou TELEGRAM_TARGET_CHAT não configurados."
            logger.warning(f"[PUBLISHER] {err}")
            return PublicationResult(
                success=False,
                platform="telegram",
                target_chat_id=target_chat or "",
                error_message=err
            )

        api_base = f"https://api.telegram.org/bot{bot_token}"

        client = None
        try:
            client = await self._http_client()
            # Check if image is available locally or via URL
            media_path = promotion.image_url
            has_local_file = media_path and os.path.isfile(media_path)

            if has_local_file:
                # Send photo with caption
                url = f"{api_base}/sendPhoto"
                with open(media_path, "rb") as f:
                    files = {"photo": (os.path.basename(media_path), f, "image/jpeg")}
                    data = {
                        "chat_id": target_chat,
                        "caption": formatted_message,
                        "parse_mode": "HTML"
                    }
                    # Fallback parse_mode if HTML fails
                    resp = await client.post(url, data=data, files=files)
                    if not resp.is_success:
                        # Retry without parse_mode
                        f.seek(0)
                        data.pop("parse_mode", None)
                        resp = await client.post(url, data=data, files={"photo": (os.path.basename(media_path), f, "image/jpeg")})
            elif promotion.image_url and promotion.image_url.startswith("http"):
                # Send photo by URL
                url = f"{api_base}/sendPhoto"
                data = {
                    "chat_id": target_chat,
                    "photo": promotion.image_url,
                    "caption": formatted_message
                }
                resp = await client.post(url, data=data)
            else:
                # Send plain text
                url = f"{api_base}/sendMessage"
                data = {
                    "chat_id": target_chat,
                    "text": formatted_message,
                    "disable_web_page_preview": False
                }
                resp = await client.post(url, data=data)

            await self._http_close(client)

            if resp.is_success:
                res_json = resp.json()
                msg_id = str(res_json.get("result", {}).get("message_id", ""))
                logger.info(f"[PUBLISHER] publicada no destino {target_chat} (msg {msg_id})")
                return PublicationResult(
                    success=True,
                    platform="telegram",
                    target_chat_id=target_chat,
                    target_message_id=msg_id,
                    published_at=datetime.now(timezone.utc)
                )
            else:
                err = f"Telegram API error ({resp.status_code}): {resp.text}"
                logger.error(f"[PUBLISHER] Falha ao publicar no Telegram: {err}")
                return PublicationResult(
                    success=False,
                    platform="telegram",
                    target_chat_id=target_chat,
                    error_message=err
                )

        except Exception as e:
            if client is not None:
                await self._http_close(client)
            logger.error(f"[PUBLISHER] Exceção ao publicar no Telegram: {e}", exc_info=True)
            return PublicationResult(
                success=False,
                platform="telegram",
                target_chat_id=target_chat,
                error_message=str(e)
            )


async def run_telegram_listener():
    """Entrypoint for standalone telegram_listener service."""
    logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(name)s - %(levelname)s - %(message)s")
    logger.info("[TELEGRAM] Iniciando listener do Telegram...")
    settings = get_settings()
    source = TelegramAdapter(settings=settings)

    # Start health check server
    health_runner = await run_health_server("telegram_listener", 8082)

    try:
        await source.listen()
    except (KeyboardInterrupt, SystemExit):
        logger.info("[TELEGRAM] Encerrando listener...")
    finally:
        await source.stop()
        await health_runner.cleanup()


if __name__ == "__main__":
    asyncio.run(run_telegram_listener())


# Backwards-compatible alias (legacy name for the input adapter)
TelegramSource = TelegramAdapter
