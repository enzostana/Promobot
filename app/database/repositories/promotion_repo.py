from datetime import datetime, timedelta, timezone
from typing import List, Optional
from sqlalchemy import desc, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload
from app.database.models import PromotionModel, PromotionSourceModel
from app.core.models import Promotion, PromotionStatus


class PromotionRepository:
    def __init__(self, session: AsyncSession):
        self.session = session

    async def create(self, promo: Promotion) -> PromotionModel:
        model = PromotionModel(
            source=promo.source,
            source_message_id=promo.source_message_id,
            source_chat_id=promo.source_chat_id,
            original_text=promo.original_text,
            product_name=promo.product_name,
            description=promo.description,
            original_price=promo.original_price,
            sale_price=promo.sale_price,
            discount_percentage=promo.discount_percentage,
            store=promo.store,
            product_id=promo.product_id,
            original_url=promo.original_url,
            affiliate_url=promo.affiliate_url,
            image_url=promo.image_url,
            category=promo.category,
            status=promo.status.value,
            content_hash=promo.content_hash,
            filter_reason=promo.filter_reason,
            error_message=promo.error_message,
            created_at=promo.created_at,
            published_at=promo.published_at,
        )
        self.session.add(model)
        await self.session.flush()

        # Add initial source reference
        if promo.source_chat_id and promo.source_message_id:
            src = PromotionSourceModel(
                promotion_id=model.id,
                source_chat_id=promo.source_chat_id,
                source_message_id=promo.source_message_id,
                captured_at=datetime.now(timezone.utc)
            )
            self.session.add(src)
            await self.session.flush()

        return model

    async def get_by_id(self, promotion_id: int) -> Optional[PromotionModel]:
        stmt = (
            select(PromotionModel)
            .options(
                selectinload(PromotionModel.sources),
                selectinload(PromotionModel.publications)
            )
            .where(PromotionModel.id == promotion_id)
        )
        result = await self.session.execute(stmt)
        return result.scalar_one_or_none()

    async def list_promotions(
        self,
        limit: int = 50,
        offset: int = 0,
        status: Optional[str] = None,
        store: Optional[str] = None
    ) -> List[PromotionModel]:
        stmt = select(PromotionModel).order_by(desc(PromotionModel.created_at)).limit(limit).offset(offset)
        if status:
            stmt = stmt.where(PromotionModel.status == status)
        if store:
            stmt = stmt.where(PromotionModel.store == store)
        result = await self.session.execute(stmt)
        return list(result.scalars().all())

    async def update_status(
        self,
        promotion_id: int,
        status: PromotionStatus,
        error_message: Optional[str] = None,
        filter_reason: Optional[str] = None,
        published_at: Optional[datetime] = None
    ) -> Optional[PromotionModel]:
        promo = await self.get_by_id(promotion_id)
        if not promo:
            return None
        promo.status = status.value
        if error_message:
            promo.error_message = error_message
        if filter_reason:
            promo.filter_reason = filter_reason
        if published_at:
            promo.published_at = published_at
        await self.session.flush()
        return promo

    async def find_duplicate(
        self,
        store: Optional[str],
        product_id: Optional[str],
        normalized_url: str,
        content_hash: Optional[str],
        hours_window: int = 24
    ) -> Optional[PromotionModel]:
        since = datetime.now(timezone.utc) - timedelta(hours=hours_window)

        # 1. Match by store and product_id
        if store and product_id:
            stmt = (
                select(PromotionModel)
                .where(
                    PromotionModel.store == store,
                    PromotionModel.product_id == product_id,
                    PromotionModel.created_at >= since
                )
                .order_by(desc(PromotionModel.created_at))
            )
            res = await self.session.execute(stmt)
            match = res.scalars().first()
            if match:
                return match

        # 2. Match by content hash
        if content_hash:
            stmt = (
                select(PromotionModel)
                .where(
                    PromotionModel.content_hash == content_hash,
                    PromotionModel.created_at >= since
                )
                .order_by(desc(PromotionModel.created_at))
            )
            res = await self.session.execute(stmt)
            match = res.scalars().first()
            if match:
                return match

        # 3. Match by original URL
        if normalized_url:
            stmt = (
                select(PromotionModel)
                .where(
                    PromotionModel.original_url == normalized_url,
                    PromotionModel.created_at >= since
                )
                .order_by(desc(PromotionModel.created_at))
            )
            res = await self.session.execute(stmt)
            match = res.scalars().first()
            if match:
                return match

        return None

    async def add_source_reference(
        self,
        promotion_id: int,
        source_chat_id: str,
        source_message_id: str
    ) -> PromotionSourceModel:
        src = PromotionSourceModel(
            promotion_id=promotion_id,
            source_chat_id=source_chat_id,
            source_message_id=source_message_id,
            captured_at=datetime.now(timezone.utc)
        )
        self.session.add(src)
        await self.session.flush()
        return src
