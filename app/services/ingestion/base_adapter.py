import abc
import re
from typing import Any, Dict, List, Optional
from sqlalchemy.ext.asyncio import AsyncSession
from app.models.annuncio import (
    Annuncio,
    ClassificazioneArma,
    CondizioneArma,
    StatoAnnuncio,
    TipologiaArma,
    TipologiaInserzionista,
)
from app.models.user import User


class BaseGunshopAdapter(abc.ABC):
    """
    Interfaccia astratta per l'importazione e la sincronizzazione di stock da armerie partner.
    Supporta feed XML/JSON (WooCommerce, PrestaShop, gestionale armeria).
    """

    # Dizionari di normalizzazione marchi noti
    BRAND_MAP = {
        r"\bberetta\b.*": "Beretta",
        r"\bglock\b.*": "Glock",
        r"\bbenelli\b.*": "Benelli",
        r"\bcz\b.*|\bceska\s*zbrojovka\b.*": "CZ",
        r"\bfranchi\b.*": "Franchi",
        r"\bsmith\s*&\s*wesson\b.*|\bs&w\b.*": "Smith & Wesson",
        r"\bcolt\b.*": "Colt",
        r"\bsig\s*sauer\b.*": "Sig Sauer",
        r"\bwalther\b.*": "Walther",
        r"\bheckler\s*&\s*koch\b.*|\bh&k\b.*": "Heckler & Koch",
        r"\btanfoglio\b.*": "Tanfoglio",
        r"\bchiappa\b.*": "Chiappa Firearms",
        r"\bperazzi\b.*": "Perazzi",
    }

    # Dizionari di normalizzazione calibri
    CALIBER_MAP = {
        r"9\s*x\s*21(\s*imi)?": "9x21",
        r"9\s*x\s*19.*|9\s*luger|9\s*para.*": "9x19 Parabellum",
        r"308\s*win.*|\.?308w?": ".308 Win",
        r"22\s*l\.?r\.?|\.?22\s*lr": ".22 LR",
        r"12\s*/\s*76.*|cal(ibro)?\s*12": "12/76",
        r"20\s*/\s*76.*|cal(ibro)?\s*20": "20/76",
        r"45\s*acp.*|\.?45\s*auto": ".45 ACP",
        r"357\s*mag.*|\.?357": ".357 Magnum",
        r"38\s*spec.*|\.?38\s*sp": ".38 Special",
        r"6\.5\s*creedmoor.*": "6.5 Creedmoor",
        r"30-06.*|30\.06": ".30-06 Springfield",
        r"223\s*rem.*|\.?223\b": ".223 Remington",
        r"300\s*win\s*mag.*|\.?300wm": ".300 Win Mag",
    }

    @classmethod
    def normalize_brand(cls, raw_brand: str) -> str:
        """Normalizza le variazioni del nome marca nel brand canonico."""
        if not raw_brand:
            return "Altro"
        clean = raw_brand.strip()
        for pattern, canonical in cls.BRAND_MAP.items():
            if re.search(pattern, clean, flags=re.IGNORECASE):
                return canonical
        return clean.title()

    @classmethod
    def normalize_caliber(cls, raw_caliber: str) -> str:
        """Normalizza le denominazioni del calibro."""
        if not raw_caliber:
            return "N/D"
        clean = raw_caliber.strip()
        for pattern, canonical in cls.CALIBER_MAP.items():
            if re.search(pattern, clean, flags=re.IGNORECASE):
                return canonical
        return clean.upper()

    @abc.abstractmethod
    def fetch_feed(self, source: Any) -> List[Dict[str, Any]]:
        """Recupera e parsa il feed grezzo dal file, URL o API."""
        pass

    @abc.abstractmethod
    def normalize_item(self, raw_item: Dict[str, Any]) -> Dict[str, Any]:
        """Trasforma il singolo elemento del feed nel formato normalizzato per il modello Annuncio."""
        pass

    async def sync_inventory(
        self,
        db: AsyncSession,
        armeria_user: Optional[User] = None,
        comune_id: int = 1,
        raw_items: Optional[List[Dict[str, Any]]] = None,
        fonte_esterna: Optional[str] = None,
    ) -> Dict[str, int]:
        """
        Sincronizza gli articoli del feed nel database.
        Se armeria_user è None, gli annunci vengono registrati come fonte esterna senza creare un account utente.
        """
        import uuid

        raw_items = raw_items or []
        stats = {"inseriti": 0, "aggiornati": 0, "scartati": 0}
        nome_fonte = fonte_esterna or ((armeria_user.ragione_sociale or armeria_user.nome) if armeria_user else "Armeria Partner")
        email_contatto = armeria_user.email if armeria_user else "info@armimarket.it"
        telefono_contatto = armeria_user.telefono if armeria_user else None

        for item in raw_items:
            try:
                norm = self.normalize_item(item)
                titolo = norm["titolo"]
                slug_base = re.sub(r"[^\w\s-]", "", titolo.lower()).strip()
                slug = f"{re.sub(r'[-\s]+', '-', slug_base)}-{uuid.uuid4().hex[:6]}"

                nuovo_annuncio = Annuncio(
                    titolo=titolo,
                    slug=slug,
                    descrizione=norm["descrizione"],
                    prezzo=norm["prezzo"],
                    stato=StatoAnnuncio.PUBBLICATO,  # Stock certificato armeria partner
                    tipologia_inserzionista=TipologiaInserzionista.ARMERIA,
                    tipologia_arma=norm.get("tipologia_arma", TipologiaArma.ARMA_CORTA),
                    marca=self.normalize_brand(norm.get("marca", "")),
                    modello=norm.get("modello", "N/D"),
                    calibro=self.normalize_caliber(norm.get("calibro", "")),
                    classificazione=norm.get("classificazione", ClassificazioneArma.COMUNE),
                    condizione=norm.get("condizione", CondizioneArma.NUOVO),
                    matricola_riservata=norm.get("matricola"),  # Conservata ma non esposta
                    comune_id=comune_id,
                    utente_id=armeria_user.id if armeria_user else None,
                    fonte_esterna=nome_fonte,
                    source_id_esterno=str(item.get("id") or ""),
                    galleria_immagini=norm.get("immagini", []),
                    email_contatto=email_contatto,
                    telefono_contatto=telefono_contatto,
                    mostra_telefono_pubblico=bool(telefono_contatto),
                )

                db.add(nuovo_annuncio)
                stats["inseriti"] += 1
            except Exception as e:
                stats["scartati"] += 1


        await db.commit()
        return stats
