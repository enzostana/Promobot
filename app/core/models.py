from datetime import datetime, timezone
from enum import Enum
from typing import List, Optional
from pydantic import BaseModel, Field


class PromotionStatus(str, Enum):
    PENDING = "pending"
    PARSED = "parsed"
    FILTERED_OUT = "filtered_out"
    DUPLICATE = "duplicate"
    PUBLISHED = "published"
    FAILED = "failed"


class RawMessage(BaseModel):
    id: str
    source: str = "telegram"
    source_message_id: str
    source_chat_id: str
    source_chat_title: Optional[str] = None
    text: str = ""
    media_path: Optional[str] = None
    media_url: Optional[str] = None
    urls: List[str] = Field(default_factory=list)
    attempts: int = 0
    received_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


class ParsedPromotion(BaseModel):
    product_name: str
    description: Optional[str] = None
    original_price: Optional[float] = None
    sale_price: Optional[float] = None
    discount_percentage: Optional[float] = None
    store: Optional[str] = None
    product_id: Optional[str] = None
    original_url: Optional[str] = None
    all_urls: List[str] = Field(default_factory=list)
    category: Optional[str] = None


class Promotion(BaseModel):
    id: Optional[int] = None
    source: str = "telegram"
    source_message_id: str
    source_chat_id: str
    original_text: str
    product_name: str
    description: Optional[str] = None
    original_price: Optional[float] = None
    sale_price: Optional[float] = None
    discount_percentage: Optional[float] = None
    store: Optional[str] = None
    product_id: Optional[str] = None
    original_url: str
    affiliate_url: Optional[str] = None
    image_url: Optional[str] = None
    category: Optional[str] = None
    status: PromotionStatus = PromotionStatus.PENDING
    content_hash: Optional[str] = None
    filter_reason: Optional[str] = None
    error_message: Optional[str] = None
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    published_at: Optional[datetime] = None


class FilterResult(BaseModel):
    passed: bool
    reason: Optional[str] = None


class PublicationResult(BaseModel):
    success: bool
    platform: str
    target_chat_id: str
    target_message_id: Optional[str] = None
    published_at: Optional[datetime] = None
    error_message: Optional[str] = None
