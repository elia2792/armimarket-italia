import re
from typing import Any, Dict, List, Optional
import defusedxml.ElementTree as ET
from app.core.network import safe_http_get
from app.models.annuncio import (
    ClassificazioneArma,
    CondizioneArma,
    TipologiaArma,
)
from app.services.ingestion.base_adapter import BaseGunshopAdapter


class XmlFeedAdapter(BaseGunshopAdapter):
    """
    Adapter per l'importazione da feed XML standard (RSS 2.0, Google Shopping XML o export gestionali armeria).
    """

    async def fetch_remote_xml(self, feed_url: str) -> str:
        """Scarica il file XML da una URL remota protetta da SSRF."""
        resp = await safe_http_get(
            feed_url,
            headers={"User-Agent": "ArmiMarket-XML-Sync/1.0"},
            timeout=30.0
        )
        resp.raise_for_status()
        return resp.text

    def fetch_feed(self, source: Any) -> List[Dict[str, Any]]:
        """Parsa il testo XML ed estrae la lista di prodotti/items."""
        xml_content = source
        if not isinstance(xml_content, str):
            xml_content = str(source)

        root = ET.fromstring(xml_content)
        items: List[Dict[str, Any]] = []

        # Riconoscimento automatico dei tag XML (item, product, arma)
        nodes = root.findall(".//item") or root.findall(".//product") or root.findall(".//arma")
        if not nodes:
            # Prova primo livello figli
            nodes = list(root)

        for node in nodes:
            item_dict: Dict[str, Any] = {}
            for child in node:
                tag_name = child.tag.split("}")[-1].lower()  # Rimuove namespace XML se presente
                item_dict[tag_name] = child.text or ""

            if item_dict.get("title") or item_dict.get("name") or item_dict.get("titolo"):
                items.append(item_dict)

        return items

    def normalize_item(self, raw_item: Dict[str, Any]) -> Dict[str, Any]:
        """Converte il dizionario estratto dal nodo XML nel formato unificato Annuncio."""
        titolo = raw_item.get("title") or raw_item.get("name") or raw_item.get("titolo") or "Arma in Catalogo"
        desc = raw_item.get("description") or raw_item.get("descrizione") or ""
        clean_desc = re.sub(r"<[^>]+>", "", desc).strip() or "Descrizione tecnica da feed armeria partner."

        # Prezzo
        price_str = raw_item.get("price") or raw_item.get("prezzo") or "0"
        price_clean = re.sub(r"[^\d.,]", "", price_str).replace(",", ".")
        try:
            prezzo = float(price_clean)
        except ValueError:
            prezzo = 0.0

        marca = raw_item.get("brand") or raw_item.get("marca") or titolo.split()[0]
        modello = raw_item.get("model") or raw_item.get("modello") or titolo
        calibro = raw_item.get("caliber") or raw_item.get("calibro") or self._detect_caliber(titolo)

        category = (raw_item.get("category") or raw_item.get("categoria") or "").lower()

        # Tipologia Arma
        if any(w in category for w in ["corta", "pistola", "revolver"]):
            tipo = TipologiaArma.ARMA_CORTA
        elif any(w in category for w in ["rigata", "carabina", "bolt"]):
            tipo = TipologiaArma.ARMA_LUNGA_RIGATA
        elif any(w in category for w in ["liscia", "fucile", "sovrapposto"]):
            tipo = TipologiaArma.CANNA_LISCIA
        elif any(w in category for w in ["aria", "depotenziata"]):
            tipo = TipologiaArma.ARIA_COMPRESSA_LIBERA
        else:
            tipo = TipologiaArma.ARMA_CORTA

        # Classificazione
        cls_text = (raw_item.get("classificazione") or category).lower()
        if "sport" in cls_text:
            classificazione = ClassificazioneArma.SPORTIVA
        elif "caccia" in cls_text:
            classificazione = ClassificazioneArma.CACCIA
        elif "non" in cls_text:
            classificazione = ClassificazioneArma.NON_APPLICABILE
        else:
            classificazione = ClassificazioneArma.COMUNE

        # Immagine
        img_url = (
            raw_item.get("image_link")
            or raw_item.get("image")
            or raw_item.get("foto")
            or raw_item.get("immagine")
        )
        immagini = [img_url] if img_url else []

        return {
            "titolo": titolo,
            "descrizione": clean_desc,
            "prezzo": prezzo,
            "marca": marca,
            "modello": modello,
            "calibro": calibro,
            "tipologia_arma": tipo,
            "classificazione": classificazione,
            "condizione": CondizioneArma.NUOVO,
            "matricola": raw_item.get("serial_number") or raw_item.get("mpn"),
            "immagini": immagini,
        }

    def _detect_caliber(self, text: str) -> str:
        for pattern in self.CALIBER_MAP:
            m = re.search(pattern, text, flags=re.IGNORECASE)
            if m:
                return m.group(0)
        return "N/D"
