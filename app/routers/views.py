from pathlib import Path
from typing import Optional
from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.core.config import settings
from app.core.database import get_db
from app.core.legal import LEGAL_DISCLAIMER_ANNUNCIO, LEGAL_DISCLAIMER_FOOTER
from app.core.security import decode_access_token
from app.models.annuncio import (
    Annuncio,
    ClassificazioneArma,
    CondizioneArma,
    StatoAnnuncio,
    TipologiaArma,
    TipologiaInserzionista,
)
from app.models.geo import Comune, Provincia, Regione
from app.models.user import RuoloUtente, User
from app.services.search_service import SearchService
from app.services.scraper.product_scraper import MultiArmeriaSearchScraper

# Setup templates directory
templates_dir = Path(__file__).resolve().parent.parent / "templates"
templates = Jinja2Templates(directory=str(templates_dir))

views_router = APIRouter(include_in_schema=False)


@views_router.get("/", response_class=HTMLResponse)
async def index_view(
    request: Request,
    q: Optional[str] = None,
    marca: Optional[str] = None,
    modello: Optional[str] = None,
    calibro: Optional[str] = None,
    regione_id: Optional[str] = None,
    tipologia_arma: Optional[str] = None,
    tipologia_inserzionista: Optional[str] = None,
    prezzo_min: Optional[str] = None,
    prezzo_max: Optional[str] = None,
    auto_scrape: Optional[str] = "1",  # Di default cerca e raschia dai siti
    db: AsyncSession = Depends(get_db)
):
    """
    Home page con ricerca avanzata su misura:
    Se l'utente specifica marca, modello, calibro o posizione,
    lo scraper interroga in tempo reale i siti delle armerie italiane, inserisce
    gli annunci con foto originali e link diretto, e restituisce i risultati aggiornati.
    """
    # 0. Parsing sicuro dei parametri numerici (gestisce le stringhe vuote "" inviate dai form HTML)
    parsed_regione_id: Optional[int] = None
    if regione_id and regione_id.strip():
        try:
            parsed_regione_id = int(regione_id.strip())
        except ValueError:
            parsed_regione_id = None

    parsed_prezzo_min: Optional[float] = None
    if prezzo_min and prezzo_min.strip():
        try:
            parsed_prezzo_min = float(prezzo_min.strip())
        except ValueError:
            parsed_prezzo_min = None

    parsed_prezzo_max: Optional[float] = None
    if prezzo_max and prezzo_max.strip():
        try:
            parsed_prezzo_max = float(prezzo_max.strip())
        except ValueError:
            parsed_prezzo_max = None

    # 1. Recupero lista regioni per il dropdown geografico
    stmt_reg = select(Regione).order_by(Regione.nome.asc())
    regioni = (await db.execute(stmt_reg)).scalars().all()
    regione_selezionata = next((r for r in regioni if r.id == parsed_regione_id), None)
    regione_nome = regione_selezionata.nome if regione_selezionata else None

    # 2. Parsing enum
    tipo_arma_enum = None
    if tipologia_arma:
        try:
            tipo_arma_enum = TipologiaArma(tipologia_arma)
        except ValueError:
            pass

    tipo_ins_enum = None
    if tipologia_inserzionista:
        try:
            tipo_ins_enum = TipologiaInserzionista(tipologia_inserzionista)
        except ValueError:
            pass

    scraper_message = None

    # 3. Se l'utente ha inserito criteri specifici (marca, modello, calibro o query libera)
    # e lo scraper è abilitato (o ci sono pochi risultati), scansiona le armerie online
    should_scrape = (auto_scrape == "1") and (marca or modello or calibro or q)
    if should_scrape:
        try:
            await MultiArmeriaSearchScraper.search_and_scrape_armerie(
                db=db,
                q=q,
                marca=marca,
                modello=modello,
                calibro=calibro,
                regione_nome=regione_nome,
                max_per_armeria=3
            )
            criteri_str = " ".join(filter(None, [marca, modello, calibro, q]))
            loc_str = f" in {regione_nome}" if regione_nome else " su tutto il territorio nazionale"
            scraper_message = f"Ricerca live completata: verificata la disponibilità sui siti web delle armerie per '{criteri_str}'{loc_str}."
        except Exception as e:
            # Fallback trasparente in caso di timeout o rete
            pass

    # 4. Ricerca nel database con tutti i filtri applicati
    annunci, totale = await SearchService.search_annunci(
        db=db,
        q=q,
        marca=marca,
        calibro=calibro,
        regione_id=parsed_regione_id,
        tipologia_arma=tipo_arma_enum,
        tipologia_inserzionista=tipo_ins_enum,
        prezzo_min=parsed_prezzo_min,
        prezzo_max=parsed_prezzo_max,
        ordina_per="data_desc",
        pagina=1,
        elementi_per_pagina=36,
        solo_pubblicati=True
    )

    # Se ancora 0 annunci e non era stato avviato lo scraper, invia notifica suggerimento
    return templates.TemplateResponse(
        request=request,
        name="index.html",
        context={
            "annunci": annunci,
            "totale": totale,
            "regioni": regioni,
            "current_q": q,
            "current_marca": marca,
            "current_modello": modello,
            "current_calibro": calibro,
            "current_regione_id": parsed_regione_id,
            "current_tipo": tipologia_arma,
            "current_ins": tipologia_inserzionista,
            "current_pmin": parsed_prezzo_min,
            "current_pmax": parsed_prezzo_max,
            "auto_scrape_active": (auto_scrape == "1"),
            "scraper_message": scraper_message,
            "version": settings.VERSION,
        }
    )


