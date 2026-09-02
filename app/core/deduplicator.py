import hashlib
import re
import urllib.parse
from typing import Dict, Optional, Tuple
from app.core.models import Promotion
from app.config.settings import Settings, get_settings


class Deduplicator:
    """
    Multi-tier deduplication engine for promotions.
    Detects duplicates based on:
    1. Normalized product URLs
    2. Store + Product ID (e.g. Amazon ASIN, Mercado Livre MLB)
    3. Content hash (normalized product name + sale price)
    4. Time window (TTL)
    """

    TRACKING_PARAMS_REGEX = re.compile(
        r'^(utm_|ref|fbclid|gclid|msclkid|ascsubtag|tag|matt_|aff_|linkCode|camp|creative)',
        re.IGNORECASE
    )

    def __init__(self, redis_client=None, settings: Optional[Settings] = None):
        self.redis = redis_client
        self.settings = settings or get_settings()
        self.ttl_seconds = self.settings.DEDUP_WINDOW_HOURS * 3600
        # In-memory fallback dictionary mapping dedup key -> promotion_id
        self._memory_cache: Dict[str, int] = {}

    def normalize_url(self, url: str) -> str:
        if not url:
            return ""
        try:
            parsed = urllib.parse.urlparse(url.strip())
            scheme = "https"
            netloc = parsed.netloc.lower()
            path = parsed.path

            if len(path) > 1 and path.endswith("/"):
                path = path[:-1]

            query_params = urllib.parse.parse_qs(parsed.query, keep_blank_values=True)
            filtered_params = {}
            for k, v in query_params.items():
                if not self.TRACKING_PARAMS_REGEX.match(k):
                    filtered_params[k] = v

            sorted_query = urllib.parse.urlencode(
                sorted((k, sorted(v)) for k, v in filtered_params.items()),
                doseq=True
            )

            return urllib.parse.urlunparse((scheme, netloc, path, "", sorted_query, ""))
        except Exception:
            return url

    def compute_content_hash(
        self,
        store: Optional[str],
        product_id: Optional[str],
        normalized_url: str,
        product_name: str,
        sale_price: Optional[float] = None
    ) -> str:
        clean_name = re.sub(r'\s+', ' ', product_name.strip().lower())
        price_str = f"{sale_price:.2f}" if sale_price is not None else "no_price"

        if store and product_id:
            raw = f"PID:{store.lower()}:{product_id.lower()}"
        elif normalized_url:
            raw = f"URL:{normalized_url}"
        else:
            raw = f"CONTENT:{clean_name}:{price_str}"

        return hashlib.sha256(raw.encode("utf-8")).hexdigest()

    async def is_duplicate(
        self,
        promotion: Promotion,
        db_repo=None
    ) -> Tuple[bool, Optional[int]]:
        """
        Checks if the promotion is a duplicate.
        Returns:
            (is_duplicate: bool, existing_promotion_id: Optional[int])
        """
        normalized_url = self.normalize_url(promotion.original_url)
        content_hash = promotion.content_hash or self.compute_content_hash(
            promotion.store,
            promotion.product_id,
            normalized_url,
            promotion.product_name,
            promotion.sale_price
        )

        keys_to_check = []
        if promotion.store and promotion.product_id:
            keys_to_check.append(f"{self.settings.REDIS_DEDUP_PREFIX}pid:{promotion.store.lower()}:{promotion.product_id.lower()}")

        if normalized_url:
            url_hash = hashlib.sha256(normalized_url.encode("utf-8")).hexdigest()
            keys_to_check.append(f"{self.settings.REDIS_DEDUP_PREFIX}url:{url_hash}")

        keys_to_check.append(f"{self.settings.REDIS_DEDUP_PREFIX}hash:{content_hash}")

        # 1. Fast check in Redis if available
        if self.redis:
            try:
                for key in keys_to_check:
                    existing_id = await self.redis.get(key)
                    if existing_id:
                        return True, int(existing_id)
            except Exception:
                pass
        else:
            # Check in-memory cache
            for key in keys_to_check:
                if key in self._memory_cache:
                    return True, self._memory_cache[key]

        # 2. Database check within time window
        if db_repo:
            try:
                existing_promo = await db_repo.find_duplicate(
                    store=promotion.store,
                    product_id=promotion.product_id,
                    normalized_url=normalized_url,
                    content_hash=content_hash,
                    hours_window=self.settings.DEDUP_WINDOW_HOURS
                )
                if existing_promo:
                    await self.record_seen(existing_promo.id, promotion, normalized_url, content_hash)
                    return True, existing_promo.id
            except Exception:
                pass

        return False, None

    async def record_seen(
        self,
        promotion_id: int,
        promotion: Promotion,
        normalized_url: Optional[str] = None,
        content_hash: Optional[str] = None
    ) -> None:
        normalized_url = normalized_url or self.normalize_url(promotion.original_url)
        content_hash = content_hash or promotion.content_hash or self.compute_content_hash(
            promotion.store,
            promotion.product_id,
            normalized_url,
            promotion.product_name,
            promotion.sale_price
        )

        keys_to_set = []
        if promotion.store and promotion.product_id:
            keys_to_set.append(f"{self.settings.REDIS_DEDUP_PREFIX}pid:{promotion.store.lower()}:{promotion.product_id.lower()}")

        if normalized_url:
            url_hash = hashlib.sha256(normalized_url.encode("utf-8")).hexdigest()
            keys_to_set.append(f"{self.settings.REDIS_DEDUP_PREFIX}url:{url_hash}")

        keys_to_set.append(f"{self.settings.REDIS_DEDUP_PREFIX}hash:{content_hash}")

        if self.redis:
            try:
                for key in keys_to_set:
                    await self.redis.set(key, str(promotion_id), ex=self.ttl_seconds)
            except Exception:
                pass
        else:
            for key in keys_to_set:
                self._memory_cache[key] = promotion_id
