from typing import List, Optional
from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession
from pydantic import BaseModel, ConfigDict
from datetime import datetime

from app.api.deps import get_db
from app.database.repositories.publication_repo import PublicationRepository

router = APIRouter(prefix="/publications", tags=["Publications"])


class PublicationOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    promotion_id: int
    platform: str
    target_chat_id: str
    target_message_id: Optional[str] = None
    formatted_content: str
    status: str
    error_message: Optional[str] = None
    published_at: datetime


@router.get("", response_model=List[PublicationOut])
async def list_publications(
    limit: int = Query(50, ge=1, le=100),
    offset: int = Query(0, ge=0),
    db: AsyncSession = Depends(get_db),
):
    repo = PublicationRepository(db)
    return await repo.list_publications(limit=limit, offset=offset)
