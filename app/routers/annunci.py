import re
import uuid
from typing import List, Optional
from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.core.database import get_db
from app.core.legal import LEGAL_DISCLAIMER_ANNUNCIO, LEGAL_DISCLAIMER_FOOTER
from app.core.rate_limit import rate_limit
from app.models.annuncio import (
    Annuncio,
    ClassificazioneArma,
    CondizioneArma,
    StatoAnnuncio,
    TipologiaArma,
    TipologiaInserzionista,
)
from app.models.geo import Comune, Provincia
from app.models.poligono import PoligonoTiro
from app.models.ricerca_salvata import RicercaSalvata
from app.models.segnalazione import SegnalazioneAnnuncio
from app.models.user import RuoloUtente, User
from app.routers.auth import get_current_user, get_optional_current_user
from app.schemas.annuncio_schema import (
    AnnuncioCreate,
    AnnuncioDetailOut,
    AnnuncioListResponse,
    AnnuncioPublicOut,
    ComuneOut,
    ContactFormRequest,
    ContactFormResponse,
    GeoJSONFeatureCollection,
    RicercaSalvataCreate,
    SegnalazioneCreate,
)
from app.services.email_service import EmailService
from app.services.moderation_service import ModerationService
from app.services.search_service import SearchService

router = APIRouter(prefix="/annunci", tags=["Bacheca Annunci Armi & Accessori"])


