from typing import List, Optional
from fastapi import APIRouter, Depends, HTTPException, Query, Response
from sqlalchemy.ext.asyncio import AsyncSession
from pydantic import BaseModel, ConfigDict
from datetime import datetime

from app.api.deps import get_db
from app.database.repositories.promotion_repo import PromotionRepository

router = APIRouter(prefix="/promotions", tags=["Promotions"])


class PromotionSourceOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    source_chat_id: str
    source_message_id: str
    captured_at: datetime


class PublicationOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    platform: str
    target_chat_id: str
    target_message_id: Optional[str] = None
    status: str
    published_at: datetime


class PromotionOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    source: str
    source_message_id: Optional[str] = None
    source_chat_id: Optional[str] = None
    product_name: str
    original_price: Optional[float] = None
    sale_price: Optional[float] = None
    discount_percentage: Optional[float] = None
    store: Optional[str] = None
    original_url: str
    affiliate_url: Optional[str] = None
    image_url: Optional[str] = None
    category: Optional[str] = None
    status: str
    created_at: datetime
    published_at: Optional[datetime] = None


class PromotionDetailOut(PromotionOut):
    sources: List[PromotionSourceOut] = []
    publications: List[PublicationOut] = []


class PaginatedPromotionOut(BaseModel):
    items: List[PromotionOut]
    total: int
    page: int
    page_size: int
    total_pages: int


@router.get("", response_model=PaginatedPromotionOut)
async def list_promotions(
    response: Response,
    page: int = Query(1, ge=1, description="Número da página"),
    page_size: int = Query(20, ge=1, le=100, description="Itens por página"),
    status: Optional[str] = Query(None, description="Filtrar por status"),
    store: Optional[str] = Query(None, description="Filtrar por loja"),
    category: Optional[str] = Query(None, description="Filtrar por categoria"),
    created_at__gte: Optional[datetime] = Query(None, description="Data inicial (ISO 8601)"),
    created_at__lte: Optional[datetime] = Query(None, description="Data final (ISO 8601)"),
    db: AsyncSession = Depends(get_db),
):
    repo = PromotionRepository(db)
    offset = (page - 1) * page_size
    
    models = await repo.list_promotions(
        limit=page_size,
        offset=offset,
        status=status,
        store=store,
        category=category,
        created_at__gte=created_at__gte,
        created_at__lte=created_at__lte
    )
    
    total = await repo.count_promotions(
        status=status,
        store=store,
        category=category,
        created_at__gte=created_at__gte,
        created_at__lte=created_at__lte
    )
    
    total_pages = (total + page_size - 1) // page_size
    
    response.headers["X-Total-Count"] = str(total)
    response.headers["X-Total-Pages"] = str(total_pages)
    response.headers["X-Current-Page"] = str(page)
    
    return PaginatedPromotionOut(
        items=models,
        total=total,
        page=page,
        page_size=page_size,
        total_pages=total_pages
    )


@router.get("/{promotion_id}", response_model=PromotionDetailOut)
async def get_promotion(
    promotion_id: int,
    db: AsyncSession = Depends(get_db),
):
    repo = PromotionRepository(db)
    promo = await repo.get_by_id(promotion_id)
    if not promo:
        raise HTTPException(status_code=404, detail="Promoção não encontrada")
    return promo