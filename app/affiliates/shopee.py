import re
import urllib.parse
from typing import Optional
from app.affiliates.base import AffiliateProvider


class ShopeeProvider(AffiliateProvider):
    """
    Shopee Affiliate Link Converter.
    Extracts item_id and injects affiliate tracking parameter.
    """

    ITEM_ID_REGEX = re.compile(
        r'-i\.(\d+)\.(\d+)|/product/(\d+)/(\d+)',
        re.IGNORECASE
    )
    DOMAIN_PATTERNS = [
        re.compile(r'shopee\.com(\.br)?$', re.IGNORECASE),
        re.compile(r'shope\.ee$', re.IGNORECASE),
    ]

    def __init__(self, tag: Optional[str] = None, app_id: Optional[str] = None):
        self.tag = tag
        self.app_id = app_id

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

    def convert(self, url: str) -> str:
        if not url:
            return ""

        parsed = urllib.parse.urlparse(url)
        params = urllib.parse.parse_qs(parsed.query, keep_blank_values=True)

        # Remove third-party affiliate tracking
        for p in ["aff_trace_key", "utm_source", "utm_medium", "utm_campaign", "af_siteid"]:
            params.pop(p, None)

        if self.tag:
            params["aff_trace_key"] = [self.tag]
        if self.app_id:
            params["app_id"] = [self.app_id]

        new_query = urllib.parse.urlencode(params, doseq=True)
        return urllib.parse.urlunparse(parsed._replace(query=new_query))
