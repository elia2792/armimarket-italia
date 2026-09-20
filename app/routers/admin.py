import email.utils
import re
from datetime import datetime
from typing import Any, Dict, List, Optional, Tuple
from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import delete, func, not_, or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.core.config import settings
from app.core.database import get_db
from app.models.annuncio import (
    Annuncio,
    ClassificazioneArma,
    CondizioneArma,
    StatoAnnuncio,
    TipologiaArma,
    TipologiaInserzionista,
)
from app.models.email_log import EmailLog, TipologiaEmail
from app.models.geo import Comune, Provincia
from app.models.segnalazione import SegnalazioneAnnuncio
from app.models.user import RuoloUtente, User
from app.routers.auth import get_current_moderator, get_current_user
from app.schemas.annuncio_schema import (
    AdminAnnuncioUpdateRequest,
    AdminAnnunciListResponse,
    AnnuncioAdminOut,
    ComuneOut,
)
from app.services.email_service import EmailService
from app.services.moderation_service import ModerationService, mask_matricola

router = APIRouter(prefix="/admin", tags=["Area Riservata Moderazione & Pubblica Sicurezza"])


async def get_current_admin(current_user: User = Depends(get_current_user)) -> User:
    """Dipendenza che richiede strettamente ruolo ADMIN."""
    if current_user.ruolo != RuoloUtente.ADMIN:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Accesso riservato esclusivamente all amministratore del sistema."
        )
    return current_user


class RejectionRequest(BaseModel):
    motivo_rifiuto: str = Field(..., min_length=5, description="Motivazione del rigetto (es. difformità TULPS)")


class ApprovalRequest(BaseModel):
    note: Optional[str] = Field(None, description="Eventuali note interne di approvazione")


class TestEmailRequest(BaseModel):
    destinatario: str = Field(..., description="Indirizzo email a cui recapitare l invio di test")


class EmailLogOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    mittente: str
    destinatario: str
    oggetto: str
    corpo_html: str
    corpo_testo: str
    tipologia: str
    inviata: bool
    errore: Optional[str] = None
    link_azione: Optional[str] = None
    data_invio: datetime


class EmailListResponse(BaseModel):
    totale: int
    pagina: int
    elementi_per_pagina: int
    conteggio_recupero: int
    conteggio_contatti: int
    conteggio_segnalazioni: int = 0
    conteggio_altre: int
    conteggio_in_arrivo: int = 0
    conteggio_errori: int = 0
    emails: List[EmailLogOut]


class ConversazioneItem(BaseModel):
    user_email: str
    user_name: str
    ultimo_oggetto: str
    anteprima: str
    data_ultimo_messaggio: datetime
    totale_messaggi: int
    ha_errori: bool
    ultima_tipologia: str
    ultimo_id: int


class ConversazioniResponse(BaseModel):
    totale: int
    pagina: int
    elementi_per_pagina: int
    conteggio_errori: int
    conteggio_recupero: int
    conteggio_contatti: int
    conteggio_segnalazioni: int = 0
    conteggio_in_arrivo: int = 0
    conteggio_altre: int
    conversazioni: List[ConversazioneItem]


class MessaggioConversazione(BaseModel):
    id: int
    mittente: str
    destinatario: str
    oggetto: str
    corpo_html: str
    corpo_testo: str
    tipologia: str
    inviata: bool
    errore: Optional[str] = None
    link_azione: Optional[str] = None
    data_invio: datetime
    is_from_admin: bool


class DettaglioConversazioneResponse(BaseModel):
    user_email: str
    user_name: str
    totale_messaggi: int
    messaggi: List[MessaggioConversazione]


class ConversazioneReplyRequest(BaseModel):
    messaggio: str = Field(..., min_length=1, max_length=10000)
    oggetto: Optional[str] = None


class SegnalazioneOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    annuncio_id: int
    motivo: str
    dettagli: str
    email_segnalatore: Optional[str] = None
    risolta: bool
    azione_intrapresa: Optional[str] = None
    data_creazione: datetime
    annuncio_titolo: Optional[str] = None
    annuncio_prezzo: Optional[float] = None
    annuncio_stato: Optional[str] = None


class RisolviSegnalazioneRequest(BaseModel):
    azione: str = Field(..., description="Azione: archiviata, respinta, ecc.")


class AdminReplyRequest(BaseModel):
    messaggio: str = Field(..., min_length=2, max_length=5000, description="Testo della risposta da inviare")
    oggetto: Optional[str] = Field(None, description="Oggetto personalizzato per la risposta")
    destinatario: Optional[str] = Field(None, description="Destinatario alternativo se diverso dal mittente originale")


def _build_annuncio_admin_out(a: Annuncio) -> AnnuncioAdminOut:
    comune_out = None
    if a.comune:
        sigla = a.comune.provincia.sigla_automobilistica if a.comune.provincia else None
        regione_nome = a.comune.provincia.regione.nome if a.comune.provincia and a.comune.provincia.regione else None
        comune_out = ComuneOut(
            id=a.comune.id,
            nome=a.comune.nome,
            cap=a.comune.cap,
            provincia_id=a.comune.provincia_id,
            latitudine=a.comune.latitudine,
            longitudine=a.comune.longitudine,
            sigla_provincia=sigla,
            nome_regione=regione_nome,
        )

    return AnnuncioAdminOut(
        id=a.id,
        titolo=a.titolo,
        slug=a.slug,
        descrizione=a.descrizione,
        prezzo=a.prezzo,
        prezzo_originale=a.prezzo_originale,
        stato=a.stato,
        tipologia_inserzionista=a.tipologia_inserzionista,
        tipologia_arma=a.tipologia_arma,
        marca=a.marca,
        modello=a.modello,
        calibro=a.calibro,
        classificazione=a.classificazione,
        condizione=a.condizione,
        comune_id=a.comune_id,
        galleria_immagini=a.galleria_immagini or [],
        link_esterno=a.link_esterno,
        email_contatto=a.email_contatto,
        telefono_contatto=a.telefono_contatto,
        visualizzazioni=a.visualizzazioni,
        data_creazione=a.data_creazione,
        data_aggiornamento=a.data_aggiornamento,
        comune=comune_out,
        fonte_esterna=a.fonte_esterna,
        is_scraped=bool(a.fonte_esterna or a.link_esterno),
        matricola_mascherata=mask_matricola(a.matricola_riservata),
        matricola_originale_disponibile=bool(a.matricola_riservata),
        note_moderazione=a.note_moderazione,
        utente_id=a.utente_id,
    )


@router.get("/moderazione", response_model=List[AnnuncioAdminOut])
async def list_pending_ads(
    pagina: int = Query(1, ge=1),
    elementi_per_pagina: int = Query(20, ge=1, le=100),
    moderatore: User = Depends(get_current_moderator),
    db: AsyncSession = Depends(get_db)
):
    """Restituisce la coda degli annunci in attesa di moderazione (stato in_moderazione)."""
    offset = (pagina - 1) * elementi_per_pagina
    stmt = (
        select(Annuncio)
        .options(selectinload(Annuncio.comune).selectinload(Comune.provincia).selectinload(Provincia.regione))
        .where(Annuncio.stato == StatoAnnuncio.IN_MODERAZIONE)
        .order_by(Annuncio.data_creazione.asc())
        .offset(offset)
        .limit(elementi_per_pagina)
    )
    result = await db.execute(stmt)
    annunci = result.scalars().all()
    return [_build_annuncio_admin_out(a) for a in annunci]


