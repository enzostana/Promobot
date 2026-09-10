import logging
import re
import time
import urllib.parse
from typing import Dict, List, Optional, Tuple

import httpx

logger = logging.getLogger(__name__)

_MEL_BASE = "https://www.mercadolivre.com.br"
_LINKBUILDER_PATH = "/afiliados/linkbuilder"
_TAGS_PATH = "/affiliate-program/api/v2/stripe/user/tags"
_CREATE_LINK_PATH = "/affiliate-program/api/v2/affiliates/createLink"

_BROWSER_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/120 Safari/537.36",
    "Accept-Language": "pt-BR,pt;q=0.9,en-US;q=0.8",
}

# Short-link patterns accepted for normalization to a canonical product page.
_CANONICAL_PRODUCT_RE = re.compile(
    r'https://www\.mercadolivre\.com\.br/(?:[^?#]*/p/MLB\d+)(?:[/?#]|$)',
    re.IGNORECASE,
)
# Item pages (produto.mercadolivre.com.br/MLB-####-<slug>-_JM) also carry an MLB id.
_ITEM_PRODUCT_RE = re.compile(
    r'https://produto\.mercadolivre\.com\.br/MLB-?\d+-[^?#]+',
    re.IGNORECASE,
)
_SLL_PATTERN = re.compile(r's\.meli\.la|meli\.la', re.IGNORECASE)


class MeliMintError(Exception):
    """Base error for official-link minting failures."""


class MeliSessionExpired(MeliMintError):
    """The stored session is no longer valid (403/401)."""


class MeliRateLimited(MeliMintError):
    """Exceeded request volume (429)."""


class MeliUrlNotAllowed(MeliMintError):
    """The product URL was rejected by the affiliate program (code 111)."""


