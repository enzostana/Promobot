import logging
import os
import time
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from sqlalchemy.ext.asyncio import AsyncSession

from app.config.settings import Settings
from app.database.repositories.setting_repo import SettingRepository

logger = logging.getLogger(__name__)

# key -> (settings_attribute, kind, is_secret, description)
EDITABLE_KEYS: Dict[str, Tuple[str, str, bool, str]] = {
    # Afiliados
    "amazon_tag": ("AMAZON_TAG", "str", True, "Tag de afiliado Amazon (ex.: minhatag-20)"),
    "mercadolivre_tag": ("MERCADOLIVRE_TAG", "str", True, "Tag Mercado Livre (matt_tool)"),
    "mercadolivre_matt_word": ("MERCADOLIVRE_MATT_WORD", "str", False, "Palavra Mercado Livre (matt_word); vazio = usa a word do /social"),
    "shopee_tag": ("SHOPEE_TAG", "str", True, "Tag Shopee (aff_trace_key)"),
    "shopee_app_id": ("SHOPEE_APP_ID", "str", True, "App ID do Shopee"),
    # Filtros
    "blocked_keywords": ("BLOCKED_KEYWORDS", "str", False, "Palavras-chave bloqueadas (separadas por vírgula)"),
    "required_keywords": ("REQUIRED_KEYWORDS", "str", False, "Palavras-chave obrigatórias (separadas por vírgula)"),
    "allowed_stores": ("ALLOWED_STORES", "str", False, "Lojas permitidas (whitelist; vazio = todas)"),
    "blocked_stores": ("BLOCKED_STORES", "str", False, "Lojas bloqueadas (blacklist)"),
    "allowed_categories": ("ALLOWED_CATEGORIES", "str", False, "Categorias permitidas (whitelist; vazio = todas)"),
    "blocked_categories": ("BLOCKED_CATEGORIES", "str", False, "Categorias bloqueadas"),
    "min_discount_percent": ("MIN_DISCOUNT_PERCENT", "float", False, "Desconto mínimo (%)"),
    "min_price": ("MIN_PRICE", "float", False, "Preço mínimo (R$)"),
    "max_price": ("MAX_PRICE", "float", False, "Preço máximo (R$)"),
    # Destino / controle
    "telegram_target_chat": ("TELEGRAM_TARGET_CHAT", "str", False, "Canal de destino (chat_id)"),
    "whatsapp_target_chat": ("WHATSAPP_TARGET_CHAT", "str", False, "Grupo/contato WhatsApp destino (JID, ex.: 120363410512355040@g.us)"),
    "whatsapp_enabled": ("WHATSAPP_ENABLED", "bool", False, "Publicar também no WhatsApp ('1' ligado, '0' desligado)"),
    "whatsapp_with_image": ("WHATSAPP_WITH_IMAGE", "bool", False, "Enviar imagem da oferta no WhatsApp ('1' sim, '0' só texto)"),
    "bot_paused": ("BOT_PAUSED", "bool", False, "Pausar o bot ('1' pausado, '0' ativo)"),
    # Caçador de ofertas (Shopee Finder)
    "shopee_api_app_id": ("SHOPEE_API_APP_ID", "str", True, "App ID da Open API Shopee (Abrir API)"),
    "shopee_api_secret": ("SHOPEE_API_SECRET", "str", True, "Secret da Open API Shopee (Abrir API)"),
    "shopee_finder_enabled": ("SHOPEE_FINDER_ENABLED", "bool", False, "Caçador Shopee ligado ('1' sim, '0' não)"),
    "shopee_finder_keywords": ("SHOPEE_FINDER_KEYWORDS", "str", False, "Keywords do caçador (separadas por vírgula)"),
    "shopee_finder_min_discount": ("SHOPEE_FINDER_MIN_DISCOUNT", "float", False, "Desconto mínimo p/ publicar (%)"),
    "shopee_finder_min_sales": ("SHOPEE_FINDER_MIN_SALES", "int", False, "Vendas mínimas do produto"),
    "shopee_finder_min_rating": ("SHOPEE_FINDER_MIN_RATING", "float", False, "Avaliação mínima (0 a 5)"),
    "shopee_finder_max_price": ("SHOPEE_FINDER_MAX_PRICE", "float", False, "Preço máximo (R$)"),
    "shopee_finder_interval_min": ("SHOPEE_FINDER_INTERVAL_MIN", "int", False, "Intervalo entre varreduras (min)"),
    # Caçador de ofertas (Mercado Livre)
    "mel_api_client_id": ("MEL_API_CLIENT_ID", "str", True, "Client ID do app Mercado Livre (developers.mercadolivre.com.br)"),
    "mel_api_client_secret": ("MEL_API_CLIENT_SECRET", "str", True, "Client Secret do app Mercado Livre"),
    "mel_refresh_token": ("MEL_REFRESH_TOKEN", "str", True, "Refresh Token (OAuth offline_access) para o /sites/MLB/search"),
    "mel_finder_enabled": ("MEL_FINDER_ENABLED", "bool", False, "Caçador Mercado Livre ligado ('1' sim, '0' não)"),
    "mel_finder_keywords": ("MEL_FINDER_KEYWORDS", "str", False, "Keywords do caçador MEL (separadas por vírgula)"),
    "mel_finder_min_discount": ("MEL_FINDER_MIN_DISCOUNT", "float", False, "Desconto mínimo p/ publicar (%)"),
    "mel_finder_max_price": ("MEL_FINDER_MAX_PRICE", "float", False, "Preço máximo (R$)"),
    "mel_finder_interval_min": ("MEL_FINDER_INTERVAL_MIN", "int", False, "Intervalo entre varreduras (min)"),
    "mel_finder_pages": ("MEL_FINDER_PAGES", "int", False, "Qtd de páginas de ofertas a varrer"),
}