@router.get("", response_model=AnnuncioListResponse)
async def search_annunci(
    q: Optional[str] = Query(None, description="Ricerca full-text su marca, modello, calibro, titolo"),
    regione_id: Optional[int] = Query(None, description="Filtro ID regione"),
    provincia_id: Optional[int] = Query(None, description="Filtro ID provincia"),
    comune_id: Optional[int] = Query(None, description="Filtro ID comune"),
    lat: Optional[float] = Query(None, ge=35.0, le=48.0, description="Latitudine per ricerca prossimità"),
    lon: Optional[float] = Query(None, ge=6.0, le=19.0, description="Longitudine per ricerca prossimità"),
    raggio_km: Optional[float] = Query(None, ge=1.0, le=500.0, description="Raggio chilometrico (PostGIS ST_DWithin)"),
    tipologia_inserzionista: Optional[TipologiaInserzionista] = Query(None, description="privato o armeria"),
    tipologia_arma: Optional[TipologiaArma] = Query(None, description="arma_corta, arma_lunga_rigata, canna_liscia, ecc."),
    marca: Optional[str] = Query(None, description="Marca (es. Beretta, Glock, Benelli)"),
    calibro: Optional[str] = Query(None, description="Calibro (es. 9x21, .308 Win, 12/76)"),
    classificazione: Optional[ClassificazioneArma] = Query(None, description="comune, sportiva, caccia"),
    condizione: Optional[CondizioneArma] = Query(None, description="nuovo, usato_ottimo, usato_buono, da_collezione"),
    prezzo_min: Optional[float] = Query(None, ge=0, description="Prezzo minimo"),
    prezzo_max: Optional[float] = Query(None, ge=0, description="Prezzo massimo"),
    ordina_per: str = Query("data_desc", pattern="^(data_desc|prezzo_asc|prezzo_desc|distanza)$"),
    pagina: int = Query(1, ge=1, description="Numero di pagina"),
    elementi_per_pagina: int = Query(20, ge=1, le=100, description="Annunci per pagina"),
    db: AsyncSession = Depends(get_db)
):
    """
    Ricerca avanzata con filtri combinati, full-text search e prossimità geografica (PostGIS).
    """
    risultati, totale = await SearchService.search_annunci(
        db=db,
        q=q,
        regione_id=regione_id,
        provincia_id=provincia_id,
        comune_id=comune_id,
        lat=lat,
        lon=lon,
        raggio_km=raggio_km,
        tipologia_inserzionista=tipologia_inserzionista,
        tipologia_arma=tipologia_arma,
        marca=marca,
        calibro=calibro,
        classificazione=classificazione,
        condizione=condizione,
        prezzo_min=prezzo_min,
        prezzo_max=prezzo_max,
        ordina_per=ordina_per,
        pagina=pagina,
        elementi_per_pagina=elementi_per_pagina,
        solo_pubblicati=True
    )

    pagine_totali = max(1, (totale + elementi_per_pagina - 1) // elementi_per_pagina)

    return AnnuncioListResponse(
        totale=totale,
        pagina=pagina,
        pagine_totali=pagine_totali,
        elementi_per_pagina=elementi_per_pagina,
        risultati=risultati
    )


@router.get("/mappa/geojson", response_model=GeoJSONFeatureCollection)
async def get_map_geojson(
    tipologia_arma: Optional[TipologiaArma] = Query(None, description="Filtra tipo arma per la mappa"),
    tipologia_inserzionista: Optional[TipologiaInserzionista] = Query(None, description="Filtra privato o armeria"),
    db: AsyncSession = Depends(get_db)
):
    """
    Restituisce un FeatureCollection GeoJSON con le coordinate geografiche di tutti gli annunci attivi.
    Ogni elemento contiene titolo, calibro, prezzo e link diretto alla scheda annuncio.
    """
    return await SearchService.get_geojson_map(
        db=db,
        tipologia_arma=tipologia_arma,
        tipologia_inserzionista=tipologia_inserzionista
    )


@router.post(
    "",
    response_model=AnnuncioPublicOut,
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(rate_limit(max_requests=10, window_seconds=60, prefix="annunci_create"))]
)
async def create_annuncio(
    annuncio_in: AnnuncioCreate,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    """
    Creazione di una nuova inserzione.
    - Controllo preventivo parole vietate (T.U.L.P.S. e divieto armi da guerra/silenziatori).
    - Privati: l'annuncio passa allo stato 'in_moderazione' prima dell'approvazione pubblica.
    - Armerie verificate: pubblicazione immediata con stato 'pubblicato'.
    - La matricola fornita viene protetta e non verrà mai mostrata pubblicamente in chiaro.
    """
    # 1. Verifica comune esistente
    stmt_comune = select(Comune).where(Comune.id == annuncio_in.comune_id)
    comune = (await db.execute(stmt_comune)).scalar_one_or_none()
    if not comune:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Il comune selezionato non è presente nell'anagrafica ISTAT."
        )

    # 2. Controllo preventivo T.U.L.P.S. sul testo
    testo_completo = f"{annuncio_in.titolo} {annuncio_in.descrizione} {annuncio_in.marca} {annuncio_in.modello}"
    is_ok, banned_term = ModerationService.verify_compliance(testo_completo)
    if not is_ok:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"Termine vietato rilevato ('{banned_term}'): inserzione non conforme alle disposizioni T.U.L.P.S."
        )

    # 3. Determinazione stato iniziale
    if current_user.ruolo == RuoloUtente.ARMERIA and current_user.is_verified:
        stato_iniziale = StatoAnnuncio.PUBBLICATO
        tipo_ins = TipologiaInserzionista.ARMERIA
    else:
        stato_iniziale = StatoAnnuncio.IN_MODERAZIONE
        tipo_ins = (
            TipologiaInserzionista.ARMERIA
            if current_user.ruolo == RuoloUtente.ARMERIA
            else TipologiaInserzionista.PRIVATO
        )

    # 4. Generazione slug univoco
    slug_base = re.sub(r"[^\w\s-]", "", annuncio_in.titolo.lower()).strip()
    slug = f"{re.sub(r'[-\s]+', '-', slug_base)}-{uuid.uuid4().hex[:6]}"

    annuncio = Annuncio(
        titolo=annuncio_in.titolo,
        slug=slug,
        descrizione=annuncio_in.descrizione,
        prezzo=annuncio_in.prezzo,
        stato=stato_iniziale,
        tipologia_inserzionista=tipo_ins,
        tipologia_arma=annuncio_in.tipologia_arma,
        marca=annuncio_in.marca,
        modello=annuncio_in.modello,
        calibro=annuncio_in.calibro,
        classificazione=annuncio_in.classificazione,
        condizione=annuncio_in.condizione,
        matricola_riservata=annuncio_in.matricola_riservata,
        comune_id=annuncio_in.comune_id,
        utente_id=current_user.id,
        galleria_immagini=annuncio_in.galleria_immagini,
        email_contatto=annuncio_in.email_contatto,
        telefono_contatto=annuncio_in.telefono_contatto,
        mostra_telefono_pubblico=annuncio_in.mostra_telefono_pubblico,
    )

    db.add(annuncio)
    await db.commit()
    await db.refresh(annuncio)

    # Carica relazioni
    stmt_full = (
        select(Annuncio)
        .options(selectinload(Annuncio.comune).selectinload(Comune.provincia).selectinload(Provincia.regione))
        .where(Annuncio.id == annuncio.id)
    )
    annuncio_completo = (await db.execute(stmt_full)).scalar_one()

    return AnnuncioPublicOut(
        id=annuncio_completo.id,
        titolo=annuncio_completo.titolo,
        slug=annuncio_completo.slug,
        descrizione=annuncio_completo.descrizione,
        prezzo=annuncio_completo.prezzo,
        stato=annuncio_completo.stato,
        tipologia_inserzionista=annuncio_completo.tipologia_inserzionista,
        tipologia_arma=annuncio_completo.tipologia_arma,
        marca=annuncio_completo.marca,
        modello=annuncio_completo.modello,
        calibro=annuncio_completo.calibro,
        classificazione=annuncio_completo.classificazione,
        condizione=annuncio_completo.condizione,
        comune_id=annuncio_completo.comune_id,
        galleria_immagini=annuncio_completo.galleria_immagini or [],
        email_contatto=annuncio_completo.email_contatto if annuncio_completo.tipologia_inserzionista == TipologiaInserzionista.ARMERIA else None,
        telefono_contatto=annuncio_completo.telefono_contatto if annuncio_completo.mostra_telefono_pubblico else None,
        visualizzazioni=annuncio_completo.visualizzazioni,
        data_creazione=annuncio_completo.data_creazione,
        data_aggiornamento=annuncio_completo.data_aggiornamento,
        comune=ComuneOut(
            id=annuncio_completo.comune.id,
            nome=annuncio_completo.comune.nome,
            codice_istat=annuncio_completo.comune.codice_istat,
            cap=annuncio_completo.comune.cap,
            provincia_id=annuncio_completo.comune.provincia_id,
            latitudine=annuncio_completo.comune.latitudine,
            longitudine=annuncio_completo.comune.longitudine,
            sigla_provincia=annuncio_completo.comune.provincia.sigla_automobilistica,
            nome_regione=annuncio_completo.comune.provincia.regione.nome,
        )
    )


