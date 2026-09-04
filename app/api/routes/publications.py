from typing import List, Optional
from fastapi import APIRouter, Depends, Query, Response
from sqlalchemy.ext.asyncio import AsyncSession
from pydantic import BaseModel, ConfigDict
from datetime import datetime

from app.api.deps import get_db
from app.database.repositories.publication_repo import PublicationRepository

router = APIRouter(prefix="/publications", tags=["Publications"])


class PublicationOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    promotion_id: int
    platform: str
    target_chat_id: str
    target_message_id: Optional[str] = None
    formatted_content: str
    status: str
    error_message: Optional[str] = None
    published_at: datetime


class PaginatedPublicationOut(BaseModel):
    items: List[PublicationOut]
    total: int
    page: int
    page_size: int
    total_pages: int


@router.get("", response_model=PaginatedPublicationOut)
async def list_publications(
    response: Response,
    page: int = Query(1, ge=1, description="Número da página"),
    page_size: int = Query(20, ge=1, le=100, description="Itens por página"),
    platform: Optional[str] = Query(None, description="Filtrar por plataforma"),
    status: Optional[str] = Query(None, description="Filtrar por status"),
    db: AsyncSession = Depends(get_db),
):
    repo = PublicationRepository(db)
    offset = (page - 1) * page_size
    
    models = await repo.list_publications(
        limit=page_size,
        offset=offset,
        platform=platform,
        status=status
    )
    total = await repo.count_publications(platform=platform, status=status)
    
    total_pages = (total + page_size - 1) // page_size
    
    response.headers["X-Total-Count"] = str(total)
    response.headers["X-Total-Pages"] = str(total_pages)
    response.headers["X-Current-Page"] = str(page)
    
    return PaginatedPublicationOut(
        items=models,
        total=total,
        page=page,
        page_size=page_size,
        total_pages=total_pages
    )