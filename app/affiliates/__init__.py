from app.affiliates.base import AffiliateProvider
from app.affiliates.amazon import AmazonProvider
from app.affiliates.mercadolivre import MercadoLivreProvider
from app.affiliates.shopee import ShopeeProvider
from app.affiliates.registry import AffiliateRegistry

__all__ = [
    "AffiliateProvider",
    "AmazonProvider",
    "MercadoLivreProvider",
    "ShopeeProvider",
    "AffiliateRegistry",
]
