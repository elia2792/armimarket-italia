from typing import Optional, Tuple
from sqlalchemy.ext.asyncio import AsyncSession
from app.core.legal import BANNED_KEYWORDS
from app.models.annuncio import Annuncio, StatoAnnuncio
from app.models.user import RuoloUtente, User


def mask_matricola(matricola: Optional[str]) -> Optional[str]:
    """
    Maschera la matricola dell'arma per la privacy e per prevenire frodi o clonazioni.
    Esempio: 'BER123456X' -> 'BE*****6X'
    """
    if not matricola:
        return None
    clean = matricola.strip()
    if len(clean) <= 4:
        return "*" * len(clean)
    prefix_len = min(2, len(clean) // 3)
    suffix_len = min(2, len(clean) // 3)
    masked_count = len(clean) - prefix_len - suffix_len
    return clean[:prefix_len] + ("*" * masked_count) + clean[-suffix_len:]


class ModerationService:
    @staticmethod
    def verify_compliance(text: str) -> Tuple[bool, Optional[str]]:
        """
        Scansiona il testo per rilevare termini non conformi alla legislazione sulle armi.
        Ritorna (True, None) se conforme, oppure (False, termine_vietato) se illegale.
        """
        lowered = text.lower()
        for kw in BANNED_KEYWORDS:
            if kw in lowered:
                return False, kw
        return True, None

    @staticmethod
    async def review_annuncio(
        db: AsyncSession,
        annuncio: Annuncio,
        nuovo_stato: StatoAnnuncio,
        moderatore: User,
        note: Optional[str] = None
    ) -> Annuncio:
        """
        Applica una decisione di moderazione (approvazione o rifiuto) con tracciamento note.
        """
        if moderatore.ruolo not in [RuoloUtente.ADMIN, RuoloUtente.MODERATORE]:
            raise PermissionError("L'utente non dispone dei permessi di moderatore di Pubblica Sicurezza.")

        annuncio.stato = nuovo_stato
        if note:
            prefix = f"[{moderatore.email}]: "
            annuncio.note_moderazione = (
                f"{annuncio.note_moderazione}\n{prefix}{note}"
                if annuncio.note_moderazione
                else f"{prefix}{note}"
            )

        await db.commit()
        await db.refresh(annuncio)
        return annuncio
