import asyncio
import logging
from contextlib import asynccontextmanager
from pathlib import Path
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from sqlalchemy import func, select

from app.core.config import settings
from app.core.database import Base, async_session_factory, engine, is_sqlite
from app.core.geo_seed import seed_geo_if_empty
from app.core.security import hash_password
from app.models.poligono import PoligonoTiro, TipologiaPoligono
from app.models.user import RuoloUtente, User
from app.routers.admin import router as admin_router
from app.routers.annunci import router as annunci_router
from app.routers.auth import router as auth_router
from app.routers.geo import router as geo_router
from app.routers.ingestion import router as ingestion_router
from app.routers.preferiti import router as preferiti_router
from app.routers.valutazioni import router as valutazioni_router
from app.routers.views import views_router

logger = logging.getLogger("app.main")


async def seed_poligoni_if_empty(session):
    """Popola un set iniziale di Poligoni di Tiro e sezioni TSN italiani se il database è vuoto."""
    count = (await session.execute(select(func.count(PoligonoTiro.id)))).scalar() or 0
    if count > 0:
        return

    sample_poligoni = [
        PoligonoTiro(
            nome="Tiro a Segno Nazionale Sezione di Milano",
            tipologia=TipologiaPoligono.TSN.value,
            indirizzo="Via Achille Papa 22, Milano (MI)",
            latitudine=45.4965,
            longitudine=9.1432,
            telefono="02 33001854",
            sito_web="https://www.tsnmilano.it",
            linee_tiro="10m aria compressa, 25m armi fuoco, 50m carabina"
        ),
        PoligonoTiro(
            nome="Tiro a Segno Nazionale Gardone Val Trompia",
            tipologia=TipologiaPoligono.TSN.value,
            indirizzo="Via Industriale 32, Gardone Val Trompia (BS)",
            latitudine=45.6925,
            longitudine=10.1872,
            telefono="030 8912440",
            sito_web="https://www.tsngardonevaltrompia.it",
            linee_tiro="10m, 25m, 50m, tunnel collaudo 300m"
        ),
        PoligonoTiro(
            nome="Tiro a Segno Nazionale Sezione di Roma",
            tipologia=TipologiaPoligono.TSN.value,
            indirizzo="Viale di Tor di Quinto 57, Roma (RM)",
            latitudine=41.9388,
            longitudine=12.4842,
            telefono="06 3332711",
            sito_web="https://www.tsnroma.it",
            linee_tiro="10m, 25m, 50m, 100m tiro dinamico"
        ),
        PoligonoTiro(
            nome="Tiro a Segno Nazionale Sezione di Bologna",
            tipologia=TipologiaPoligono.TSN.value,
            indirizzo="Via Agucchi 98, Bologna (BO)",
            latitudine=44.5167,
            longitudine=11.3117,
            telefono="051 381640",
            sito_web="https://www.tsnbologna.it",
            linee_tiro="10m, 25m, 50m, 100m, 300m"
        ),
        PoligonoTiro(
            nome="Tiro a Segno Nazionale Sezione di Napoli",
            tipologia=TipologiaPoligono.TSN.value,
            indirizzo="Via Campegna 267, Napoli (NA)",
            latitudine=40.8294,
            longitudine=14.1956,
            telefono="081 2392766",
            sito_web="https://www.tsnnapoli.it",
            linee_tiro="10m, 25m, 50m"
        ),
        PoligonoTiro(
            nome="TAV Cieli Aperti (Tiro a Volo FITAV)",
            tipologia=TipologiaPoligono.TIRO_A_VOLO.value,
            indirizzo="Cascina Cieli Aperti, Cologno al Serio (BG)",
            latitudine=45.5802,
            longitudine=9.7042,
            telefono="035 896131",
            sito_web="https://www.cieliaperti.it",
            linee_tiro="Fossa Olimpica, Compak Sporting, Elica"
        ),
        PoligonoTiro(
            nome="Tiro Dinamico Club Le Tre Piume",
            tipologia=TipologiaPoligono.PRIVATO.value,
            indirizzo="Via Argine Sinistro 45, Curtarolo (PD)",
            latitudine=45.5204,
            longitudine=11.8315,
            telefono="049 9620120",
            sito_web="https://www.letrepiume.it",
            linee_tiro="Campi dinamici IPSC / IDPA, sagome metalliche"
        ),
    ]
    session.add_all(sample_poligoni)
    await session.commit()
    logger.info("Inizializzati poligoni e TSN di riferimento sulla mappa.")


