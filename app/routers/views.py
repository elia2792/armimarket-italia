from pathlib import Path
from typing import Optional, List
from fastapi import APIRouter, Depends, HTTPException, Request, Response
from fastapi.responses import HTMLResponse, RedirectResponse, PlainTextResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy import select, func, or_
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
from app.core.seo import (
    CATEGORIE_SEO,
    REGIONI_SEO,
    ENUM_TO_CAT_SLUG,
    slugify,
    genera_url_annuncio,
    estrai_id_da_slug_annuncio,
    genera_meta_description_annuncio,
    genera_alt_immagine_annuncio,
    genera_schema_product_annuncio,
    genera_schema_breadcrumb,
    genera_sitemap_xml,
    genera_robots_txt,
)

# Setup templates directory
templates_dir = Path(__file__).resolve().parent.parent / "templates"
templates = Jinja2Templates(directory=str(templates_dir))

views_router = APIRouter(include_in_schema=False)


def _get_base_url(request: Request) -> str:
    """Restituisce il BASE_URL di configurazione o ricavato dalla request corrente."""
    if settings.BASE_URL and "localhost" not in settings.BASE_URL:
        return settings.BASE_URL.rstrip("/")
    return f"{request.url.scheme}://{request.url.netloc}".rstrip("/")


