from functools import lru_cache
from typing import List, Optional
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore"
    )

    # General / Application
    APP_ENV: str = "development"
    DEBUG: bool = False
    LOG_LEVEL: str = "INFO"

    # Database (PostgreSQL)
    DATABASE_URL: str = "postgresql+asyncpg://promobot:promosecret123@localhost:5432/promobot"
    DATABASE_URL_SYNC: str = "postgresql://promobot:promosecret123@localhost:5432/promobot"

    # Redis (Queue, deduplication cache)
    REDIS_URL: str = "redis://localhost:6379/0"
    REDIS_QUEUE_NAME: str = "promobot:raw_messages"
    REDIS_DEDUP_PREFIX: str = "promobot:dedup:"
    DEDUP_WINDOW_HOURS: int = 24
    WORKER_MAX_ATTEMPTS: int = 3

    # Telegram Credentials & Config
    TELEGRAM_API_ID: Optional[int] = None
    TELEGRAM_API_HASH: Optional[str] = None
    TELEGRAM_BOT_TOKEN: Optional[str] = None
    TELEGRAM_SESSION_STRING: Optional[str] = None
    TELEGRAM_SESSION_NAME: str = "promobot_session"
    TELEGRAM_SOURCE_CHATS: str = ""
    TELEGRAM_TARGET_CHAT: Optional[str] = None

    # Affiliate Providers
    AMAZON_TAG: Optional[str] = None
    MERCADOLIVRE_TAG: Optional[str] = None
    SHOPEE_APP_ID: Optional[str] = None
    SHOPEE_TAG: Optional[str] = None

    # Filters
    MIN_DISCOUNT_PERCENT: float = 0.0
    MIN_PRICE: Optional[float] = None
    MAX_PRICE: Optional[float] = None
    ALLOWED_STORES: str = ""
    BLOCKED_STORES: str = ""
    ALLOWED_CATEGORIES: str = ""
    BLOCKED_CATEGORIES: str = ""
    BLOCKED_KEYWORDS: str = "esgotado,sorteio,rifa,fake,esgotada,golpe"
    REQUIRED_KEYWORDS: str = ""

    def get_telegram_source_chats(self) -> List[str]:
        if not self.TELEGRAM_SOURCE_CHATS:
            return []
        return [c.strip() for c in self.TELEGRAM_SOURCE_CHATS.split(",") if c.strip()]

    def get_blocked_keywords(self) -> List[str]:
        if not self.BLOCKED_KEYWORDS:
            return []
        return [k.strip().lower() for k in self.BLOCKED_KEYWORDS.split(",") if k.strip()]

    def get_required_keywords(self) -> List[str]:
        if not self.REQUIRED_KEYWORDS:
            return []
        return [k.strip().lower() for k in self.REQUIRED_KEYWORDS.split(",") if k.strip()]

    def get_allowed_stores(self) -> List[str]:
        if not self.ALLOWED_STORES:
            return []
        return [s.strip().lower() for s in self.ALLOWED_STORES.split(",") if s.strip()]

    def get_blocked_stores(self) -> List[str]:
        if not self.BLOCKED_STORES:
            return []
        return [s.strip().lower() for s in self.BLOCKED_STORES.split(",") if s.strip()]

    def get_allowed_categories(self) -> List[str]:
        if not self.ALLOWED_CATEGORIES:
            return []
        return [c.strip().lower() for c in self.ALLOWED_CATEGORIES.split(",") if c.strip()]

    def get_blocked_categories(self) -> List[str]:
        if not self.BLOCKED_CATEGORIES:
            return []
        return [c.strip().lower() for c in self.BLOCKED_CATEGORIES.split(",") if c.strip()]


@lru_cache()
def get_settings() -> Settings:
    return Settings()