@views_router.get("/mappa", response_class=HTMLResponse)
async def map_view(request: Request):
    """Mappa interattiva a schermo intero con Leaflet.js e pin cliccabili."""
    return templates.TemplateResponse(
        request=request,
        name="mappa.html",
        context={
            "version": settings.VERSION,
        }
    )


@views_router.get("/sincronizza", response_class=HTMLResponse)
async def sync_view(request: Request):
    """Pannello web per la sincronizzazione e importazione feed armerie partner."""
    return templates.TemplateResponse(
        request=request,
        name="sincronizza.html",
        context={
            "version": settings.VERSION,
        }
    )


@views_router.get("/scheda/{id}", response_class=HTMLResponse)
async def ad_detail_view(id: int, request: Request, db: AsyncSession = Depends(get_db)):
    """Scheda di dettaglio dell'arma con mappa della posizione e conformità T.U.L.P.S."""
    stmt = (
        select(Annuncio)
        .options(
            selectinload(Annuncio.comune).selectinload(Comune.provincia).selectinload(Provincia.regione),
            selectinload(Annuncio.utente)
        )
        .where(Annuncio.id == id)
    )
    res = await db.execute(stmt)
    annuncio = res.scalar_one_or_none()

    if not annuncio:
        raise HTTPException(status_code=404, detail="Annuncio non trovato.")

    # Controllo stato annuncio e autenticazione (cookie, header, query param)
    if annuncio.stato != StatoAnnuncio.PUBBLICATO:
        token = None
        auth_header = request.headers.get("Authorization")
        if auth_header and auth_header.startswith("Bearer "):
            token = auth_header.split(" ", 1)[1].strip()
        elif request.cookies.get("armimarket_token"):
            token = request.cookies.get("armimarket_token")

        current_user = None
        if token:
            payload = decode_access_token(token)
            if payload and "sub" in payload:
                try:
                    u_id = int(payload["sub"])
                    current_user = (
                        await db.execute(select(User).where(User.id == u_id, User.is_active == True))
                    ).scalar_one_or_none()
                except (ValueError, TypeError):
                    pass

        is_owner = current_user and current_user.id == annuncio.utente_id
        is_staff = current_user and current_user.ruolo in [RuoloUtente.ADMIN, RuoloUtente.MODERATORE]
        if not (is_owner or is_staff):
            raise HTTPException(status_code=404, detail="Annuncio non trovato.")

    # Incremento visualizzazioni
    annuncio.visualizzazioni += 1
    await db.commit()

    lat = annuncio.comune.latitudine if annuncio.comune else 41.9028
    lon = annuncio.comune.longitudine if annuncio.comune else 12.4964
    precisione = (
        "esatta_armeria"
        if annuncio.tipologia_inserzionista == TipologiaInserzionista.ARMERIA
        else "comunale_protetta"
    )

    # Proprietà aggiuntive per il template
    setattr(annuncio, "latitudine_mappa", lat)
    setattr(annuncio, "longitudine_mappa", lon)
    setattr(annuncio, "precisione_mappa", precisione)
    setattr(annuncio, "disclaimer_legale", LEGAL_DISCLAIMER_ANNUNCIO)
    setattr(
        annuncio,
        "matricola_visibile",
        "[RISERVATA AI SENSI DEL REGOLAMENTO DI PUBBLICA SICUREZZA - Verificabile solo di persona da acquirente munito di titolo]"
    )

    return templates.TemplateResponse(
        request=request,
        name="scheda.html",
        context={
            "annuncio": annuncio,
            "version": settings.VERSION,
        }
    )