SECTIONS: Dict[str, List[str]] = {
    "afiliados": ["amazon_tag", "mercadolivre_tag", "mercadolivre_matt_word", "shopee_tag", "shopee_app_id"],
    "filtros": [
        "blocked_keywords", "required_keywords", "allowed_stores", "blocked_stores",
        "allowed_categories", "blocked_categories", "min_discount_percent",
        "min_price", "max_price",
    ],
    "destinos": ["telegram_target_chat", "whatsapp_target_chat", "whatsapp_enabled", "whatsapp_with_image", "bot_paused"],
    "caçador": [
        "shopee_api_app_id", "shopee_api_secret", "shopee_finder_enabled",
        "shopee_finder_keywords", "shopee_finder_min_discount", "shopee_finder_min_sales",
        "shopee_finder_min_rating", "shopee_finder_max_price", "shopee_finder_interval_min",
        "mel_api_client_id", "mel_api_client_secret", "mel_finder_enabled",
        "mel_finder_keywords", "mel_finder_min_discount", "mel_finder_max_price",
        "mel_finder_interval_min", "mel_finder_pages", "mel_refresh_token",
    ],
}

SECRET_KEYS: set = {k for k, (_, _, secret, _) in EDITABLE_KEYS.items() if secret}

# DB key -> host secret file (relative to SECRET_FILES_DIR)
SECRET_FILES: Dict[str, str] = {
    "amazon_tag": "amazon_tag.txt",
    "mercadolivre_tag": "mercadolivre_tag.txt",
    "shopee_tag": "shopee_tag.txt",
    "shopee_app_id": "shopee_app_id.txt",
    "shopee_api_app_id": "shopee_api_app_id.txt",
    "shopee_api_secret": "shopee_api_secret.txt",
    "mel_api_client_id": "mel_api_client_id.txt",
    "mel_api_client_secret": "mel_api_client_secret.txt",
    "mel_refresh_token": "mel_refresh_token.txt",
}

# Directory where panel writes tag files so future container recreates pick them up.
SECRET_FILES_DIR = os.environ.get("SECRET_FILES_DIR", "/app/secret_files")


def _coerce(kind: str, value: str) -> Any:
    if kind == "float":
        try:
            return float(value)
        except (TypeError, ValueError):
            return value
    if kind == "int":
        try:
            return int(float(value))
        except (TypeError, ValueError):
            return value
    if kind == "bool":
        return value in ("1", "true", "True", "on")
    return value


def mask_secret(value: Optional[str]) -> str:
    if not value:
        return ""
    if len(value) <= 4:
        return "•" * len(value)
    return value[:4] + "•" * (len(value) - 4)


