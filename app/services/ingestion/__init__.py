from app.services.ingestion.base_adapter import BaseGunshopAdapter
from app.services.ingestion.mock_adapter import MockWooCommerceShopAdapter
from app.services.ingestion.woocommerce_adapter import WooCommerceLiveAdapter
from app.services.ingestion.xml_adapter import XmlFeedAdapter

__all__ = [
    "BaseGunshopAdapter",
    "MockWooCommerceShopAdapter",
    "WooCommerceLiveAdapter",
    "XmlFeedAdapter",
]
