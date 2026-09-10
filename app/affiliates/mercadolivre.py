import logging
import re
import unicodedata
import urllib.parse
from difflib import SequenceMatcher
from typing import Callable, Optional, Tuple

import httpx

from app.affiliates.base import AffiliateProvider
from app.affiliates.meli_mint import (
    MeliLinkMinter,
    MeliMintError,
    MeliRateLimited,
    MeliSessionExpired,
    MeliUrlNotAllowed,
)

logger = logging.getLogger(__name__)

_BROWSER_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/120 Safari/537.36",
    "Accept-Language": "pt-BR,pt;q=0.9,en-US;q=0.8",
}


def _read_session_file(path: Optional[str]) -> Optional[str]:
    if not path:
        return None
    try:
        with open(path, "r", encoding="utf-8") as fh:
            value = fh.read().strip()
        return value or None
    except OSError:
        return None


class MercadoLivreProvider(AffiliateProvider):
    """
    Mercado Livre Affiliate Link Converter.
    Extracts MLB product identifier and injects affiliate tracking parameter.

    Short links (meli.la/<code>) resolve to a channel's *social* profile page
    (e.g. /social/guru) whose click attribution belongs to the channel. To rebind
    attribution to the user's own tag, the resolver follows the redirect, parses
    the product actually shared in the post (first canonical /p/MLB<id> link, which
    matches the page's og:title) and rebuilds a canonical product URL carrying the
    user's matt_tool.
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
    SHORTLINK_PATTERN = re.compile(r'^meli\.la$', re.IGNORECASE)
    OG_TITLE_REGEX = re.compile(r'property="og:title"\s+content="([^"]+)"', re.IGNORECASE)
    PRODUCT_LINK_REGEX = re.compile(r'https://www\.mercadolivre\.com\.br/([a-z0-9\-]+/p/MLB(\d+))', re.IGNORECASE)

    def __init__(self,
                 tag: Optional[str] = None,
                 word: Optional[str] = None,
                 route: str = "product",
                 resolver: Optional[Callable[[str], str]] = None,
                 page_fetcher: Optional[Callable[[str], str]] = None,
                 mint: bool = False,
                 session_file: Optional[str] = None,
                 session: Optional[str] = None):
        self.tag = tag
        self.word = word
        self.route = route
        self.mint_enabled = mint
        self._resolver = resolver or self._resolve_shortlink
        self._page_fetcher = page_fetcher or self._fetch_page
        self._mint_session = session or _read_session_file(session_file)
        self._minter = MeliLinkMinter(ssid=self._mint_session, word=word) if mint else None

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

    def _is_shortlink(self, url: str) -> bool:
        try:
            return bool(self.SHORTLINK_PATTERN.fullmatch(urllib.parse.urlparse(url).netloc.lower()))
        except Exception:
            return False

    def _resolve_shortlink(self, url: str) -> str:
        """Follows the meli.la redirect chain and returns the final URL."""
        try:
            with httpx.Client(follow_redirects=True, timeout=10.0, headers=_BROWSER_HEADERS) as client:
                resp = client.get(url)
                return str(resp.url)
        except Exception as e:
            logger.warning(f"[MELI] Falha ao resolver shortlink {url}: {e}")
            return ""

    def _fetch_page(self, url: str) -> str:
        """Fetches the resolved social page HTML."""
        try:
            with httpx.Client(follow_redirects=True, timeout=12.0, headers=_BROWSER_HEADERS) as client:
                resp = client.get(url)
                return resp.text
        except Exception as e:
            logger.warning(f"[MELI] Falha ao buscar página social {url}: {e}")
            return ""

    @staticmethod
    def _normalize(title: str) -> str:
        """Lowercases, strips accents and collapses to hyphen-separated words."""
        title = unicodedata.normalize("NFKD", title)
        title = "".join(c for c in title if not unicodedata.combining(c))
        title = title.lower()
        return "-".join(re.findall(r"[a-z0-9]+", title))

    def extract_product_from_page(self, html: str) -> Optional[Tuple[str, str]]:
        """
        Returns (canonical product URL, mlb_id) for the product shared in the
        social post. The product actually shared is the first /p/MLB link whose
        slug best matches the page's og:title (the remaining links are related
        recommendations from the profile).
        """
        if not html:
            return None

        og_match = self.OG_TITLE_REGEX.search(html)
        og_title_norm = self._normalize(og_match.group(1)) if og_match else ""

        candidates = []
        for slug, mlb_id in self.PRODUCT_LINK_REGEX.findall(html):
            slug_norm = self._normalize(slug.split("/p/")[0])
            similarity = SequenceMatcher(None, og_title_norm, slug_norm).ratio() if og_title_norm else 0.0
            candidates.append((slug_norm, similarity, slug, mlb_id))

        if not candidates:
            return None

        # Highest similarity wins; ties keep first occurrence (stable sort).
        best_slug_norm, best_sim, best_slug, best_mlb = sorted(
            candidates, key=lambda c: (-c[1])
        )[0]
        if og_title_norm and best_sim < 0.5:
            logger.warning(f"[MELI] Nenhum produto da página social bate com og:title (sim={best_sim:.2f}); usando primeiro link.")
        return f"https://www.mercadolivre.com.br/{best_slug}", best_mlb

    def _rewrite_tracking(self, url: str) -> str:
        """Drops third-party MELI tracking params and injects the user's tag.

        Essentially cleans the URL down to a single product page bound to the
        user's attribution (matt_tool + matt_word). The fragment and the channel
        offer/deal params (#polycard_client, pdp_filters, deal_print_id, ...) are
        removed so visitors land on the product itself — never on a listing page.

        matt_word (the affiliate's campaign/profile handle) is kept as the user's
        own value: the product page uses it to bind attribution for the affiliate
        headline/banner shown to visitors.
        """
        parsed = urllib.parse.urlparse(url)
        params = urllib.parse.parse_qs(parsed.query, keep_blank_values=True)

        # Remove channel-provided, offer-page and extraneous tracking params
        tracking_params = [
            "matt_tool", "matt_word", "tracking_id", "utm_source", "utm_medium", "utm_campaign",
            "pdp_filters", "polycard_client", "deal_print_id", "position", "sid",
            "wid", "searchVariation", "ref",
        ]
        for p in tracking_params:
            params.pop(p, None)

        if self.tag:
            params["matt_tool"] = [self.tag]
        if self.word:
            params["matt_word"] = [self.word]

        new_query = urllib.parse.urlencode(params, doseq=True)
        return urllib.parse.urlunparse(parsed._replace(query=new_query, fragment=""))

    def _build_social_url(self) -> str:
        """Legacy profile-page link (the affiliate's full product list).

        Kept only for reference: posts must link the single offered product, so
        this is no longer used by ``convert``. Visitors landing here see the whole
        list, which is exactly what we avoid.
        """
        parsed = urllib.parse.urlparse("https://www.mercadolivre.com.br/social/")
        params = {"forceInApp": "true"}
        if self.tag:
            params["matt_tool"] = self.tag
        if self.word:
            params["matt_word"] = self.word
        new_url = f"{parsed.scheme}://{parsed.netloc}/social/{self.word}"
        return urllib.parse.urlunparse(parsed._replace(path=f"/social/{self.word}", query=urllib.parse.urlencode(params)))

    def _try_mint(self, url: str) -> Optional[str]:
        """Attempts official link minting; returns the /sec/ URL or None."""
        if not self._minter or not self._minter.available:
            return None

        canonical = self._minter.canonicalize(url)
        if not canonical:
            return None

        try:
            minted = self._minter.create_links([canonical])
        except MeliSessionExpired as e:
            logger.warning(f"[MELI] {e} (link oficial indisponível; usando fallback).")
            return None
        except MeliRateLimited as e:
            logger.warning(f"[MELI] {e} (usando fallback).")
            return None
        except MeliUrlNotAllowed:
            logger.warning("[MELI] Produto inelegível para o programa de afiliados; usando fallback.")
            return None
        except MeliMintError as e:
            logger.warning(f"[MELI] {e} (usando fallback).")
            return None

        short = minted.get(canonical)
        if short:
            logger.info("[MELI] Link oficial mintado para o produto.")
        return short

    def _is_own_official_link(self, url: str) -> bool:
        """True when the shortlink already resolves to this affiliate's headline page.

        Official minted /sec links resolve to ``/social/<word>?ref=<signed>`` — the
        page that renders the product's headline. Passing them through unchanged keeps
        the headline; re-resolving them into a bare product URL loses it.
        """
        if not self.word or not self._is_shortlink(url):
            return False
        resolved = self._resolver(url)
        return bool(resolved and f"/social/{self.word}" in resolved)

    def convert(self, url: str) -> str:
        if not url:
            return ""

        # Already an official link of this affiliate (minted earlier): keep it so
        # the headline is preserved.
        if self._is_own_official_link(url):
            logger.info("[MELI] Link oficial do afiliado detectado; mantendo intacto.")
            return url

        # Preferred: official minted link — lands on the single product with the
        # affiliate's headline attribution.
        official = self._try_mint(url)
        if official:
            return official

        # Fallback: the single product page bound to the user's tag. Never the
        # affiliate's /social/ listing page.
        if self._minter:
            canonical = self._minter.canonicalize(url)
            if canonical:
                logger.info(f"[MELI] Mint indisponível; fallback para produto: {canonical}")
                return self._rewrite_tracking(canonical)

        if self._is_shortlink(url):
            resolved = self._resolver(url)
            if not resolved:
                # Network failure: fall back to annotating the shortlink itself.
                return self._rewrite_tracking(url)

            html = self._page_fetcher(resolved)
            product = self.extract_product_from_page(html)
            if product:
                canonical_url, mlb_id = product
                logger.info(f"[MELI] Shortlink resolvido -> produto {mlb_id}; rebind matt_tool={self.tag}")
                return self._rewrite_tracking(canonical_url)

            # Page did not expose the product: keep the resolved URL but rebind
            # attribution on it as best effort.
            logger.warning("[MELI] Não foi possível extrair produto da página social; usando URL resolvida.")
            return self._rewrite_tracking(resolved)

        return self._rewrite_tracking(url)
