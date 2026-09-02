from contextlib import asynccontextmanager
import logging
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.config.settings import get_settings
from app.database.session import init_db
from app.api.routes.health import router as health_router
from app.api.routes.promotions import router as promotions_router
from app.api.routes.sources import router as sources_router
from app.api.routes.publications import router as publications_router

logger = logging.getLogger("promobot")


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Startup actions
    settings = get_settings()
    logging.basicConfig(
        level=getattr(logging, settings.LOG_LEVEL.upper(), logging.INFO),
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s"
    )
    logger.info("Iniciando PromoBot API...")
    try:
        await init_db()
        logger.info("Tabelas do banco de dados verificadas/inicializadas com sucesso.")
    except Exception as e:
        logger.warning(f"Aviso ao inicializar tabelas na inicialização: {e}")

    yield

    # Shutdown actions
    logger.info("Encerrando PromoBot API...")


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

    app.include_router(health_router)
    app.include_router(promotions_router)
    app.include_router(sources_router)
    app.include_router(publications_router)

    return app


app = create_app()

if __name__ == "__main__":
    import uvicorn
    uvicorn.run("app.main:app", host="0.0.0.0", port=8000, reload=True)
