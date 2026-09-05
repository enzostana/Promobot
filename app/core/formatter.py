from typing import Optional
import re
from app.core.models import Promotion

_URL_RE = re.compile(r"(?:https?://|www\.)\S+", re.IGNORECASE)


class PromotionFormatter:
    """
    Decoupled formatter for promotions.
    Renders structured Promotion objects into standardized presentation messages.
    """

    DEFAULT_DISCLAIMER = "⚡ Oferta sujeita a alteração de preço/estoque."

    def __init__(self, template: Optional[str] = None):
        self.template = template

    def format_currency(self, value: Optional[float]) -> str:
        """
        Formats float into Brazilian Real notation:
        Examples:
            1899.0 -> "1.899"
            1899.90 -> "1.899,90"
            99.5 -> "99,50"
        """
        if value is None:
            return ""
        # Check if value has fractional cents
        if value.is_integer():
            formatted = f"{int(value):,}".replace(",", ".")
        else:
            formatted = f"{value:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")
        return formatted

    def format(self, promotion: Promotion) -> str:
        """
        Generates the standard promotion message according to the project template.
        """
        lines = []

        # Product Title
        product_title = promotion.product_name.strip() if promotion.product_name else "Oferta Especial"
        product_title = _URL_RE.sub("", product_title)
        product_title = re.sub(r"\s+", " ", product_title).strip()
        if not product_title:
            product_title = "Oferta Especial"
        lines.append(f"🔥 {product_title}")
        lines.append("")

        # Price Block
        price_lines = []
        if promotion.original_price is not None and promotion.original_price > 0:
            formatted_orig = self.format_currency(promotion.original_price)
            price_lines.append(f"💰 De: R$ {formatted_orig}")

        if promotion.sale_price is not None and promotion.sale_price > 0:
            formatted_sale = self.format_currency(promotion.sale_price)
            price_lines.append(f"🔥 Por: R$ {formatted_sale}")
        elif not price_lines:
            # If no price detected, skip price line or show info
            pass

        if price_lines:
            lines.extend(price_lines)
            lines.append("")

        # Discount Block
        if promotion.discount_percentage is not None and promotion.discount_percentage > 0:
            disc_str = f"{int(promotion.discount_percentage)}" if promotion.discount_percentage.is_integer() else f"{promotion.discount_percentage:.1f}"
            lines.append(f"📉 {disc_str}% OFF")
            lines.append("")

        # Call to Action & Link
        target_link = promotion.affiliate_url or promotion.original_url
        lines.append("🛒 COMPRAR AGORA")
        lines.append(target_link)
        lines.append("")

        # Disclaimer
        lines.append(self.DEFAULT_DISCLAIMER)

        return "\n".join(lines).strip()
