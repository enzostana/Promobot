from contextlib import asynccontextmanager
import logging
import uuid
from fastapi import FastAPI, Request, Response
from fastapi.middleware.cors import CORSMiddleware

from app.config.settings import get_settings
from app.database.session import init_db
from app.api.routes.health import router as health_router
from app.api.routes.promotions import router as promotions_router
from app.api.routes.sources import router as sources_router
from app.api.routes.publications import router as publications_router
from app.api.routes.dashboard import router as dashboard_router
from app.logging_config import setup_logging, get_logger, set_correlation_id, correlation_id_var

logger = get_logger("promobot")


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Startup actions
    settings = get_settings()
    setup_logging(settings.LOG_LEVEL, json_format=settings.APP_ENV == "production")
    logger.info("Iniciando PromoBot API...")
    try:
        await init_db()
        logger.info("Tabelas do banco de dados verificadas/inicializadas com sucesso.")
    except Exception as e:
        logger.warning(f"Aviso ao inicializar tabelas na inicialização: {e}")

    yield

    # Shutdown actions
    logger.info("Encerrando PromoBot API...")


async def correlation_id_middleware(request: Request, call_next):
    """Add correlation ID to request and response headers."""
    correlation_id = request.headers.get("X-Request-ID", uuid.uuid4().hex[:8])
    request.state.correlation_id = correlation_id
    token = set_correlation_id(correlation_id)
    try:
        response = await call_next(request)
    finally:
        correlation_id_var.reset(token)
    response.headers["X-Request-ID"] = correlation_id
    return response


def create_app() -> FastAPI:
    settings = get_settings()
    app = FastAPI(
        title="PromoBot API",
        description="API do Agregador e Distribuidor de Promoções",
        version="1.0.0",
        lifespan=lifespan,
        docs_url="/docs",
        redoc_url="/redoc"
    )

    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    # Add correlation ID middleware
    app.middleware("http")(correlation_id_middleware)

    app.include_router(health_router)
    app.include_router(promotions_router)
    app.include_router(sources_router)
    app.include_router(publications_router)
    app.include_router(dashboard_router)

    return app


app = create_app()


if __name__ == "__main__":
    import uvicorn
    uvicorn.run("app.main:app", host="0.0.0.0", port=8000, reload=True)
