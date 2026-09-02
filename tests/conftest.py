import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from app.database.models import Base
from app.config.settings import Settings
from app.core.models import Promotion, PublicationResult
from app.core.publisher import Publisher


@pytest.fixture
def test_settings():
    return Settings(
        APP_ENV="test",
        DEBUG=True,
        DATABASE_URL="sqlite+aiosqlite:///:memory:",
        REDIS_URL="redis://localhost:6379/15",
        AMAZON_TAG="testtag-20",
        MERCADOLIVRE_TAG="meli_test_tag",
        SHOPEE_TAG="shopee_test_tag",
        SHOPEE_APP_ID="shopee_app_123",
        MIN_DISCOUNT_PERCENT=10.0,
        MAX_PRICE=3000.0,
        MIN_PRICE=10.0,
        BLOCKED_STORES="aliexpress",
        BLOCKED_CATEGORIES="moda",
        BLOCKED_KEYWORDS="esgotado,sorteio,rifa,fake"
    )


@pytest_asyncio.fixture
async def async_db_session():
    """In-memory SQLite async session for tests."""
    engine = create_async_engine("sqlite+aiosqlite:///:memory:", echo=False)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    session_factory = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)
    async with session_factory() as session:
        yield session

    await engine.dispose()


class MockPublisher(Publisher):
    def __init__(self, should_succeed: bool = True):
        self.should_succeed = should_succeed
        self.published_promotions = []

    async def publish(self, promotion: Promotion, formatted_message: str) -> PublicationResult:
        self.published_promotions.append((promotion, formatted_message))
        if self.should_succeed:
            return PublicationResult(
                success=True,
                platform="mock_telegram",
                target_chat_id="@test_channel",
                target_message_id="9999",
            )
        return PublicationResult(
            success=False,
            platform="mock_telegram",
            target_chat_id="@test_channel",
            error_message="Simulated publication error"
        )


@pytest.fixture
def mock_publisher():
    return MockPublisher(should_succeed=True)
