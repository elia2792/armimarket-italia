import pytest
from httpx import AsyncClient
from app.core.validators import (
    validate_partita_iva,
    normalize_partita_iva,
    validate_codice_fiscale,
    normalize_codice_fiscale,
)
from app.models.user import RuoloUtente, User


def test_validator_partita_iva_algorithm():
    # P.IVA valide reali italiane
    assert validate_partita_iva("00811720580") is True  # Enel
    assert validate_partita_iva("00159560366") is True  # Ferrari
    assert validate_partita_iva("01234567897") is True  # Checksum calcolato
    assert validate_partita_iva(" 00811720580 ") is True  # Con spazi
    assert validate_partita_iva("008-1172-0580") is True  # Con trattini

    # P.IVA non valide
    assert validate_partita_iva("01234567890") is False  # Checksum errato
    assert validate_partita_iva("00000000000") is False  # Tutto zero
    assert validate_partita_iva("123456789") is False    # Troppo corta
    assert validate_partita_iva("123456789012") is False # Troppo lunga
    assert validate_partita_iva("ABC12345678") is False  # Con lettere
    assert validate_partita_iva(None) is False
    assert validate_partita_iva("") is False


def test_validator_codice_fiscale():
    assert validate_codice_fiscale("RSSMRA80A01H501Z") is True
    assert validate_codice_fiscale("rssmra80a01h501z") is True
    assert validate_codice_fiscale("RSSMRA80A01H501") is False   # 15 caratteri
    assert validate_codice_fiscale("1234567890123456") is False  # Solo cifre
    assert validate_codice_fiscale(None) is False


@pytest.mark.asyncio
async def test_armeria_registration_with_piva_and_optional_address(client: AsyncClient, db_session):
    """
    Verifica che un'armeria possa registrarsi con P.IVA valida
    senza fornire alcun indirizzo sede (campo facoltativo/opzionale).
    """
    payload = {
        "email": "armeria.centrale@test.it",
        "password": "PasswordSicura2026!",
        "nome": "Mario",
        "cognome": "Titolare",
        "ragione_sociale": "Armeria Centrale S.r.l.",
        "partita_iva": "00811720580",
        "licenza_tulps": "Licenza Questura n. 45678/PS",
        "ruolo": "armeria",
        "comune_id": 1,
        "indirizzo": None,  # INDIRIZZO SEDE NON FORNITO (OPZIONALE)
        "telefono": "+39 02 1234567"
    }

    resp = await client.post("/api/v1/auth/register", json=payload)
    assert resp.status_code == 201, f"Atteso 201, ottenuto {resp.status_code}: {resp.text}"
    data = resp.json()
    assert data["ruolo"] == "armeria"
    assert data["partita_iva"] == "00811720580"
    assert data["codice_fiscale"] is None
    assert data["indirizzo"] is None


@pytest.mark.asyncio
async def test_armeria_registration_rejects_invalid_piva(client: AsyncClient, db_session):
    """Verifica che un'armeria con P.IVA formalmente invalida venga respinta."""
    payload = {
        "email": "armeria.invalida@test.it",
        "password": "PasswordSicura2026!",
        "nome": "Giuseppe",
        "cognome": "Verdi",
        "ragione_sociale": "Armeria Fake",
        "partita_iva": "01234567890",  # Checksum non valido
        "licenza_tulps": "Licenza n. 123",
        "ruolo": "armeria",
        "comune_id": 1
    }

    resp = await client.post("/api/v1/auth/register", json=payload)
    assert resp.status_code in (400, 422), f"Atteso 400/422, ottenuto {resp.status_code}"


@pytest.mark.asyncio
async def test_armeria_registration_rejects_missing_piva(client: AsyncClient, db_session):
    """Verifica che un'armeria senza Partita IVA venga respinta."""
    payload = {
        "email": "armeria.senza.piva@test.it",
        "password": "PasswordSicura2026!",
        "nome": "Giuseppe",
        "cognome": "Verdi",
        "ragione_sociale": "Armeria Fake",
        "partita_iva": None,
        "licenza_tulps": "Licenza n. 123",
        "ruolo": "armeria",
        "comune_id": 1
    }

    resp = await client.post("/api/v1/auth/register", json=payload)
    assert resp.status_code in (400, 422), f"Atteso 400/422, ottenuto {resp.status_code}"


