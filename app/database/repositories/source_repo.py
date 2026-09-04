from typing import List, Optional
from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession
from app.database.models import SourceModel


class SourceRepository:
    def __init__(self, session: AsyncSession):
        self.session = session

    async def get_or_create(
        self,
        chat_id: str,
        platform: str = "telegram",
        name: Optional[str] = None
    ) -> SourceModel:
        stmt = select(SourceModel).where(
            SourceModel.chat_id == chat_id,
            SourceModel.platform == platform
        )
        result = await self.session.execute(stmt)
        source = result.scalar_one_or_none()
        if not source:
            source = SourceModel(
                chat_id=chat_id,
                platform=platform,
                name=name or chat_id,
                is_active=True
            )
            self.session.add(source)
            await self.session.flush()
        return source

    async def list_sources(
        self,
        active_only: bool = False,
        limit: int = 50,
        offset: int = 0
    ) -> List[SourceModel]:
        stmt = select(SourceModel).order_by(SourceModel.created_at.desc()).limit(limit).offset(offset)
        if active_only:
            stmt = stmt.where(SourceModel.is_active == True)
        result = await self.session.execute(stmt)
        return list(result.scalars().all())

    async def count_sources(self, active_only: bool = False) -> int:
        stmt = select(func.count(SourceModel.id))
        if active_only:
            stmt = stmt.where(SourceModel.is_active == True)
        result = await self.session.execute(stmt)
        return result.scalar_one()
