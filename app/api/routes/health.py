import logging
from fastapi import APIRouter, Depends
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession
import redis.asyncio as redis

from app.api.deps import get_db
from app.config.settings import get_settings

router = APIRouter(tags=["Health"])
logger = logging.getLogger(__name__)


@router.get("/health")
async def health_check(db: AsyncSession = Depends(get_db)):
    settings = get_settings()
    db_status = "ok"
    redis_status = "ok"

    # 1. Check PostgreSQL
    try:
        await db.execute(text("SELECT 1"))
    except Exception as e:
        logger.error(f"[HEALTH] Database check failed: {e}")
        db_status = f"unhealthy: {str(e)}"

    # 2. Check Redis
    try:
        r = redis.from_url(settings.REDIS_URL)
        await r.ping()
        await r.aclose()
    except Exception as e:
        logger.error(f"[HEALTH] Redis check failed: {e}")
        redis_status = f"unhealthy: {str(e)}"

    overall_status = "healthy" if db_status == "ok" and redis_status == "ok" else "degraded"

    return {
        "status": overall_status,
        "database": db_status,
        "redis": redis_status,
        "app_env": settings.APP_ENV,
    }
