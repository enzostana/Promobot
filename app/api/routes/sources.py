from typing import List, Optional
from fastapi import APIRouter, Depends, Query, Response
from sqlalchemy.ext.asyncio import AsyncSession
from pydantic import BaseModel, ConfigDict
from datetime import datetime

from app.api.deps import get_db
from app.database.repositories.source_repo import SourceRepository

router = APIRouter(prefix="/sources", tags=["Sources"])


class SourceOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    platform: str
    chat_id: str
    name: Optional[str] = None
    is_active: bool
    created_at: datetime


class PaginatedSourceOut(BaseModel):
    items: List[SourceOut]
    total: int
    page: int
    page_size: int
    total_pages: int


@router.get("", response_model=PaginatedSourceOut)
async def list_sources(
    response: Response,
    page: int = Query(1, ge=1, description="Número da página"),
    page_size: int = Query(20, ge=1, le=100, description="Itens por página"),
    active_only: bool = Query(False, description="Apenas fontes ativas"),
    db: AsyncSession = Depends(get_db),
):
    repo = SourceRepository(db)
    offset = (page - 1) * page_size
    
    models = await repo.list_sources(active_only=active_only, limit=page_size, offset=offset)
    total = await repo.count_sources(active_only=active_only)
    
    total_pages = (total + page_size - 1) // page_size
    
    response.headers["X-Total-Count"] = str(total)
    response.headers["X-Total-Pages"] = str(total_pages)
    response.headers["X-Current-Page"] = str(page)
    
    return PaginatedSourceOut(
        items=models,
        total=total,
        page=page,
        page_size=page_size,
        total_pages=total_pages
    )