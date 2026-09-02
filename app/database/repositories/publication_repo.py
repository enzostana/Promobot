from datetime import datetime, timezone
from typing import List, Optional
from sqlalchemy import desc, select
from sqlalchemy.ext.asyncio import AsyncSession
from app.database.models import PublicationModel


class PublicationRepository:
    def __init__(self, session: AsyncSession):
        self.session = session

    async def create(
        self,
        promotion_id: int,
        target_chat_id: str,
        formatted_content: str,
        platform: str = "telegram",
        target_message_id: Optional[str] = None,
        status: str = "published",
        error_message: Optional[str] = None
    ) -> PublicationModel:
        pub = PublicationModel(
            promotion_id=promotion_id,
            platform=platform,
            target_chat_id=target_chat_id,
            target_message_id=target_message_id,
            formatted_content=formatted_content,
            status=status,
            error_message=error_message,
            published_at=datetime.now(timezone.utc)
        )
        self.session.add(pub)
        await self.session.flush()
        return pub

    async def list_publications(self, limit: int = 50, offset: int = 0) -> List[PublicationModel]:
        stmt = select(PublicationModel).order_by(desc(PublicationModel.published_at)).limit(limit).offset(offset)
        result = await self.session.execute(stmt)
        return list(result.scalars().all())
