import logging
from typing import Optional
from app.adapters.base import MessageSource
from app.core.publisher import Publisher
from app.core.models import Promotion, PublicationResult

logger = logging.getLogger(__name__)


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
    Placeholder/Interface for future WhatsApp publisher.
    """

    def __init__(self, config=None):
        self.config = config

    async def publish(self, promotion: Promotion, formatted_message: str) -> PublicationResult:
        logger.warning("[WHATSAPP] WhatsAppPublisher chamado, mas adapter ainda não está implementado.")
        return PublicationResult(
            success=False,
            platform="whatsapp",
            target_chat_id="",
            error_message="WhatsAppPublisher ainda não implementado."
        )