@router.get("/{id}", response_model=AnnuncioDetailOut)
async def get_annuncio_detail(
    id: int,
    db: AsyncSession = Depends(get_db),
    current_user: Optional[User] = Depends(get_optional_current_user),
):
    """
    Restituisce la scheda completa di un annuncio:
    - PUBBLICATO: visibile a tutti
    - IN_MODERAZIONE: visibile solo al proprietario e allo staff (admin/moderatori)
    - RIFIUTATO / SOSPESO: riservato a proprietario e staff; restituisce 404 a utenti non autorizzati.
    - Incrementa automaticamente il contatore delle visualizzazioni.
    - Fornisce coordinate per la visualizzazione sulla mappa (centrate sul comune a tutela della privacy per privati).
    - Espone i disclaimer T.U.L.P.S. obbligatori.
    - La matricola non viene MAI fornita in chiaro.
    """
    stmt = (
        select(Annuncio)
        .options(
            selectinload(Annuncio.comune).selectinload(Comune.provincia).selectinload(Provincia.regione)
        )
        .where(Annuncio.id == id)
    )
    res = await db.execute(stmt)
    annuncio = res.scalar_one_or_none()

    if not annuncio:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Annuncio non trovato."
        )

    # Controllo stato annuncio e autorizzazioni
    if annuncio.stato != StatoAnnuncio.PUBBLICATO:
        is_owner = current_user and current_user.id == annuncio.utente_id
        is_staff = current_user and current_user.ruolo in [RuoloUtente.ADMIN, RuoloUtente.MODERATORE]
        if not (is_owner or is_staff):
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Annuncio non trovato."
            )

    # Incremento visualizzazioni
    annuncio.visualizzazioni += 1
    await db.commit()

    comune_out = None
    lat_mappa = 41.9028  # Default Roma se privo
    lon_mappa = 12.4964
    if annuncio.comune:
        lat_mappa = annuncio.comune.latitudine
        lon_mappa = annuncio.comune.longitudine
        comune_out = ComuneOut(
            id=annuncio.comune.id,
            nome=annuncio.comune.nome,
            codice_istat=annuncio.comune.codice_istat,
            cap=annuncio.comune.cap,
            provincia_id=annuncio.comune.provincia_id,
            latitudine=annuncio.comune.latitudine,
            longitudine=annuncio.comune.longitudine,
            sigla_provincia=annuncio.comune.provincia.sigla_automobilistica,
            nome_regione=annuncio.comune.provincia.regione.nome,
        )

    precisione = (
        "esatta_armeria"
        if annuncio.tipologia_inserzionista == TipologiaInserzionista.ARMERIA
        else "comunale_protetta"
    )

    return AnnuncioDetailOut(
        id=annuncio.id,
        titolo=annuncio.titolo,
        slug=annuncio.slug,
        descrizione=annuncio.descrizione,
        prezzo=annuncio.prezzo,
        stato=annuncio.stato,
        tipologia_inserzionista=annuncio.tipologia_inserzionista,
        tipologia_arma=annuncio.tipologia_arma,
        marca=annuncio.marca,
        modello=annuncio.modello,
        calibro=annuncio.calibro,
        classificazione=annuncio.classificazione,
        condizione=annuncio.condizione,
        comune_id=annuncio.comune_id,
        galleria_immagini=annuncio.galleria_immagini or [],
        email_contatto=annuncio.email_contatto if annuncio.tipologia_inserzionista == TipologiaInserzionista.ARMERIA else None,
        telefono_contatto=annuncio.telefono_contatto if annuncio.mostra_telefono_pubblico else None,
        visualizzazioni=annuncio.visualizzazioni,
        data_creazione=annuncio.data_creazione,
        data_aggiornamento=annuncio.data_aggiornamento,
        comune=comune_out,
        latitudine_mappa=lat_mappa,
        longitudine_mappa=lon_mappa,
        precisione_mappa=precisione,
    )


