from typing import Any, Dict, List, Optional
from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile, status
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.network import safe_http_get, validate_url_safe
from app.models.geo import Comune
from app.models.user import RuoloUtente, User
from app.routers.auth import get_current_admin, get_current_moderator
from app.services.ingestion.mock_adapter import MockWooCommerceShopAdapter
from app.services.ingestion.woocommerce_adapter import WooCommerceLiveAdapter
from app.services.ingestion.xml_adapter import XmlFeedAdapter

router = APIRouter(prefix="/ingestion", tags=["Sincronizzazione Feed Armerie Partner"])


class SyncUrlRequest(BaseModel):
    armeria_id: Optional[int] = Field(None, description="ID dell'armeria destinataria (default: prima armeria verificata)")
    feed_type: str = Field("woocommerce", description="'woocommerce', 'xml' o 'json'")
    feed_url: str = Field(..., description="URL dell'endpoint o feed (es. https://armeria.it/wp-json/wc/v3/products)")
    consumer_key: Optional[str] = Field(None, description="Consumer Key WooCommerce / PrestaShop API Key")
    consumer_secret: Optional[str] = Field(None, description="Consumer Secret WooCommerce")
    comune_id: Optional[int] = Field(None, description="ID comune sede armeria (opzionale)")


class SyncResponse(BaseModel):
    success: bool
    armeria_nome: str
    comune_nome: str
    articoli_analizzati: int
    inseriti: int
    aggiornati: int
    scartati: int
    message: str


@router.get("/armerie")
async def list_armerie(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_moderator)
):
    """
    Elenco delle armerie partner disponibili a cui associare le importazioni di stock.
    Riservato a moderatori e amministratori della piattaforma.
    """
    stmt = select(User).where(User.ruolo == RuoloUtente.ARMERIA).order_by(User.nome.asc())
    res = await db.execute(stmt)
    armerie = res.scalars().all()
    return [
        {
            "id": a.id,
            "ragione_sociale": a.ragione_sociale or a.nome,
            "email": a.email,
            "licenza_tulps": a.licenza_tulps,
            "telefono": a.telefono,
            "is_verified": a.is_verified,
        }
        for a in armerie
    ]


@router.post("/sync-url", response_model=SyncResponse)
async def sync_remote_feed(
    req: SyncUrlRequest,
    db: AsyncSession = Depends(get_db),
    admin: User = Depends(get_current_admin)
):
    """
    Sincronizza lo stock di un'armeria interrogando un feed remoto via URL (WooCommerce REST API, XML RSS o JSON).
    Normalizza automaticamente marchi, calibri, categorie e crea annunci certificati 'pubblicato'.
    Riservato agli amministratori. Con protezione anti-SSRF rigorosa.
    """
    # 0. Validazione SSRF preventiva sull'URL
    try:
        req.feed_url = validate_url_safe(req.feed_url)
    except ValueError as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"URL non consentito o non sicuro: {str(e)}"
        )

    # 1. Recupero utente armeria
    stmt = select(User).where(User.ruolo == RuoloUtente.ARMERIA)
    if req.armeria_id:
        stmt = stmt.where(User.id == req.armeria_id)
    res = await db.execute(stmt)
    armeria = res.scalars().first()

    if not armeria:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Nessuna armeria partner trovata a cui associare il feed."
        )

    # 2. Comune associato (default Gardone Val Trompia / Brescia o da richiesta)
    comune_id = req.comune_id or 1
    stmt_comune = select(Comune).where(Comune.id == comune_id)
    comune = (await db.execute(stmt_comune)).scalar_one_or_none()
    if not comune:
        stmt_comune = select(Comune).order_by(Comune.id.asc()).limit(1)
        comune = (await db.execute(stmt_comune)).scalar_one_or_none()
        comune_id = comune.id if comune else 1
    comune_nome = comune.nome if comune else "Gardone Val Trompia"

    # 3. Selezione ed esecuzione adapter con protezione SSRF
    try:
        if req.feed_type.lower() == "woocommerce":
            adapter = WooCommerceLiveAdapter()
            raw_products = await adapter.fetch_remote_products(
                base_url=req.feed_url,
                consumer_key=req.consumer_key,
                consumer_secret=req.consumer_secret
            )
            raw_items = adapter.fetch_feed(raw_products)
        elif req.feed_type.lower() == "xml":
            adapter = XmlFeedAdapter()
            xml_text = await adapter.fetch_remote_xml(req.feed_url)
            raw_items = adapter.fetch_feed(xml_text)
        else:
            # Fallback JSON generico con safe_http_get
            resp = await safe_http_get(req.feed_url, timeout=30.0)
            resp.raise_for_status()
            adapter = MockWooCommerceShopAdapter()
            raw_items = adapter.fetch_feed(resp.json())
    except ValueError as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Richiesta di rete bloccata per sicurezza (SSRF): {str(e)}"
        )
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=f"Errore durante l'interrogazione dell'endpoint remoto: {str(e)}"
        )

    if not raw_items:
        return SyncResponse(
            success=True,
            armeria_nome=armeria.ragione_sociale or armeria.nome,
            comune_nome=comune_nome,
            articoli_analizzati=0,
            inseriti=0,
            aggiornati=0,
            scartati=0,
            message="Il feed è stato contattato ma non contiene prodotti attivi."
        )

    # 4. Sincronizzazione ed inserimento nel database
    stats = await adapter.sync_inventory(
        db=db,
        armeria_user=armeria,
        comune_id=comune_id,
        raw_items=raw_items
    )

    return SyncResponse(
        success=True,
        armeria_nome=armeria.ragione_sociale or armeria.nome,
        comune_nome=comune_nome,
        articoli_analizzati=len(raw_items),
        inseriti=stats["inseriti"],
        aggiornati=stats["aggiornati"],
        scartati=stats["scartati"],
        message=f"Sincronizzazione completata con successo: {stats['inseriti']} nuovi annunci pubblicati."
    )


