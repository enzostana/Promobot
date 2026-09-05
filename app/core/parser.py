import re
import urllib.parse
from typing import List, Optional, Tuple
from app.core.models import ParsedPromotion, RawMessage


class PromotionParser:
    """
    Parser for promotion messages.
    Extracts URLs, stores, product titles, prices (original and promotional),
    discounts, and categories from unstructured text.
    """

    # URL regex: matches standard URLs, markdown links, HTML href
    URL_REGEX = re.compile(
        r'(?:https?://|www\.)[^\s<>"\'\)\]\}]+',
        re.IGNORECASE
    )
    MARKDOWN_URL_REGEX = re.compile(
        r'\[([^\]]+)\]\((https?://[^\s\)]+)\)',
        re.IGNORECASE
    )
    HTML_URL_REGEX = re.compile(
        r'<a\s+(?:[^>]*?\s+)?href=["\'](https?://[^"\']+)["\']',
        re.IGNORECASE
    )

    # Store mapping
    STORE_DOMAINS = {
        "amazon": [r"amazon\.com(\.br)?", r"amzn\.to", r"a\.co"],
        "mercadolivre": [r"mercadolivre\.com(\.br)?", r"mercadolibre\.com", r"produto\.mercadolivre\.com\.br", r"meli\.la"],
        "shopee": [r"shopee\.com\.br", r"shope\.ee", r"s\.shopee\.com\.br"],
        "magalu": [r"magazineluiza\.com\.br", r"magalu\.me"],
        "aliexpress": [r"aliexpress\.com", r"aliexpress\.com\.br", r"s\.click\.aliexpress\.com"],
    }

    # Price patterns
    PRICE_ORIGINAL_REGEX = re.compile(
        r'(?i)(?:de|preço\s*original|de\s*r\$|de:)\s*:?\s*R?\$?\s*([0-9\.\,]+)'
    )
    PRICE_SALE_REGEX = re.compile(
        r'(?i)(?:por|a\s*partir\s*de|apenas|por\s*r\$|por:)\s*:?\s*R?\$?\s*([0-9\.\,]+)'
    )
    PRICE_GENERIC_REGEX = re.compile(
        r'R\$\s*([0-9\.\,]+)'
    )
    DISCOUNT_EXPLICIT_REGEX = re.compile(
        r'(\d+(?:[\.,]\d+)?)\s*%\s*(?:OFF|off|de\s+desconto|desc\.?)'
    )

    # Noise emojis and headers to clean from titles
    TITLE_CLEANUP_REGEX = re.compile(
        r'^[\s🔥⚡🚨💥📢🎯🛒🏷️👉👇🔝📌📍‼️\[\]\(\)\-\*\_]+|[\s🔥⚡🚨💥📢🎯🛒🏷️👉👇🔝📌📍‼️\[\]\(\)\-\*\_]+$',
        re.UNICODE
    )

    GENERIC_BANNER_WORDS = {
        "mega oferta", "oferta", "ofertas", "promocao", "promoção", "promocoes", "promoções",
        "super oferta", "oferta do dia", "achadinho", "achadinhos", "imperdível", "imperdivel",
        "corre", "corre!", "atenção", "atencao", "alerta de promo", "alerta de promoção"
    }

    def parse(self, message: RawMessage) -> ParsedPromotion:
        raw_text = message.text or ""
        urls = self.extract_urls(raw_text)
        if message.urls:
            for u in message.urls:
                if u not in urls:
                    urls.append(u)

        primary_url = self._select_primary_url(urls)
        store = self.identify_store(primary_url) if primary_url else None
        orig_price, sale_price = self.extract_prices(raw_text)
        discount = self.extract_discount(raw_text, orig_price, sale_price)
        product_name = self.extract_product_name(raw_text, urls)
        category = self.infer_category(raw_text, product_name)

        return ParsedPromotion(
            product_name=product_name,
            description=self._extract_description(raw_text),
            original_price=orig_price,
            sale_price=sale_price,
            discount_percentage=discount,
            store=store,
            original_url=primary_url,
            all_urls=urls,
            category=category,
        )

    def extract_urls(self, text: str) -> List[str]:
        urls: List[str] = []
        if not text:
            return urls

        for _, link in self.MARKDOWN_URL_REGEX.findall(text):
            cleaned = self._clean_url(link)
            if cleaned and cleaned not in urls:
                urls.append(cleaned)

        for link in self.HTML_URL_REGEX.findall(text):
            cleaned = self._clean_url(link)
            if cleaned and cleaned not in urls:
                urls.append(cleaned)

        for match in self.URL_REGEX.findall(text):
            cleaned = self._clean_url(match)
            if cleaned and cleaned not in urls:
                urls.append(cleaned)

        return urls

    def _clean_url(self, url: str) -> str:
        url = url.strip()
        url = re.sub(r'[\.,;:!\?\)\]\>]+$', '', url)
        if url.startswith("www."):
            url = "https://" + url
        return url

    def identify_store(self, url: Optional[str]) -> Optional[str]:
        if not url:
            return None
        try:
            parsed = urllib.parse.urlparse(url)
            netloc = parsed.netloc.lower()
            if not netloc and parsed.path:
                netloc = parsed.path.split("/")[0].lower()

            for store, patterns in self.STORE_DOMAINS.items():
                for pattern in patterns:
                    if re.search(pattern, netloc, re.IGNORECASE):
                        return store

            netloc = re.sub(r'^(?:www\d*|m)\.', '', netloc)
            parts = netloc.split(".")
            if len(parts) >= 3 and parts[-1] == "br" and parts[-2] in ("com", "net", "org"):
                return parts[-3]
            elif len(parts) >= 2:
                return parts[-2]
            return parts[0] if parts else "unknown"
        except Exception:
            return "unknown"

    def _select_primary_url(self, urls: List[str]) -> Optional[str]:
        if not urls:
            return None
        for url in urls:
            store = self.identify_store(url)
            if store and store in self.STORE_DOMAINS:
                return url
        return urls[0]

    def parse_number(self, value_str: str) -> Optional[float]:
        if not value_str:
            return None
        val = value_str.strip().replace(" ", "")
        val = re.sub(r'[^\d\.,]', '', val)
        if not val:
            return None

        if "." in val and "," in val:
            dot_idx = val.rfind(".")
            comma_idx = val.rfind(",")
            if comma_idx > dot_idx:
                val = val.replace(".", "").replace(",", ".")
            else:
                val = val.replace(",", "")
            try:
                return float(val)
            except ValueError:
                return None

        if "," in val:
            val = val.replace(",", ".")
            try:
                return float(val)
            except ValueError:
                return None

        if "." in val:
            parts = val.split(".")
            if len(parts) == 2 and len(parts[1]) == 3 and int(parts[0]) > 0:
                val = val.replace(".", "")
            try:
                return float(val)
            except ValueError:
                return None

        try:
            return float(val)
        except ValueError:
            return None

    def extract_prices(self, text: str) -> Tuple[Optional[float], Optional[float]]:
        if not text:
            return None, None

        orig_price: Optional[float] = None
        sale_price: Optional[float] = None

        orig_match = self.PRICE_ORIGINAL_REGEX.search(text)
        if orig_match:
            orig_price = self.parse_number(orig_match.group(1))

        sale_match = self.PRICE_SALE_REGEX.search(text)
        if sale_match:
            sale_price = self.parse_number(sale_match.group(1))

        if sale_price is not None:
            return orig_price, sale_price

        all_prices: List[float] = []
        for match in self.PRICE_GENERIC_REGEX.finditer(text):
            p = self.parse_number(match.group(1))
            if p is not None and p > 0:
                all_prices.append(p)

        if len(all_prices) == 1:
            sale_price = all_prices[0]
        elif len(all_prices) >= 2:
            p1, p2 = all_prices[0], all_prices[1]
            if p1 > p2:
                orig_price, sale_price = p1, p2
            else:
                orig_price, sale_price = None, p1

        return orig_price, sale_price

    def extract_discount(
        self, text: str, orig_price: Optional[float], sale_price: Optional[float]
    ) -> Optional[float]:
        match = self.DISCOUNT_EXPLICIT_REGEX.search(text)
        if match:
            disc_str = match.group(1).replace(",", ".")
            try:
                return round(float(disc_str), 1)
            except ValueError:
                pass

        if orig_price and sale_price and orig_price > sale_price > 0:
            calc_discount = ((orig_price - sale_price) / orig_price) * 100.0
            return round(calc_discount, 1)

        return None

    def extract_product_name(self, text: str, urls: List[str]) -> str:
        if not text:
            return "Oferta Especial"

        for match in self.MARKDOWN_URL_REGEX.finditer(text):
            link_text = match.group(1).strip()
            if len(link_text) > 3 and not link_text.lower().startswith(("compre", "clique", "acesse", "link")):
                return self._clean_title(link_text)

        lines = [line.strip() for line in text.splitlines() if line.strip()]
        for line in lines:
            # Skip hashtag lines
            if line.startswith("#"):
                continue
            # Skip lines that are just URLs
            if any(url in line for url in urls) and len(line.split()) <= 2:
                continue
            # Skip lines that are exclusively price indicators
            if self.PRICE_ORIGINAL_REGEX.match(line) or self.PRICE_SALE_REGEX.match(line):
                continue
            # Skip lines that are short tags like "CUPOM:", "FRETE GRÁTIS"
            if line.lower().startswith(("cupom", "frete", "compre aqui", "link:", "corre", "pega")):
                continue

            cleaned = self._clean_title(line)
            # Strip any embedded URLs so the product name never carries a raw link
            cleaned = self.URL_REGEX.sub("", cleaned)
            cleaned = re.sub(r"\s+", " ", cleaned).strip()
            # Skip generic banners like "MEGA OFERTA"
            if cleaned.lower() in self.GENERIC_BANNER_WORDS:
                continue

            if len(cleaned) >= 4:
                return cleaned

        return "Oferta Especial"

    def _clean_title(self, title: str) -> str:
        title = self.TITLE_CLEANUP_REGEX.sub("", title)
        title = re.sub(r'[\*_~`]', '', title)
        title = re.sub(r'\s+', ' ', title).strip()
        return title

    def infer_category(self, text: str, title: str) -> Optional[str]:
        haystack = f"{title} {text}".lower()
        categories = {
            "eletronicos": ["tv", "smart tv", "smartphone", "celular", "monitor", "fone", "bluetooth", "notebook", "tablet", "fone de ouvido"],
            "informatica": ["teclado", "mouse", "ssd", "ram", "placa de vídeo", "processador", "pc gamer"],
            "eletrodomesticos": ["geladeira", "fogao", "microondas", "air fryer", "aspirador", "maquina de lavar", "cafeteira"],
            "games": ["playstation", "ps5", "xbox", "nintendo", "switch", "game", "console"],
            "casa": ["panela", "travesseiro", "colchao", "sofa", "cadeira", "mesa"],
            "moda": ["tenis", "camiseta", "calca", "mochila", "relogio"],
        }
        for cat, keywords in categories.items():
            if any(re.search(r'\b' + re.escape(kw) + r'\b', haystack) for kw in keywords):
                return cat
        return None

    def _extract_description(self, text: str) -> Optional[str]:
        cleaned = text.strip()
        return cleaned if cleaned else None