@views_router.get("/registrati", response_class=HTMLResponse)
async def registrati_view(request: Request):
    """Pagina di registrazione account per privati muniti di titolo e armerie autorizzate."""
    return templates.TemplateResponse(
        request=request,
        name="registrati.html",
        context={"version": settings.VERSION}
    )


@views_router.get("/login", response_class=HTMLResponse)
async def login_view(request: Request):
    """Pagina di accesso account."""
    return templates.TemplateResponse(
        request=request,
        name="login.html",
        context={"version": settings.VERSION}
    )


@views_router.get("/nuovo-annuncio", response_class=HTMLResponse)
async def nuovo_annuncio_view(request: Request):
    """Modulo di caricamento nuovo annuncio per utenti registrati (armerie o privati)."""
    return templates.TemplateResponse(
        request=request,
        name="nuovo_annuncio.html",
        context={"version": settings.VERSION}
    )


@views_router.get("/profilo", response_class=HTMLResponse)
async def profilo_view(request: Request):
    """Area personale dell'utente: gestione propri annunci (cancella venduti, cambia stato) e annunci preferiti."""
    return templates.TemplateResponse(
        request=request,
        name="profilo.html",
        context={"version": settings.VERSION}
    )


@views_router.get("/recupera-password", response_class=HTMLResponse)
async def recupera_password_view(request: Request):
    """Pagina per la richiesta di recupero password tramite link email."""
    return templates.TemplateResponse(
        request=request,
        name="recupera_password.html",
        context={"version": settings.VERSION}
    )


@views_router.get("/reimposta-password", response_class=HTMLResponse)
async def reimposta_password_view(request: Request, token: Optional[str] = None):
    """Pagina di reimpostazione effettiva della password con verifica token."""
    return templates.TemplateResponse(
        request=request,
        name="reimposta_password.html",
        context={"version": settings.VERSION, "token": token or ""}
    )


@views_router.get("/admin/posta", response_class=HTMLResponse)
async def admin_posta_view(request: Request):
    """Casella postale webmail riservata all'amministratore per consultare email inviate e recuperi password."""
    return templates.TemplateResponse(
        request=request,
        name="admin_posta.html",
        context={"version": settings.VERSION}
    )


@views_router.get("/contatta-admin", response_class=HTMLResponse)
async def contatta_admin_view(request: Request):
    """Modulo di contatto per scrivere direttamente all'Amministratore (Admin) senza esporne l'email."""
    return templates.TemplateResponse(
        request=request,
        name="contatta_admin.html",
        context={"version": settings.VERSION}
    )


@views_router.get("/admin/utenti", response_class=HTMLResponse)
async def admin_utenti_view(request: Request):
    """Pannello admin: elenco e gestione di tutti gli account registrati sulla piattaforma."""
    return templates.TemplateResponse(
        request=request,
        name="admin_utenti.html",
        context={"version": settings.VERSION}
    )
