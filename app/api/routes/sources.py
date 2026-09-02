from typing import List, Optional
from fastapi import APIRouter, Depends
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


@router.get("", response_model=List[SourceOut])
async def list_sources(
    active_only: bool = False,
    db: AsyncSession = Depends(get_db),
):
    repo = SourceRepository(db)
    return await repo.list_sources(active_only=active_only)
