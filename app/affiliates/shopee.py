import logging
import re
import urllib.parse
from typing import Callable, Optional

import httpx

from app.affiliates.base import AffiliateProvider

logger = logging.getLogger(__name__)

_BROWSER_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/120 Safari/537.36",
    "Accept-Language": "pt-BR,pt;q=0.9,en-US;q=0.8",
}


class ShopeeProvider(AffiliateProvider):
    """
    Shopee Affiliate Link Converter.
    Extracts item_id and injects affiliate tracking parameter.

    Short links (shp.ee / br.shp.ee) are resolved to the canonical product URL
    before injecting aff_trace_key. If resolution fails the promotion is
    discarded (returns "") so no link is ever published without the tag.
    """

    ITEM_ID_REGEX = re.compile(
        r'-i\.(\d+)\.(\d+)|/product/(\d+)/(\d+)',
        re.IGNORECASE
    )
    DOMAIN_PATTERNS = [
        re.compile(r'shopee\.com(\.br)?$', re.IGNORECASE),
        re.compile(r'(?:br\.)?shp\.ee$', re.IGNORECASE),
        re.compile(r's\.shopee\.com\.br$', re.IGNORECASE),
    ]
    SHORTLINK_PATTERN = re.compile(r'^(?:br\.)?shp\.ee$', re.IGNORECASE)
    # Link de afiliado oficial gerado pela Open API autenticada
    # (ex.: https://s.shopee.com.br/2LYNS7zn2S). Já contém a atribuição da conta
    # (mmp_pid/utm_source=an_<id>), então deve passar intacto.
    OFFICIAL_AFFILIATE_PATTERN = re.compile(r'^s\.shopee\.com\.br$', re.IGNORECASE)

    def __init__(self,
                 tag: Optional[str] = None,
                 app_id: Optional[str] = None,
                 resolver: Optional[Callable[[str], str]] = None):
        self.tag = tag
        self.app_id = app_id
        self._resolver = resolver or self._resolve_shortlink

    @property
    def store_name(self) -> str:
        return "shopee"

    def can_handle(self, url: str) -> bool:
        if not url:
            return False
        try:
            parsed = urllib.parse.urlparse(url)
            netloc = parsed.netloc.lower()
            return any(pattern.search(netloc) for pattern in self.DOMAIN_PATTERNS)
        except Exception:
            return False

    def extract_product_id(self, url: str) -> Optional[str]:
        if not url:
            return None
        match = self.ITEM_ID_REGEX.search(url)
        if match:
            # Returns shop_id:item_id
            groups = [g for g in match.groups() if g]
            if len(groups) >= 2:
                return f"{groups[0]}:{groups[1]}"
        return None

    def _is_shortlink(self, url: str) -> bool:
        try:
            return bool(self.SHORTLINK_PATTERN.fullmatch(urllib.parse.urlparse(url).netloc.lower()))
        except Exception:
            return False

    def _is_official_affiliate(self, url: str) -> bool:
        try:
            return bool(self.OFFICIAL_AFFILIATE_PATTERN.fullmatch(urllib.parse.urlparse(url).netloc.lower()))
        except Exception:
            return False

    def _resolve_shortlink(self, url: str) -> str:
        """Follows the shp.ee redirect chain and returns the final URL."""
        try:
            with httpx.Client(follow_redirects=True, timeout=10.0, headers=_BROWSER_HEADERS) as client:
                resp = client.get(url)
                return str(resp.url)
        except Exception as e:
            logger.warning(f"[SHOPEE] Falha ao resolver shortlink {url}: {e}")
            return ""

    def _rewrite_tracking(self, url: str) -> str:
        """Drops third-party Shopee tracking params and injects the user's tag."""
        parsed = urllib.parse.urlparse(url)
        params = urllib.parse.parse_qs(parsed.query, keep_blank_values=True)

        # Remove channel-provided and extraneous tracking params
        tracking_params = ["aff_trace_key", "utm_source", "utm_medium", "utm_campaign", "utm_content",
                           "af_siteid", "uls_trackid", "d_id"]
        for p in tracking_params:
            params.pop(p, None)

        if self.tag:
            params["aff_trace_key"] = [self.tag]
        if self.app_id:
            params["app_id"] = [self.app_id]

        new_query = urllib.parse.urlencode(params, doseq=True)
        return urllib.parse.urlunparse(parsed._replace(query=new_query))

    def convert(self, url: str) -> str:
        if not url:
            return ""

        # Já é link de afiliado oficial da conta (API autenticada): não mexer,
        # senão a atribuição é perdida. Adicionar aff_trace_key aqui é inócuo e
        # o parâmetro não é reconhecido pelo Shopee para crédito de comissão.
        if self._is_official_affiliate(url):
            return url

        if self._is_shortlink(url):
            resolved = self._resolver(url)
            if not resolved:
                # Network failure: discard so no link is published without the tag.
                logger.warning(f"[SHOPEE] Shortlink não resolvido, promoção descartada: {url}")
                return ""

            logger.info(f"[SHOPEE] Shortlink resolvido -> {resolved}")
            return self._rewrite_tracking(resolved)

        return self._rewrite_tracking(url)
