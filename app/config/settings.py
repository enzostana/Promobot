from functools import lru_cache
from pathlib import Path
from typing import List, Optional
from urllib.parse import quote_plus
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
    # Messages older than this (minutes) are discarded to avoid retroactive
    # posting (e.g. queue backlog accumulated while the bot was paused or
    # Telegram reconnect letting through old channel posts). 0 = disabled.
    STALE_AFTER_MINUTES: int = 15

    # Database Connection Pool
    DB_POOL_SIZE: int = 5
    DB_MAX_OVERFLOW: int = 10
    DB_POOL_RECYCLE: int = 1800
    DB_POOL_TIMEOUT: int = 30

    # Telegram Credentials & Config - no defaults for secrets
    TELEGRAM_API_ID: Optional[int] = None
    TELEGRAM_API_HASH: Optional[str] = None
    TELEGRAM_BOT_TOKEN: Optional[str] = None
    TELEGRAM_SESSION_STRING: Optional[str] = None
    TELEGRAM_SESSION_NAME: str = "promobot_session"
    TELEGRAM_SOURCE_CHATS: str = ""
    TELEGRAM_TARGET_CHAT: Optional[str] = None
    TELEGRAM_LISTENER_ENABLED: bool = True

    # WhatsApp (Evolution API) - no defaults for secrets
    EVOLUTION_URL: str = "http://evolution-api:8080"
    EVOLUTION_INSTANCE: str = "promobot"
    EVOLUTION_API_KEY: Optional[str] = None
    WHATSAPP_TARGET_CHAT: Optional[str] = None
    WHATSAPP_ENABLED: bool = True
    WHATSAPP_WITH_IMAGE: bool = True

    # Affiliate Providers - no defaults for secrets
    AMAZON_TAG: Optional[str] = None
    MERCADOLIVRE_TAG: Optional[str] = None
    MERCADOLIVRE_WORD: Optional[str] = None
    MERCADOLIVRE_MATT_WORD: Optional[str] = None
    MERCADOLIVRE_ROUTE: str = "product"
    MERCADOLIVRE_MINT: bool = False
    MERCADOLIVRE_SESSION_FILE: Optional[str] = None
    SHOPEE_APP_ID: Optional[str] = None
    SHOPEE_TAG: Optional[str] = None

    # Shopee Finder (caçador de ofertas via Open API de Afiliados)
    SHOPEE_API_APP_ID: Optional[str] = None
    SHOPEE_API_SECRET: Optional[str] = None
    SHOPEE_FINDER_ENABLED: bool = False
    SHOPEE_FINDER_KEYWORDS: str = "fone bluetooth,smart watch,smart tv,cafeteira,perfume masculino,tênis"
    SHOPEE_FINDER_MIN_DISCOUNT: float = 20.0
    SHOPEE_FINDER_MIN_SALES: int = 50
    SHOPEE_FINDER_MIN_RATING: float = 4.0
    SHOPEE_FINDER_MAX_PRICE: float = 500.0
    SHOPEE_FINDER_INTERVAL_MIN: int = 30

    # Mercado Livre Finder (caçador via API pública + tag matt_tool)
    MEL_API_CLIENT_ID: Optional[str] = None
    MEL_API_CLIENT_SECRET: Optional[str] = None
    MEL_REFRESH_TOKEN: Optional[str] = None
    MEL_FINDER_ENABLED: bool = False
    MEL_FINDER_KEYWORDS: str = "fone bluetooth,smart watch,smart tv,cafeteira,perfume masculino,tênis"
    MEL_FINDER_MIN_DISCOUNT: float = 20.0
    MEL_FINDER_MAX_PRICE: float = 500.0
    MEL_FINDER_INTERVAL_MIN: int = 30
    MEL_FINDER_PAGES: int = 3

    # Amazon Finder (caçador via scraping da página pública de ofertas)
    AMAZON_FINDER_ENABLED: bool = False
    AMAZON_FINDER_KEYWORDS: str = "fone bluetooth,smart watch,smart tv,cafeteira,perfume masculino,tênis"
    AMAZON_FINDER_MIN_DISCOUNT: float = 20.0
    AMAZON_FINDER_MAX_PRICE: float = 500.0
    AMAZON_FINDER_INTERVAL_MIN: int = 30

    # Site público (Rufino Promo)
    SITE_TITLE: str = "Rufino Promo"
    SITE_REFRESH_SECONDS: int = 20
    MEDIA_CACHE_DIR: str = "/app/media_cache"
    MEL_OAUTH_REDIRECT_URI: str = "https://promobot.enzostana.space/"

    # Dashboard Auth
    DASHBOARD_USERNAME: Optional[str] = None
    DASHBOARD_PASSWORD: Optional[str] = None

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
        return f"postgresql+asyncpg://{self.POSTGRES_USER}:{quote_plus(pwd)}@{self.POSTGRES_HOST}:{self.POSTGRES_PORT}/{self.POSTGRES_DB}"

    @property
    def DATABASE_URL_SYNC(self) -> str:
        pwd = self.POSTGRES_PASSWORD or _read_secret("postgres_password") or ""
        return f"postgresql://{self.POSTGRES_USER}:{quote_plus(pwd)}@{self.POSTGRES_HOST}:{self.POSTGRES_PORT}/{self.POSTGRES_DB}"

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        # Load secrets from Docker secrets files if not set via env
        self.TELEGRAM_API_HASH = self.TELEGRAM_API_HASH or _read_secret("telegram_api_hash")
        self.TELEGRAM_BOT_TOKEN = self.TELEGRAM_BOT_TOKEN or _read_secret("telegram_bot_token")
        self.TELEGRAM_SESSION_STRING = self.TELEGRAM_SESSION_STRING or _read_secret("telegram_session_string")
        self.EVOLUTION_API_KEY = self.EVOLUTION_API_KEY or _read_secret("evolution_api_key")
        self.AMAZON_TAG = self.AMAZON_TAG or _read_secret("amazon_tag")
        self.MERCADOLIVRE_TAG = self.MERCADOLIVRE_TAG or _read_secret("mercadolivre_tag")
        self.SHOPEE_APP_ID = self.SHOPEE_APP_ID or _read_secret("shopee_app_id")
        self.SHOPEE_TAG = self.SHOPEE_TAG or _read_secret("shopee_tag")
        self.SHOPEE_API_APP_ID = self.SHOPEE_API_APP_ID or _read_secret("shopee_api_app_id")
        self.SHOPEE_API_SECRET = self.SHOPEE_API_SECRET or _read_secret("shopee_api_secret")
        self.MEL_API_CLIENT_ID = self.MEL_API_CLIENT_ID or _read_secret("mel_api_client_id")
        self.MEL_API_CLIENT_SECRET = self.MEL_API_CLIENT_SECRET or _read_secret("mel_api_client_secret")
        self.MEL_REFRESH_TOKEN = self.MEL_REFRESH_TOKEN or _read_secret("mel_refresh_token")
        # Postgres password can come from env or secret
        if not self.POSTGRES_PASSWORD:
            self.POSTGRES_PASSWORD = _read_secret("postgres_password")

    def get_telegram_source_chats(self) -> List[str]:
        if not self.TELEGRAM_SOURCE_CHATS:
            return []
        return [c.strip() for c in self.TELEGRAM_SOURCE_CHATS.split(",") if c.strip()]

    def get_shopee_finder_keywords(self) -> List[str]:
        if not self.SHOPEE_FINDER_KEYWORDS:
            return []
        return [k.strip() for k in self.SHOPEE_FINDER_KEYWORDS.split(",") if k.strip()]

    def get_mel_finder_keywords(self) -> List[str]:
        if not self.MEL_FINDER_KEYWORDS:
            return []
        return [k.strip() for k in self.MEL_FINDER_KEYWORDS.split(",") if k.strip()]

    def get_amazon_finder_keywords(self) -> List[str]:
        if not self.AMAZON_FINDER_KEYWORDS:
            return []
        return [k.strip() for k in self.AMAZON_FINDER_KEYWORDS.split(",") if k.strip()]

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
