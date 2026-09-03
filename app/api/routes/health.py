import logging
from fastapi import APIRouter, Depends, Response, status
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession
import redis.asyncio as redis

from app.api.deps import get_db
from app.config.settings import get_settings
from app.workers.queue import RedisQueue

router = APIRouter(tags=["Health"])
logger = logging.getLogger(__name__)


async def _check_dependencies(settings) -> tuple[str, str, int]:
    """Check DB and Redis, return (db_status, redis_status, queue_lag)."""
    db_status = "ok"
    redis_status = "ok"
    queue_lag = 0

    # Check PostgreSQL
    try:
        from app.database.session import async_session_maker
        async with async_session_maker() as session:
            await session.execute(text("SELECT 1"))
    except Exception as e:
        logger.error(f"[HEALTH] Database check failed: {e}")
        db_status = f"unhealthy: {str(e)}"

    # Check Redis and queue lag
    try:
        r = redis.from_url(settings.REDIS_URL)
        await r.ping()
        queue_lag = await r.llen(settings.REDIS_QUEUE_NAME)
        await r.aclose()
    except Exception as e:
        logger.error(f"[HEALTH] Redis check failed: {e}")
        redis_status = f"unhealthy: {str(e)}"

    return db_status, redis_status, queue_lag


@router.get("/live")
async def liveness_check():
    """Liveness probe - only checks if process is alive."""
    return {"status": "alive"}


@router.get("/ready")
async def readiness_check(response: Response):
    """Readiness probe - checks DB, Redis, and queue."""
    settings = get_settings()
    db_status, redis_status, queue_lag = await _check_dependencies(settings)

    overall_status = "healthy" if db_status == "ok" and redis_status == "ok" else "degraded"

    if overall_status == "degraded":
        response.status_code = status.HTTP_503_SERVICE_UNAVAILABLE

    return {
        "status": overall_status,
        "database": db_status,
        "redis": redis_status,
        "queue_lag": queue_lag,
        "app_env": settings.APP_ENV,
    }


@router.get("/health")
async def health_check(db: AsyncSession = Depends(get_db)):
    """Full health check (legacy endpoint)."""
    settings = get_settings()
    db_status, redis_status, queue_lag = await _check_dependencies(settings)

    overall_status = "healthy" if db_status == "ok" and redis_status == "ok" else "degraded"

    return {
        "status": overall_status,
        "database": db_status,
        "redis": redis_status,
        "queue_lag": queue_lag,
        "app_env": settings.APP_ENV,
    }
