from typing import List, Optional
from fastapi import APIRouter, Depends, HTTPException, Query
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


@router.get("", response_model=List[PromotionOut])
async def list_promotions(
    limit: int = Query(50, ge=1, le=100),
    offset: int = Query(0, ge=0),
    status: Optional[str] = Query(None, description="Filtrar por status (e.g. published, duplicate, filtered_out)"),
    store: Optional[str] = Query(None, description="Filtrar por loja (e.g. amazon, mercadolivre)"),
    db: AsyncSession = Depends(get_db),
):
    repo = PromotionRepository(db)
    models = await repo.list_promotions(limit=limit, offset=offset, status=status, store=store)
    return models


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
