import json
from typing import Any, Dict, List
from app.models.annuncio import (
    ClassificazioneArma,
    CondizioneArma,
    TipologiaArma,
)
from app.services.ingestion.base_adapter import BaseGunshopAdapter


class MockWooCommerceShopAdapter(BaseGunshopAdapter):
    """
    Adapter per feed JSON esportati da negozi online armeria basati su WooCommerce o PrestaShop.
    """

    def fetch_feed(self, source: Any) -> List[Dict[str, Any]]:
        """Carica il feed da stringa JSON, file o dizionario."""
        if isinstance(source, str):
            return json.loads(source)
        elif isinstance(source, list):
            return source
        return []

    def normalize_item(self, raw_item: Dict[str, Any]) -> Dict[str, Any]:
        """Estrae gli attributi WooCommerce e li mappa sullo schema Annuncio."""
        # Mappatura tipologia arma da stringhe e-commerce
        cat = str(raw_item.get("category", "")).lower()
        if "corta" in cat or "pistola" in cat or "revolver" in cat:
            tipo_arma = TipologiaArma.ARMA_CORTA
        elif "rigata" in cat or "carabina" in cat or "fucile rigato" in cat:
            tipo_arma = TipologiaArma.ARMA_LUNGA_RIGATA
        elif "liscia" in cat or "sovrapposto" in cat or "semiautomatico caccia" in cat:
            tipo_arma = TipologiaArma.CANNA_LISCIA
        elif "aria" in cat or "depotenziata" in cat:
            tipo_arma = TipologiaArma.ARIA_COMPRESSA_LIBERA
        elif "ottica" in cat or "accessori" in cat:
            tipo_arma = TipologiaArma.ACCESSORIO_OTTICA
        else:
            tipo_arma = TipologiaArma.ARMA_CORTA

        # Mappatura classificazione
        cls_raw = str(raw_item.get("classificazione", "")).lower()
        if "sport" in cls_raw:
            classificazione = ClassificazioneArma.SPORTIVA
        elif "caccia" in cls_raw:
            classificazione = ClassificazioneArma.CACCIA
        elif "non" in cls_raw:
            classificazione = ClassificazioneArma.NON_APPLICABILE
        else:
            classificazione = ClassificazioneArma.COMUNE

        # Condizione
        cond_raw = str(raw_item.get("condizione", "")).lower()
        if "nuov" in cond_raw:
            condizione = CondizioneArma.NUOVO
        elif "collezion" in cond_raw:
            condizione = CondizioneArma.DA_COLLEZIONE
        elif "buon" in cond_raw:
            condizione = CondizioneArma.USATO_BUONO
        else:
            condizione = CondizioneArma.USATO_OTTIMO

        return {
            "titolo": raw_item.get("name", "Arma in Vendita"),
            "descrizione": raw_item.get("description", "Descrizione non disponibile."),
            "prezzo": float(raw_item.get("regular_price", 0.0)),
            "marca": raw_item.get("brand", "Generico"),
            "modello": raw_item.get("model", "N/D"),
            "calibro": raw_item.get("caliber", "N/D"),
            "tipologia_arma": tipo_arma,
            "classificazione": classificazione,
            "condizione": condizione,
            "matricola": raw_item.get("serial_number"),
            "immagini": raw_item.get("images", []),
        }
