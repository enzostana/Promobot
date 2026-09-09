import logging
import re
from typing import Dict, List, Optional
from uuid import uuid4

import httpx

from app.config.settings import Settings
from app.core.formatter import PromotionFormatter
from app.core.models import RawMessage

logger = logging.getLogger(__name__)

API_BASE = "https://api.mercadolibre.com"

_THUMB_RE = re.compile(r"-I\.jpg$", re.IGNORECASE)


def _enlarge_thumbnail(url: str) -> str:
    """Trocas a imagem reduzida (…-I.jpg) pela versão original diminuída (…-O)."""
    if not url:
        return url
    return _THUMB_RE.sub("-O.jpg", url)


class MercadoLivreFinder:
    """
    Caçador de ofertas via API pública do Mercado Livre (/sites/MLB/search).
    O Auth usa OAuth2 client_credentials (app de developers.mercadolivre.com.br).
    Filtra itens com desconto real (original_price presente) e gera RawMessages.
    O link (permalink) já resta no formato de produto; o AffiliateRegistry injeta
    matt_tool na hora do parse, no pipeline normal.
    """

    def __init__(
        self,
        settings: Optional[Settings] = None,
        client: Optional[httpx.AsyncClient] = None,
        api_base: str = API_BASE,
    ):
        self.settings = settings or Settings()
        self.client_id = self.settings.MEL_API_CLIENT_ID
        self.client_secret = self.settings.MEL_API_CLIENT_SECRET
        self.api_base = api_base
        self._client = client
        self._owns_client = client is None
        self._formatter = PromotionFormatter()

    label = "Mercado Livre"

    def enabled(self) -> bool:
        return bool(self.settings.MEL_FINDER_ENABLED)

    @property
    def interval_min(self) -> int:
        return max(1, int(self.settings.MEL_FINDER_INTERVAL_MIN or 30))

    def credentials_ok(self) -> bool:
        return bool(self.client_id and self.client_secret)

    @property
    def keywords(self) -> List[str]:
        return self.settings.get_mel_finder_keywords()

    async def _get_token(self, client) -> str:
        resp = await client.post(
            f"{self.api_base}/oauth/token",
            data={
                "grant_type": "client_credentials",
                "client_id": self.client_id,
                "client_secret": self.client_secret,
            },
        )
        if resp.status_code >= 400:
            logger.warning(f"[FINDER-MEL] falha no token (http {resp.status_code}): {resp.text[:300]}")
            resp.raise_for_status()
        data = resp.json()
        return data["access_token"]

    @staticmethod
    def _offer_from_result(result: dict) -> Dict[str, Optional[float]]:
        try:
            price = float(result.get("price") or 0)
        except (TypeError, ValueError):
            price = 0.0
        try:
            original = result.get("original_price")
            original = float(original) if original is not None else None
        except (TypeError, ValueError):
            original = None
        discount = 0.0
        if original and price:
            discount = round((1 - price / original) * 100, 1)
        return {
            "item_id": result.get("id"),
            "product_name": (result.get("title") or "").strip(),
            "permalink": result.get("permalink") or "",
            "thumbnail": _enlarge_thumbnail(result.get("thumbnail") or ""),
            "price": price,
            "original_price": original,
            "discount_percentage": discount,
            "sold_quantity": result.get("sold_quantity") or 0,
            "condition": result.get("condition"),
            "official_store": result.get("official_store_name"),
            "shop_name": result.get("seller", {}).get("nickname") if isinstance(result.get("seller"), dict) else None,
        }

    def _passes(self, offer: dict) -> bool:
        try:
            st = self.settings
            if offer["original_price"] is None or offer["price"] <= 0:
                return False
            if st.MEL_FINDER_MIN_DISCOUNT and offer["discount_percentage"] < st.MEL_FINDER_MIN_DISCOUNT:
                return False
            if st.MEL_FINDER_MAX_PRICE and offer["price"] > st.MEL_FINDER_MAX_PRICE:
                return False
        except Exception:
            return False
        return bool(offer["permalink"])

    async def search(
        self, keyword: str, token: str, limit: int = 50, client: Optional[httpx.AsyncClient] = None
    ) -> List[dict]:
        client = client or self._client
        resp = await client.get(
            f"{self.api_base}/sites/MLB/search",
            params={"q": keyword, "limit": limit},
            headers={"Authorization": f"Bearer {token}"},
        )
        if resp.status_code >= 400:
            logger.warning(f"[FINDER-MEL] search http {resp.status_code}: {resp.text[:300]}")
            resp.raise_for_status()
        data = resp.json()
        results = data.get("results") or []
        offers = [self._offer_from_result(r) for r in results]
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
        if offer["permalink"]:
            text += f"\n\n{offer['permalink']}"
        return RawMessage(
            id=f"mel-{uuid4().hex[:8]}-{offer['item_id']}",
            source="mel_finder",
            source_message_id=f"mel-{offer['item_id']}",
            source_chat_id="caçador:mercadolivre",
            source_chat_title="Caçador Mercado Livre",
            text=text,
            urls=[offer["permalink"]],
            media_url=offer["thumbnail"] or None,
        )

    async def scan(self, queue, limit: int = 50) -> int:
        if self._owns_client:
            async with httpx.AsyncClient(timeout=30.0) as client:
                return await self._scan_with(client, queue, limit)
        return await self._scan_with(self._client, queue, limit)

    async def _scan_with(self, client, queue, limit: int) -> int:
        token = await self._get_token(client)
        total = 0
        for keyword in self.keywords:
            try:
                offers = await self.search(keyword, token, limit=limit, client=client)
            except Exception as e:
                logger.warning(f"[FINDER-MEL] erro na busca '{keyword}': {e}")
                continue
            for offer in offers:
                raw = self.build_message(offer)
                await queue.enqueue(raw)
                total += 1
        return total