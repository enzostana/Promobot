import html as _html
import logging
import re
from typing import Dict, List, Optional
from uuid import uuid4

import httpx

from app.config.settings import Settings
from app.core.formatter import PromotionFormatter
from app.core.models import RawMessage

logger = logging.getLogger(__name__)

OFFERS_URL = "https://www.mercadolivre.com.br/ofertas"

UA_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36"
    ),
    "Accept-Language": "pt-BR,pt;q=0.9",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
}

_THUMB_RE = re.compile(r"-I\.jpg$", re.IGNORECASE)
_CARD_SPLIT_RE = re.compile(r'(?=<div class="andes-card poly-card)')
_TITLE_RE = re.compile(r'class="poly-component__title">([^<]+)</a>')
_HREF_RE = re.compile(r'<a href="(https[^"]+?)".*?class="poly-component__title"')
_IMG_RE = re.compile(r'class="poly-component__picture" src="(https[^"]+?)"')
_PRICE_RE = re.compile(
    r'class="andes-money-amount poly-price__amount[^"]*"[^>]*aria-label="([^"]+)"'
)
_ANTES_RE = re.compile(r'aria-label="Antes: ([^"]+)"')
_MLB_ID_RE = re.compile(r"(?:MLB|MLBU)[_/-]?(\d+)")


def _enlarge_thumbnail(url: str) -> str:
    """Trocas a imagem reduzida (…-I.jpg) pela versão original diminuída (…-O)."""
    if not url:
        return url
    return _THUMB_RE.sub("-O.jpg", url)


def _parse_amount(label: Optional[str]) -> float:
    if not label:
        return 0.0
    label = label.strip()
    m = re.search(r"([\d.]+)\s*reais(?:\s*com\s+([\d.,]+)\s*centavos)?", label)
    if m:
        reais = float(m.group(1).replace(".", "")) or 0.0
        cents = 0.0
        if m.group(2):
            cents = float(m.group(2).replace(".", "").replace(",", "."))
        return reais + cents / 100
    m = re.search(r"R\$\s*([\d.,]+)", label)
    if m:
        try:
            return float(m.group(1).replace(".", "").replace(",", "."))
        except ValueError:
            return 0.0
    return 0.0


def _item_id(url: str, title: str) -> str:
    m = _MLB_ID_RE.search(url or "")
    if m:
        return m.group(1)
    slug = re.sub(r"[^A-Za-z0-9]+", "-", (url or "").rstrip("/").split("/")[-1])[:60]
    return (slug or "").strip("-") or "-"


class MercadoLivreFinder:
    """
    Caçador de ofertas do Mercado Livre via scraping da página pública de ofertas
    (https://www.mercadolivre.com.br/ofertas). Não usa a API: o endpoint
    /sites/MLB/search foi descontinuado (HTTP 403), então a fonte passou a ser o
    HTML server-rendered (blocos 'poly-card').

    Ofertas passam pelos filtros existentes (desconto mínimo, preço máximo) e pelo
    filtro de temas via keywords (o título precisa conter uma das keywords). A página
    é SSR, então um fetch simples com User-Agent de navegador é suficiente.
    """

    def __init__(
        self,
        settings: Optional[Settings] = None,
        client: Optional[httpx.AsyncClient] = None,
        api_base: str = "",
        refresh_saver: Optional[callable] = None,
    ):
        self.settings = settings or Settings()
        self.client_id = self.settings.MEL_API_CLIENT_ID
        self.client_secret = self.settings.MEL_API_CLIENT_SECRET
        self.refresh_token = self.settings.MEL_REFRESH_TOKEN
        self.api_base = api_base
        self._client = client
        self._owns_client = client is None
        self._refresh_saver = refresh_saver
        self._formatter = PromotionFormatter()

    def enabled(self) -> bool:
        return bool(self.settings.MEL_FINDER_ENABLED)

    @property
    def label(self) -> str:
        return "Mercado Livre"

    @property
    def interval_min(self) -> int:
        return max(1, int(self.settings.MEL_FINDER_INTERVAL_MIN or 30))

    def credentials_ok(self) -> bool:
        # Scraping da página pública não exige credenciais OAuth.
        return True

    @property
    def keywords(self) -> List[str]:
        return self.settings.get_mel_finder_keywords()

    @staticmethod
    def _offer_from_block(block: str) -> Optional[Dict]:
        title_m = _TITLE_RE.search(block)
        if not title_m:
            return None
        title = _html.unescape(title_m.group(1)).strip()
        href_m = _HREF_RE.search(block)
        permalink = href_m.group(1) if href_m else ""
        thumb_m = _IMG_RE.search(block)
        thumbnail = thumb_m.group(1) if thumb_m else ""

        price_m = _PRICE_RE.search(block)
        antes_m = _ANTES_RE.search(block)
        price = _parse_amount(price_m.group(1) if price_m else None)
        original = _parse_amount(antes_m.group(1) if antes_m else None)
        original = original or None

        discount = 0.0
        if original and price > 0:
            discount = round((1 - price / original) * 100, 1)

        if not permalink or not price:
            return None
        return {
            "item_id": _item_id(permalink, title),
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
        blocks = _CARD_SPLIT_RE.split(html)[1:]
        offers = []
        for block in blocks:
            offer = MercadoLivreFinder._offer_from_block(block)
            if offer:
                offers.append(offer)
        return offers

    def _passes(self, offer: dict) -> bool:
        try:
            st = self.settings
            if offer["original_price"] is None or offer["price"] <= 0:
                return False
            if st.MEL_FINDER_MIN_DISCOUNT and offer["discount_percentage"] < st.MEL_FINDER_MIN_DISCOUNT:
                return False
            if st.MEL_FINDER_MAX_PRICE and offer["price"] > st.MEL_FINDER_MAX_PRICE:
                return False
            title = (offer["product_name"] or "").lower()
            if self.keywords and not any(k.lower() in title for k in self.keywords):
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
            id=f"mel-{uuid4().hex[:8]}-{offer['item_id']}",
            source="mel_finder",
            source_message_id=f"mel-scrape-{offer['item_id']}",
            source_chat_id="caçador:mercadolivre",
            source_chat_title="Caçador Mercado Livre",
            text=text,
            urls=[offer["permalink"]],
            media_url=offer["thumbnail"] or None,
        )

    async def scan(self, queue, limit: int = 50) -> int:
        if self._owns_client:
            async with httpx.AsyncClient(timeout=30.0, follow_redirects=True) as client:
                return await self._scan_with(client, queue, limit)
        return await self._scan_with(self._client, queue, limit)

    async def _scan_with(self, client, queue, limit: int) -> int:
        resp = await client.get(OFFERS_URL, headers=UA_HEADERS)
        if resp.status_code >= 400:
            logger.warning(f"[FINDER-MEL] página de ofertas http {resp.status_code}: {resp.text[:200]}")
            resp.raise_for_status()
        offers = self._parse_offers(resp.text)

        seen = set()
        total = 0
        for offer in offers:
            if not self._passes(offer):
                continue
            if offer["permalink"] in seen:
                continue
            seen.add(offer["permalink"])
            raw = self.build_message(offer)
            await queue.enqueue(raw)
            total += 1
            if limit and total >= limit:
                break
        return total