@pytest.mark.asyncio
async def test_privato_registration_optional_cf(client: AsyncClient, db_session):
    """Verifica che un privato possa registrarsi sia con sia senza codice fiscale."""
    # 1. Privato senza codice fiscale
    resp1 = await client.post("/api/v1/auth/register", json={
        "email": "privato.senza.cf@test.it",
        "password": "PasswordSicura2026!",
        "nome": "Luigi",
        "cognome": "Bianchi",
        "ruolo": "privato",
        "comune_id": 1,
        "indirizzo": None
    })
    assert resp1.status_code == 201
    data1 = resp1.json()
    assert data1["ruolo"] == "privato"
    assert data1["codice_fiscale"] is None
    assert data1["partita_iva"] is None

    # 2. Privato con codice fiscale valido
    resp2 = await client.post("/api/v1/auth/register", json={
        "email": "privato.con.cf@test.it",
        "password": "PasswordSicura2026!",
        "nome": "Marco",
        "cognome": "Neri",
        "codice_fiscale": "RSSMRA80A01H501Z",
        "ruolo": "privato",
        "comune_id": 1
    })
    assert resp2.status_code == 201
    data2 = resp2.json()
    assert data2["ruolo"] == "privato"
    assert data2["codice_fiscale"] == "RSSMRA80A01H501Z"


@pytest.mark.asyncio
async def test_profile_and_admin_piva_exposure(client: AsyncClient, db_session, admin_token_headers):
    """
    Verifica che il profilo armeria e l'endpoint admin espongano la Partita IVA
    per le armerie registrate.
    """
    # Registra armeria
    reg_resp = await client.post("/api/v1/auth/register", json={
        "email": "armeria.visibile@test.it",
        "password": "PasswordSicura2026!",
        "nome": "Armeria",
        "cognome": "Visibile",
        "ragione_sociale": "Armeria Visibile Srl",
        "partita_iva": "00159560366",
        "licenza_tulps": "TULPS-9988",
        "ruolo": "armeria",
        "comune_id": 1
    })
    assert reg_resp.status_code == 201

    # Login armeria
    login_resp = await client.post("/api/v1/auth/login", json={
        "email": "armeria.visibile@test.it",
        "password": "PasswordSicura2026!"
    })
    assert login_resp.status_code == 200
    token = login_resp.json()["access_token"]

    # Profilo /auth/me
    me_resp = await client.get("/api/v1/auth/me", headers={"Authorization": f"Bearer {token}"})
    assert me_resp.status_code == 200
    me_data = me_resp.json()
    assert me_data["partita_iva"] == "00159560366"
    assert me_data["codice_fiscale"] is None

    # Admin utenti list
    admin_resp = await client.get(
        "/api/v1/admin/utenti",
        headers=admin_token_headers
    )
    assert admin_resp.status_code == 200
    utenti = admin_resp.json()
    armeria_in_admin = next((u for u in utenti if u["email"] == "armeria.visibile@test.it"), None)
    assert armeria_in_admin is not None
    assert armeria_in_admin["partita_iva"] == "00159560366"
    assert armeria_in_admin["ruolo"] == "armeria"


def test_template_and_css_checks():
    """Verifica statica che nei template e nel CSS i requisiti siano soddisfatti."""
    # 1. Registrati: l'etichetta dell'indirizzo non ha asterischi
    with open("app/templates/registrati.html", "r", encoding="utf-8") as f:
        reg_html = f.read()
    assert "Indirizzo o Sede (Opzionale per privati) *" not in reg_html
    assert "Indirizzo della Sede del Negozio *" not in reg_html
    assert 'Indirizzo o Sede <span class="text-slate-500 font-normal">(Opzionale)</span>' in reg_html
    assert "regIndirizzo').required = false" in reg_html

    # 2. Base template: classe theme-light e sfondo chiaro
    with open("app/templates/base.html", "r", encoding="utf-8") as f:
        base_html = f.read()
    assert "theme-light" in base_html
    assert "bg-[#F7F5EF]" in base_html

    # 3. Styles.css: variabili e regole tema chiaro presenti
    with open("app/static/css/styles.css", "r", encoding="utf-8") as f:
        css = f.read()
    assert "--bg-main: #F7F5EF;" in css
    assert "--olive: #68733F;" in css
    assert "--tan: #B59A68;" in css
    assert "--text-primary: #252821;" in css