@views_router.get("/", response_class=HTMLResponse)
@views_router.get("/annunci", response_class=HTMLResponse)
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
    auto_scrape: Optional[str] = "1",
    pagina: int = 1,
    db: AsyncSession = Depends(get_db)
):
    """
    Homepage e Catalogo Generale Annunci con:
    - Paginazione fissa da 50 annunci per pagina (best practice crawl budget)
    - URL canonico coerente
    - noindex, follow su ricerche con filtri complessi per preservare il crawl budget
    - Dati strutturati globali WebSite e Organization
    """
    # Parsing e sanificazione parametri
    parsed_regione_id = None
    if regione_id and regione_id.isdigit():
        parsed_regione_id = int(regione_id)

    parsed_prezzo_min = None
    if prezzo_min:
        try:
            parsed_prezzo_min = float(prezzo_min)
        except ValueError:
            pass

    parsed_prezzo_max = None
    if prezzo_max:
        try:
            parsed_prezzo_max = float(prezzo_max)
        except ValueError:
            pass

    parsed_tipo_arma = None
    if tipologia_arma:
        for t in TipologiaArma:
            if t.value == tipologia_arma:
                parsed_tipo_arma = t
                break

    parsed_tipo_ins = None
    if tipologia_inserzionista:
        for ins in TipologiaInserzionista:
            if ins.value == tipologia_inserzionista:
                parsed_tipo_ins = ins
                break

    scraper_message = None

    # Caricamento regioni per tendina filtro
    regioni_stmt = select(Regione).order_by(Regione.nome)
    regioni = (await db.execute(regioni_stmt)).scalars().all()

    regione_nome = None
    if parsed_regione_id:
        reg_match = next((r.nome for r in regioni if r.id == parsed_regione_id), None)
        regione_nome = reg_match

    # Esegui scansione live armerie esterne se abilitata
    if auto_scrape == "1" and (q or marca or modello or calibro):
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
            scraper_message = "Ricerca Live completata: annunci verificati e aggiornati con successo."
        except Exception:
            pass

    # Query annunci paginati con limite a 50 elementi per pagina
    annunci, totale = await SearchService.search_annunci(
        db=db,
        q=q,
        marca=marca,
        calibro=calibro,
        regione_id=parsed_regione_id,
        tipologia_arma=parsed_tipo_arma,
        tipologia_inserzionista=parsed_tipo_ins,
        prezzo_min=parsed_prezzo_min,
        prezzo_max=parsed_prezzo_max,
        pagina=pagina,
        elementi_per_pagina=50,
        solo_pubblicati=True
    )

    totale_pagine = max(1, (totale + 49) // 50) if totale > 0 else 1
    base_url = _get_base_url(request)

    # Strategia indicizzazione filtri:
    # Se ci sono filtri di ricerca secondari o parametri liberi, imposta noindex per evitare crawl budget sprecato
    ha_filtri_complessi = bool(q or marca or modello or calibro or prezzo_min or prezzo_max or tipologia_inserzionista or regione_id or tipologia_arma)
    seo_robots = "noindex, follow" if ha_filtri_complessi else "index, follow"
    canonical_url = f"{base_url}/" if pagina == 1 else f"{base_url}/?pagina={pagina}"
    prev_page_url = None
    next_page_url = None
    if not ha_filtri_complessi:
        if pagina > 1:
            prev_page_url = f"{base_url}/" if pagina == 2 else f"{base_url}/?pagina={pagina - 1}"
        if pagina < totale_pagine:
            next_page_url = f"{base_url}/?pagina={pagina + 1}"

    return templates.TemplateResponse(
        request=request,
        name="index.html",
        context={
            "annunci": annunci,
            "totale": totale,
            "pagina": pagina,
            "totale_pagine": totale_pagine,
            "elementi_per_pagina": 50,
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
            "base_url": base_url,
            "canonical_url": canonical_url,
            "prev_page_url": prev_page_url,
            "next_page_url": next_page_url,
            "seo_robots": seo_robots,
            "seo_title": "ArmiMarket Italia — Bacheca Annunci Armi Usate e Nuove | Armerie e Privati",
            "seo_description": "Bacheca motore di ricerca per annunci di armi usate e nuove in Italia conformemente al T.U.L.P.S. Scopri pistole, carabine, fucili da caccia e tiro sportivo.",
            "pagination_base_path": "/",
        }
    )


@views_router.get("/annunci/{categoria_slug}", response_class=HTMLResponse)
async def category_view(
    categoria_slug: str,
    request: Request,
    pagina: int = 1,
    db: AsyncSession = Depends(get_db)
):
    """
    Landing page SEO-friendly per categoria specifica:
    - URL pulito: /annunci/{categoria_slug}
    - Title, meta description e H1 su misura
    - BreadcrumbList Schema.org
    - Paginazione server-side a 50 annunci per pagina con rel prev/next
    - Tag canonical coerente (/annunci/{slug} o ?pagina=X)
    """
    cat_info = CATEGORIE_SEO.get(categoria_slug)
    if not cat_info:
        raise HTTPException(status_code=404, detail="Categoria non trovata.")

    base_url = _get_base_url(request)

    annunci, totale = await SearchService.search_annunci(
        db=db,
        tipologia_arma=cat_info["enum"],
        pagina=pagina,
        elementi_per_pagina=50,
        solo_pubblicati=True
    )
    totale_pagine = max(1, (totale + 49) // 50) if totale > 0 else 1

    breadcrumbs = [
        {"name": "Home", "url": f"{base_url}/"},
        {"name": "Annunci", "url": f"{base_url}/annunci"},
        {"name": cat_info["nome"], "url": f"{base_url}/annunci/{categoria_slug}"}
    ]
    schema_breadcrumb = genera_schema_breadcrumb(breadcrumbs)

    canonical_url = f"{base_url}/annunci/{categoria_slug}" if pagina == 1 else f"{base_url}/annunci/{categoria_slug}?pagina={pagina}"
    prev_page_url = None
    next_page_url = None
    if pagina > 1:
        prev_page_url = f"{base_url}/annunci/{categoria_slug}" if pagina == 2 else f"{base_url}/annunci/{categoria_slug}?pagina={pagina - 1}"
    if pagina < totale_pagine:
        next_page_url = f"{base_url}/annunci/{categoria_slug}?pagina={pagina + 1}"

    regioni = (await db.execute(select(Regione).order_by(Regione.nome))).scalars().all()

    return templates.TemplateResponse(
        request=request,
        name="index.html",
        context={
            "annunci": annunci,
            "totale": totale,
            "pagina": pagina,
            "totale_pagine": totale_pagine,
            "elementi_per_pagina": 50,
            "regioni": regioni,
            "version": settings.VERSION,
            "base_url": base_url,
            "canonical_url": canonical_url,
            "prev_page_url": prev_page_url,
            "next_page_url": next_page_url,
            "seo_robots": "index, follow",
            "seo_title": cat_info["titolo_seo"],
            "seo_description": cat_info["descrizione_seo"],
            "page_h1": cat_info["h1"],
            "page_intro": cat_info["intro_testo"],
            "active_category_name": cat_info["nome"],
            "schema_breadcrumb": schema_breadcrumb,
            "current_tipo": cat_info["enum"].value if hasattr(cat_info["enum"], "value") else str(cat_info["enum"]),
            "pagination_base_path": f"/annunci/{categoria_slug}",
        }
    )


@views_router.get("/annunci/regione/{regione_slug}", response_class=HTMLResponse)
async def regional_view(
    regione_slug: str,
    request: Request,
    pagina: int = 1,
    db: AsyncSession = Depends(get_db)
):
    """
    Landing page SEO-friendly territoriale (/annunci/regione/{regione_slug}):
    - Title e meta description geolocalizzati
    - Paginazione server-side a 50 annunci per pagina con rel prev/next
    - Gestione intelligente index/noindex: index, follow se ha annunci; noindex, follow se vuota
    """
    reg_slug_clean = regione_slug.lower().strip()
    reg_info = REGIONI_SEO.get(reg_slug_clean)

    if reg_info:
        # Trova l'oggetto Regione dal database corrispondente al nome o all'ID
        reg_obj = (
            await db.execute(
                select(Regione).where(
                    func.lower(Regione.nome) == reg_info["nome"].lower()
                ).limit(1)
            )
        ).scalar_one_or_none()
        if not reg_obj:
            reg_obj = (
                await db.execute(
                    select(Regione).where(Regione.id == reg_info["id"]).limit(1)
                )
            ).scalar_one_or_none()
        reg_nome = reg_info["nome"]
        reg_id = reg_obj.id if reg_obj else reg_info["id"]
    else:
        # Fallback nel caso esista una regione nel DB con nome corrispondente allo slug
        reg_obj = (
            await db.execute(
                select(Regione).where(
                    func.lower(Regione.nome) == reg_slug_clean.replace("-", " ")
                )
            )
        ).scalar_one_or_none()
        if not reg_obj:
            raise HTTPException(status_code=404, detail="Regione non trovata.")
        reg_nome = reg_obj.nome
        reg_id = reg_obj.id

    if not reg_info:
        reg_title = f"Annunci Armi Usate e Nuove in {reg_nome} | ArmiMarket Italia"
        reg_desc = f"Trova annunci di armi usate e nuove in {reg_nome}. Compravendita lecita tra privati e armerie autorizzate."
        reg_h1 = f"Armi Usate e Nuove in Vendita in {reg_nome}"
        reg_intro = f"Consulta gli annunci di armi da caccia, tiro sportivo e collezione disponibili nella regione {reg_nome}."
    else:
        reg_title = reg_info["titolo_seo"]
        reg_desc = reg_info["descrizione_seo"]
        reg_h1 = reg_info["h1"]
        reg_intro = reg_info["intro_testo"]

    base_url = _get_base_url(request)
    annunci, totale = await SearchService.search_annunci(
        db=db,
        regione_id=reg_id,
        pagina=pagina,
        elementi_per_pagina=50,
        solo_pubblicati=True
    )
    totale_pagine = max(1, (totale + 49) // 50) if totale > 0 else 1

    breadcrumbs = [
        {"name": "Home", "url": f"{base_url}/"},
        {"name": "Annunci", "url": f"{base_url}/annunci"},
        {"name": reg_nome, "url": f"{base_url}/annunci/regione/{reg_slug_clean}"}
    ]
    schema_breadcrumb = genera_schema_breadcrumb(breadcrumbs)
    canonical_url = f"{base_url}/annunci/regione/{reg_slug_clean}" if pagina == 1 else f"{base_url}/annunci/regione/{reg_slug_clean}?pagina={pagina}"

    prev_page_url = None
    next_page_url = None
    if pagina > 1:
        prev_page_url = f"{base_url}/annunci/regione/{reg_slug_clean}" if pagina == 2 else f"{base_url}/annunci/regione/{reg_slug_clean}?pagina={pagina - 1}"
    if pagina < totale_pagine:
        next_page_url = f"{base_url}/annunci/regione/{reg_slug_clean}?pagina={pagina + 1}"

    # Strategia SEO per regioni: se ci sono annunci -> index, follow; se vuota -> noindex, follow per non impoverire l'indice
    seo_robots = "index, follow" if totale > 0 else "noindex, follow"

    regioni = (await db.execute(select(Regione).order_by(Regione.nome))).scalars().all()

    return templates.TemplateResponse(
        request=request,
        name="index.html",
        context={
            "annunci": annunci,
            "totale": totale,
            "pagina": pagina,
            "totale_pagine": totale_pagine,
            "elementi_per_pagina": 50,
            "regioni": regioni,
            "version": settings.VERSION,
            "base_url": base_url,
            "canonical_url": canonical_url,
            "prev_page_url": prev_page_url,
            "next_page_url": next_page_url,
            "seo_robots": seo_robots,
            "seo_title": reg_title,
            "seo_description": reg_desc,
            "page_h1": reg_h1,
            "page_intro": reg_intro,
            "active_region_name": reg_nome,
            "schema_breadcrumb": schema_breadcrumb,
            "current_regione_id": reg_id,
            "pagination_base_path": f"/annunci/regione/{reg_slug_clean}",
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


@views_router.get("/scheda/{id}")
async def legacy_ad_detail_redirect(id: int, request: Request, db: AsyncSession = Depends(get_db)):
    """
    Redirect 301 permanente per preservare la SEO da /scheda/{id} al nuovo URL SEO /annuncio/{slug}-{id}.
    Verifica i permessi prima di eseguire il redirect per impedire l'enumeration di annunci non pubblicati.
    """
    stmt = select(Annuncio).where(Annuncio.id == id)
    annuncio = (await db.execute(stmt)).scalar_one_or_none()
    if not annuncio:
        raise HTTPException(status_code=404, detail="Annuncio non trovato.")

    is_public = (annuncio.stato == StatoAnnuncio.PUBBLICATO)
    is_sold = (annuncio.stato == StatoAnnuncio.VENDUTO)
    if not is_public and not is_sold:
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
            raise HTTPException(status_code=404, detail="Annuncio non disponibile.")

    url_seo = genera_url_annuncio(annuncio.id, annuncio.titolo)
    return RedirectResponse(url=url_seo, status_code=301)


@views_router.get("/annuncio/{slug_and_id}", response_class=HTMLResponse)
async def ad_detail_view(slug_and_id: str, request: Request, db: AsyncSession = Depends(get_db)):
    """
    Scheda di dettaglio SEO-friendly dell'annuncio (/annuncio/{slug}-{id}):
    - Title parlante unico
    - Meta description generata dai dati reali
    - Breadcrumbs SEO e BreadcrumbList JSON-LD
    - Product / IndividualProduct Schema.org JSON-LD
    - Mappa Leaflet e conformità T.U.L.P.S.
    - Sezione annunci simili per internal linking
    - Gestione annunci venduti/scaduti (badge chiaro e noindex)
    """
    ad_id = estrai_id_da_slug_annuncio(slug_and_id)
    if not ad_id:
        raise HTTPException(status_code=404, detail="Annuncio non trovato.")

    stmt = (
        select(Annuncio)
        .options(
            selectinload(Annuncio.comune).selectinload(Comune.provincia).selectinload(Provincia.regione),
            selectinload(Annuncio.utente)
        )
        .where(Annuncio.id == ad_id)
    )
    res = await db.execute(stmt)
    annuncio = res.scalar_one_or_none()

    if not annuncio:
        raise HTTPException(status_code=404, detail="Annuncio non trovato.")

    # Controllo canonical dello slug: se l'utente digita uno slug errato o un ID nudo, 301 redirect all'URL canonico unico
    canonical_slug_id = f"{slugify(annuncio.titolo)}-{annuncio.id}"
    if slug_and_id != canonical_slug_id:
        return RedirectResponse(url=f"/annuncio/{canonical_slug_id}", status_code=301)

    # Controllo stato annuncio e permessi di visualizzazione
    is_public = (annuncio.stato == StatoAnnuncio.PUBBLICATO)
    is_sold = (annuncio.stato == StatoAnnuncio.VENDUTO)

    # Gli annunci venduti o scaduti rimangono visibili per la SEO con badge chiaro
    if not is_public and not is_sold:
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
            raise HTTPException(status_code=404, detail="Annuncio non disponibile.")

    # Incremento visualizzazioni solo per annunci attivi
    if is_public:
        annuncio.visualizzazioni += 1
        await db.commit()

    base_url = _get_base_url(request)
    canonical_url = f"{base_url}/annuncio/{canonical_slug_id}"

    lat = annuncio.comune.latitudine if annuncio.comune else 41.9028
    lon = annuncio.comune.longitudine if annuncio.comune else 12.4964
    precisione = (
        "esatta_armeria"
        if annuncio.tipologia_inserzionista == TipologiaInserzionista.ARMERIA
        else "comunale_protetta"
    )


    setattr(annuncio, "latitudine_mappa", lat)
    setattr(annuncio, "longitudine_mappa", lon)
    setattr(annuncio, "precisione_mappa", precisione)
    setattr(annuncio, "disclaimer_legale", LEGAL_DISCLAIMER_ANNUNCIO)
    setattr(
        annuncio,
        "matricola_visibile",
        "[RISERVATA AI SENSI DEL REGOLAMENTO DI PUBBLICA SICUREZZA - Verificabile solo di persona da acquirente munito di titolo]"
    )

    # Categoria info per breadcrumbs e URL
    cat_slug = ENUM_TO_CAT_SLUG.get(annuncio.tipologia_arma)
    categoria_info = CATEGORIE_SEO.get(cat_slug) if cat_slug else None

    # Costruzione Breadcrumbs
    breadcrumbs = [
        {"name": "Home", "url": f"{base_url}/"},
        {"name": "Annunci", "url": f"{base_url}/annunci"},
    ]
    if categoria_info:
        breadcrumbs.append({
            "name": categoria_info["nome"],
            "url": f"{base_url}/annunci/{categoria_info['slug']}"
        })
    breadcrumbs.append({"name": annuncio.titolo, "url": canonical_url})

    # Dati strutturati Schema.org
    schema_product = genera_schema_product_annuncio(annuncio, canonical_url, base_url)
    schema_breadcrumb = genera_schema_breadcrumb(breadcrumbs)

    # Annunci simili / correlati per favorire l'internal linking
    stmt_simili = (
        select(Annuncio)
        .options(selectinload(Annuncio.comune))
        .where(
            Annuncio.id != annuncio.id,
            Annuncio.stato == StatoAnnuncio.PUBBLICATO,
            or_(
                Annuncio.tipologia_arma == annuncio.tipologia_arma,
                Annuncio.marca == annuncio.marca,
            )
        )
        .order_by(Annuncio.id.desc())
        .limit(4)
    )
    annunci_simili_raw = (await db.execute(stmt_simili)).scalars().all()
    annunci_simili = list(annunci_simili_raw)

    # Metadati SEO per l'annuncio
    seo_title = f"{annuncio.titolo} | ArmiMarket Italia"
    seo_desc = genera_meta_description_annuncio(annuncio)
    # Se annuncio venduto o non pubblicato, impostiamo noindex
    seo_robots = "noindex, follow" if not is_public else "index, follow"

    og_img = annuncio.galleria_immagini[0] if annuncio.galleria_immagini else f"{base_url}/static/img/og-preview.jpg"
    main_image_alt = genera_alt_immagine_annuncio(annuncio, 1)

    # Carica riepilogo valutazioni e recensioni del venditore (utente registrato o fonte esterna)
    from app.services.valutazione_service import ValutazioneService
    valutazioni_riepilogo = await ValutazioneService.get_riepilogo(
        db=db,
        utente_id=annuncio.utente_id,
        fonte_esterna=annuncio.fonte_esterna
    )

    return templates.TemplateResponse(
        request=request,
        name="scheda.html",
        context={
            "annuncio": annuncio,
            "valutazioni_riepilogo": valutazioni_riepilogo,
            "version": settings.VERSION,
            "base_url": base_url,
            "canonical_url": canonical_url,
            "seo_title": seo_title,
            "seo_description": seo_desc,
            "seo_robots": seo_robots,
            "og_image": og_img,
            "main_image_alt": main_image_alt,
            "categoria_info": categoria_info,
            "schema_product": schema_product,
            "schema_breadcrumb": schema_breadcrumb,
            "annunci_simili": annunci_simili,
        }
    )


@views_router.get("/guide", response_class=HTMLResponse)
async def guide_view(request: Request):
    """Guida normativa e legale alla compravendita di armi tra privati e armerie in Italia."""
    base_url = _get_base_url(request)
    return templates.TemplateResponse(
        request=request,
        name="guide.html",
        context={
            "version": settings.VERSION,
            "base_url": base_url,
            "canonical_url": f"{base_url}/guide",
        }
    )


@views_router.get("/faq", response_class=HTMLResponse)
async def faq_view(request: Request):
    """Domande frequenti (FAQ) con Schema.org FAQPage JSON-LD per rich snippets Google."""
    base_url = _get_base_url(request)
    return templates.TemplateResponse(
        request=request,
        name="faq.html",
        context={
            "version": settings.VERSION,
            "base_url": base_url,
            "canonical_url": f"{base_url}/faq",
        }
    )


@views_router.get("/sitemap.xml", response_class=Response)
async def sitemap_xml_view(request: Request, db: AsyncSession = Depends(get_db)):
    """Sitemap dinamica conforme a sitemaps.org con URL canonici degli annunci attivi e regioni indicizzabili."""
    base_url = _get_base_url(request)
    stmt = (
        select(Annuncio)
        .options(
            selectinload(Annuncio.comune)
            .selectinload(Comune.provincia)
            .selectinload(Provincia.regione)
        )
        .where(Annuncio.stato == StatoAnnuncio.PUBBLICATO)
        .order_by(Annuncio.id.desc())
    )
    annunci_attivi = (await db.execute(stmt)).scalars().all()
    
    # Raccoglie solo le regioni con almeno un annuncio attivo pubblicato
    regioni_attive = set()
    for a in annunci_attivi:
        if a.comune and a.comune.provincia and a.comune.provincia.regione:
            reg_obj = a.comune.provincia.regione
            reg_slug = getattr(reg_obj, "slug", None) or slugify(reg_obj.nome)
            if reg_slug:
                regioni_attive.add(reg_slug)

    xml_content = genera_sitemap_xml(base_url, annunci_attivi, regioni_attive=regioni_attive)
    return Response(content=xml_content, media_type="application/xml")



@views_router.get("/robots.txt", response_class=PlainTextResponse)
async def robots_txt_view(request: Request):
    """File robots.txt per la gestione del crawl budget dei motori di ricerca."""
    base_url = _get_base_url(request)
    return PlainTextResponse(content=genera_robots_txt(base_url))


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


@views_router.get("/admin", response_class=HTMLResponse)
async def admin_dashboard_view(request: Request):
    """Pannello admin principale: panoramica di tutte le statistiche della piattaforma."""
    return templates.TemplateResponse(
        request=request,
        name="admin_dashboard.html",
        context={"version": settings.VERSION}
    )


@views_router.get("/logout")
async def logout_view():
    """Logout infallibile lato server: rimozione cookie e reindirizzamento alla homepage."""
    response = RedirectResponse(url="/", status_code=303)
    response.headers["Clear-Site-Data"] = '"cache", "cookies", "storage"'
    response.delete_cookie(key="armimarket_token", path="/")
    response.delete_cookie(key="access_token", path="/")
    response.delete_cookie(key="token", path="/")
    return response