def validate_section(section: str, payload: Dict[str, str]) -> List[str]:
    """Validates a section payload. Returns a list of error messages (empty = ok)."""
    errors: List[str] = []
    allowed = SECTIONS.get(section, [])
    for key, raw_value in payload.items():
        if key not in allowed:
            errors.append(f"Chave desconhecida na seção '{section}': '{key}'")
            continue
        if not isinstance(raw_value, str):
            errors.append(f"Valor inválido para '{key}'")
            continue
        value = raw_value.strip()
        if not value:
            continue
        _, kind, _, _ = EDITABLE_KEYS[key]
        if kind == "float":
            try:
                number = float(value.replace(",", "."))
            except ValueError:
                errors.append(f"'{key}' deve ser um número")
                continue
            if key == "min_discount_percent" and not (0 <= number <= 100):
                errors.append("'min_discount_percent' deve estar entre 0 e 100")
                continue
            if key == "shopee_finder_min_discount" and not (0 <= number <= 100):
                errors.append("'shopee_finder_min_discount' deve estar entre 0 e 100")
                continue
            if key == "mel_finder_min_discount" and not (0 <= number <= 100):
                errors.append("'mel_finder_min_discount' deve estar entre 0 e 100")
                continue
            if key == "shopee_finder_min_rating" and not (0 <= number <= 5):
                errors.append("'shopee_finder_min_rating' deve estar entre 0 e 5")
                continue
            if number < 0:
                errors.append(f"'{key}' deve ser maior ou igual a 0")
        if kind == "int":
            try:
                number = int(float(value.replace(",", ".")))
            except ValueError:
                errors.append(f"'{key}' deve ser um número inteiro")
                continue
            if number < 0:
                errors.append(f"'{key}' deve ser maior ou igual a 0")
            if key == "shopee_finder_interval_min" and number < 1:
                errors.append("'shopee_finder_interval_min' deve ser maior ou igual a 1")
        if kind == "bool" and value not in ("0", "1"):
            errors.append(f"'{key}' deve ser '0' ou '1'")
    return errors


def resolve_values(base: Settings, overrides: Dict[str, str]) -> Dict[str, Dict[str, Any]]:
    """Computes effective + masked values for every editable key."""
    resolved: Dict[str, Dict[str, Any]] = {}
    for key, (attr, _, secret, description) in EDITABLE_KEYS.items():
        base_value = getattr(base, attr, None)
        configured_in_db = key in overrides
        effective = overrides.get(key) if configured_in_db else ("" if base_value is None else str(base_value))
        resolved[key] = {
            "attr": attr,
            "description": description,
            "secret": secret,
            "value": effective,
            "masked": mask_secret(effective) if secret else "",
            "configured_in_db": configured_in_db,
        }
    return resolved


class RuntimeOverrides:
    """
    In-process cache of runtime settings stored in the DB 'settings' table.
    Overrides take precedence over env/docker-secrets. TTL keeps DB access off
    the hot path while still propagating panel changes within a few seconds.
    """

    def __init__(self, ttl: float = 3.0):
        self.ttl = ttl
        self._cache: Optional[Dict[str, str]] = None
        self._cache_ts = 0.0

    async def load(self, session: AsyncSession, force: bool = False) -> Dict[str, str]:
        now = time.monotonic()
        if self._cache is None or force or (now - self._cache_ts) >= self.ttl:
            repo = SettingRepository(session)
            values = await repo.get_all()
            self._cache = {k: v for k, v in values.items() if k in EDITABLE_KEYS}
            self._cache_ts = now
        return self._cache

    async def apply(self, session: AsyncSession, settings: Settings, force: bool = False) -> None:
        overrides = await self.load(session, force=force)
        for key, value in overrides.items():
            attr, kind, _, _ = EDITABLE_KEYS[key]
            if attr == "BOT_PAUSED" or not hasattr(settings, attr):
                continue
            setattr(settings, attr, _coerce(kind, value))

    def is_paused(self) -> bool:
        if not self._cache:
            return False
        return self._cache.get("bot_paused") == "1"


def write_secret_file(key: str, value: str) -> bool:
    """Best-effort write of a tag value to the host secrets directory."""
    filename = SECRET_FILES.get(key)
    if not filename:
        return False
    try:
        directory = Path(SECRET_FILES_DIR)
        directory.mkdir(parents=True, exist_ok=True)
        path = directory / filename
        path.write_text(value.strip() + "\n")
        logger.info(f"[SETTINGS] arquivo de secret atualizado: {path}")
        return True
    except Exception as e:
        logger.warning(f"[SETTINGS] não foi possível gravar {filename}: {e}")
        return False