@router.post(
    "/{id}/contatta",
    response_model=ContactFormResponse,
    dependencies=[Depends(rate_limit(max_requests=5, window_seconds=60, prefix="annunci_contatta"))]
)
async def contact_advertiser(
    id: int,
    form_in: ContactFormRequest,
    db: AsyncSession = Depends(get_db)
):
    """
    Invio richiesta di contatto all'inserzionista:
    - Obbligatorio dichiarare il possesso di un titolo di polizia valido.
    - Obbligatorio confermare la conoscenza dell'obbligo di denuncia di detenzione entro 72 ore.
    - Protezione e garanzia della legalità del contatto.
    """
    stmt = select(Annuncio).where(Annuncio.id == id, Annuncio.stato == StatoAnnuncio.PUBBLICATO)
    annuncio = (await db.execute(stmt)).scalar_one_or_none()

    if not annuncio:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Annuncio non trovato o non più disponibile."
        )

    # Invia email al venditore e registra la notifica nella casella email della piattaforma
    from app.services.email_service import EmailService
    await EmailService.send_contact_request_email(
        to_email=annuncio.email_contatto,
        buyer_nome=form_in.nome_mittente,
        buyer_email=form_in.email_mittente,
        titolo_polizia=form_in.titolo_di_polizia,
        messaggio=form_in.messaggio,
        annuncio_titolo=annuncio.titolo,
        annuncio_id=annuncio.id,
        db=db
    )

    return ContactFormResponse(
        success=True,
        message=(
            f"La tua richiesta è stata inoltrata al venditore ({annuncio.email_contatto}). "
            f"Ricorda che la cessione potrà avvenire solo di persona previa verifica del titolo "
            f"'{form_in.titolo_di_polizia}' e con l'obbligo di denuncia entro 72 ore."
        )
    )