@router.post("/sync-file", response_model=SyncResponse)
async def sync_uploaded_file(
    file: UploadFile = File(...),
    armeria_id: Optional[int] = Form(None),
    comune_id: Optional[int] = Form(1),
    db: AsyncSession = Depends(get_db),
    admin: User = Depends(get_current_admin)
):
    """
    Sincronizza il catalogo caricando direttamente un file export (XML o JSON).
    Riservato agli amministratori.
    """
    stmt = select(User).where(User.ruolo == RuoloUtente.ARMERIA)
    if armeria_id:
        stmt = stmt.where(User.id == armeria_id)
    res = await db.execute(stmt)
    armeria = res.scalars().first()

    if not armeria:
        raise HTTPException(status_code=404, detail="Armeria partner non trovata.")

    stmt_c = select(Comune).where(Comune.id == comune_id)
    c = (await db.execute(stmt_c)).scalar_one_or_none()
    if not c:
        stmt_c = select(Comune).order_by(Comune.id.asc()).limit(1)
        c = (await db.execute(stmt_c)).scalar_one_or_none()
        comune_id = c.id if c else 1
    comune_nome = c.nome if c else "Sede Armeria"

    content = await file.read()
    filename = file.filename.lower() if file.filename else ""

    try:
        if filename.endswith(".xml") or b"<?xml" in content[:100] or b"<rss" in content[:100]:
            adapter = XmlFeedAdapter()
            raw_items = adapter.fetch_feed(content.decode("utf-8", errors="ignore"))
        else:
            adapter = MockWooCommerceShopAdapter()
            raw_items = adapter.fetch_feed(content.decode("utf-8", errors="ignore"))
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Errore nel parsing del file: {str(e)}")

    stats = await adapter.sync_inventory(db, armeria, comune_id, raw_items)

    return SyncResponse(
        success=True,
        armeria_nome=armeria.ragione_sociale or armeria.nome,
        comune_nome=comune_nome,
        articoli_analizzati=len(raw_items),
        inseriti=stats["inseriti"],
        aggiornati=stats["aggiornati"],
        scartati=stats["scartati"],
        message=f"File importato con successo: {stats['inseriti']} armi sincronizzate."
    )


# --- ENDPOINT SCRAPER ONLINE ARMERIE ITALIANE ---

class ScrapeUrlRequest(BaseModel):
    url: str = Field(..., description="URL della singola scheda prodotto o categoria da raschiare")
    armeria_id: Optional[int] = Field(None, description="ID armeria a cui associare gli annunci")
    comune_id: Optional[int] = Field(None, description="ID comune sede armeria")


