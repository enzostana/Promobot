import logging
from datetime import datetime, timezone
from typing import Optional
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.models import (
    Promotion,
    PromotionStatus,
    RawMessage,
)
from app.core.parser import PromotionParser
from app.affiliates.registry import AffiliateRegistry
from app.core.deduplicator import Deduplicator
from app.core.filters import PromotionFilter
from app.core.formatter import PromotionFormatter
from app.core.publisher import Publisher
from app.database.models import AffiliateLinkModel
from app.database.repositories.promotion_repo import PromotionRepository
from app.database.repositories.source_repo import SourceRepository
from app.database.repositories.publication_repo import PublicationRepository
from app.config.settings import Settings, get_settings

logger = logging.getLogger(__name__)


class PromotionProcessor:
    """
    Core orchestrator for the promotion ingestion and distribution pipeline.
    Ensures clear separation of responsibilities and structured logging:
    [TELEGRAM] -> [PARSER] -> [AFFILIATE] -> [DEDUP] -> [FILTER] -> [PUBLISHER]
    """

    def __init__(
        self,
        parser: Optional[PromotionParser] = None,
        affiliate_registry: Optional[AffiliateRegistry] = None,
        deduplicator: Optional[Deduplicator] = None,
        promotion_filter: Optional[PromotionFilter] = None,
        formatter: Optional[PromotionFormatter] = None,
        publisher: Optional[Publisher] = None,
        settings: Optional[Settings] = None,
    ):
        self.settings = settings or get_settings()
        self.parser = parser or PromotionParser()
        self.affiliates = affiliate_registry or AffiliateRegistry(self.settings)
        self.deduplicator = deduplicator or Deduplicator(settings=self.settings)
        self.filters = promotion_filter or PromotionFilter(self.settings)
        self.formatter = formatter or PromotionFormatter()
        self.publisher = publisher

    async def process(self, raw_msg: RawMessage, db_session: Optional[AsyncSession] = None) -> Optional[Promotion]:
        """
        Executes the full pipeline for a single raw message.
        Guarantees that an error in any single promotion will not crash the worker.
        """
        promo_repo = PromotionRepository(db_session) if db_session else None
        source_repo = SourceRepository(db_session) if db_session else None
        pub_repo = PublicationRepository(db_session) if db_session else None

        try:
            # 1. Register or get source
            if source_repo and raw_msg.source_chat_id:
                try:
                    await source_repo.get_or_create(
                        chat_id=raw_msg.source_chat_id,
                        platform=raw_msg.source,
                        name=raw_msg.source_chat_title
                    )
                except Exception as e:
                    logger.warning(f"[SOURCE] Erro ao registrar fonte {raw_msg.source_chat_id}: {e}")

            # 2. Parse raw message
            parsed = self.parser.parse(raw_msg)
            if not parsed.original_url:
                logger.info(f"[PARSER] Mensagem descartada: nenhum link válido encontrado na msg {raw_msg.source_message_id}")
                return None

            logger.info(
                f"[PARSER] promoção identificada: '{parsed.product_name}' - "
                f"Por: R$ {parsed.sale_price if parsed.sale_price else 'N/A'} "
                f"(Loja: {parsed.store or 'desconhecida'})"
            )

            # 3. Convert affiliate link
            affiliate_url, store_name, product_id = self.affiliates.convert(parsed.original_url)
            effective_store = store_name or parsed.store
            effective_product_id = product_id or parsed.product_id

            logger.info(f"[AFFILIATE] link convertido: {parsed.original_url} -> {affiliate_url}")

            # Build preliminary Promotion domain object
            normalized_url = self.deduplicator.normalize_url(parsed.original_url)
            content_hash = self.deduplicator.compute_content_hash(
                effective_store,
                effective_product_id,
                normalized_url,
                parsed.product_name,
                parsed.sale_price
            )

            promo = Promotion(
                source=raw_msg.source,
                source_message_id=raw_msg.source_message_id,
                source_chat_id=raw_msg.source_chat_id,
                original_text=raw_msg.text,
                product_name=parsed.product_name,
                description=parsed.description,
                original_price=parsed.original_price,
                sale_price=parsed.sale_price,
                discount_percentage=parsed.discount_percentage,
                store=effective_store,
                product_id=effective_product_id,
                original_url=parsed.original_url,
                affiliate_url=affiliate_url,
                image_url=raw_msg.media_path or raw_msg.media_url,
                category=parsed.category,
                status=PromotionStatus.PENDING,
                content_hash=content_hash,
                created_at=datetime.now(timezone.utc),
            )

            # 4. Deduplication check
            is_dup, existing_id = await self.deduplicator.is_duplicate(promo, db_repo=promo_repo)
            if is_dup:
                logger.info(f"[DEDUP] promoção duplicada detectada (id existente: {existing_id})")
                promo.status = PromotionStatus.DUPLICATE
                if promo_repo and existing_id:
                    # Register this source as another source capturing the deal
                    await promo_repo.add_source_reference(
                        promotion_id=existing_id,
                        source_chat_id=raw_msg.source_chat_id,
                        source_message_id=raw_msg.source_message_id
                    )
                return promo

            logger.info(f"[DEDUP] promoção nova: hash={content_hash[:12]}...")

            # 5. Apply filters
            filter_result = self.filters.evaluate(promo)
            if not filter_result.passed:
                logger.info(f"[FILTER] promoção rejeitada: {filter_result.reason}")
                promo.status = PromotionStatus.FILTERED_OUT
                promo.filter_reason = filter_result.reason
                if promo_repo:
                    saved_model = await promo_repo.create(promo)
                    promo.id = saved_model.id
                return promo

            logger.info(f"[FILTER] promoção aprovada (desconto: {promo.discount_percentage or 0}%)")

            # 6. Formatting
            formatted_message = self.formatter.format(promo)

            # 7. Publication
            pub_result = None
            if self.publisher:
                pub_result = await self.publisher.publish(promo, formatted_message)
                if pub_result.success:
                    promo.status = PromotionStatus.PUBLISHED
                    promo.published_at = pub_result.published_at or datetime.now(timezone.utc)
                else:
                    promo.status = PromotionStatus.FAILED
                    promo.error_message = pub_result.error_message
            else:
                # If no publisher injected (e.g. testing), mark published
                promo.status = PromotionStatus.PUBLISHED
                promo.published_at = datetime.now(timezone.utc)

            # 8. Save promotion and metadata to PostgreSQL
            if promo_repo:
                saved_model = await promo_repo.create(promo)
                promo.id = saved_model.id

                # Save affiliate link record
                if promo.affiliate_url and db_session:
                    aff_link = AffiliateLinkModel(
                        promotion_id=promo.id,
                        store=promo.store or "unknown",
                        original_url=promo.original_url,
                        affiliate_url=promo.affiliate_url,
                        created_at=datetime.now(timezone.utc)
                    )
                    db_session.add(aff_link)
                    await db_session.flush()

                # Save publication log
                if pub_repo and pub_result:
                    await pub_repo.create(
                        promotion_id=promo.id,
                        platform=pub_result.platform,
                        target_chat_id=pub_result.target_chat_id,
                        target_message_id=pub_result.target_message_id,
                        formatted_content=formatted_message,
                        status="published" if pub_result.success else "failed",
                        error_message=pub_result.error_message
                    )

            # 9. Record in deduplication cache
            if promo.id and promo.status == PromotionStatus.PUBLISHED:
                await self.deduplicator.record_seen(
                    promotion_id=promo.id,
                    promotion=promo,
                    normalized_url=normalized_url,
                    content_hash=content_hash
                )

            return promo

        except Exception as e:
            logger.error(f"[ERROR] falha no processamento da promoção: {e}", exc_info=True)
            # Guarantee failed status record if possible
            if promo_repo and 'promo' in locals():
                try:
                    promo.status = PromotionStatus.FAILED
                    promo.error_message = str(e)
                    await promo_repo.create(promo)
                except Exception:
                    pass
            return None
