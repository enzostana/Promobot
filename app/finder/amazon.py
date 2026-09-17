import asyncio
import json
import logging
import re
from typing import Dict, List, Optional
from uuid import uuid4

import httpx

from app.config.settings import Settings
from app.core.formatter import PromotionFormatter
from app.core.models import RawMessage
from app.core.parser import _fold_text

logger = logging.getLogger(__name__)

DEALS_URL = "https://www.amazon.com.br/deals"
_PRODUCTS_RE = re.compile(r'"products"\s*:\s*\[')

UA_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36"
    ),
    "Accept-Language": "pt-BR,pt;q=0.9,en-US;q=0.8,en;q=0.7",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
}


def _matched_keyword(title: str, keywords: List[str]) -> Optional[str]:
    """Retorna a primeira keyword configurada presente no título (folded)."""
    if not keywords:
        return None
    folded_title = _fold_text(title or "")
    for kw in keywords:
        if _fold_text(kw) in folded_title:
            return kw
    return None


def _find_balanced_json(html: str, start: int) -> Optional[str]:
    """Retorna o trecho JSON balanceado de um array/objeto cujo início está em *start*."""
    depth = 0
    in_str = False
    i = start
    n = len(html)
    while i < n:
        c = html[i]
        if in_str:
            if c == "\\":
                i += 2
                continue
            if c == '"':
                in_str = False
        elif c == '"':
            in_str = True
        elif c == "[":
            depth += 1
        elif c == "]":
            depth -= 1
            if depth == 0:
                return html[start:i + 1]
        i += 1
    return None


def _embedded_products(html: str) -> List[Dict]:
    """Extrai do HTML da página de ofertas o array 'products' (JSON embutido do
    storefront de deals da Amazon). Retorna [] quando não encontra produtos."""
    candidates = []
    for m in _PRODUCTS_RE.finditer(html):
        chunk = _find_balanced_json(html, m.end() - 1)
        if not chunk:
            continue
        try:
            arr = json.loads(chunk)
        except (ValueError, json.JSONDecodeError):
            continue
        if isinstance(arr, list) and arr and isinstance(arr[0], dict) and arr[0].get("asin"):
            candidates.append(arr)
    if not candidates:
        return []
    return max(candidates, key=len)


def _parse_amount(value: Optional[str]) -> float:
    if not value:
        return 0.0
    cleaned = value.strip().replace(" ", "")
    if cleaned.count(",") == 1 and cleaned.count(".") > 0 and cleaned.find(",") > cleaned.rfind("."):
        cleaned = cleaned.replace(".", "").replace(",", ".")
    try:
        return float(cleaned.replace(",", "."))
    except ValueError:
        m = re.search(r"(\d+(?:[.,]\d+)*)", cleaned)
        if not m:
            return 0.0
        raw = m.group(1)
        if raw.count(".") > 1 or (raw.count(",") == 1 and raw.count(".") == 0):
            raw = raw.replace(".", "").replace(",", ".")
        elif raw.count(",") == 1 and raw.count(".") == 1:
            raw = raw.replace(".", "").replace(",", ".")
        if raw.count(",") == 1 and raw.count(".") == 0:
            raw = raw.replace(",", ".")
        try:
            return float(raw)
        except ValueError:
            return 0.0


def _product_permalink(asin: str) -> str:
    return f"https://www.amazon.com.br/dp/{asin}"


