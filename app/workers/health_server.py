"""Shared health server for background workers (Worker, TelegramListener)."""
import logging
from aiohttp import web
from app.config.settings import get_settings
import redis.asyncio as redis

logger = logging.getLogger(__name__)


async def _get_health_data(service_name: str) -> dict:
    """Collect health data for a worker service."""
    settings = get_settings()
    queue_lag = 0
    redis_status = "ok"
    last_processed = None

    try:
        r = redis.from_url(settings.REDIS_URL)
        await r.ping()
        queue_lag = await r.llen(settings.REDIS_QUEUE_NAME)
        # Try to get last processed timestamp from Redis
        raw_last_processed = await r.get(f"promobot:last_processed:{service_name}")
        last_processed = raw_last_processed.decode("utf-8") if raw_last_processed else None
        await r.aclose()
    except Exception as e:
        logger.error(f"[HEALTH:{service_name}] Redis check failed: {e}")
        redis_status = f"unhealthy: {str(e)}"
    else:
        redis_status = "ok"

    return {
        "status": "healthy" if redis_status == "ok" else "degraded",
        "service": service_name,
        "redis": redis_status,
        "queue_lag": queue_lag,
        "last_processed_at": last_processed,
    }


async def health_handler(service_name: str, request: web.Request) -> web.Response:
    """Health check endpoint handler."""
    data = await _get_health_data(service_name)
    status_code = 200 if data["status"] == "healthy" else 503
    return web.json_response(data, status=status_code)


def create_health_app(service_name: str) -> web.Application:
    """Create aiohttp app with health endpoint."""
    app = web.Application()
    app.router.add_get("/health", lambda req: health_handler(service_name, req))
    app.router.add_get("/live", lambda req: web.json_response({"status": "alive", "service": service_name}))
    return app


async def run_health_server(service_name: str, port: int = 8081):
    """Run health check HTTP server."""
    app = create_health_app(service_name)
    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, "0.0.0.0", port)
    await site.start()
    logger.info(f"[HEALTH:{service_name}] Health server listening on port {port}")
    return runner