from abc import ABC, abstractmethod
from typing import Optional
from app.core.models import Promotion, PublicationResult


class Publisher(ABC):
    """
    Abstract interface for publishing promotions to external platforms
    (Telegram, WhatsApp, etc.).
    """

    @abstractmethod
    async def publish(self, promotion: Promotion, formatted_message: str) -> PublicationResult:
        """
        Publishes the formatted promotion to the target channel/group.
        """
        pass
