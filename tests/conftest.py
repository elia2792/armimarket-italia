import asyncio
import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy.pool import StaticPool
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.core.database import Base, get_db
from app.core.security import create_access_token, hash_password
from app.main import app
from app.models.geo import Comune, Provincia, Regione
from app.models.user import RuoloUtente, User

test_engine = create_async_engine(
    "sqlite+aiosqlite://",
    connect_args={"check_same_thread": False},
    poolclass=StaticPool,
)

TestSessionLocal = async_sessionmaker(
    bind=test_engine,
    class_=AsyncSession,
    expire_on_commit=False,
)


@pytest_asyncio.fixture(scope="session")
def event_loop():
    loop = asyncio.new_event_loop()
    yield loop
    loop.close()


@pytest_asyncio.fixture(scope="function")
async def db_session():
    async with test_engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
        await conn.run_sync(Base.metadata.create_all)

    async with TestSessionLocal() as session:
        # Crea dati base geografici
        reg = Regione(nome="Lombardia", codice_istat="03")
        session.add(reg)
        await session.flush()

        prov_mi = Provincia(nome="Milano", sigla_automobilistica="MI", regione_id=reg.id)
        prov_bs = Provincia(nome="Brescia", sigla_automobilistica="BS", regione_id=reg.id)
        session.add_all([prov_mi, prov_bs])
        await session.flush()

        comune_mi = Comune(
            nome="Milano",
            cap="20121",
            provincia_id=prov_mi.id,
            latitudine=45.4642,
            longitudine=9.1900,
            coordinate="POINT(9.1900 45.4642)",
        )
        comune_monza = Comune(
            nome="Monza",
            cap="20900",
            provincia_id=prov_mi.id,
            latitudine=45.5845,
            longitudine=9.2744,
            coordinate="POINT(9.2744 45.5845)",
        )
        comune_bs = Comune(
            nome="Gardone Val Trompia",
            cap="25063",
            provincia_id=prov_bs.id,
            latitudine=45.6936,
            longitudine=10.1839,
            coordinate="POINT(10.1839 45.6936)",
        )
        session.add_all([comune_mi, comune_monza, comune_bs])
        await session.flush()

        # Utente Admin
        admin = User(
            email="admin.test@armimarket.it",
            hashed_password=hash_password("AdminTest123!"),
            nome="Admin",
            cognome="Test",
            ruolo=RuoloUtente.ADMIN,
            is_active=True,
            is_verified=True,
        )
        # Utente Privato
        privato = User(
            email="privato.test@armimarket.it",
            hashed_password=hash_password("PrivatoTest123!"),
            nome="Mario",
            cognome="Rossi",
            codice_fiscale="RSSMRA80A01F205X",
            ruolo=RuoloUtente.PRIVATO,
            telefono="+39 340 1112233",
            is_active=True,
            is_verified=True,
        )
        # Utente Armeria
        armeria = User(
            email="armeria.test@armimarket.it",
            hashed_password=hash_password("ArmeriaTest123!"),
            nome="Armeria",
            ragione_sociale="Armeria Test Srl",
            partita_iva="01122334455",
            licenza_tulps="LIC-12345",
            ruolo=RuoloUtente.ARMERIA,
            telefono="+39 02 1234567",
            is_active=True,
            is_verified=True,
        )
        session.add_all([admin, privato, armeria])
        await session.commit()

        from app.main import seed_poligoni_if_empty
        await seed_poligoni_if_empty(session)


        yield session

    async with test_engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)


@pytest_asyncio.fixture(scope="function")
async def client(db_session):
    async def override_get_db():
        yield db_session

    app.dependency_overrides[get_db] = override_get_db
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac
    app.dependency_overrides.clear()


@pytest.fixture
def admin_token_headers():
    token = create_access_token(subject=1, extra_claims={"ruolo": "admin"})
    return {"Authorization": f"Bearer {token}"}


@pytest.fixture
def private_token_headers():
    token = create_access_token(subject=2, extra_claims={"ruolo": "privato"})
    return {"Authorization": f"Bearer {token}"}
