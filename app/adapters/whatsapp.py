import asyncio
import base64
import logging
import os
import uuid
from datetime import datetime, timezone
from typing import Optional

import httpx
from mimetypes import guess_type

from app.adapters.base import MessageSource
from app.core.publisher import Publisher
from app.core.models import Promotion, PublicationResult
from app.config.settings import Settings, get_settings

logger = logging.getLogger(__name__)

DEFAULT_MIME = "image/jpeg"


class WhatsAppSource(MessageSource):
    """
    Placeholder/Interface for future WhatsApp listener.
    Can be implemented with WhatsApp Cloud API, Baileys, or Z-API.
    """

    def __init__(self, config=None):
        self.config = config

    async def start(self) -> None:
        logger.info("[WHATSAPP] WhatsAppSource interface pronta para extensão futura.")

    async def listen(self) -> None:
        logger.info("[WHATSAPP] WhatsApp listener ainda não implementado (agendado para v2).")

    async def stop(self) -> None:
        logger.info("[WHATSAPP] WhatsAppSource finalizado.")


class WhatsAppPublisher(Publisher):
    """
    WhatsApp publisher via Evolution API (sendText / sendMedia).

    Publishes formatted promotions to a configured WhatsApp group/contact.
    Media is sent as a base64 data-URI when the image is only available as a
    local file (media_cache inside the worker container).
    """

    RETRYABLE_STATUS = {429, 500, 502, 503, 504}
    MAX_RETRIES = 3
    BASE_BACKOFF = 0.5
    MAX_BACKOFF = 8.0

    def __init__(self, settings: Optional[Settings] = None, client: Optional[httpx.AsyncClient] = None):
        self.settings = settings or get_settings()
        self._client = client

    @property
    def enabled(self) -> bool:
        return bool(
            self.settings.WHATSAPP_ENABLED
            and self.settings.WHATSAPP_TARGET_CHAT
        )

    def _create_retry_transport(self) -> httpx.AsyncClient:
        transport = httpx.AsyncHTTPTransport(retries=3)
        return httpx.AsyncClient(transport=transport, timeout=30.0)

    async def _post_with_retry(
        self,
        client: httpx.AsyncClient,
        url: str,
        *,
        json_body: dict,
        headers: Optional[dict] = None,
    ) -> httpx.Response:
        """POST JSON with manual retry for 429/5xx status codes."""
        for attempt in range(self.MAX_RETRIES):
            resp = await client.post(url, json=json_body, headers=headers)
            if resp.status_code not in self.RETRYABLE_STATUS or attempt == self.MAX_RETRIES - 1:
                return resp
            delay = min(self.BASE_BACKOFF * (2 ** attempt), self.MAX_BACKOFF)
            retry_after = resp.headers.get("Retry-After")
            if retry_after and retry_after.isdigit():
                delay = max(delay, float(retry_after))
            await asyncio.sleep(delay)
        return resp

    async def _http_client(self) -> httpx.AsyncClient:
        if self._client is not None:
            return self._client
        client = self._create_retry_transport()
        return await client.__aenter__()

    async def _http_close(self, client: httpx.AsyncClient) -> None:
        if self._client is None:
            await client.__aexit__(None, None, None)

    def _mime_for(self, path: str) -> str:
        mime, _ = guess_type(path)
        return mime or DEFAULT_MIME

    def _media_payload(self, promotion: Promotion) -> Optional[str]:
        """
        Returns the 'media' value for sendMedia:
        - local file -> base64 (raw, no data: prefix)
        - http(s) URL -> passed through
        - otherwise None (text-only)
        """
        media_ref = promotion.image_url
        if not media_ref:
            return None

        # Local file (e.g. downloaded from Telegram into media_cache)
        if os.path.isfile(media_ref):
            try:
                with open(media_ref, "rb") as f:
                    b64 = base64.b64encode(f.read()).decode("ascii")
                # Evolution API rejects data-URIs; it expects raw base64 or URL.
                return b64
            except Exception as e:
                logger.warning(f"[WHATSAPP] Falha ao codificar imagem local {media_ref}: {e}")
                return None

        # Public URL reachable by the Evolution API container
        if media_ref.startswith(("http://", "https://")):
            return media_ref

        return None

    async def publish(self, promotion: Promotion, formatted_message: str) -> PublicationResult:
        api_key = self.settings.EVOLUTION_API_KEY
        instance = self.settings.EVOLUTION_INSTANCE
        target_chat = self.settings.WHATSAPP_TARGET_CHAT
        base_url = self.settings.EVOLUTION_URL.rstrip("/")

        if not api_key or not target_chat or not base_url:
            err = "EVOLUTION_API_KEY, EVOLUTION_URL ou WHATSAPP_TARGET_CHAT não configurados."
            logger.warning(f"[WHATSAPP] {err}")
            return PublicationResult(
                success=False,
                platform="whatsapp",
                target_chat_id=target_chat or "",
                error_message=err
            )

        headers = {"apikey": api_key, "Content-Type": "application/json"}
        client = None
        try:
            client = await self._http_client()

            media = self._media_payload(promotion) if self.settings.WHATSAPP_WITH_IMAGE else None
            if media:
                url = f"{base_url}/message/sendMedia/{instance}"
                # Media mime type is derived from the image source (file/URL), since
                # raw base64 has no header to inspect.
                mime = self._mime_for(promotion.image_url or "image.jpg")
                body = {
                    "number": target_chat,
                    "mediatype": "image",
                    "mimetype": mime,
                    "media": media,
                    "caption": formatted_message,
                    "fileName": f"promo_{uuid.uuid4().hex[:8]}.jpg",
                }
            else:
                url = f"{base_url}/message/sendText/{instance}"
                body = {"number": target_chat, "text": formatted_message}

            resp = await self._post_with_retry(client, url, json_body=body, headers={"apikey": api_key})
            await self._http_close(client)

            if 200 <= resp.status_code < 300:
                res_json = resp.json() if resp.content else {}
                key = res_json.get("key", {}) if isinstance(res_json, dict) else {}
                msg_id = str(key.get("id") or "") if isinstance(key, dict) else ""
                logger.info(f"[WHATSAPP] publicada em {target_chat} (msg {msg_id})")
                return PublicationResult(
                    success=True,
                    platform="whatsapp",
                    target_chat_id=target_chat,
                    target_message_id=msg_id,
                    published_at=datetime.now(timezone.utc)
                )

            err = f"Evolution API error ({resp.status_code}): {resp.text}"
            logger.error(f"[WHATSAPP] Falha ao publicar no WhatsApp: {err}")
            return PublicationResult(
                success=False,
                platform="whatsapp",
                target_chat_id=target_chat,
                error_message=err
            )

        except Exception as e:
            if client is not None:
                await self._http_close(client)
            logger.error(f"[WHATSAPP] Exceção ao publicar no WhatsApp: {e}", exc_info=True)
            return PublicationResult(
                success=False,
                platform="whatsapp",
                target_chat_id=target_chat,
                error_message=str(e)
            )