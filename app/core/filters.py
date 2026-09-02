import re
from typing import Optional
from app.core.models import FilterResult, Promotion
from app.config.settings import Settings, get_settings


class PromotionFilter:
    """
    Configurable filter engine for promotions.
    Enforces rules on price, discount, stores, categories, and keywords.
    """

    def __init__(self, settings: Optional[Settings] = None):
        self.settings = settings or get_settings()

    def evaluate(self, promotion: Promotion) -> FilterResult:
        # 1. Check blocked keywords in text and title
        blocked_keywords = self.settings.get_blocked_keywords()
        combined_text = f"{promotion.product_name} {promotion.original_text}".lower()
        for kw in blocked_keywords:
            if re.search(r'\b' + re.escape(kw) + r'\b', combined_text):
                return FilterResult(
                    passed=False,
                    reason=f"Palavra-chave bloqueada identificada: '{kw}'"
                )

        # 2. Check required keywords (if any configured)
        required_keywords = self.settings.get_required_keywords()
        if required_keywords:
            if not any(re.search(r'\b' + re.escape(kw) + r'\b', combined_text) for kw in required_keywords):
                return FilterResult(
                    passed=False,
                    reason=f"Nenhuma das palavras-chave obrigatórias foi encontrada"
                )

        # 3. Check blocked stores
        blocked_stores = self.settings.get_blocked_stores()
        if promotion.store and promotion.store.lower() in blocked_stores:
            return FilterResult(
                passed=False,
                reason=f"Loja bloqueada: '{promotion.store}'"
            )

        # 4. Check allowed stores (if whitelist is active)
        allowed_stores = self.settings.get_allowed_stores()
        if allowed_stores and promotion.store:
            if promotion.store.lower() not in allowed_stores:
                return FilterResult(
                    passed=False,
                    reason=f"Loja não permitida: '{promotion.store}'"
                )

        # 5. Check blocked categories
        blocked_categories = self.settings.get_blocked_categories()
        if promotion.category and promotion.category.lower() in blocked_categories:
            return FilterResult(
                passed=False,
                reason=f"Categoria bloqueada: '{promotion.category}'"
            )

        # 6. Check allowed categories
        allowed_categories = self.settings.get_allowed_categories()
        if allowed_categories and promotion.category:
            if promotion.category.lower() not in allowed_categories:
                return FilterResult(
                    passed=False,
                    reason=f"Categoria não permitida: '{promotion.category}'"
                )

        # 7. Check minimum discount percentage
        if self.settings.MIN_DISCOUNT_PERCENT > 0:
            if promotion.discount_percentage is not None:
                if promotion.discount_percentage < self.settings.MIN_DISCOUNT_PERCENT:
                    return FilterResult(
                        passed=False,
                        reason=f"Desconto ({promotion.discount_percentage:.1f}%) abaixo do mínimo configurado ({self.settings.MIN_DISCOUNT_PERCENT:.1f}%)"
                    )

        # 8. Check maximum price
        if self.settings.MAX_PRICE is not None and promotion.sale_price is not None:
            if promotion.sale_price > self.settings.MAX_PRICE:
                return FilterResult(
                    passed=False,
                    reason=f"Preço (R$ {promotion.sale_price:.2f}) acima do teto configurado (R$ {self.settings.MAX_PRICE:.2f})"
                )

        # 9. Check minimum price
        if self.settings.MIN_PRICE is not None and promotion.sale_price is not None:
            if promotion.sale_price < self.settings.MIN_PRICE:
                return FilterResult(
                    passed=False,
                    reason=f"Preço (R$ {promotion.sale_price:.2f}) abaixo do piso configurado (R$ {self.settings.MIN_PRICE:.2f})"
                )

        return FilterResult(passed=True, reason=None)
