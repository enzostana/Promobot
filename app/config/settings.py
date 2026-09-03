from functools import lru_cache
from pathlib import Path
from typing import List, Optional
from pydantic_settings import BaseSettings, SettingsConfigDict


def _read_secret(name: str) -> Optional[str]:
    """Read secret from Docker secrets directory (/run/secrets/)."""
    path = Path(f"/run/secrets/{name}")
    if path.exists():
        return path.read_text().strip()
    return None


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

    # Database (PostgreSQL) - no defaults for secrets
    POSTGRES_USER: str = "promobot"
    POSTGRES_PASSWORD: Optional[str] = None
    POSTGRES_DB: str = "promobot"
    POSTGRES_HOST: str = "postgres"
    POSTGRES_PORT: int = 5432

    # Redis (Queue, deduplication cache)
    REDIS_URL: str = "redis://redis:6379/0"
    REDIS_QUEUE_NAME: str = "promobot:raw_messages"
    REDIS_DEDUP_PREFIX: str = "promobot:dedup:"
    DEDUP_WINDOW_HOURS: int = 24
    WORKER_MAX_ATTEMPTS: int = 3

    # Telegram Credentials & Config - no defaults for secrets
    TELEGRAM_API_ID: Optional[int] = None
    TELEGRAM_API_HASH: Optional[str] = None
    TELEGRAM_BOT_TOKEN: Optional[str] = None
    TELEGRAM_SESSION_STRING: Optional[str] = None
    TELEGRAM_SESSION_NAME: str = "promobot_session"
    TELEGRAM_SOURCE_CHATS: str = ""
    TELEGRAM_TARGET_CHAT: Optional[str] = None

    # Affiliate Providers - no defaults for secrets
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

    @property
    def DATABASE_URL(self) -> str:
        pwd = self.POSTGRES_PASSWORD or _read_secret("postgres_password") or ""
        return f"postgresql+asyncpg://{self.POSTGRES_USER}:{pwd}@{self.POSTGRES_HOST}:{self.POSTGRES_PORT}/{self.POSTGRES_DB}"

    @property
    def DATABASE_URL_SYNC(self) -> str:
        pwd = self.POSTGRES_PASSWORD or _read_secret("postgres_password") or ""
        return f"postgresql://{self.POSTGRES_USER}:{pwd}@{self.POSTGRES_HOST}:{self.POSTGRES_PORT}/{self.POSTGRES_DB}"

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        # Load secrets from Docker secrets files if not set via env
        self.TELEGRAM_API_HASH = self.TELEGRAM_API_HASH or _read_secret("telegram_api_hash")
        self.TELEGRAM_BOT_TOKEN = self.TELEGRAM_BOT_TOKEN or _read_secret("telegram_bot_token")
        self.AMAZON_TAG = self.AMAZON_TAG or _read_secret("amazon_tag")
        self.MERCADOLIVRE_TAG = self.MERCADOLIVRE_TAG or _read_secret("mercadolivre_tag")
        self.SHOPEE_APP_ID = self.SHOPEE_APP_ID or _read_secret("shopee_app_id")
        self.SHOPEE_TAG = self.SHOPEE_TAG or _read_secret("shopee_tag")
        # Postgres password can come from env or secret
        if not self.POSTGRES_PASSWORD:
            self.POSTGRES_PASSWORD = _read_secret("postgres_password")

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
