from datetime import datetime, timezone
from typing import List, Optional
from sqlalchemy import desc, select
from sqlalchemy.ext.asyncio import AsyncSession
from app.database.models import AffiliateLinkModel


class AffiliateLinkRepository:
    def __init__(self, session: AsyncSession):
        self.session = session

    async def create(
        self,
        store: str,
        original_url: str,
        affiliate_url: str,
        promotion_id: Optional[int] = None
    ) -> AffiliateLinkModel:
        link = AffiliateLinkModel(
            promotion_id=promotion_id,
            store=store,
            original_url=original_url,
            affiliate_url=affiliate_url,
            created_at=datetime.now(timezone.utc)
        )
        self.session.add(link)
        await self.session.flush()
        return link

    async def list_by_promotion(self, promotion_id: int) -> List[AffiliateLinkModel]:
        stmt = (
            select(AffiliateLinkModel)
            .where(AffiliateLinkModel.promotion_id == promotion_id)
            .order_by(desc(AffiliateLinkModel.created_at))
        )
        result = await self.session.execute(stmt)
        return list(result.scalars().all())

    async def list_links(self, limit: int = 50, offset: int = 0) -> List[AffiliateLinkModel]:
        stmt = (
            select(AffiliateLinkModel)
            .order_by(desc(AffiliateLinkModel.created_at))
            .limit(limit)
            .offset(offset)
        )
        result = await self.session.execute(stmt)
        return list(result.scalars().all())

    async def find_by_original_url(self, original_url: str) -> Optional[AffiliateLinkModel]:
        stmt = select(AffiliateLinkModel).where(AffiliateLinkModel.original_url == original_url)
        result = await self.session.execute(stmt)
        return result.scalar_one_or_none()
