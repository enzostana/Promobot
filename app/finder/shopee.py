import hashlib
import json
import logging
import time
from typing import Dict, List, Optional
from uuid import uuid4

import httpx

from app.config.settings import Settings
from app.core.formatter import PromotionFormatter
from app.core.models import RawMessage

logger = logging.getLogger(__name__)

DEFAULT_ENDPOINT = "https://open-api.affiliate.shopee.com.br/graphql"

PRODUCT_OFFER_QUERY = """{{
  productOfferV2(keyword: "{keyword}", listType: 0, sortType: 1, page: {page}, limit: {limit}) {{
    nodes {{
      itemId productName productLink offerLink imageUrl
      priceMin priceMax priceDiscountRate sales ratingStar commission
      shopId shopName shopType
    }}
    pageInfo {{ page limit hasNextPage }}
  }}
}}"""


class ShopeeFinder:
    """
    Caçador de ofertas via Open API de Afiliados Shopee (GraphQL).
    Busca produtos por keyword, filtra por regras configuradas e gera
    RawMessages que entram na mesma fila/pipeline do PromoBot.
    """

    def __init__(
        self,
        settings: Optional[Settings] = None,
        client: Optional[httpx.AsyncClient] = None,
        endpoint: str = DEFAULT_ENDPOINT,
    ):
        self.settings = settings or Settings()
        self.app_id = self.settings.SHOPEE_API_APP_ID
        self.secret = self.settings.SHOPEE_API_SECRET
        self.endpoint = endpoint
        self._client = client
        self._owns_client = client is None
        self._formatter = PromotionFormatter()

    label = "Shopee"

    def enabled(self) -> bool:
        return bool(self.settings.SHOPEE_FINDER_ENABLED)

    @property
    def interval_min(self) -> int:
        return max(1, int(self.settings.SHOPEE_FINDER_INTERVAL_MIN or 30))

    def credentials_ok(self) -> bool:
        return bool(self.app_id and self.secret)

    @property
    def keywords(self) -> List[str]:
        return self.settings.get_shopee_finder_keywords()

    @staticmethod
    def build_signature(app_id: str, secret: str, timestamp: str, payload: str) -> str:
        raw = f"{app_id}{timestamp}{payload}{secret}"
        return hashlib.sha256(raw.encode("utf-8")).hexdigest()

    def _build_headers(self, payload: str) -> Dict[str, str]:
        timestamp = str(int(time.time()))
        signature = self.build_signature(self.app_id, self.secret, timestamp, payload)
        return {
            "Authorization": (
                f"SHA256 Credential={self.app_id}, Timestamp={timestamp}, "
                f"Signature={signature}"
            ),
            "Content-Type": "application/json",
        }

    async def _post(self, payload: dict) -> dict:
        body = json.dumps(payload, separators=(",", ":"), ensure_ascii=False)
        headers = self._build_headers(body)
        if self._owns_client:
            async with httpx.AsyncClient(timeout=30.0) as client:
                return await self._post_with(client, headers, payload)
        return await self._post_with(self._client, headers, payload)

    @staticmethod
    async def _post_with(client, headers: dict, payload: dict) -> dict:
        resp = await client.post(DEFAULT_ENDPOINT, headers=headers, json=payload)
        if resp.status_code >= 400:
            logger.warning(f"[FINDER] Shopee API http {resp.status_code}: {resp.text[:300]}")
            resp.raise_for_status()
        data = resp.json()
        if data.get("errors"):
            raise RuntimeError(f"[FINDER] Shopee API error: {data['errors']}")
        return data

    def _offer_from_node(self, node: dict) -> Dict[str, Optional[float]]:
        try:
            price = float(node.get("priceMin") or 0)
        except (TypeError, ValueError):
            price = 0.0
        rate_raw = node.get("priceDiscountRate")
        rate = None
        try:
            if rate_raw is not None:
                value = float(rate_raw)
                rate = value if value < 1 else value / 100.0
        except (TypeError, ValueError):
            rate = None
        discount_pct = round((rate or 0) * 100)
        original_price = None
        if rate and 0 < rate < 1 and price:
            original_price = price / (1 - rate)
        return {
            "item_id": node.get("itemId"),
            "shop_id": node.get("shopId"),
            "product_name": (node.get("productName") or "").strip(),
            "product_link": node.get("productLink") or "",
            "offer_link": node.get("offerLink") or "",
            "image_url": node.get("imageUrl") or "",
            "price": price,
            "original_price": original_price,
            "discount_percentage": discount_pct,
            "sales": self._to_number(node.get("sales"), 0, int),
            "rating": self._to_number(node.get("ratingStar"), 0.0, float),
            "commission": self._to_number(node.get("commission"), 0.0, float),
            "shop_name": node.get("shopName") or "",
            "shop_type": node.get("shopType"),
        }

    @staticmethod
    def _to_number(value, default, cast):
        try:
            return cast(value) if value is not None else default
        except (TypeError, ValueError):
            return default

    def _passes(self, offer: dict) -> bool:
        try:
            st = self.settings
            if st.SHOPEE_FINDER_MIN_DISCOUNT and offer["discount_percentage"] < st.SHOPEE_FINDER_MIN_DISCOUNT:
                return False
            if st.SHOPEE_FINDER_MIN_SALES and offer["sales"] < st.SHOPEE_FINDER_MIN_SALES:
                return False
            if st.SHOPEE_FINDER_MIN_RATING and offer["rating"] < st.SHOPEE_FINDER_MIN_RATING:
                return False
            if st.SHOPEE_FINDER_MAX_PRICE and offer["price"] > st.SHOPEE_FINDER_MAX_PRICE:
                return False
        except Exception:
            return False
        return bool(offer["product_link"] or offer["offer_link"])

    async def search(self, keyword: str, limit: int = 20, page: int = 1) -> List[dict]:
        query = PRODUCT_OFFER_QUERY.format(keyword=keyword, page=page, limit=limit)
        data = await self._post({"query": query})
        nodes = ((data.get("data") or {}).get("productOfferV2") or {}).get("nodes") or []
        offers = [self._offer_from_node(node) for node in nodes]
        return [offer for offer in offers if self._passes(offer)]

    def build_message(self, offer: dict) -> RawMessage:
        lines = [f"🔥 {offer['product_name'] or 'Oferta'}"[:200]]
        if offer.get("original_price"):
            lines.append("")
            lines.append(f"💰 De: R$ {self._formatter.format_currency(offer['original_price'])}")
        if offer.get("price"):
            lines.append("")
            lines.append(f"🔥 Por: R$ {self._formatter.format_currency(offer['price'])}")
        lines.append("")
        lines.append(f"📉 {offer['discount_percentage']}% OFF")
        text = "\n".join(lines)
        url = offer["product_link"] or offer["offer_link"]
        if url:
            text += f"\n\n{url}"
        item_id = offer["item_id"]
        return RawMessage(
            id=f"shopee-{uuid4().hex[:8]}-{item_id}",
            source="shopee_finder",
            source_message_id=f"shopee-{item_id}",
            source_chat_id="caçador:shopee",
            source_chat_title="Caçador Shopee",
            text=text,
            urls=[url] if url else [],
            media_url=offer["image_url"] or None,
        )

    async def scan(self, queue, limit: int = 20) -> int:
        total = 0
        for keyword in self.keywords:
            try:
                offers = await self.search(keyword, limit=limit)
            except Exception as e:
                logger.warning(f"[FINDER] erro na busca '{keyword}': {e}")
                continue
            for offer in offers:
                raw = self.build_message(offer)
                await queue.enqueue(raw)
                total += 1
        return total