@router.get("/utente/miei", response_model=List[AnnuncioPublicOut])
async def get_my_annunci(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    """Restituisce tutti gli annunci pubblicati o caricati dall'utente autenticato (inclusi venduti e in moderazione)."""
    stmt = (
        select(Annuncio)
        .where(Annuncio.utente_id == current_user.id)
        .options(
            selectinload(Annuncio.comune).selectinload(Comune.provincia).selectinload(Provincia.regione)
        )
        .order_by(Annuncio.data_creazione.desc())
    )
    res = await db.execute(stmt)
    annunci = res.scalars().all()

    out = []
    for a in annunci:
        comune_out = None
        if a.comune:
            comune_out = ComuneOut(
                id=a.comune.id,
                nome=a.comune.nome,
                cap=a.comune.cap,
                provincia_id=a.comune.provincia_id,
                latitudine=a.comune.latitudine,
                longitudine=a.comune.longitudine,
                sigla_provincia=a.comune.provincia.sigla_automobilistica if a.comune.provincia else None,
                nome_regione=a.comune.provincia.regione.nome if a.comune.provincia and a.comune.provincia.regione else None
            )
        out.append(
            AnnuncioPublicOut(
                id=a.id,
                titolo=a.titolo,
                slug=a.slug,
                descrizione=a.descrizione,
                prezzo=a.prezzo,
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
                telefono_contatto=a.telefono_contatto if a.mostra_telefono_pubblico else None,
                visualizzazioni=a.visualizzazioni,
                data_creazione=a.data_creazione,
                data_aggiornamento=a.data_aggiornamento,
                comune=comune_out
            )
        )
    return out


@router.delete("/{id}", status_code=status.HTTP_200_OK)
async def delete_annuncio(
    id: int,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    """
    Rimuove definitivamente un annuncio dal database:
    - Permette agli inserzionisti di eliminare gli annunci di armi vendute.
    - Evita l'accumulo di dati obsoleti.
    - Consente l'eliminazione anche agli amministratori/moderatori.
    """
    stmt = select(Annuncio).where(Annuncio.id == id)
    annuncio = (await db.execute(stmt)).scalar_one_or_none()

    if not annuncio:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Annuncio non trovato."
        )

    # Verifica autorizzazione (proprietario dell'annuncio o staff admin/moderatore)
    if annuncio.utente_id != current_user.id and current_user.ruolo not in [RuoloUtente.ADMIN, RuoloUtente.MODERATORE]:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Non hai i permessi per eliminare questo annuncio."
        )

    await db.delete(annuncio)
    await db.commit()
    return {"message": "Annuncio rimosso con successo per articolo venduto/ritirato.", "id": id}


@router.patch("/{id}/stato", status_code=status.HTTP_200_OK)
async def update_annuncio_stato(
    id: int,
    nuovo_stato: StatoAnnuncio = Query(..., description="Nuovo stato dell'annuncio (es. venduto, pubblicato, archiviato)"),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    """Aggiorna lo stato di un annuncio (es. contrassegna come VENDUTO o ARCHIVIATO)."""
    stmt = select(Annuncio).where(Annuncio.id == id)
    annuncio = (await db.execute(stmt)).scalar_one_or_none()

    if not annuncio:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Annuncio non trovato."
        )

    if annuncio.utente_id != current_user.id and current_user.ruolo not in [RuoloUtente.ADMIN, RuoloUtente.MODERATORE]:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Non hai i permessi per modificare questo annuncio."
        )

    # Prevenzione bypass moderazione: solo admin/moderatori possono pubblicare o approvare direttamente
    if current_user.ruolo not in [RuoloUtente.ADMIN, RuoloUtente.MODERATORE]:
        if nuovo_stato == StatoAnnuncio.PUBBLICATO:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Solo l'amministratore o un moderatore autorizzato può approvare o pubblicare direttamente un annuncio."
            )
        if nuovo_stato == StatoAnnuncio.RIFIUTATO:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Non puoi contrassegnare l'annuncio come rifiutato."
            )
        if nuovo_stato not in [StatoAnnuncio.VENDUTO, StatoAnnuncio.ARCHIVIATO, StatoAnnuncio.IN_MODERAZIONE]:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Transizione di stato a '{nuovo_stato.value}' non consentita per l'inserzionista."
            )

    annuncio.stato = nuovo_stato
    await db.commit()
    return {"message": f"Stato annuncio aggiornato a '{nuovo_stato.value}'.", "id": id, "stato": nuovo_stato.value}


