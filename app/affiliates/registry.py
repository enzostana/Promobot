import re
import urllib.parse
from typing import Dict, List, Optional, Tuple
from app.affiliates.base import AffiliateProvider
from app.affiliates.amazon import AmazonProvider
from app.affiliates.mercadolivre import MercadoLivreProvider
from app.affiliates.shopee import ShopeeProvider
from app.config.settings import Settings, get_settings


class AffiliateRegistry:
    """
    Registry for managing and routing to store-specific affiliate providers.
    """

    def __init__(self, settings: Optional[Settings] = None):
        self.settings = settings or get_settings()
        self._providers: List[AffiliateProvider] = []
        self._init_default_providers()

    def _init_default_providers(self) -> None:
        self.register(AmazonProvider(tag=self.settings.AMAZON_TAG))
        self.register(MercadoLivreProvider(tag=self.settings.MERCADOLIVRE_TAG))
        self.register(ShopeeProvider(tag=self.settings.SHOPEE_TAG, app_id=self.settings.SHOPEE_APP_ID))

    def register(self, provider: AffiliateProvider) -> None:
        self._providers.append(provider)

    def get_provider(self, url: str) -> Optional[AffiliateProvider]:
        if not url:
            return None
        for provider in self._providers:
            if provider.can_handle(url):
                return provider
        return None

    def convert(self, url: str) -> Tuple[str, str, Optional[str]]:
        """
        Converts URL to affiliate URL.
        Returns:
            (affiliate_url, store_name, product_id)
        """
        if not url:
            return "", "unknown", None

        provider = self.get_provider(url)
        if provider:
            product_id = provider.extract_product_id(url)
            affiliate_url = provider.convert(url)
            return affiliate_url, provider.store_name, product_id

        # Fallback for unknown stores: clean basic tracking and return
        clean_url = self._clean_generic_url(url)
        store_name = self._extract_domain_name(url)
        return clean_url, store_name, None

    def _clean_generic_url(self, url: str) -> str:
        try:
            parsed = urllib.parse.urlparse(url)
            params = urllib.parse.parse_qs(parsed.query, keep_blank_values=True)
            for key in list(params.keys()):
                if key.lower().startswith(("utm_", "fbclid", "gclid", "msclkid", "ref_")):
                    params.pop(key, None)
            new_query = urllib.parse.urlencode(params, doseq=True)
            return urllib.parse.urlunparse(parsed._replace(query=new_query))
        except Exception:
            return url

    def _extract_domain_name(self, url: str) -> str:
        try:
            parsed = urllib.parse.urlparse(url)
            netloc = parsed.netloc.lower()
            # Strip www, www2, m.
            netloc = re.sub(r'^(?:www\d*|m)\.', '', netloc)
            parts = netloc.split(".")
            if len(parts) >= 3 and parts[-1] == "br" and parts[-2] in ("com", "net", "org", "gov", "edu"):
                return parts[-3]
            elif len(parts) >= 2:
                return parts[-2]
            return parts[0] if parts else "unknown"
        except Exception:
            return "unknown"
