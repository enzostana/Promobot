from datetime import datetime, timezone
from typing import List, Optional
from sqlalchemy import (
    Boolean, Column, DateTime, ForeignKey, Integer, Numeric, String, Text
)
from sqlalchemy.orm import DeclarativeBase, relationship


class Base(DeclarativeBase):
    pass


class SourceModel(Base):
    __tablename__ = "sources"

    id = Column(Integer, primary_key=True, autoincrement=True)
    platform = Column(String(50), default="telegram", nullable=False)
    chat_id = Column(String(100), index=True, nullable=False)
    name = Column(String(255), nullable=True)
    is_active = Column(Boolean, default=True, nullable=False)
    created_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), nullable=False)


class PromotionModel(Base):
    __tablename__ = "promotions"

    id = Column(Integer, primary_key=True, autoincrement=True)
    source = Column(String(50), default="telegram", nullable=False)
    source_message_id = Column(String(100), nullable=True)
    source_chat_id = Column(String(100), index=True, nullable=True)
    original_text = Column(Text, nullable=False)
    product_name = Column(String(500), nullable=False)
    description = Column(Text, nullable=True)
    original_price = Column(Numeric(10, 2), nullable=True)
    sale_price = Column(Numeric(10, 2), nullable=True)
    discount_percentage = Column(Numeric(5, 2), nullable=True)
    store = Column(String(100), index=True, nullable=True)
    product_id = Column(String(100), index=True, nullable=True)
    original_url = Column(Text, nullable=False)
    affiliate_url = Column(Text, nullable=True)
    image_url = Column(Text, nullable=True)
    category = Column(String(100), index=True, nullable=True)
    status = Column(String(50), default="pending", index=True, nullable=False)
    content_hash = Column(String(64), index=True, nullable=True)
    filter_reason = Column(Text, nullable=True)
    error_message = Column(Text, nullable=True)
    created_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), index=True, nullable=False)
    published_at = Column(DateTime(timezone=True), nullable=True)

    sources = relationship("PromotionSourceModel", back_populates="promotion", cascade="all, delete-orphan")
    publications = relationship("PublicationModel", back_populates="promotion", cascade="all, delete-orphan")


class PromotionSourceModel(Base):
    """
    Tracks multiple captured sources for the same promotion.
    """
    __tablename__ = "promotion_sources"

    id = Column(Integer, primary_key=True, autoincrement=True)
    promotion_id = Column(Integer, ForeignKey("promotions.id", ondelete="CASCADE"), nullable=False, index=True)
    source_chat_id = Column(String(100), nullable=False)
    source_message_id = Column(String(100), nullable=False)
    captured_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), nullable=False)

    promotion = relationship("PromotionModel", back_populates="sources")


class AffiliateLinkModel(Base):
    __tablename__ = "affiliate_links"

    id = Column(Integer, primary_key=True, autoincrement=True)
    promotion_id = Column(Integer, ForeignKey("promotions.id", ondelete="SET NULL"), nullable=True)
    store = Column(String(100), nullable=False)
    original_url = Column(Text, nullable=False)
    affiliate_url = Column(Text, nullable=False)
    created_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), nullable=False)


class PublicationModel(Base):
    __tablename__ = "publications"

    id = Column(Integer, primary_key=True, autoincrement=True)
    promotion_id = Column(Integer, ForeignKey("promotions.id", ondelete="CASCADE"), nullable=False, index=True)
    platform = Column(String(50), default="telegram", nullable=False)
    target_chat_id = Column(String(100), nullable=False)
    target_message_id = Column(String(100), nullable=True)
    formatted_content = Column(Text, nullable=False)
    status = Column(String(50), default="published", nullable=False)
    error_message = Column(Text, nullable=True)
    published_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), nullable=False)

    promotion = relationship("PromotionModel", back_populates="publications")


class FilterModel(Base):
    __tablename__ = "filters"

    id = Column(Integer, primary_key=True, autoincrement=True)
    rule_name = Column(String(100), unique=True, nullable=False)
    rule_type = Column(String(50), nullable=False)
    value = Column(String(255), nullable=False)
    is_active = Column(Boolean, default=True, nullable=False)
    created_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), nullable=False)


class SettingModel(Base):
    __tablename__ = "settings"

    id = Column(Integer, primary_key=True, autoincrement=True)
    key = Column(String(100), unique=True, index=True, nullable=False)
    value = Column(Text, nullable=False)
    description = Column(Text, nullable=True)
    updated_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), nullable=False)
