import re
import urllib.parse
from typing import Optional
from app.affiliates.base import AffiliateProvider


class AmazonProvider(AffiliateProvider):
    """
    Amazon Affiliate Link Converter.
    Extracts ASIN and adds or updates the 'tag' parameter.
    """

    ASIN_REGEX = re.compile(
        r'/(?:dp|gp/product|gp/aw/d|product)/([A-Z0-9]{10})',
        re.IGNORECASE
    )
    DOMAIN_PATTERNS = [
        re.compile(r'amazon\.com(\.br)?$', re.IGNORECASE),
        re.compile(r'amzn\.to$', re.IGNORECASE),
        re.compile(r'a\.co$', re.IGNORECASE),
    ]

    def __init__(self, tag: Optional[str] = None):
        self.tag = tag

    @property
    def store_name(self) -> str:
        return "amazon"

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
        match = self.ASIN_REGEX.search(url)
        if match:
            return match.group(1).upper()
        return None

    def convert(self, url: str) -> str:
        if not url:
            return ""

        asin = self.extract_product_id(url)
        if not self.tag:
            # If no affiliate tag is configured, return canonical or cleaned URL
            if asin:
                return f"https://www.amazon.com.br/dp/{asin}"
            return self._strip_tracking(url)

        if asin:
            # Canonical product affiliate link
            return f"https://www.amazon.com.br/dp/{asin}?tag={self.tag}"

        # If ASIN was not in the path (e.g. short link or search page), append/replace tag query param
        return self._inject_tag(url, self.tag)

    def _strip_tracking(self, url: str) -> str:
        parsed = urllib.parse.urlparse(url)
        params = urllib.parse.parse_qs(parsed.query, keep_blank_values=True)
        # Remove tracking parameters
        params_to_remove = ["tag", "ref", "ref_", "linkCode", "ascsubtag", "camp", "creative"]
        for p in params_to_remove:
            params.pop(p, None)
        new_query = urllib.parse.urlencode(params, doseq=True)
        return urllib.parse.urlunparse(parsed._replace(query=new_query))

    def _inject_tag(self, url: str, tag: str) -> str:
        cleaned = self._strip_tracking(url)
        parsed = urllib.parse.urlparse(cleaned)
        params = urllib.parse.parse_qs(parsed.query, keep_blank_values=True)
        params["tag"] = [tag]
        new_query = urllib.parse.urlencode(params, doseq=True)
        return urllib.parse.urlunparse(parsed._replace(query=new_query))