@router.post("/moderazione/{id}/approva")
async def approve_annuncio(
    id: int,
    req: ApprovalRequest,
    moderatore: User = Depends(get_current_moderator),
    db: AsyncSession = Depends(get_db)
):
    """Approva l annuncio e lo pubblica sul portale."""
    stmt = select(Annuncio).where(Annuncio.id == id)
    annuncio = (await db.execute(stmt)).scalar_one_or_none()

    if not annuncio:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Annuncio non trovato.")

    await ModerationService.review_annuncio(
        db=db,
        annuncio=annuncio,
        nuovo_stato=StatoAnnuncio.PUBBLICATO,
        moderatore=moderatore,
        note=req.note or "Approvato da moderatore di Pubblica Sicurezza."
    )

    return {
        "success": True,
        "message": f"Annuncio #{id} approvato con successo e reso pubblico.",
        "stato": annuncio.stato
    }


@router.post("/moderazione/{id}/rifiuta")
async def reject_annuncio(
    id: int,
    req: RejectionRequest,
    moderatore: User = Depends(get_current_moderator),
    db: AsyncSession = Depends(get_db)
):
    """Rifiuta l annuncio specificando la motivazione di non conformità."""
    stmt = select(Annuncio).where(Annuncio.id == id)
    annuncio = (await db.execute(stmt)).scalar_one_or_none()

    if not annuncio:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Annuncio non trovato.")

    await ModerationService.review_annuncio(
        db=db,
        annuncio=annuncio,
        nuovo_stato=StatoAnnuncio.RIFIUTATO,
        moderatore=moderatore,
        note=f"RIFIUTATO: {req.motivo_rifiuto}"
    )

    return {
        "success": True,
        "message": f"Annuncio #{id} rifiutato.",
        "motivo": req.motivo_rifiuto,
        "stato": annuncio.stato
    }


# =========================================================================
# GESTIONE COMPLETA ANNUNCI (Privati vs Armerie, Modifica & Rimozione)
# =========================================================================

