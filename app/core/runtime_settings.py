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
    "bot_paused": ("BOT_PAUSED", "bool", False, "Pausar o bot ('1' pausado, '0' ativo)"),
}

SECTIONS: Dict[str, List[str]] = {
    "afiliados": ["amazon_tag", "mercadolivre_tag", "shopee_tag", "shopee_app_id"],
    "filtros": [
        "blocked_keywords", "required_keywords", "allowed_stores", "blocked_stores",
        "allowed_categories", "blocked_categories", "min_discount_percent",
        "min_price", "max_price",
    ],
    "destinos": ["telegram_target_chat", "bot_paused"],
}

SECRET_KEYS: set = {k for k, (_, _, secret, _) in EDITABLE_KEYS.items() if secret}

# DB key -> host secret file (relative to SECRET_FILES_DIR)
SECRET_FILES: Dict[str, str] = {
    "amazon_tag": "amazon_tag.txt",
    "mercadolivre_tag": "mercadolivre_tag.txt",
    "shopee_tag": "shopee_tag.txt",
    "shopee_app_id": "shopee_app_id.txt",
}

# Directory where panel writes tag files so future container recreates pick them up.
SECRET_FILES_DIR = os.environ.get("SECRET_FILES_DIR", "/app/secret_files")


def _coerce(kind: str, value: str) -> Any:
    if kind == "float":
        try:
            return float(value)
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
            if number < 0:
                errors.append(f"'{key}' deve ser maior ou igual a 0")
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