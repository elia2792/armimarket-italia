import logging
from typing import Dict, List, Optional, Tuple
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.models.annuncio import Annuncio
from app.models.user import RuoloUtente, User
from app.models.valutazione import Valutazione
from app.schemas.valutazione_schema import (
    RiepilogoValutazioniOut,
    ValutazioneCreate,
    ValutazioneOut,
)

logger = logging.getLogger(__name__)


class ValutazioneService:
    @staticmethod
    async def crea_o_aggiorna_valutazione(
        db: AsyncSession,
        autore: User,
        data: ValutazioneCreate
    ) -> Tuple[Valutazione, bool]:
        """
        Crea una nuova valutazione o aggiorna quella esistente dello stesso autore
        verso il medesimo destinatario (utente o armeria).
        Restituisce (valutazione, is_created).
        """
        # 1. Controllo auto-valutazione
        if data.recensito_utente_id and data.recensito_utente_id == autore.id:
            raise ValueError("Non puoi recensire o valutare te stesso.")

        # 2. Controllo esistenza utente destinatario
        if data.recensito_utente_id:
            user_dest = (await db.execute(
                select(User).where(User.id == data.recensito_utente_id)
            )).scalar_one_or_none()
            if not user_dest:
                raise ValueError("L'utente che desideri valutare non esiste.")

        # 3. Controllo annuncio di riferimento (opzionale)
        if data.annuncio_id:
            ad = (await db.execute(
                select(Annuncio).where(Annuncio.id == data.annuncio_id)
            )).scalar_one_or_none()
            if not ad:
                data.annuncio_id = None

        # 4. Ricerca eventuale recensione pregressa dello stesso autore verso lo stesso target
        fonte_clean = data.fonte_esterna.strip() if data.fonte_esterna else None

        stmt = select(Valutazione).where(Valutazione.autore_id == autore.id)
        if data.recensito_utente_id:
            stmt = stmt.where(Valutazione.recensito_utente_id == data.recensito_utente_id)
        elif fonte_clean:
            stmt = stmt.where(func.lower(Valutazione.fonte_esterna) == fonte_clean.lower())

        valutazione_esistente = (await db.execute(stmt)).scalar_one_or_none()

        if valutazione_esistente:
            # Aggiornamento
            valutazione_esistente.voto = data.voto
            valutazione_esistente.titolo = data.titolo
            valutazione_esistente.commento = data.commento
            if data.annuncio_id:
                valutazione_esistente.annuncio_id = data.annuncio_id
            await db.commit()
            await db.refresh(valutazione_esistente)
            return valutazione_esistente, False
        else:
            # Creazione
            nuova_valutazione = Valutazione(
                autore_id=autore.id,
                recensito_utente_id=data.recensito_utente_id,
                fonte_esterna=fonte_clean,
                annuncio_id=data.annuncio_id,
                voto=data.voto,
                titolo=data.titolo,
                commento=data.commento,
            )
            db.add(nuova_valutazione)
            await db.commit()
            await db.refresh(nuova_valutazione)
            return nuova_valutazione, True

    @staticmethod
    async def get_riepilogo(
        db: AsyncSession,
        utente_id: Optional[int] = None,
        fonte_esterna: Optional[str] = None
    ) -> RiepilogoValutazioniOut:
        """
        Calcola statistiche e carica le ultime valutazioni per un utente o un'armeria esterna.
        """
        if not utente_id and not fonte_esterna:
            return RiepilogoValutazioniOut()

        stmt_base = select(Valutazione)
        if utente_id:
            stmt_base = stmt_base.where(Valutazione.recensito_utente_id == utente_id)
        elif fonte_esterna:
            stmt_base = stmt_base.where(func.lower(Valutazione.fonte_esterna) == fonte_esterna.strip().lower())

        # Carica valutazioni con autore
        stmt_valutazioni = stmt_base.options(selectinload(Valutazione.autore)).order_by(Valutazione.data_creazione.desc())
        valutazioni = (await db.execute(stmt_valutazioni)).scalars().all()

        if not valutazioni:
            return RiepilogoValutazioniOut(
                media_voto=0.0,
                totale_valutazioni=0,
                distribuzione_voti={1: 0, 2: 0, 3: 0, 4: 0, 5: 0},
                valutazioni=[]
            )

        totale = len(valutazioni)
        somma = sum(v.voto for v in valutazioni)
        media = round(somma / totale, 1)

        distribuzione = {1: 0, 2: 0, 3: 0, 4: 0, 5: 0}
        for v in valutazioni:
            if v.voto in distribuzione:
                distribuzione[v.voto] += 1

        valutazioni_out = []
        for v in valutazioni:
            autore_name = v.autore.display_name if v.autore else "Utente ArmiMarket"
            autore_pic = v.autore.foto_profilo if v.autore else None
            valutazioni_out.append(
                ValutazioneOut(
                    id=v.id,
                    voto=v.voto,
                    titolo=v.titolo,
                    commento=v.commento,
                    data_creazione=v.data_creazione,
                    data_aggiornamento=v.data_aggiornamento,
                    autore_id=v.autore_id,
                    autore_display_name=autore_name,
                    autore_foto=autore_pic,
                    recensito_utente_id=v.recensito_utente_id,
                    fonte_esterna=v.fonte_esterna,
                    annuncio_id=v.annuncio_id
                )
            )

        return RiepilogoValutazioniOut(
            media_voto=media,
            totale_valutazioni=totale,
            distribuzione_voti=distribuzione,
            valutazioni=valutazioni_out
        )

    @staticmethod
    async def get_valutazioni_ricevute_utente(
        db: AsyncSession,
        utente_id: int
    ) -> List[ValutazioneOut]:
        """Restituisce l'elenco delle valutazioni ricevute dall'utente."""
        stmt = (
            select(Valutazione)
            .where(Valutazione.recensito_utente_id == utente_id)
            .options(selectinload(Valutazione.autore))
            .order_by(Valutazione.data_creazione.desc())
        )
        res = await db.execute(stmt)
        valutazioni = res.scalars().all()

        out = []
        for v in valutazioni:
            autore_name = v.autore.display_name if v.autore else "Utente ArmiMarket"
            autore_pic = v.autore.foto_profilo if v.autore else None
            out.append(
                ValutazioneOut(
                    id=v.id,
                    voto=v.voto,
                    titolo=v.titolo,
                    commento=v.commento,
                    data_creazione=v.data_creazione,
                    data_aggiornamento=v.data_aggiornamento,
                    autore_id=v.autore_id,
                    autore_display_name=autore_name,
                    autore_foto=autore_pic,
                    recensito_utente_id=v.recensito_utente_id,
                    fonte_esterna=v.fonte_esterna,
                    annuncio_id=v.annuncio_id
                )
            )
        return out

    @staticmethod
    async def elimina_valutazione(
        db: AsyncSession,
        valutazione_id: int,
        user: User
    ) -> bool:
        """Elimina una valutazione (consentito solo all'autore o all'admin)."""
        stmt = select(Valutazione).where(Valutazione.id == valutazione_id)
        val = (await db.execute(stmt)).scalar_one_or_none()
        if not val:
            return False

        if user.ruolo != RuoloUtente.ADMIN and val.autore_id != user.id:
            raise PermissionError("Non hai i permessi per eliminare questa recensione.")

        await db.delete(val)
        await db.commit()
        return True
