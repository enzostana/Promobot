import re
import urllib.parse
from typing import Optional
from app.affiliates.base import AffiliateProvider


class MercadoLivreProvider(AffiliateProvider):
    """
    Mercado Livre Affiliate Link Converter.
    Extracts MLB product identifier and injects affiliate tracking parameter.
    """

    MLB_REGEX = re.compile(
        r'(MLB-?\d+)',
        re.IGNORECASE
    )
    DOMAIN_PATTERNS = [
        re.compile(r'mercadolivre\.com(\.br)?$', re.IGNORECASE),
        re.compile(r'mercadolibre\.com$', re.IGNORECASE),
        re.compile(r'meli\.la$', re.IGNORECASE),
    ]

    def __init__(self, tag: Optional[str] = None):
        self.tag = tag

    @property
    def store_name(self) -> str:
        return "mercadolivre"

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
        match = self.MLB_REGEX.search(url)
        if match:
            # Normalize to MLB123456789 without hyphen
            return match.group(1).upper().replace("-", "")
        return None

    def convert(self, url: str) -> str:
        if not url:
            return ""

        parsed = urllib.parse.urlparse(url)
        params = urllib.parse.parse_qs(parsed.query, keep_blank_values=True)

        # Remove common extraneous tracking params
        tracking_params = ["matt_tool", "matt_word", "tracking_id", "utm_source", "utm_medium", "utm_campaign"]
        for p in tracking_params:
            params.pop(p, None)

        if self.tag:
            # Inject Mercado Livre affiliate tracking parameter
            params["matt_tool"] = [self.tag]

        new_query = urllib.parse.urlencode(params, doseq=True)
        return urllib.parse.urlunparse(parsed._replace(query=new_query))