@router.post(
    "/{id}/segnala",
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(rate_limit(max_requests=5, window_seconds=60, prefix="annunci_segnala"))]
)
async def segnala_annuncio(
    id: int,
    req: SegnalazioneCreate,
    db: AsyncSession = Depends(get_db)
):
    """
    Invia una segnalazione per annuncio non conforme (difformità T.U.L.P.S., sospetta truffa, ecc.).
    La segnalazione viene registrata per la revisione e rimozione immediata da parte dell'Admin.
    """
    stmt = select(Annuncio).where(Annuncio.id == id)
    annuncio = (await db.execute(stmt)).scalar_one_or_none()
    if not annuncio:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Annuncio da segnalare non trovato."
        )

    segnalazione = SegnalazioneAnnuncio(
        annuncio_id=id,
        motivo=req.motivo,
        dettagli=req.dettagli,
        email_segnalatore=req.email_segnalatore,
    )
    db.add(segnalazione)
    await db.commit()
    await db.refresh(segnalazione)

    # Invia notifica alla casella postale amministratore
    await EmailService.send_report_notification_to_admin(
        annuncio_id=annuncio.id,
        annuncio_titolo=annuncio.titolo,
        motivo=req.motivo,
        dettagli=req.dettagli,
        email_segnalatore=req.email_segnalatore,
        db=db
    )

    return {
        "success": True,
        "message": "Segnalazione ricevuta con successo. L'amministrazione esaminerà l'annuncio per eventuale rimozione immediata.",
        "segnalazione_id": segnalazione.id
    }


@router.post(
    "/salva-ricerca",
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(rate_limit(max_requests=10, window_seconds=60, prefix="annunci_salva_ricerca"))]
)
async def save_search_alert(
    req: RicercaSalvataCreate,
    db: AsyncSession = Depends(get_db)
):
    """Salva i criteri di ricerca per ricevere avvisi quando vengono pubblicati nuovi annunci compatibili."""
    ricerca = RicercaSalvata(
        email=req.email,
        criteri=req.criteri,
        descrizione_ricerca=req.descrizione_ricerca,
        attiva=True
    )
    db.add(ricerca)
    await db.commit()
    await db.refresh(ricerca)

    return {
        "success": True,
        "message": f"Avviso salvato per {req.email}! Riceverai notifiche sui nuovi annunci per '{req.descrizione_ricerca}'.",
        "id": ricerca.id
    }


@router.get("/poligoni")
async def list_poligoni(
    db: AsyncSession = Depends(get_db)
):
    """Restituisce l'elenco dei poligoni di tiro e sezioni TSN censiti sulla mappa."""
    stmt = (
        select(PoligonoTiro)
        .options(selectinload(PoligonoTiro.comune))
        .order_by(PoligonoTiro.nome.asc())
    )
    res = await db.execute(stmt)
    poligoni = res.scalars().all()

    out = []
    for p in poligoni:
        out.append({
            "id": p.id,
            "nome": p.nome,
            "tipologia": p.tipologia,
            "indirizzo": p.indirizzo,
            "latitudine": p.latitudine,
            "longitudine": p.longitudine,
            "telefono": p.telefono,
            "sito_web": p.sito_web,
            "linee_tiro": p.linee_tiro,
            "comune": p.comune.nome if p.comune else None
        })
    return out