async def hourly_catalog_scraper_task():
    """
    Task periodico in background che ogni ora (3600s) esegue la sincronizzazione e lo scraping automatico
    dei cataloghi armerie per mantenere il portale sempre aggiornato con nuovi arrivi e variazioni di prezzo.
    """
    logger.info("Hourly catalog scraper background task avviato.")
    # Attende 10 secondi dall'avvio per permettere l'inizializzazione del database
    await asyncio.sleep(10)

    popular_queries = ["Beretta", "Glock", "Benelli", "Carabina", "Pistola"]

    while True:
        try:
            logger.info("Avvio ciclo periodico scraping orario cataloghi armerie...")
            async with async_session_factory() as session:
                from app.services.scraper.product_scraper import MultiArmeriaSearchScraper
                for term in popular_queries:
                    try:
                        await MultiArmeriaSearchScraper.search_and_scrape_armerie(
                            db=session,
                            q=term,
                            max_per_armeria=2
                        )
                    except Exception as e:
                        logger.warning(f"Errore scraping periodico per query '{term}': {e}")
            logger.info("Ciclo scraping orario completato. Prossima sincronizzazione automatica tra 1 ora.")
        except asyncio.CancelledError:
            logger.info("Task periodico scraping interrotto.")
            break
        except Exception as e:
            logger.error(f"Errore imprevisto nel task periodico di scraping: {e}")

        # Intervallo orario: 3600 secondi
        await asyncio.sleep(3600)


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Lifecycle manager: inizializzazione schema tabelle, admin, poligoni e task orario scraping."""
    is_production = settings.ENVIRONMENT.lower().strip() in ("production", "prod")
    # Assicura le estensioni e le colonne necessarie in modo idempotente all'avvio
    async with engine.begin() as conn:
        if not is_sqlite:
            try:
                await conn.execute(__import__("sqlalchemy").text("CREATE EXTENSION IF NOT EXISTS postgis;"))
            except Exception:
                pass
        if not is_production:
            await conn.run_sync(Base.metadata.create_all)
        if not is_sqlite:
            # Aggiornamento idempotente dello schema PostgreSQL di produzione (disaccoppiamento scraping da utenti)
            for migration_sql in [
                "ALTER TABLE annunci ALTER COLUMN utente_id DROP NOT NULL;",
                "ALTER TABLE annunci ADD COLUMN IF NOT EXISTS fonte_esterna VARCHAR(200);",
                "ALTER TABLE annunci ADD COLUMN IF NOT EXISTS source_id_esterno VARCHAR(100);",
                "CREATE INDEX IF NOT EXISTS ix_annunci_fonte_esterna ON annunci (fonte_esterna);",
                "CREATE INDEX IF NOT EXISTS ix_annunci_source_id_esterno ON annunci (source_id_esterno);",
                "ALTER TABLE utenti ADD COLUMN IF NOT EXISTS foto_profilo VARCHAR(512);",
                "ALTER TABLE comuni ADD COLUMN IF NOT EXISTS codice_istat VARCHAR(6);",
                """CREATE TABLE IF NOT EXISTS valutazioni (
                    id SERIAL PRIMARY KEY,
                    autore_id INTEGER NOT NULL REFERENCES utenti(id) ON DELETE CASCADE,
                    recensito_utente_id INTEGER REFERENCES utenti(id) ON DELETE CASCADE,
                    fonte_esterna VARCHAR(200),
                    annuncio_id INTEGER REFERENCES annunci(id) ON DELETE SET NULL,
                    voto INTEGER NOT NULL,
                    titolo VARCHAR(150),
                    commento TEXT NOT NULL,
                    data_creazione TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP NOT NULL,
                    data_aggiornamento TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP NOT NULL
                );""",
                "CREATE INDEX IF NOT EXISTS ix_valutazioni_autore_id ON valutazioni (autore_id);",
                "CREATE INDEX IF NOT EXISTS ix_valutazioni_recensito_utente_id ON valutazioni (recensito_utente_id);",
                "CREATE INDEX IF NOT EXISTS ix_valutazioni_fonte_esterna ON valutazioni (fonte_esterna);"
            ]:
                try:
                    await conn.execute(__import__("sqlalchemy").text(migration_sql))
                except Exception as e:
                    logger.debug(f"Migrazione idempotente pass: {e}")
        else:
            for migration_sql in [
                "ALTER TABLE annunci ADD COLUMN fonte_esterna VARCHAR(200)",
                "ALTER TABLE annunci ADD COLUMN source_id_esterno VARCHAR(100)",
                "ALTER TABLE utenti ADD COLUMN foto_profilo VARCHAR(512)",
                "ALTER TABLE comuni ADD COLUMN codice_istat VARCHAR(6)",
            ]:
                try:
                    await conn.execute(__import__("sqlalchemy").text(migration_sql))
                except Exception:
                    pass

    # Inizializza o sincronizza superuser amministratore e poligoni
    async with async_session_factory() as session:
        stmt = select(User).where(User.email == settings.FIRST_SUPERUSER_EMAIL.lower())
        res = await session.execute(stmt)
        admin = res.scalar_one_or_none()
        if not admin:
            admin_user = User(
                email=settings.FIRST_SUPERUSER_EMAIL.lower(),
                hashed_password=hash_password(settings.FIRST_SUPERUSER_PASSWORD),
                nome="Admin",
                cognome="",
                ruolo=RuoloUtente.ADMIN,
                is_active=True,
                is_verified=True,
            )
            session.add(admin_user)
            await session.commit()
            logger.info("Creato superuser admin predefinito: %s", settings.FIRST_SUPERUSER_EMAIL.lower())
        else:
            # Sincronizza password e stato attivo se modificati nelle variabili d'ambiente
            admin.hashed_password = hash_password(settings.FIRST_SUPERUSER_PASSWORD)
            admin.ruolo = RuoloUtente.ADMIN
            admin.is_active = True
            admin.is_verified = True
            await session.commit()
            logger.info("Sincronizzato superuser admin con le credenziali di configurazione: %s", settings.FIRST_SUPERUSER_EMAIL.lower())
        await seed_geo_if_empty(session)
        await seed_poligoni_if_empty(session)

    # Avvia task periodico di scraping orario in background
    scraper_task = asyncio.create_task(hourly_catalog_scraper_task())

    yield

    scraper_task.cancel()
    try:
        await scraper_task
    except asyncio.CancelledError:
        pass

    # Cleanup alla disconnessione
    await engine.dispose()



app = FastAPI(
    title="ArmiMarket Italia - Piattaforma Annunci Armi & Tiro",
    description=(
        "API REST per la bacheca di consultazione e ricerca geolocalizzata conforme "
        "alle disposizioni di Pubblica Sicurezza (T.U.L.P.S. e D.Lgs. 104/2018). "
        "Nessun e-commerce: solo bacheca informativa e contatto tra autorizzati muniti di titolo."
    ),
    version=settings.VERSION,
    lifespan=lifespan,
    docs_url="/docs",
    redoc_url="/redoc",
)

# Security Headers & Content-Security-Policy Middleware
from app.core.security_headers import SecurityHeadersMiddleware
app.add_middleware(SecurityHeadersMiddleware)

# CORS Middleware restrittivo (con credenziali, vietato wildcard *)
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.ALLOWED_ORIGINS,
    allow_credentials=True,
    allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"],
    allow_headers=["*"],
)

# Registrazione Router API v1
app.include_router(auth_router, prefix=settings.API_V1_STR)
app.include_router(geo_router, prefix=settings.API_V1_STR)
app.include_router(annunci_router, prefix=settings.API_V1_STR)
app.include_router(admin_router, prefix=settings.API_V1_STR)
app.include_router(ingestion_router, prefix=settings.API_V1_STR)
app.include_router(preferiti_router, prefix=settings.API_V1_STR)
app.include_router(valutazioni_router, prefix=settings.API_V1_STR)

# Registrazione Router Viste Web (Home, Mappa Interattiva, Scheda Dettaglio)
app.include_router(views_router)

# Serve file statici (avatar, upload) da /static
_STATIC_DIR = Path(__file__).resolve().parent / "static"
_STATIC_DIR.mkdir(parents=True, exist_ok=True)

if settings.AVATAR_UPLOAD_DIR:
    _persistent_avatar_dir = Path(settings.AVATAR_UPLOAD_DIR).resolve()
    _persistent_avatar_dir.mkdir(parents=True, exist_ok=True)
    app.mount("/static/uploads/avatars", StaticFiles(directory=str(_persistent_avatar_dir)), name="avatars_persistent")

if settings.UPLOAD_DIR and Path(settings.UPLOAD_DIR).resolve() != (_STATIC_DIR / "uploads").resolve():
    _persistent_annunci_dir = Path(settings.UPLOAD_DIR).resolve() / "annunci"
    _persistent_annunci_dir.mkdir(parents=True, exist_ok=True)
    app.mount("/static/uploads/annunci", StaticFiles(directory=str(_persistent_annunci_dir)), name="annunci_persistent")

app.mount("/static", StaticFiles(directory=str(_STATIC_DIR)), name="static")


@app.get("/health", tags=["Sistema"])
async def healthcheck():
    """Endpoint di controllo integrità del servizio."""
    return {
        "status": "healthy",
        "app": settings.PROJECT_NAME,
        "version": settings.VERSION,
        "legal_compliance": "T.U.L.P.S. & D.Lgs. 104/2018 Validated"
    }
