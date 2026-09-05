from typing import Dict, Optional
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from app.database.models import SettingModel


class SettingRepository:
    def __init__(self, session: AsyncSession):
        self.session = session

    async def get_all(self) -> Dict[str, str]:
        result = await self.session.execute(select(SettingModel))
        return {row.key: row.value for row in result.scalars().all()}

    async def get(self, key: str) -> Optional[str]:
        stmt = select(SettingModel).where(SettingModel.key == key)
        result = await self.session.execute(stmt)
        row = result.scalar_one_or_none()
        return row.value if row else None

    async def upsert(self, key: str, value: str) -> None:
        stmt = select(SettingModel).where(SettingModel.key == key)
        result = await self.session.execute(stmt)
        row = result.scalar_one_or_none()
        if row:
            row.value = value
        else:
            self.session.add(SettingModel(key=key, value=value))
        await self.session.flush()