from app.api.routes.health import router as health_router
from app.api.routes.promotions import router as promotions_router
from app.api.routes.sources import router as sources_router
from app.api.routes.publications import router as publications_router

__all__ = [
    "health_router",
    "promotions_router",
    "sources_router",
    "publications_router",
]