@router.get("/annunci", response_model=AdminAnnunciListResponse)
async def list_all_annunci_admin(
    tipologia_inserzionista: Optional[str] = Query(None, description="Filtro 'privato' o 'armeria'"),
    stato: Optional[str] = Query(None, description="Filtro stato: pubblicato, in_moderazione, venduto, rifiutato"),
    search: Optional[str] = Query(None, description="Ricerca testuale per titolo, marca, modello, calibro, armeria"),
    pagina: int = Query(1, ge=1),
    elementi_per_pagina: int = Query(20, ge=1, le=100),
    admin: User = Depends(get_current_moderator),
    db: AsyncSession = Depends(get_db)
):
    """
    Restituisce l'elenco completo degli annunci con suddivisione tra Privati e Armerie,
    filtri per stato, ricerca testuale libera e contatori KPI aggregati.
    """
    # Contatori globali per schede riassuntive
    cnt_totale = (await db.execute(select(func.count(Annuncio.id)))).scalar() or 0
    cnt_privati = (await db.execute(
        select(func.count(Annuncio.id)).where(Annuncio.tipologia_inserzionista == TipologiaInserzionista.PRIVATO)
    )).scalar() or 0
    cnt_armerie = (await db.execute(
        select(func.count(Annuncio.id)).where(Annuncio.tipologia_inserzionista == TipologiaInserzionista.ARMERIA)
    )).scalar() or 0
    cnt_moderazione = (await db.execute(
        select(func.count(Annuncio.id)).where(Annuncio.stato == StatoAnnuncio.IN_MODERAZIONE)
    )).scalar() or 0

    stmt = (
        select(Annuncio)
        .options(selectinload(Annuncio.comune).selectinload(Comune.provincia).selectinload(Provincia.regione))
    )

    if tipologia_inserzionista:
        tipo_clean = tipologia_inserzionista.lower().strip()
        if tipo_clean == "privato":
            stmt = stmt.where(Annuncio.tipologia_inserzionista == TipologiaInserzionista.PRIVATO)
        elif tipo_clean == "armeria":
            stmt = stmt.where(Annuncio.tipologia_inserzionista == TipologiaInserzionista.ARMERIA)

    if stato:
        try:
            st_enum = StatoAnnuncio(stato.lower().strip())
            stmt = stmt.where(Annuncio.stato == st_enum)
        except ValueError:
            pass

    if search:
        term = f"%{search.strip().lower()}%"
        stmt = stmt.where(
            or_(
                Annuncio.titolo.ilike(term),
                Annuncio.marca.ilike(term),
                Annuncio.modello.ilike(term),
                Annuncio.calibro.ilike(term),
                Annuncio.fonte_esterna.ilike(term),
            )
        )

    # Conteggio filtrato
    count_stmt = select(func.count()).select_from(stmt.subquery())
    filtered_total = (await db.execute(count_stmt)).scalar() or 0

    pagine_totali = max(1, (filtered_total + elementi_per_pagina - 1) // elementi_per_pagina)
    offset = (pagina - 1) * elementi_per_pagina
    stmt = stmt.order_by(Annuncio.data_creazione.desc()).offset(offset).limit(elementi_per_pagina)

    annunci = (await db.execute(stmt)).scalars().all()
    results = [_build_annuncio_admin_out(a) for a in annunci]

    return AdminAnnunciListResponse(
        totale=filtered_total,
        totale_privati=cnt_privati,
        totale_armerie=cnt_armerie,
        totale_in_moderazione=cnt_moderazione,
        pagina=pagina,
        elementi_per_pagina=elementi_per_pagina,
        pagine_totali=pagine_totali,
        annunci=results
    )


@router.get("/annunci/{id}", response_model=AnnuncioAdminOut)
async def get_annuncio_admin(
    id: int,
    admin: User = Depends(get_current_moderator),
    db: AsyncSession = Depends(get_db)
):
    """Recupera i dettagli completi di un singolo annuncio per l'amministratore."""
    stmt = (
        select(Annuncio)
        .options(selectinload(Annuncio.comune).selectinload(Comune.provincia).selectinload(Provincia.regione))
        .where(Annuncio.id == id)
    )
    annuncio = (await db.execute(stmt)).scalar_one_or_none()
    if not annuncio:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Annuncio non trovato.")
    return _build_annuncio_admin_out(annuncio)


@router.put("/annunci/{id}", response_model=AnnuncioAdminOut)
async def update_annuncio_admin(
    id: int,
    req: AdminAnnuncioUpdateRequest,
    admin: User = Depends(get_current_moderator),
    db: AsyncSession = Depends(get_db)
):
    """
    Modifica qualsiasi campo di un annuncio esistente (es. titolo, prezzo, marca, calibro, comune, stato).
    Riservato a utenti amministratori o moderatori di Pubblica Sicurezza.
    """
    stmt = (
        select(Annuncio)
        .options(selectinload(Annuncio.comune).selectinload(Comune.provincia).selectinload(Provincia.regione))
        .where(Annuncio.id == id)
    )
    annuncio = (await db.execute(stmt)).scalar_one_or_none()
    if not annuncio:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Annuncio non trovato.")

    # Se il comune viene modificato, verifichiamo la sua presenza anagrafica ISTAT
    if req.comune_id is not None and req.comune_id != annuncio.comune_id:
        stmt_c = select(Comune).where(Comune.id == req.comune_id)
        comune = (await db.execute(stmt_c)).scalar_one_or_none()
        if not comune:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Comune ISTAT selezionato non valido.")
        annuncio.comune_id = req.comune_id

    # Aggiornamento campi scalari
    if req.titolo is not None:
        annuncio.titolo = req.titolo.strip()
    if req.descrizione is not None:
        annuncio.descrizione = req.descrizione.strip()
    if req.prezzo is not None:
        annuncio.prezzo = req.prezzo
    if req.prezzo_originale is not None:
        annuncio.prezzo_originale = req.prezzo_originale
    if req.marca is not None:
        annuncio.marca = req.marca.strip()
    if req.modello is not None:
        annuncio.modello = req.modello.strip()
    if req.calibro is not None:
        annuncio.calibro = req.calibro.strip()
    if req.tipologia_arma is not None:
        annuncio.tipologia_arma = req.tipologia_arma
    if req.classificazione is not None:
        annuncio.classificazione = req.classificazione
    if req.condizione is not None:
        annuncio.condizione = req.condizione
    if req.tipologia_inserzionista is not None:
        annuncio.tipologia_inserzionista = req.tipologia_inserzionista
    if req.stato is not None:
        annuncio.stato = req.stato
    if req.email_contatto is not None:
        annuncio.email_contatto = req.email_contatto
    if req.telefono_contatto is not None:
        annuncio.telefono_contatto = req.telefono_contatto
    if req.mostra_telefono_pubblico is not None:
        annuncio.mostra_telefono_pubblico = req.mostra_telefono_pubblico
    if req.galleria_immagini is not None:
        annuncio.galleria_immagini = req.galleria_immagini
    if req.fonte_esterna is not None:
        annuncio.fonte_esterna = req.fonte_esterna.strip() or None
    if req.link_esterno is not None:
        annuncio.link_esterno = req.link_esterno.strip() or None
    if req.note_moderazione is not None:
        annuncio.note_moderazione = req.note_moderazione.strip() or None

    annuncio.data_aggiornamento = datetime.utcnow()
    await db.commit()

    # Ricarica l'annuncio con relazioni fresche per la serializzazione
    stmt_reload = (
        select(Annuncio)
        .options(selectinload(Annuncio.comune).selectinload(Comune.provincia).selectinload(Provincia.regione))
        .where(Annuncio.id == id)
    )
    annuncio_aggiornato = (await db.execute(stmt_reload)).scalar_one()
    return _build_annuncio_admin_out(annuncio_aggiornato)


@router.delete("/annunci/{id}")
async def delete_annuncio_admin(
    id: int,
    admin: User = Depends(get_current_moderator),
    db: AsyncSession = Depends(get_db)
):
    """Elimina definitivamente un annuncio dal portale."""
    stmt = select(Annuncio).where(Annuncio.id == id)
    annuncio = (await db.execute(stmt)).scalar_one_or_none()
    if not annuncio:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Annuncio non trovato.")
    await db.delete(annuncio)
    await db.commit()
    return {"status": "success", "success": True, "message": f"Annuncio #{id} eliminato con successo dall'amministratore."}


# =========================================================================
# CASELLA EMAIL / WEBMAIL AMMINISTRATORE (Consultazione e invio email)
# =========================================================================

def get_email_counterpart(email_obj: EmailLog) -> Tuple[str, str]:
    """Determina l'interlocutore (email e nome) contrapposto all'amministratore/sistema."""
    admin_markers = [
        (settings.ADMIN_EMAIL or "").lower(),
        (settings.EMAILS_FROM_EMAIL or "").lower(),
        "admin",
        "no-reply",
        "armimarket"
    ]

    mittente_raw = email_obj.mittente or ""
    destinatario_raw = email_obj.destinatario or ""

    real_name, mittente_email = email.utils.parseaddr(mittente_raw)
    if not mittente_email:
        m = re.search(r"[\w\.\-+]+@[\w\.\-]+", mittente_raw)
        mittente_email = m.group(0) if m else mittente_raw

    _, dest_email = email.utils.parseaddr(destinatario_raw)
    if not dest_email:
        m = re.search(r"[\w\.\-+]+@[\w\.\-]+", destinatario_raw)
        dest_email = m.group(0) if m else destinatario_raw

    mittente_email = mittente_email.strip().lower()
    dest_email = dest_email.strip().lower()

    is_mittente_admin = any(marker and marker in mittente_email for marker in admin_markers) or "admin" in mittente_raw.lower()
    if is_mittente_admin:
        counter_email = dest_email
        counter_name = dest_email.split("@")[0].replace(".", " ").capitalize() if "@" in dest_email else dest_email
    else:
        counter_email = mittente_email
        counter_name = real_name if real_name else (mittente_email.split("@")[0].replace(".", " ").capitalize() if "@" in mittente_email else mittente_email)

    return counter_email, counter_name


WEB_PAGE_TIPOLOGIE = [
    TipologiaEmail.RICHIESTA_CONTATTO.value,
    TipologiaEmail.SEGNALAZIONE.value,
    TipologiaEmail.RECUPERO_PASSWORD.value,
    TipologiaEmail.RISPOSTA_ADMIN.value,
    TipologiaEmail.MODERAZIONE.value,
    TipologiaEmail.ALERT_RICERCA.value,
    TipologiaEmail.TEST.value,
    TipologiaEmail.SISTEMA.value
]


def filter_solo_email_sito(stmt):
    """Filtra le email per mostrare SOLO quelle generate dalle pagine web del portale."""
    return stmt.where(
        EmailLog.tipologia.in_(WEB_PAGE_TIPOLOGIE),
        or_(EmailLog.link_azione.is_(None), not_(EmailLog.link_azione.like("msgid:%")))
    )


@router.get("/email", response_model=EmailListResponse)
async def list_admin_emails(
    pagina: int = Query(1, ge=1),
    elementi_per_pagina: int = Query(25, ge=1, le=100),
    tipologia: Optional[str] = Query(None, description="Filtra per tipologia"),
    search: Optional[str] = Query(None, description="Cerca per destinatario, mittente o oggetto"),
    admin: User = Depends(get_current_admin),
    db: AsyncSession = Depends(get_db)
):
    """
    Restituisce la lista di tutte le email generate dalle pagine web di ArmiMarket.
    Include contatori statistici per le cartelle della webmail.
    """
    stmt = filter_solo_email_sito(select(EmailLog))
    if tipologia:
        if tipologia == "errori":
            stmt = stmt.where(or_(EmailLog.inviata == False, EmailLog.errore.isnot(None)))
        elif tipologia == "altre":
            stmt = stmt.where(EmailLog.tipologia.notin_([
                TipologiaEmail.RECUPERO_PASSWORD.value,
                TipologiaEmail.RICHIESTA_CONTATTO.value,
                TipologiaEmail.SEGNALAZIONE.value
            ]))
        else:
            stmt = stmt.where(EmailLog.tipologia == tipologia)

    if search and search.strip():
        q_term = f"%{search.strip()}%"
        stmt = stmt.where(
            (EmailLog.destinatario.ilike(q_term)) |
            (EmailLog.mittente.ilike(q_term)) |
            (EmailLog.oggetto.ilike(q_term)) |
            (EmailLog.corpo_testo.ilike(q_term))
        )

    # Conteggio totale filtrato
    count_stmt = select(func.count()).select_from(stmt.subquery())
    totale = (await db.execute(count_stmt)).scalar() or 0

    # Paginazione e ordinamento per data decrescente
    offset = (pagina - 1) * elementi_per_pagina
    stmt = stmt.order_by(EmailLog.data_invio.desc()).offset(offset).limit(elementi_per_pagina)
    result = await db.execute(stmt)
    emails = result.scalars().all()

    # Conteggi cartelle globali (esclusivamente dal sito web)
    base_count = lambda cond: select(func.count(EmailLog.id)).where(
        EmailLog.tipologia.in_(WEB_PAGE_TIPOLOGIE),
        or_(EmailLog.link_azione.is_(None), not_(EmailLog.link_azione.like("msgid:%"))),
        cond
    )
    c_recupero = (await db.execute(base_count(EmailLog.tipologia == TipologiaEmail.RECUPERO_PASSWORD.value))).scalar() or 0
    c_contatti = (await db.execute(base_count(EmailLog.tipologia == TipologiaEmail.RICHIESTA_CONTATTO.value))).scalar() or 0
    c_segnalazioni = (await db.execute(base_count(EmailLog.tipologia == TipologiaEmail.SEGNALAZIONE.value))).scalar() or 0
    c_errori = (await db.execute(base_count(or_(EmailLog.inviata == False, EmailLog.errore.isnot(None))))).scalar() or 0
    c_altre = (await db.execute(base_count(EmailLog.tipologia.notin_([
        TipologiaEmail.RECUPERO_PASSWORD.value,
        TipologiaEmail.RICHIESTA_CONTATTO.value,
        TipologiaEmail.SEGNALAZIONE.value
    ])))).scalar() or 0

    return EmailListResponse(
        totale=totale,
        pagina=pagina,
        elementi_per_pagina=elementi_per_pagina,
        conteggio_recupero=c_recupero,
        conteggio_contatti=c_contatti,
        conteggio_segnalazioni=c_segnalazioni,
        conteggio_in_arrivo=0,
        conteggio_errori=c_errori,
        conteggio_altre=c_altre,
        emails=[EmailLogOut.model_validate(e) for e in emails]
    )


@router.get("/email/conversazioni", response_model=ConversazioniResponse)
async def list_admin_conversazioni(
    pagina: int = Query(1, ge=1),
    elementi_per_pagina: int = Query(25, ge=1, le=100),
    tipologia: Optional[str] = Query(None, description="Filtra per tipologia"),
    solo_errori: bool = Query(False, description="Mostra solo conversazioni con errori"),
    search: Optional[str] = Query(None, description="Cerca per testo, email o oggetto"),
    admin: User = Depends(get_current_admin),
    db: AsyncSession = Depends(get_db)
):
    """
    Raggruppa le email generate dal sito web in conversazioni unificate per utente (stile Gmail/Outlook),
    integrando messaggi ricevuti, inviati e risposte admin.
    """
    stmt = filter_solo_email_sito(select(EmailLog))
    if tipologia:
        if tipologia == "errori":
            stmt = stmt.where(or_(EmailLog.inviata == False, EmailLog.errore.isnot(None)))
        elif tipologia == "altre":
            stmt = stmt.where(EmailLog.tipologia.notin_([
                TipologiaEmail.RECUPERO_PASSWORD.value,
                TipologiaEmail.RICHIESTA_CONTATTO.value,
                TipologiaEmail.SEGNALAZIONE.value
            ]))
        else:
            stmt = stmt.where(EmailLog.tipologia == tipologia)
    elif solo_errori:
        stmt = stmt.where(or_(EmailLog.inviata == False, EmailLog.errore.isnot(None)))

    if search and search.strip():
        q = f"%{search.strip()}%"
        stmt = stmt.where(
            (EmailLog.destinatario.ilike(q)) |
            (EmailLog.mittente.ilike(q)) |
            (EmailLog.oggetto.ilike(q)) |
            (EmailLog.corpo_testo.ilike(q))
        )

    stmt = stmt.order_by(EmailLog.data_invio.desc())
    all_emails = (await db.execute(stmt)).scalars().all()

    # Raggruppamento in conversazioni
    conversations_map: Dict[str, Dict[str, Any]] = {}
    for em in all_emails:
        c_email, c_name = get_email_counterpart(em)
        if not c_email:
            c_email = em.destinatario.lower()
            c_name = c_email

        if c_email not in conversations_map:
            conversations_map[c_email] = {
                "user_email": c_email,
                "user_name": c_name,
                "ultimo_oggetto": em.oggetto,
                "anteprima": (em.corpo_testo or em.oggetto)[:120],
                "data_ultimo_messaggio": em.data_invio,
                "totale_messaggi": 0,
                "ha_errori": False,
                "ultima_tipologia": em.tipologia,
                "ultimo_id": em.id
            }

        conversations_map[c_email]["totale_messaggi"] += 1
        if not em.inviata or em.errore:
            conversations_map[c_email]["ha_errori"] = True

    conv_list = list(conversations_map.values())
    conv_list.sort(key=lambda x: x["data_ultimo_messaggio"], reverse=True)

    totale = len(conv_list)
    offset = (pagina - 1) * elementi_per_pagina
    paginated_convs = conv_list[offset:offset + elementi_per_pagina]

    # Conteggi globali
    base_count = lambda cond: select(func.count(EmailLog.id)).where(
        EmailLog.tipologia.in_(WEB_PAGE_TIPOLOGIE),
        or_(EmailLog.link_azione.is_(None), not_(EmailLog.link_azione.like("msgid:%"))),
        cond
    )
    c_recupero = (await db.execute(base_count(EmailLog.tipologia == TipologiaEmail.RECUPERO_PASSWORD.value))).scalar() or 0
    c_contatti = (await db.execute(base_count(EmailLog.tipologia == TipologiaEmail.RICHIESTA_CONTATTO.value))).scalar() or 0
    c_segnalazioni = (await db.execute(base_count(EmailLog.tipologia == TipologiaEmail.SEGNALAZIONE.value))).scalar() or 0
    c_errori = (await db.execute(base_count(or_(EmailLog.inviata == False, EmailLog.errore.isnot(None))))).scalar() or 0
    c_altre = (await db.execute(base_count(EmailLog.tipologia.notin_([
        TipologiaEmail.RECUPERO_PASSWORD.value,
        TipologiaEmail.RICHIESTA_CONTATTO.value,
        TipologiaEmail.SEGNALAZIONE.value
    ])))).scalar() or 0

    return ConversazioniResponse(
        totale=totale,
        pagina=pagina,
        elementi_per_pagina=elementi_per_pagina,
        conteggio_errori=c_errori,
        conteggio_recupero=c_recupero,
        conteggio_contatti=c_contatti,
        conteggio_segnalazioni=c_segnalazioni,
        conteggio_in_arrivo=0,
        conteggio_altre=c_altre,
        conversazioni=[ConversazioneItem(**c) for c in paginated_convs]
    )


@router.get("/email/conversazioni/{user_email:path}", response_model=DettaglioConversazioneResponse)
async def get_admin_conversazione_detail(
    user_email: str,
    admin: User = Depends(get_current_admin),
    db: AsyncSession = Depends(get_db)
):
    """
    Restituisce l'intero thread cronologico di messaggi scambiati con uno specifico utente (solo dal sito).
    """
    target = user_email.strip().lower()
    stmt = filter_solo_email_sito(
        select(EmailLog).where(
            (EmailLog.destinatario.ilike(target)) |
            (EmailLog.mittente.ilike(f"%{target}%"))
        )
    ).order_by(EmailLog.data_invio.asc())

    result = await db.execute(stmt)
    emails = result.scalars().all()
    if not emails:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Nessun messaggio trovato per questa conversazione.")

    admin_markers = [
        (settings.ADMIN_EMAIL or "").lower(),
        (settings.EMAILS_FROM_EMAIL or "").lower(),
        "admin",
        "no-reply"
    ]

    messaggi = []
    user_name = target
    for e in emails:
        m_lower = (e.mittente or "").lower()
        is_admin = any(marker in m_lower for marker in admin_markers) or "admin" in m_lower
        if not is_admin:
            r_name, _ = email.utils.parseaddr(e.mittente)
            if r_name:
                user_name = r_name

        messaggi.append(MessaggioConversazione(
            id=e.id,
            mittente=e.mittente,
            destinatario=e.destinatario,
            oggetto=e.oggetto,
            corpo_html=e.corpo_html,
            corpo_testo=e.corpo_testo,
            tipologia=e.tipologia,
            inviata=e.inviata,
            errore=e.errore,
            link_azione=e.link_azione,
            data_invio=e.data_invio,
            is_from_admin=is_admin
        ))

    return DettaglioConversazioneResponse(
        user_email=target,
        user_name=user_name,
        totale_messaggi=len(messaggi),
        messaggi=messaggi
    )


@router.post("/email/conversazioni/{user_email:path}/rispondi")
async def reply_admin_conversazione(
    user_email: str,
    req: ConversazioneReplyRequest,
    admin: User = Depends(get_current_admin),
    db: AsyncSession = Depends(get_db)
):
    """Invia una risposta integrata nel thread della conversazione dell'utente via Google SMTP."""
    target = user_email.strip().lower()
    subject = req.oggetto or f"Risposta Amministrazione ArmiMarket Italia"
    sent = await EmailService.send_admin_reply_email(
        to_email=target,
        subject=subject,
        reply_message=req.messaggio,
        db=db
    )
    return {
        "success": True,
        "inviata_smtp": sent,
        "destinatario": target,
        "message": f"Risposta inviata con successo a {target}."
    }


@router.post("/email/sincronizza")
async def sync_google_emails(
    admin: User = Depends(get_current_admin),
    db: AsyncSession = Depends(get_db)
):
    """Sincronizza le email in arrivo dall'account Google Gmail (IMAP)."""
    res = await EmailService.sync_imap_emails(db=db)
    return res


@router.post("/email/{id}/riprova")
async def retry_failed_email(
    id: int,
    admin: User = Depends(get_current_admin),
    db: AsyncSession = Depends(get_db)
):
    """Riprova l'invio via SMTP Gmail di un'email fallita precedentemente."""
    success, error = await EmailService.retry_send_email(email_id=id, db=db)
    if success:
        return {"success": True, "message": f"Email #{id} inviata con successo tramite Gmail SMTP."}
    else:
        return {"success": False, "error": error, "message": f"Tentativo di invio non riuscito: {error}"}


@router.post("/email/{id}/risolvi")
async def resolve_single_email_error(
    id: int,
    admin: User = Depends(get_current_admin),
    db: AsyncSession = Depends(get_db)
):
    """Segna un'email con errore come risolta/archiviata."""
    stmt = select(EmailLog).where(EmailLog.id == id)
    email_obj = (await db.execute(stmt)).scalar_one_or_none()
    if not email_obj:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Email non trovata.")
    email_obj.inviata = True
    email_obj.errore = None
    await db.commit()
    return {"success": True, "message": f"Errore per email #{id} contrassegnato come risolto."}


@router.post("/email/errori/risolvi-tutti")
async def resolve_all_email_errors(
    admin: User = Depends(get_current_admin),
    db: AsyncSession = Depends(get_db)
):
    """Segna tutte le email fallite o di test come risolte/archiviate, azzerando gli errori."""
    count = await EmailService.resolve_all_errors(db=db)
    return {
        "success": True,
        "risolti": count,
        "message": f"{count} errori di invio sono stati risolti e azzerati con successo."
    }


@router.post("/email/pulisci-esterne")
async def purge_external_emails(
    admin: User = Depends(get_current_admin),
    db: AsyncSession = Depends(get_db)
):
    """Rimuove dal database eventuali email importate da caselle esterne IMAP, lasciando esclusivamente i log generati dal sito."""
    stmt = delete(EmailLog).where(
        or_(
            EmailLog.tipologia == TipologiaEmail.IN_ARRIVO.value,
            EmailLog.link_azione.like("msgid:%")
        )
    )
    result = await db.execute(stmt)
    await db.commit()
    return {"success": True, "deleted_count": result.rowcount, "message": f"{result.rowcount} email esterne rimosse con successo."}


@router.get("/email/{id}", response_model=EmailLogOut)
async def get_admin_email_detail(
    id: int,
    admin: User = Depends(get_current_admin),
    db: AsyncSession = Depends(get_db)
):
    """Restituisce il dettaglio completo e il corpo HTML renderizzabile di una specifica email."""
    stmt = select(EmailLog).where(EmailLog.id == id)
    email_obj = (await db.execute(stmt)).scalar_one_or_none()
    if not email_obj:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Email non trovata nella casella postale.")
    return EmailLogOut.model_validate(email_obj)


@router.post("/email/test")
async def send_admin_test_email(
    req: TestEmailRequest,
    admin: User = Depends(get_current_admin),
    db: AsyncSession = Depends(get_db)
):
    """Invia un email di test per verificare la connettività e memorizzarla nella casella postale."""
    sent = await EmailService.send_test_email(req.destinatario.strip(), db=db)
    return {
        "success": True,
        "inviata_smtp": sent,
        "message": f"Email di test registrata e inviata a {req.destinatario}." if sent else f"Email registrata nella webmail locale per {req.destinatario} (SMTP non configurato)."
    }


@router.delete("/email/{id}")
async def delete_admin_email(
    id: int,
    admin: User = Depends(get_current_admin),
    db: AsyncSession = Depends(get_db)
):
    """Rimuove un messaggio dalla casella postale amministratore."""
    stmt = select(EmailLog).where(EmailLog.id == id)
    email_obj = (await db.execute(stmt)).scalar_one_or_none()
    if not email_obj:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Email non trovata.")
    await db.delete(email_obj)
    await db.commit()
    return {"success": True, "message": f"Messaggio #{id} eliminato dalla casella postale."}


@router.post("/email/{id}/rispondi")
async def reply_admin_email(
    id: int,
    req: AdminReplyRequest,
    admin: User = Depends(get_current_admin),
    db: AsyncSession = Depends(get_db)
):
    """Risponde a una email pervenuta nella webmail amministratore."""
    stmt = select(EmailLog).where(EmailLog.id == id)
    email_obj = (await db.execute(stmt)).scalar_one_or_none()
    if not email_obj:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Email non trovata.")

    # Determina indirizzo destinatario
    target_email = req.destinatario
    if not target_email:
        match = re.search(r"[\w\.\-+]+@[\w\.\-]+", email_obj.mittente)
        if match:
            target_email = match.group(0)
        else:
            target_email = email_obj.destinatario

    await EmailService.send_admin_reply_email(
        to_email=target_email,
        subject=req.oggetto or email_obj.oggetto,
        reply_message=req.messaggio,
        db=db
    )

    return {
        "success": True,
        "destinatario": target_email,
        "message": f"Risposta inviata con successo a {target_email} dall'Amministratore (Admin)."
    }


# =========================================================================
# GESTIONE SEGNALAZIONI ANNUNCI NON CONFORMI (T.U.L.P.S. & Truffe)
# =========================================================================

@router.get("/segnalazioni", response_model=List[SegnalazioneOut])
async def list_segnalazioni(
    solo_aperte: bool = Query(True, description="Mostra solo segnalazioni non ancora risolte"),
    admin: User = Depends(get_current_admin),
    db: AsyncSession = Depends(get_db)
):
    """Elenca le segnalazioni di annunci non conformi o sospetti ricevute dagli utenti."""
    stmt = (
        select(SegnalazioneAnnuncio)
        .options(selectinload(SegnalazioneAnnuncio.annuncio))
        .order_by(SegnalazioneAnnuncio.data_creazione.desc())
    )
    if solo_aperte:
        stmt = stmt.where(SegnalazioneAnnuncio.risolta == False)

    res = await db.execute(stmt)
    segnalazioni = res.scalars().all()

    out = []
    for s in segnalazioni:
        ann_titolo = s.annuncio.titolo if s.annuncio else "[Annuncio Rimosso]"
        ann_prezzo = s.annuncio.prezzo if s.annuncio else None
        ann_stato = s.annuncio.stato.value if s.annuncio else "rimosso"
        out.append(
            SegnalazioneOut(
                id=s.id,
                annuncio_id=s.annuncio_id,
                motivo=s.motivo,
                dettagli=s.dettagli,
                email_segnalatore=s.email_segnalatore,
                risolta=s.risolta,
                azione_intrapresa=s.azione_intrapresa,
                data_creazione=s.data_creazione,
                annuncio_titolo=ann_titolo,
                annuncio_prezzo=ann_prezzo,
                annuncio_stato=ann_stato
            )
        )
    return out


@router.post("/segnalazioni/{id}/risolvi")
async def resolve_segnalazione(
    id: int,
    req: RisolviSegnalazioneRequest,
    admin: User = Depends(get_current_admin),
    db: AsyncSession = Depends(get_db)
):
    """Archivia o contrassegna come risolta una segnalazione."""
    stmt = select(SegnalazioneAnnuncio).where(SegnalazioneAnnuncio.id == id)
    s = (await db.execute(stmt)).scalar_one_or_none()
    if not s:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Segnalazione non trovata.")

    s.risolta = True
    s.azione_intrapresa = req.azione
    await db.commit()
    return {"success": True, "message": f"Segnalazione #{id} risolta con esito: {req.azione}"}


@router.delete("/segnalazioni/{id}/elimina-annuncio")
async def delete_reported_ad(
    id: int,
    admin: User = Depends(get_current_admin),
    db: AsyncSession = Depends(get_db)
):
    """
    Rimuove direttamente e definitivamente l'annuncio segnalato come non conforme dal portale.
    Contrassegna la segnalazione come risolta con azione 'annuncio_eliminato_da_admin'.
    """
    stmt = select(SegnalazioneAnnuncio).where(SegnalazioneAnnuncio.id == id)
    s = (await db.execute(stmt)).scalar_one_or_none()
    if not s:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Segnalazione non trovata.")

    annuncio_id = s.annuncio_id
    stmt_ad = select(Annuncio).where(Annuncio.id == annuncio_id)
    annuncio = (await db.execute(stmt_ad)).scalar_one_or_none()

    if not annuncio:
        s.risolta = True
        s.azione_intrapresa = "annuncio_gia_non_presente"
        await db.commit()
        return {"success": True, "message": f"L'annuncio #{annuncio_id} risulta già rimosso."}

    # Rimozione definitiva annuncio
    await db.delete(annuncio)
    await db.commit()

    # Se il cascade non ha cancellato la segnalazione, verifichiamo e aggiorniamo
    s_check = (await db.execute(select(SegnalazioneAnnuncio).where(SegnalazioneAnnuncio.id == id))).scalar_one_or_none()
    if s_check:
        s_check.risolta = True
        s_check.azione_intrapresa = "annuncio_eliminato_da_admin"
        await db.commit()

    return {
        "success": True,
        "message": f"Annuncio #{annuncio_id} segnalato come non conforme è stato rimosso definitivamente dal sito ArmiMarket Italia.",
        "annuncio_id": annuncio_id
    }


# =========================================================================
# GESTIONE ACCOUNT UTENTI (solo Admin)
# =========================================================================

class UserAdminOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    email: str
    nome: str
    cognome: Optional[str] = None
    ragione_sociale: Optional[str] = None
    nickname: Optional[str] = None
    partita_iva: Optional[str] = None
    codice_fiscale: Optional[str] = None
    ruolo: str
    is_active: bool
    is_verified: bool
    data_registrazione: datetime
    telefono: Optional[str] = None
    indirizzo: Optional[str] = None
    foto_profilo: Optional[str] = None
    numero_annunci: int = 0


@router.get("/utenti", response_model=List[UserAdminOut])
async def list_utenti(
    pagina: int = Query(1, ge=1),
    per_pagina: int = Query(30, ge=1, le=100),
    ruolo: Optional[str] = Query(None, description="Filtra per ruolo: privato, armeria, admin"),
    attivo: Optional[bool] = Query(None, description="Filtra per stato account"),
    cerca: Optional[str] = Query(None, description="Cerca per nome, email o nickname"),
    admin: User = Depends(get_current_admin),
    db: AsyncSession = Depends(get_db),
):
    """Restituisce l'elenco paginato di tutti gli account registrati sulla piattaforma."""
    from sqlalchemy import func as sqlfunc
    from app.models.annuncio import Annuncio

    SYSTEM_BOT_EMAIL = "indicizzatore.bot@armimarket.it"
    from app.services.scraper.directory import ARMERIE_TARGETS
    directory_emails = [a["email"].lower() for a in ARMERIE_TARGETS if a.get("email")]
    stmt = select(User).where(User.email != SYSTEM_BOT_EMAIL)
    if directory_emails:
        stmt = stmt.where(~sqlfunc.lower(User.email).in_(directory_emails))
    if ruolo:
        stmt = stmt.where(User.ruolo == ruolo)
    if attivo is not None:
        stmt = stmt.where(User.is_active == attivo)
    if cerca and cerca.strip():
        q = f"%{cerca.strip()}%"
        stmt = stmt.where(
            User.email.ilike(q) | User.nome.ilike(q) |
            User.cognome.ilike(q) | User.nickname.ilike(q) |
            User.ragione_sociale.ilike(q)
        )

    count_stmt = select(sqlfunc.count()).select_from(stmt.subquery())
    totale = (await db.execute(count_stmt)).scalar() or 0

    offset = (pagina - 1) * per_pagina
    stmt = stmt.order_by(User.data_registrazione.desc()).offset(offset).limit(per_pagina)
    result = await db.execute(stmt)
    utenti = result.scalars().all()

    # Conta annunci per ogni utente con una query singola
    from sqlalchemy import case
    ids = [u.id for u in utenti]
    if ids:
        counts_stmt = (
            select(Annuncio.utente_id, sqlfunc.count(Annuncio.id).label("cnt"))
            .where(Annuncio.utente_id.in_(ids))
            .group_by(Annuncio.utente_id)
        )
        counts_res = await db.execute(counts_stmt)
        counts_map = {row.utente_id: row.cnt for row in counts_res}
    else:
        counts_map = {}

    out = []
    for u in utenti:
        out.append(UserAdminOut(
            id=u.id, email=u.email, nome=u.nome, cognome=u.cognome,
            ragione_sociale=u.ragione_sociale, nickname=u.nickname,
            partita_iva=u.partita_iva, codice_fiscale=u.codice_fiscale,
            ruolo=u.ruolo.value if hasattr(u.ruolo, 'value') else u.ruolo,
            is_active=u.is_active, is_verified=u.is_verified,
            data_registrazione=u.data_registrazione,
            telefono=u.telefono, indirizzo=u.indirizzo,
            foto_profilo=u.foto_profilo,
            numero_annunci=counts_map.get(u.id, 0)
        ))
    return out


@router.get("/utenti/{utente_id}", response_model=UserAdminOut)
async def get_utente_detail(
    utente_id: int,
    admin: User = Depends(get_current_admin),
    db: AsyncSession = Depends(get_db),
):
    """Restituisce il dettaglio completo di un account utente."""
    from app.models.annuncio import Annuncio
    from sqlalchemy import func as sqlfunc

    stmt = select(User).where(User.id == utente_id)
    u = (await db.execute(stmt)).scalar_one_or_none()
    if not u:
        raise HTTPException(status_code=404, detail="Utente non trovato.")

    cnt_stmt = select(sqlfunc.count(Annuncio.id)).where(Annuncio.utente_id == utente_id)
    num_annunci = (await db.execute(cnt_stmt)).scalar() or 0

    return UserAdminOut(
        id=u.id, email=u.email, nome=u.nome, cognome=u.cognome,
        ragione_sociale=u.ragione_sociale, nickname=u.nickname,
        partita_iva=u.partita_iva, codice_fiscale=u.codice_fiscale,
        ruolo=u.ruolo.value if hasattr(u.ruolo, 'value') else u.ruolo,
        is_active=u.is_active, is_verified=u.is_verified,
        data_registrazione=u.data_registrazione,
        telefono=u.telefono, indirizzo=u.indirizzo,
        foto_profilo=u.foto_profilo,
        numero_annunci=num_annunci
    )


@router.patch("/utenti/{utente_id}/disabilita")
async def disabilita_utente(
    utente_id: int,
    admin: User = Depends(get_current_admin),
    db: AsyncSession = Depends(get_db),
):
    """Disabilita un account utente (blocca l'accesso senza eliminare i dati)."""
    u = (await db.execute(select(User).where(User.id == utente_id))).scalar_one_or_none()
    if not u:
        raise HTTPException(status_code=404, detail="Utente non trovato.")
    if u.ruolo == RuoloUtente.ADMIN:
        raise HTTPException(status_code=403, detail="Impossibile disabilitare un account Admin.")
    u.is_active = False
    await db.commit()
    return {"success": True, "message": f"Account #{utente_id} ({u.email}) disabilitato. L'utente non potrà più accedere."}


@router.patch("/utenti/{utente_id}/riabilita")
async def riabilita_utente(
    utente_id: int,
    admin: User = Depends(get_current_admin),
    db: AsyncSession = Depends(get_db),
):
    """Riabilita un account utente precedentemente disabilitato."""
    u = (await db.execute(select(User).where(User.id == utente_id))).scalar_one_or_none()
    if not u:
        raise HTTPException(status_code=404, detail="Utente non trovato.")
    u.is_active = True
    await db.commit()
    return {"success": True, "message": f"Account #{utente_id} ({u.email}) riabilitato con successo."}


@router.delete("/utenti/{utente_id}")
async def elimina_utente(
    utente_id: int,
    admin: User = Depends(get_current_admin),
    db: AsyncSession = Depends(get_db),
):
    """
    Elimina definitivamente un account utente e tutti i suoi annunci dal database.
    Operazione irreversibile — richiede ruolo ADMIN.
    """
    if utente_id == admin.id:
        raise HTTPException(status_code=400, detail="Non puoi eliminare il tuo stesso account Admin.")

    u = (await db.execute(select(User).where(User.id == utente_id))).scalar_one_or_none()
    if not u:
        raise HTTPException(status_code=404, detail="Utente non trovato.")
    if u.ruolo == RuoloUtente.ADMIN:
        raise HTTPException(status_code=403, detail="Impossibile eliminare un account Admin.")

    email_rimossa = u.email
    await db.delete(u)   # cascade elimina annunci e preferiti
    await db.commit()

    return {
        "success": True,
        "message": f"Account '{email_rimossa}' e tutti i suoi dati sono stati rimossi definitivamente dalla piattaforma."
    }


# =========================================================================
# STATISTICHE GLOBALI PIATTAFORMA (solo Admin)
# =========================================================================

@router.get("/statistiche")
async def get_piattaforma_statistiche(
    admin: User = Depends(get_current_admin),
    db: AsyncSession = Depends(get_db),
):
    """
    Restituisce metriche e statistiche aggregate globali del portale ArmiMarket Italia:
    - Utenti: totali, privati, armerie, attivi, disabilitati
    - Annunci: totali, pubblicati, in moderazione, rifiutati, venduti, bozze
    - Visualizzazioni totali
    - Ripartizione annunci per tipologia arma e inserzionista
    - Log messaggi/email ed esiti
    - Segnalazioni di conformità
    """
    from app.models.annuncio import Annuncio, StatoAnnuncio, TipologiaArma, TipologiaInserzionista
    from app.models.email_log import EmailLog
    from app.models.segnalazione import SegnalazioneAnnuncio
    from sqlalchemy import case, func as sqlfunc

    # 1. Statistiche Utenti Registrati (escluso bot tecnico di scraping ed armerie della directory)
    SYSTEM_BOT_EMAIL = "indicizzatore.bot@armimarket.it"
    from app.services.scraper.directory import ARMERIE_TARGETS
    directory_emails = [a["email"].lower() for a in ARMERIE_TARGETS if a.get("email")]
    user_cond = (User.email != SYSTEM_BOT_EMAIL)
    if directory_emails:
        user_cond = user_cond & (~sqlfunc.lower(User.email).in_(directory_emails))

    user_stats_res = await db.execute(
        select(
            sqlfunc.count(User.id).label("totale"),
            sqlfunc.sum(case((User.ruolo == RuoloUtente.PRIVATO, 1), else_=0)).label("privati"),
            sqlfunc.sum(case((User.ruolo == RuoloUtente.ARMERIA, 1), else_=0)).label("armerie"),
            sqlfunc.sum(case((User.ruolo == RuoloUtente.ADMIN, 1), else_=0)).label("admin"),
            sqlfunc.sum(case((User.is_active == True, 1), else_=0)).label("attivi"),
            sqlfunc.sum(case((User.is_active == False, 1), else_=0)).label("disabilitati"),
        ).where(user_cond)
    )
    user_row = user_stats_res.one()

    # 2. Statistiche Annunci per Stato e Visualizzazioni Totali
    annunci_stats_res = await db.execute(
        select(
            sqlfunc.count(Annuncio.id).label("totale"),
            sqlfunc.sum(case((Annuncio.stato == StatoAnnuncio.PUBBLICATO, 1), else_=0)).label("pubblicati"),
            sqlfunc.sum(case((Annuncio.stato == StatoAnnuncio.IN_MODERAZIONE, 1), else_=0)).label("in_moderazione"),
            sqlfunc.sum(case((Annuncio.stato == StatoAnnuncio.RIFIUTATO, 1), else_=0)).label("rifiutati"),
            sqlfunc.sum(case((Annuncio.stato == StatoAnnuncio.VENDUTO, 1), else_=0)).label("venduti"),
            sqlfunc.sum(case((Annuncio.stato == StatoAnnuncio.BOZZA, 1), else_=0)).label("bozza"),
            sqlfunc.coalesce(sqlfunc.sum(Annuncio.visualizzazioni), 0).label("totale_visualizzazioni"),
        )
    )
    annunci_row = annunci_stats_res.one()

    # 3. Annunci per Tipologia Inserzionista
    inserzionista_stats_res = await db.execute(
        select(
            sqlfunc.sum(case((Annuncio.tipologia_inserzionista == TipologiaInserzionista.ARMERIA, 1), else_=0)).label("armeria"),
            sqlfunc.sum(case((Annuncio.tipologia_inserzionista == TipologiaInserzionista.PRIVATO, 1), else_=0)).label("privato"),
        )
    )
    ins_row = inserzionista_stats_res.one()

    # 4. Annunci per Tipologia Arma
    armi_stats_res = await db.execute(
        select(
            sqlfunc.sum(case((Annuncio.tipologia_arma == TipologiaArma.ARMA_CORTA, 1), else_=0)).label("arma_corta"),
            sqlfunc.sum(case((Annuncio.tipologia_arma == TipologiaArma.ARMA_LUNGA_RIGATA, 1), else_=0)).label("arma_lunga_rigata"),
            sqlfunc.sum(case((Annuncio.tipologia_arma == TipologiaArma.CANNA_LISCIA, 1), else_=0)).label("canna_liscia"),
            sqlfunc.sum(case((Annuncio.tipologia_arma == TipologiaArma.ARIA_COMPRESSA_LIBERA, 1), else_=0)).label("aria_compressa_libera"),
            sqlfunc.sum(case((Annuncio.tipologia_arma == TipologiaArma.ACCESSORIO_OTTICA, 1), else_=0)).label("accessorio_ottica"),
        )
    )
    armi_row = armi_stats_res.one()

    # 5. Statistiche Email inviate dal sistema
    email_stats_res = await db.execute(
        select(
            sqlfunc.count(EmailLog.id).label("totale"),
            sqlfunc.sum(case((EmailLog.inviata == True, 1), else_=0)).label("inviate"),
            sqlfunc.sum(case((EmailLog.inviata == False, 1), else_=0)).label("errori"),
        )
    )
    email_row = email_stats_res.one()

    # 6. Statistiche Segnalazioni
    segnalazioni_stats_res = await db.execute(
        select(
            sqlfunc.count(SegnalazioneAnnuncio.id).label("totale"),
            sqlfunc.sum(case((SegnalazioneAnnuncio.risolta == True, 1), else_=0)).label("risolte"),
            sqlfunc.sum(case((SegnalazioneAnnuncio.risolta == False, 1), else_=0)).label("aperte"),
        )
    )
    segnalazioni_row = segnalazioni_stats_res.one()

    # 7. Statistiche Valutazioni & Recensioni
    from app.models.valutazione import Valutazione
    valutazioni_stats_res = await db.execute(
        select(
            sqlfunc.count(Valutazione.id).label("totale"),
            sqlfunc.coalesce(sqlfunc.avg(Valutazione.voto), 0.0).label("media_voto"),
        )
    )
    valutazioni_row = valutazioni_stats_res.one()

    return {
        "success": True,
        "utenti": {
            "totale": int(user_row.totale or 0),
            "privati": int(user_row.privati or 0),
            "armerie": int(user_row.armerie or 0),
            "admin": int(user_row.admin or 0),
            "attivi": int(user_row.attivi or 0),
            "disabilitati": int(user_row.disabilitati or 0),
        },
        "annunci": {
            "totale": int(annunci_row.totale or 0),
            "pubblicati": int(annunci_row.pubblicati or 0),
            "in_moderazione": int(annunci_row.in_moderazione or 0),
            "rifiutati": int(annunci_row.rifiutati or 0),
            "venduti": int(annunci_row.venduti or 0),
            "bozza": int(annunci_row.bozza or 0),
            "totale_visualizzazioni": int(annunci_row.totale_visualizzazioni or 0),
        },
        "inserzionisti": {
            "armeria": int(ins_row.armeria or 0),
            "privato": int(ins_row.privato or 0),
        },
        "tipologie_arma": {
            "arma_corta": int(armi_row.arma_corta or 0),
            "arma_lunga_rigata": int(armi_row.arma_lunga_rigata or 0),
            "canna_liscia": int(armi_row.canna_liscia or 0),
            "aria_compressa_libera": int(armi_row.aria_compressa_libera or 0),
            "accessorio_ottica": int(armi_row.accessorio_ottica or 0),
        },
        "comunicazioni": {
            "email_totali": int(email_row.totale or 0),
            "email_inviate": int(email_row.inviate or 0),
            "email_errori": int(email_row.errori or 0),
            "segnalazioni_totali": int(segnalazioni_row.totale or 0),
            "segnalazioni_aperte": int(segnalazioni_row.aperte or 0),
            "segnalazioni_risolte": int(segnalazioni_row.risolte or 0),
            "valutazioni_totali": int(valutazioni_row.totale or 0),
            "valutazioni_media": round(float(valutazioni_row.media_voto or 0.0), 1),
        }
    }

