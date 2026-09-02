from abc import ABC, abstractmethod
from typing import Optional


class AffiliateProvider(ABC):
    """
    Abstract base class for store affiliate link converters.
    """

    @property
    @abstractmethod
    def store_name(self) -> str:
        """Returns the canonical store identifier (e.g. 'amazon', 'mercadolivre')."""
        pass

    @abstractmethod
    def can_handle(self, url: str) -> bool:
        """Determines if this provider can handle the given URL."""
        pass

    @abstractmethod
    def convert(self, url: str) -> str:
        """Converts the original URL into an affiliate link."""
        pass

    @abstractmethod
    def extract_product_id(self, url: str) -> Optional[str]:
        """Extracts unique product identifier (e.g. ASIN, MLB ID) if available."""
        pass