class AmazonFinder:
    retry_attempts = 3
    retry_backoff_s = 10.0
    """
    Caçador de ofertas da Amazon via scraping da página pública de ofertas
    (https://www.amazon.com.br/deals). A página é um storefront JS: o HTML traz
    um JSON embutido ('productSearchResponse.products') com ~30 produtos por
    fetch — título, ASIN, preço da oferta, preço de antes e badge de desconto.

    Não há API pública de afiliados gratuita (PA-API exige conta Paid) e a
    paginação '?startIndex=N' é ignorada pela Amazon (o resto é carregado via
    AJAX com token de sessão), então o caçador faz um único fetch por ciclo e
    aplica os filtros existentes (desconto mínimo, preço máximo) + keywords no
    título. O link gerado é o produto canônico /dp/<ASIN>, cuja tag de afiliado
    é injetada pelo pipeline (AmazonProvider).
    """

    def __init__(
        self,
        settings: Optional[Settings] = None,
        client: Optional[httpx.AsyncClient] = None,
        deals_url: str = DEALS_URL,
    ):
        self.settings = settings or Settings()
        self.deals_url = deals_url
        self._client = client
        self._owns_client = client is None
        self._formatter = PromotionFormatter()

    label = "Amazon"

    def enabled(self) -> bool:
        return bool(self.settings.AMAZON_FINDER_ENABLED)

    @property
    def interval_min(self) -> int:
        return max(1, int(self.settings.AMAZON_FINDER_INTERVAL_MIN or 30))

    def credentials_ok(self) -> bool:
        # Scraping da página pública de ofertas não exige credenciais.
        return True

    @property
    def keywords(self) -> List[str]:
        return self.settings.get_amazon_finder_keywords()

    @staticmethod
    def _offer_from_product(product: Dict) -> Optional[Dict]:
        asin = (product.get("asin") or "").strip().upper()
        title = (product.get("title") or "").strip()
        if not asin or not title:
            return None

        permalink = _product_permalink(asin)

        images = (product.get("image") or {}).get("hiRes") or {}
        base_url = images.get("baseUrl") or ""
        ext = images.get("extension") or "jpg"
        thumbnail = f"{base_url}.{ext}" if base_url else ""

        price = _parse_amount(product.get("price", {}).get("priceToPay", {}).get("price"))
        original = None
        basis = product.get("price", {}).get("basisPrice") or {}
        if basis.get("strikethrough"):
            original = _parse_amount(basis.get("price")) or None

        discount = 0.0
        if original and price > 0:
            discount = round((1 - price / original) * 100, 1)
        if not discount:
            fragments = ((product.get("dealBadge") or {}).get("label") or {}).get("content") or {}
            for frag in fragments.get("fragments") or []:
                text = frag.get("text") or ""
                m = re.search(r"(\d+(?:[.,]\d+)?)", text)
                if m:
                    discount = round(float(m.group(1).replace(",", ".")), 1)
                    break

        if price <= 0:
            return None

        return {
            "item_id": asin,
            "product_name": title,
            "permalink": permalink,
            "thumbnail": thumbnail,
            "price": price,
            "original_price": original,
            "discount_percentage": discount,
            "sold_quantity": 0,
            "condition": None,
            "official_store": None,
            "shop_name": None,
        }

    @staticmethod
    def _parse_offers(html: str) -> List[Dict]:
        offers = []
        seen = set()
        for product in _embedded_products(html):
            offer = AmazonFinder._offer_from_product(product)
            if offer and offer["permalink"] not in seen:
                seen.add(offer["permalink"])
                offers.append(offer)
        return offers

    def _passes(self, offer: dict) -> bool:
        try:
            st = self.settings
            if offer["price"] <= 0:
                return False
            if st.AMAZON_FINDER_MIN_DISCOUNT and offer["discount_percentage"] < st.AMAZON_FINDER_MIN_DISCOUNT:
                return False
            if st.AMAZON_FINDER_MAX_PRICE and offer["price"] > st.AMAZON_FINDER_MAX_PRICE:
                return False
            offer["matched_keyword"] = _matched_keyword(offer["product_name"] or "", self.keywords)
            if self.keywords and offer["matched_keyword"] is None:
                return False
        except Exception:
            return False
        return bool(offer["permalink"])

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
            id=f"amazon-{uuid4().hex[:8]}-{offer['item_id']}",
            source="amazon_finder",
            source_message_id=f"amazon-scrape-{offer['item_id']}",
            source_chat_id="caçador:amazon",
            source_chat_title="Caçador Amazon",
            text=text,
            urls=[offer["permalink"]],
            media_url=offer["thumbnail"] or None,
            matched_keyword=offer.get("matched_keyword"),
        )

    async def scan(self, queue, limit: int = 50) -> int:
        if self._owns_client:
            async with httpx.AsyncClient(timeout=30.0, follow_redirects=True) as client:
                return await self._scan_with(client, queue, limit)
        return await self._scan_with(self._client, queue, limit)

    async def _scan_with(self, client, queue, limit: int) -> int:
        offers = []
        attempts = max(1, int(self.retry_attempts))
        for attempt in range(attempts):
            resp = await client.get(self.deals_url, headers=UA_HEADERS)
            if resp.status_code >= 400:
                logger.warning(
                    f"[FINDER-AMAZON] varredura http {resp.status_code} "
                    f"(tentativa {attempt + 1}/{attempts}): {self.deals_url[:120]}"
                )
                offers = []
            else:
                offers = self._parse_offers(resp.text)
            if offers:
                break
            if attempt < attempts - 1:
                await asyncio.sleep(self.retry_backoff_s * (attempt + 1))
        if not offers:
            logger.warning(
                f"[FINDER-AMAZON] sem ofertas após {attempts} tentativa(s) em "
                f"{self.deals_url[:120]} (anti-bot intermitente; próximo ciclo tenta de novo)."
            )
            return 0
        total = 0
        max_enqueued = max(1, int(limit or 0)) if limit else 0
        for offer in offers:
            if not self._passes(offer):
                continue
            raw = self.build_message(offer)
            await queue.enqueue(raw)
            total += 1
            if max_enqueued and total >= max_enqueued:
                break
        logger.info(
            f"[FINDER-AMAZON] varredura do storefront de ofertas enfileirou {total} "
            f"oferta(s) novas de {len(offers)} encontradas (filtro de {len(self.keywords)} keywords)."
        )
        return total