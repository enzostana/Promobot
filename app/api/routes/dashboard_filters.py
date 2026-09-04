from typing import List
from fastapi import APIRouter, Depends
from sqlalchemy import select, distinct
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_db
from app.database.models import PromotionModel, SourceModel, PublicationModel

router = APIRouter(prefix="/dashboard/filters", tags=["Dashboard Filters"])


@router.get("/stores", response_model=List[str])
async def get_stores(db: AsyncSession = Depends(get_db)):
    result = await db.execute(
        select(distinct(PromotionModel.store))
        .where(PromotionModel.store.is_not(None))
        .order_by(PromotionModel.store)
    )
    return [row for row in result.scalars().all() if row]


@router.get("/statuses", response_model=List[str])
async def get_statuses(db: AsyncSession = Depends(get_db)):
    result = await db.execute(
        select(distinct(PromotionModel.status))
        .order_by(PromotionModel.status)
    )
    return list(result.scalars().all())


@router.get("/categories", response_model=List[str])
async def get_categories(db: AsyncSession = Depends(get_db)):
    result = await db.execute(
        select(distinct(PromotionModel.category))
        .where(PromotionModel.category.is_not(None))
        .order_by(PromotionModel.category)
    )
    return [row for row in result.scalars().all() if row]


@router.get("/platforms", response_model=List[str])
async def get_platforms(db: AsyncSession = Depends(get_db)):
    promo_result = await db.execute(
        select(distinct(PromotionModel.source))
        .where(PromotionModel.source.is_not(None))
    )
    source_result = await db.execute(
        select(distinct(SourceModel.platform))
        .where(SourceModel.platform.is_not(None))
    )
    pub_result = await db.execute(
        select(distinct(PublicationModel.platform))
        .where(PublicationModel.platform.is_not(None))
    )
    all_platforms = set(promo_result.scalars().all())
    all_platforms.update(source_result.scalars().all())
    all_platforms.update(pub_result.scalars().all())
    return sorted([p for p in all_platforms if p])