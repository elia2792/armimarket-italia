import re
from typing import Any, Dict, List, Optional
from app.core.network import safe_http_get
from app.models.annuncio import (
    ClassificazioneArma,
    CondizioneArma,
    TipologiaArma,
)
from app.services.ingestion.base_adapter import BaseGunshopAdapter


class WooCommerceLiveAdapter(BaseGunshopAdapter):
    """
    Adapter per interfacciarsi con le API REST native di WooCommerce v3
    (endpoint /wp-json/wc/v3/products) di armerie partner online.
    """

    async def fetch_remote_products(
        self,
        base_url: str,
        consumer_key: Optional[str] = None,
        consumer_secret: Optional[str] = None,
        category: Optional[str] = None,
        per_page: int = 50,
        page: int = 1,
    ) -> List[Dict[str, Any]]:
        """
        Interroga le API REST di WooCommerce per estrarre il catalogo prodotti.
        """
        endpoint = base_url.rstrip("/")
        if not endpoint.endswith("/products"):
            endpoint = f"{endpoint}/wp-json/wc/v3/products"

        params: Dict[str, Any] = {
            "status": "publish",
            "per_page": per_page,
            "page": page,
        }
        if category:
            params["category"] = category

        auth = None
        if consumer_key and consumer_secret:
            auth = (consumer_key, consumer_secret)

        resp = await safe_http_get(
            endpoint,
            params=params,
            auth=auth,
            headers={"User-Agent": "ArmiMarket-Sync-Bot/1.0 (+https://armimarket.it)"},
            timeout=30.0
        )
        resp.raise_for_status()
        return resp.json()

    def fetch_feed(self, source: Any) -> List[Dict[str, Any]]:
        """Riceve la lista di prodotti grezza JSON restituita da WooCommerce."""
        if isinstance(source, list):
            return source
        elif isinstance(source, str):
            import json
            return json.loads(source)
        return []

    def normalize_item(self, raw_item: Dict[str, Any]) -> Dict[str, Any]:
        """
        Estrae attributi dal modello di prodotto WooCommerce (titolo, categorie, meta_data, attributes).
        """
        name = raw_item.get("name", "Arma in Catalogo")
        # Pulizia tag HTML dalla descrizione
        raw_desc = raw_item.get("description") or raw_item.get("short_description") or ""
        clean_desc = re.sub(r"<[^>]+>", "", raw_desc).strip() or "Descrizione tecnica da catalogo armeria."

        # Prezzo
        price_str = raw_item.get("price") or raw_item.get("regular_price") or "0"
        try:
            prezzo = float(price_str)
        except (ValueError, TypeError):
            prezzo = 0.0

        # Categorie WooCommerce
        categories = [c.get("name", "") for c in raw_item.get("categories", [])]
        cat_text = " ".join(categories).lower()

        # Attributi personalizzati (Calibro, Marca, Classificazione)
        attributes = {
            attr.get("name", "").lower(): " ".join(attr.get("options", []))
            for attr in raw_item.get("attributes", [])
        }

        # Tipologia Arma
        if any(w in cat_text for w in ["corta", "pistola", "revolver", "handgun"]):
            tipo_arma = TipologiaArma.ARMA_CORTA
        elif any(w in cat_text for w in ["rigata", "carabina", "bolt action", "rifle"]):
            tipo_arma = TipologiaArma.ARMA_LUNGA_RIGATA
        elif any(w in cat_text for w in ["liscia", "fucile", "sovrapposto", "semiautomatico", "doppietta"]):
            tipo_arma = TipologiaArma.CANNA_LISCIA
        elif any(w in cat_text for w in ["aria", "depotenziata", "7.5"]):
            tipo_arma = TipologiaArma.ARIA_COMPRESSA_LIBERA
        elif any(w in cat_text for w in ["ottica", "accessori", "red dot"]):
            tipo_arma = TipologiaArma.ACCESSORIO_OTTICA
        else:
            tipo_arma = TipologiaArma.ARMA_CORTA

        # Marca
        marca_raw = (
            attributes.get("marca")
            or attributes.get("brand")
            or raw_item.get("brand")
            or name.split()[0]
        )

        # Calibro
        calibro_raw = (
            attributes.get("calibro")
            or attributes.get("caliber")
            or self._detect_caliber_from_name(name)
        )

        # Classificazione
        cls_raw = attributes.get("classificazione", "").lower()
        if "sport" in cls_raw or "sportiv" in cat_text:
            classificazione = ClassificazioneArma.SPORTIVA
        elif "caccia" in cls_raw or "venator" in cat_text:
            classificazione = ClassificazioneArma.CACCIA
        elif "non" in cls_raw:
            classificazione = ClassificazioneArma.NON_APPLICABILE
        else:
            classificazione = ClassificazioneArma.COMUNE

        # Condizione (nuovo o usato)
        cond_raw = attributes.get("condizione", "").lower()
        if "usato" in cond_raw or "usato" in cat_text:
            condizione = CondizioneArma.USATO_OTTIMO
        else:
            condizione = CondizioneArma.NUOVO

        # Immagini
        images = [img.get("src") for img in raw_item.get("images", []) if img.get("src")]

        return {
            "titolo": name,
            "descrizione": clean_desc,
            "prezzo": prezzo,
            "marca": marca_raw,
            "modello": raw_item.get("sku") or name,
            "calibro": calibro_raw,
            "tipologia_arma": tipo_arma,
            "classificazione": classificazione,
            "condizione": condizione,
            "matricola": raw_item.get("sku"),
            "immagini": images,
        }

    def _detect_caliber_from_name(self, name: str) -> str:
        """Cerca denominazioni di calibri noti nel titolo del prodotto."""
        for pattern in self.CALIBER_MAP:
            m = re.search(pattern, name, flags=re.IGNORECASE)
            if m:
                return m.group(0)
        return "N/D"
