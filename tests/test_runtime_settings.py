import pytest
from app.config.settings import Settings
from app.core.runtime_settings import (
    EDITABLE_KEYS,
    RuntimeOverrides,
    mask_secret,
    resolve_values,
    validate_section,
)
from app.database.repositories.setting_repo import SettingRepository


@pytest.fixture
def base_settings():
    return Settings(
        APP_ENV="test",
        DEBUG=True,
        AMAZON_TAG="env-amazon",
        MERCADOLIVRE_TAG="env-meli",
        BLOCKED_STORES="",
    )


def test_editable_keys_mapping():
    assert EDITABLE_KEYS["amazon_tag"][0] == "AMAZON_TAG"
    assert EDITABLE_KEYS["mercadolivre_tag"][0] == "MERCADOLIVRE_TAG"
    assert EDITABLE_KEYS["shopee_tag"][0] == "SHOPEE_TAG"
    assert EDITABLE_KEYS["shopee_app_id"][0] == "SHOPEE_APP_ID"
    assert EDITABLE_KEYS["bot_paused"][0] == "BOT_PAUSED"


def test_mask_secret():
    assert mask_secret("") == ""
    assert mask_secret("1234") == "••••"
    assert mask_secret("12345678") == "1234••••"


def test_validate_section_valid_and_invalid():
    assert validate_section("filtros", {"min_discount_percent": "15.5", "blocked_stores": "amazon"}) == []
    assert validate_section("filtros", {"min_discount_percent": "abc"}) != []
    assert validate_section("filtros", {"min_discount_percent": "150"}) != []
    assert validate_section("destinos", {"bot_paused": "2"}) != []
    assert validate_section("destinos", {"bot_paused": "0"}) == []
    unknown = validate_section("afiliados", {"min_price": "10"})
    assert unknown != []


def test_resolve_values_precedence(base_settings):
    overrides = {"mercadolivre_tag": "novo-meli"}
    resolved = resolve_values(base_settings, overrides)
    assert resolved["amazon_tag"]["value"] == "env-amazon"
    assert resolved["amazon_tag"]["configured_in_db"] is False
    assert resolved["mercadolivre_tag"]["value"] == "novo-meli"
    assert resolved["mercadolivre_tag"]["configured_in_db"] is True
    assert resolved["amazon_tag"]["masked"] == mask_secret("env-amazon")


@pytest.mark.asyncio
async def test_runtime_overrides_applies_and_caches(async_db_session):
    repo = SettingRepository(async_db_session)
    await repo.upsert("amazon_tag", "db-amazon")
    await repo.upsert("bot_paused", "1")

    overrides = RuntimeOverrides(ttl=600)
    settings = Settings(APP_ENV="test", AMAZON_TAG="env-amazon")
    await overrides.apply(async_db_session, settings)

    assert settings.AMAZON_TAG == "db-amazon"
    assert overrides.is_paused() is True

    # New value stored after cache fill must not show until forced refresh
    await repo.upsert("amazon_tag", "db-amazon-2")
    await overrides.apply(async_db_session, settings)
    assert settings.AMAZON_TAG == "db-amazon"
    await overrides.apply(async_db_session, settings, force=True)
    assert settings.AMAZON_TAG == "db-amazon-2"