class MeliLinkMinter:
    """Mints official MELI affiliate links (`mercadolivre.com/sec/<code>`).

    Replicates the exact flow the Central's "Gerador de Links" uses, driven by
    the affiliate's own session cookie (`ssid`). The session value is read from
    a docker secret / env and is never logged.
    """

    TIMEOUT = 15.0
    BATCH_SIZE = 20

    def __init__(self, ssid: Optional[str] = None, word: Optional[str] = None,
                 transport: Optional[httpx.BaseTransport] = None):
        self._ssid = ssid
        self._word = word
        self._transport = transport
        self._temp_cookies: Dict[str, str] = {}
        self._csrf_token: Optional[str] = None
        self._tag_in_use: Optional[str] = None
        self._tags_checked_at: float = 0.0
        self._cache: Dict[Tuple[str, str], str] = {}
        self._client: Optional[httpx.Client] = None

    @property
    def available(self) -> bool:
        return bool(self._ssid)

    def _new_client(self) -> httpx.Client:
        cookies = {"ssid": self._ssid} if self._ssid else {}
        cookies.update(self._temp_cookies)
        headers = _BROWSER_HEADERS.copy()
        headers.update({
            "Accept": "application/json",
            "Origin": _MEL_BASE,
            "Referer": f"{_MEL_BASE}{_LINKBUILDER_PATH}",
        })
        if self._csrf_token:
            headers["X-CSRF-Token"] = self._csrf_token
        return httpx.Client(
            base_url=_MEL_BASE,
            headers=headers,
            cookies=cookies,
            timeout=self.TIMEOUT,
            transport=self._transport,
        )

    def _process_set_cookies(self, resp: httpx.Response) -> None:
        for cookie in resp.headers.get_list("set-cookie"):
            for part in cookie.split(";")[0].split(","):
                part = part.strip()
                if "=" in part:
                    key, _, value = part.partition("=")
                    key = key.strip()
                    if key in ("_csrf", "_d2id", "_mldataSessionId"):
                        self._temp_cookies[key] = value
                        if key == "_csrf":
                            self._csrf_token = value

    def _ensure_bootstrap(self) -> None:
        if not self.available:
            raise MeliSessionExpired("Sem sessão ssid configurada.")

        if self._csrf_token and self._temp_cookies.get("_csrf"):
            return

        try:
            client = self._new_client()
            resp = client.get(_LINKBUILDER_PATH)
            self._process_set_cookies(resp)
        except httpx.HTTPStatusError as e:
            if e.response.status_code in (401, 403):
                raise MeliSessionExpired(f"Bootstrap rejeitado (HTTP {e.response.status_code}).")
            raise MeliMintError(f"Bootstrap falhou: HTTP {e.response.status_code}") from e
        except httpx.HTTPError as e:
            raise MeliMintError(f"Bootstrap sem resposta: {e}") from e

        if not self._csrf_token:
            if resp.status_code in (401, 403):
                raise MeliSessionExpired("Bootstrap sem _csrf (sessão inválida).")
            raise MeliMintError("Bootstrap não forneceu _csrf.")

    def _ensure_tag(self, client: httpx.Client) -> str:
        if self._tag_in_use:
            return self._tag_in_use

        if time.monotonic() - self._tags_checked_at > 300:
            try:
                resp = client.get(_TAGS_PATH)
                if resp.status_code == 200:
                    tags = resp.json()
                    if isinstance(tags, list):
                        for item in tags:
                            if item.get("in_use"):
                                self._tag_in_use = item.get("name")
                                break
                        if not self._tag_in_use and tags:
                            self._tag_in_use = tags[0].get("name")
                        self._tags_checked_at = time.monotonic()
                    elif isinstance(tags, dict) and tags.get("name"):
                        self._tag_in_use = tags.get("name")
                        self._tags_checked_at = time.monotonic()
            except Exception:
                logger.debug("[MELI-MINT] Falha ao consultar etiquetas; usando fallback configurado.")

        return self._tag_in_use or (self._word or "")

    def canonicalize(self, url: str) -> str:
        """Resolves short links and normalizes to a clean product URL (no query/fragment)."""
        url = url.strip().strip("\"'")

        if _SLL_PATTERN.search(urllib.parse.urlparse(url).netloc):
            try:
                with httpx.Client(follow_redirects=True, timeout=10.0, headers=_BROWSER_HEADERS) as c:
                    url = str(c.get(url).url)
            except Exception:
                return ""

        if _CANONICAL_PRODUCT_RE.match(url) or _ITEM_PRODUCT_RE.match(url):
            parsed = urllib.parse.urlparse(url)
            return urllib.parse.urlunparse(parsed._replace(query="", fragment=""))
        return ""

    def create_links(self, urls: List[str]) -> Dict[str, str]:
        """Returns {origin_url: official_short_url} for the eligible URLs."""
        result: Dict[str, str] = {}
        if not self.available or not urls:
            return result

        pending = [u for u in urls if (u, "official") not in self._cache]
        deduped = list(pending)

        for batch in (deduped[i:i + self.BATCH_SIZE] for i in range(0, len(deduped), self.BATCH_SIZE)):
            try:
                self._ensure_bootstrap()
            except MeliMintError:
                raise

            client = self._new_client()
            try:
                tag = self._ensure_tag(client)
                payload = {"urls": batch, "tag": tag}
                resp = client.post(_CREATE_LINK_PATH, json=payload)
                if resp.status_code in (401, 403):
                    self._temp_cookies = {}
                    self._csrf_token = None
                    raise MeliSessionExpired(f"Sessão rejeitada (HTTP {resp.status_code}).")
                if resp.status_code == 429:
                    raise MeliRateLimited("Rate limit do endpoint de afiliados (429).")
                if resp.status_code >= 400:
                    raise MeliMintError(f"createLink respondeu HTTP {resp.status_code}.")

                body = resp.json()
                entries = body.get("urls") or []
                if not entries:
                    logger.warning(f"[MELI-MINT] createLink 200 sem entries; corpo: {str(body)[:300]}")
                for entry in entries:
                    origin = entry.get("origin_url")
                    short = entry.get("short_url")
                    if origin and short:
                        self._cache[(origin, "official")] = short
                        result[origin] = short
                    elif origin:
                        error_code = entry.get("error_code")
                        logger.warning(
                            f"[MELI-MINT] sem short_url: {origin} (error_code={error_code}, "
                            f"chaves={sorted(entry)[:8]})"
                        )
            finally:
                client.close()

        # Cache-aware: any URL already minted this process keeps its link.
        for u in urls:
            if u in self._cache and (u, "official") in self._cache:
                result[u] = self._cache[(u, "official")]
        return result

    def close(self) -> None:
        if self._client is not None:
            self._client.close()
            self._client = None