@router.post("/scrape-url", response_model=SyncResponse)
async def scrape_product_url(
    req: ScrapeUrlRequest,
    db: AsyncSession = Depends(get_db),
    admin: User = Depends(get_current_admin)
):
    """
    Raschial'URL fornito (singolo prodotto o pagina catalogo di un'armeria italiana reale),
    estrae titolo, descrizione originale, foto originali in alta risoluzione, prezzo e crea
    l'annuncio con il link diretto di rimando all'armeria.
    Riservato agli amministratori. Con protezione anti-SSRF.
    """
    from app.services.scraper.product_scraper import UniversalArmeriaScraper

    # 0. Validazione SSRF preventiva sull'URL
    try:
        req.url = validate_url_safe(req.url)
    except ValueError as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"URL non consentito o non sicuro: {str(e)}"
        )

    # 1. Trova eventuale armeria partner registrata (opzionale)
    armeria = None
    if req.armeria_id:
        stmt = select(User).where(User.ruolo == RuoloUtente.ARMERIA, User.id == req.armeria_id)
        armeria = (await db.execute(stmt)).scalars().first()

    armeria_nome = (armeria.ragione_sociale or armeria.nome) if armeria else "Armeria Fonte Esterna"

    comune_id = req.comune_id or 1
    stmt_c = select(Comune).where(Comune.id == comune_id)
    c = (await db.execute(stmt_c)).scalar_one_or_none()
    if not c:
        stmt_c = select(Comune).order_by(Comune.id.asc()).limit(1)
        c = (await db.execute(stmt_c)).scalar_one_or_none()
        comune_id = c.id if c else 1
    comune_nome = c.nome if c else "Sede Armeria"

    # 2. Controlla se è una pagina di catalogo/categoria oppure singolo prodotto
    urls_to_scrape = []
    if any(k in req.url for k in ["/categoria", "/category", "-armi", "/armi/"]):
        urls_to_scrape = await UniversalArmeriaScraper.discover_product_links_from_catalog(req.url, max_links=10)
    
    if not urls_to_scrape:
        urls_to_scrape = [req.url]

    stats = await UniversalArmeriaScraper.scrape_and_save_listings(
        db=db,
        product_urls=urls_to_scrape,
        armeria_user=armeria,
        comune_id=comune_id,
        armeria_info={"nome": armeria_nome} if not armeria else None
    )

    return SyncResponse(
        success=True,
        armeria_nome=armeria_nome,
        comune_nome=comune_nome,
        articoli_analizzati=len(urls_to_scrape),
        inseriti=stats["inseriti"],
        aggiornati=stats["esistenti"],
        scartati=stats["scartati"],
        message=f"Scraping completato: {stats['inseriti']} armi reali inserite con foto e link originale!"
    )


@router.post("/scrape-all-directory", response_model=SyncResponse)
async def scrape_all_directory(
    db: AsyncSession = Depends(get_db),
    admin: User = Depends(get_current_admin)
):
    """
    Avvia lo scraper automatico sulle armerie online italiane censite nella directory.
    Scarica annunci reali, foto originali e link di rimando diretto senza creare utenti.
    Riservato agli amministratori.
    """
    from app.services.scraper.product_scraper import UniversalArmeriaScraper
    from app.services.scraper.directory import ARMERIE_TARGETS

    tot_analizzati = 0
    tot_inseriti = 0
    tot_esistenti = 0
    tot_scartati = 0

    for target in ARMERIE_TARGETS:
        # Le armerie della directory sono fonti esterne di scraping e NON utenti registrati: armeria_user=None!

        # Trova comune
        stmt_comune = select(Comune).where(Comune.nome.ilike(f"%{target['citta']}%"))
        comune = (await db.execute(stmt_comune)).scalars().first()
        if not comune:
            stmt_comune = select(Comune).order_by(Comune.id.asc()).limit(1)
            comune = (await db.execute(stmt_comune)).scalars().first()
        comune_id = comune.id if comune else 1

        # Raccoglie link prodotti
        product_links = list(target.get("prodotti_diretti", []))
        for cat_url in target.get("catalogo_urls", []):
            cat_prods = await UniversalArmeriaScraper.discover_product_links_from_catalog(cat_url, max_links=8)
            product_links.extend(cat_prods)

        product_links = list(set(product_links))
        tot_analizzati += len(product_links)

        if product_links:
            stats = await UniversalArmeriaScraper.scrape_and_save_listings(
                db=db,
                product_urls=product_links,
                armeria_user=None,
                comune_id=comune_id,
                armeria_info=target
            )
            tot_inseriti += stats["inseriti"]
            tot_esistenti += stats["esistenti"]
            tot_scartati += stats["scartati"]


    return SyncResponse(
        success=True,
        armeria_nome="Directory Armerie Online Italiane",
        comune_nome="Territorio Nazionale",
        articoli_analizzati=tot_analizzati,
        inseriti=tot_inseriti,
        aggiornati=tot_esistenti,
        scartati=tot_scartati,
        message=f"Scraper completato con successo: inseriti {tot_inseriti} annunci reali da armerie online italiane!"
    )
