import io
import pytest
from httpx import ASGITransport, AsyncClient
from PIL import Image
from pydantic import ValidationError
from sqlalchemy import select

from app.core.config import DEFAULT_DEV_SECRET, Settings, settings
from app.core.rate_limit import default_rate_limiter, get_client_ip
from app.core.security import create_access_token
from app.main import app
from app.models.annuncio import (
    Annuncio,
    ClassificazioneArma,
    CondizioneArma,
    StatoAnnuncio,
    TipologiaArma,
    TipologiaInserzionista,
)
from app.models.user import RuoloUtente, User


# ==============================================================================
# 1. TEST RATE LIMITING & CLIENT IP PROXY HANDLING
# ==============================================================================

def test_rate_limit_client_ip_anti_spoofing():
    """
    Verifica che get_client_ip() rifiuti tentativi di spoofing tramite header HTTP
    quando la richiesta non proviene da un reverse proxy certificato / autorizzato.
    """
    class MockClient:
        host = "198.51.100.25"  # IP effettivo del socket client

    class MockRequestDirect:
        client = MockClient()
        headers = {
            "x-forwarded-for": "10.0.0.1, 1.2.3.4",
            "cf-connecting-ip": "203.0.113.99"
        }

    # Se BEHIND_TRUSTED_PROXY è False (client si connette direttamente al server)
    orig_trusted = settings.BEHIND_TRUSTED_PROXY
    try:
        settings.BEHIND_TRUSTED_PROXY = False
        resolved_ip = get_client_ip(MockRequestDirect())
        # Deve tassativamente ignorare gli header spoofati e restituire l'IP socket effettivo
        assert resolved_ip == "198.51.100.25"

        # Se BEHIND_TRUSTED_PROXY è True (dietro reverse proxy Render/Cloudflare)
        settings.BEHIND_TRUSTED_PROXY = True
        resolved_trusted = get_client_ip(MockRequestDirect())
        # Deve accettare l'header certificato da Cloudflare
        assert resolved_trusted == "203.0.113.99"

        # Se non c'è CF-Connecting-IP ma solo X-Forwarded-For
        class MockRequestXFF:
            client = MockClient()
            headers = {"x-forwarded-for": "198.51.100.77, 10.0.0.2"}

        resolved_xff = get_client_ip(MockRequestXFF())
        assert resolved_xff == "198.51.100.77"
    finally:
        settings.BEHIND_TRUSTED_PROXY = orig_trusted


@pytest.mark.asyncio
async def test_rate_limit_exceeded_returns_429_and_retry_after(client: AsyncClient):
    """
    Verifica che il rate limiter restituisca HTTP 429 Too Many Requests
    e l'header Retry-After quando la soglia viene superata.
    """
    default_rate_limiter.clear()

    # /api/v1/auth/forgot-password ha una soglia di 3 richieste / 60s
    for i in range(3):
        resp = await client.post(
            "/api/v1/auth/forgot-password",
            json={"email": f"test{i}@example.com"}
        )
        assert resp.status_code == 200

    # La 4a richiesta deve essere respinta con HTTP 429
    resp_blocked = await client.post(
        "/api/v1/auth/forgot-password",
        json={"email": "blocked@example.com"}
    )
    assert resp_blocked.status_code == 429
    assert "Retry-After" in resp_blocked.headers
    retry_after = int(resp_blocked.headers["Retry-After"])
    assert retry_after > 0
    assert "Troppe richieste" in resp_blocked.json()["detail"]

    default_rate_limiter.clear()


# ==============================================================================
# 2. TEST CSP HARDENING & STATIC TAILWIND BUILD
# ==============================================================================

@pytest.mark.asyncio
async def test_csp_no_unsafe_inline_in_script_src(client: AsyncClient):
    """
    Verifica che nella Content Security Policy di produzione:
    - 'unsafe-inline' sia ASSENTE da script-src;
    - https://cdn.tailwindcss.com sia ASSENTE (sostituito da build locale);
    - un nonce per-request o origini autorizzate siano presenti.
    """
    resp = await client.get("/health")
    assert resp.status_code == 200

    csp = resp.headers.get("content-security-policy", "")
    assert csp != ""

    # Estrai la direttiva script-src
    directives = [d.strip() for d in csp.split(";") if d.strip().startswith("script-src")]
    assert len(directives) == 1
    script_src = directives[0]

    # Verifica vincolante: NESSUN 'unsafe-inline' in script-src!
    assert "'unsafe-inline'" not in script_src
    # Nessun CDN di compilazione Tailwind a runtime
    assert "cdn.tailwindcss.com" not in csp
    # Solo risorse legittime consentite
    assert "'self'" in script_src
    assert "https://unpkg.com" in script_src


@pytest.mark.asyncio
async def test_static_assets_available(client: AsyncClient):
    """
    Verifica che i file statici compilati siano correttamente serviti:
    - /static/css/tailwind.min.css
    - /static/css/styles.css
    - /static/js/app.js
    """
    resp_tw = await client.get("/static/css/tailwind.min.css")
    assert resp_tw.status_code == 200
    assert len(resp_tw.content) > 1000  # Build presente e popolata

    resp_css = await client.get("/static/css/styles.css")
    assert resp_css.status_code == 200
    assert b"--olive" in resp_css.content

    resp_js = await client.get("/static/js/app.js")
    assert resp_js.status_code == 200
    assert b"escapeHtml" in resp_js.content


# ==============================================================================
# 3. TEST PRIVACY EMAIL INSERZIONISTI PRIVATI
# ==============================================================================

@pytest.mark.asyncio
async def test_privacy_email_privato_non_esposta_pubblicamente(client: AsyncClient, db_session):
    """
    Verifica che le API pubbliche non espongano MAI l'indirizzo email personale
    di un inserzionista privato, consentendo al contempo il contatto tramite form.
    """
    # 1. Inserisci annuncio di un privato
    ad_privato = Annuncio(
        titolo="Pistola Beretta PX4 Storm Privato",
        slug="pistola-beretta-px4-storm-privato-test",
        descrizione="Descrizione lecita arma per cessione di persona.",
        prezzo=550.0,
        stato=StatoAnnuncio.PUBBLICATO,
        tipologia_inserzionista=TipologiaInserzionista.PRIVATO,
        tipologia_arma=TipologiaArma.ARMA_CORTA,
        marca="Beretta",
        modello="PX4 Storm",
        calibro="9x21",
        classificazione=ClassificazioneArma.COMUNE,
        condizione=CondizioneArma.USATO_OTTIMO,
        matricola_riservata="PX4TEST12345",
        comune_id=1,
        utente_id=2,
        email_contatto="segreto.privato@example.com"
    )

    # 2. Inserisci annuncio di un'armeria commerciale
    ad_armeria = Annuncio(
        titolo="Carabina Sabatti Rover Armeria",
        slug="carabina-sabatti-rover-armeria-test",
        descrizione="Carabina bolt action nuova in pronta consegna.",
        prezzo=890.0,
        stato=StatoAnnuncio.PUBBLICATO,
        tipologia_inserzionista=TipologiaInserzionista.ARMERIA,
        tipologia_arma=TipologiaArma.ARMA_LUNGA_RIGATA,
        marca="Sabatti",
        modello="Rover",
        calibro=".308 Win",
        classificazione=ClassificazioneArma.CACCIA,
        condizione=CondizioneArma.NUOVO,
        matricola_riservata="SAB308TEST",
        comune_id=1,
        utente_id=3,
        email_contatto="info@armeriarover.it"
    )

    db_session.add_all([ad_privato, ad_armeria])
    await db_session.commit()
    await db_session.refresh(ad_privato)
    await db_session.refresh(ad_armeria)

    # A) Verifica GET /api/v1/annunci/{id} per il PRIVATO
    resp_detail_privato = await client.get(f"/api/v1/annunci/{ad_privato.id}")
    assert resp_detail_privato.status_code == 200
    data_p = resp_detail_privato.json()
    assert data_p["email_contatto"] is None
    assert "segreto.privato@example.com" not in str(data_p)

    # B) Verifica GET /api/v1/annunci/{id} per l'ARMERIA (email aziendale visibile)
    resp_detail_armeria = await client.get(f"/api/v1/annunci/{ad_armeria.id}")
    assert resp_detail_armeria.status_code == 200
    data_a = resp_detail_armeria.json()
    assert data_a["email_contatto"] == "info@armeriarover.it"

    # C) Verifica GET /api/v1/annunci (ricerca lista pubblica)
    resp_list = await client.get("/api/v1/annunci?q=Beretta")
    assert resp_list.status_code == 200
    items = resp_list.json()["risultati"]
    for item in items:
        if item["id"] == ad_privato.id:
            assert item["email_contatto"] is None
            assert "segreto.privato@example.com" not in str(item)

    # D) Verifica che il contatto interno con form funzioni regolarmente per il privato
    default_rate_limiter.clear()
    resp_contact = await client.post(
        f"/api/v1/annunci/{ad_privato.id}/contatta",
        json={
            "nome_mittente": "Acquirente Titolato",
            "email_mittente": "acquirente@example.com",
            "titolo_di_polizia": "Porto d'Armi Tiro a Volo",
            "messaggio": "Salve, vorrei concordare l'acquisto di persona.",
            "accetto_disclaimer_legale": True
        }
    )
    assert resp_contact.status_code == 200
    assert resp_contact.json()["success"] is True
    default_rate_limiter.clear()


# ==============================================================================
# 4. TEST SECRET_KEY PRODUCTION-SAFE
# ==============================================================================

def test_secret_key_validation_in_production():
    """
    Verifica che in ambiente di produzione (ENVIRONMENT=production):
    - Se SECRET_KEY è assente o corrisponde al valore default, l'avvio fallisce.
    - Se SECRET_KEY è troppo corta (< 32 caratteri), l'avvio fallisce.
    - Se SECRET_KEY è sicura e >= 32 caratteri, la configurazione è valida.
    - In development, il valore di default è accettato senza sollevare errori.
    """
    # 1. In ambiente development: il default è consentito
    dev_settings = Settings(ENVIRONMENT="development", SECRET_KEY=DEFAULT_DEV_SECRET)
    assert dev_settings.ENVIRONMENT == "development"

    # 2. In ambiente production: il default solleva ValueError
    with pytest.raises(ValidationError) as exc_info:
        Settings(ENVIRONMENT="production", SECRET_KEY=DEFAULT_DEV_SECRET)
    err_str = str(exc_info.value)
    assert "SECRET_KEY deve essere obbligatoriamente fornita" in err_str
    # Nessun segreto stampato nei messaggi di errore
    assert DEFAULT_DEV_SECRET not in err_str

    # 3. In ambiente production: chiave troppo corta (< 32 caratteri) solleva ValueError
    with pytest.raises(ValidationError) as exc_short:
        Settings(ENVIRONMENT="production", SECRET_KEY="chiave-troppo-corta")
    assert "lunghezza minima di almeno 32 caratteri" in str(exc_short.value)

    # 4. In ambiente production: chiave valida ad alta entropia (>= 32 caratteri)
    prod_valid = Settings(
        ENVIRONMENT="production",
        SECRET_KEY="c4b918a287f34c568910be14ef712984a921d3f07a689b145892cfa712948bc1",
        FIRST_SUPERUSER_PASSWORD="StrongProductionSecretPass2026!#"
    )
    assert prod_valid.ENVIRONMENT == "production"


# ==============================================================================
# 5. TEST CSRF REVIEW SU TUTTI GLI ENDPOINT MUTATIVI
# ==============================================================================

@pytest.mark.asyncio
async def test_csrf_review_tutti_endpoint_mutativi_rifiutano_cookie(client: AsyncClient, db_session):
    """
    Audit mirato CSRF:
    Verifica sistematica che NESSUN endpoint mutativo accetti autenticazione basata su cookie.
    Tutti gli endpoint mutativi devono restituire HTTP 401 Unauthorized se invocati solo con cookie.
    """
    user = (await db_session.execute(select(User).where(User.id == 2))).scalar_one()
    token = create_access_token(subject=user.id, extra_claims={"ruolo": user.ruolo.value})

    client.cookies.set("armimarket_token", token)

    mutative_endpoints = [
        ("POST", "/api/v1/annunci", {
            "titolo": "Test CSRF Annuncio",
            "descrizione": "Descrizione arma lecita lunga almeno venti caratteri",
            "prezzo": 500.0,
            "tipologia_arma": "arma_corta",
            "marca": "Beretta",
            "modello": "98FS",
            "calibro": "9x21",
            "comune_id": 1,
            "email_contatto": "test@test.it"
        }),
        ("PUT", "/api/v1/auth/me", {"nickname": "HackerNick"}),
        ("POST", "/api/v1/preferiti/1", None),
        ("DELETE", "/api/v1/preferiti/1", None),
        ("PATCH", "/api/v1/annunci/1/stato?nuovo_stato=archiviato", None),
        ("DELETE", "/api/v1/annunci/1", None),
    ]

    try:
        for method, path, payload in mutative_endpoints:
            if method == "POST":
                resp = await client.post(path, json=payload)
            elif method == "PUT":
                resp = await client.put(path, json=payload)
            elif method == "PATCH":
                resp = await client.patch(path)
            elif method == "DELETE":
                resp = await client.delete(path)

            assert resp.status_code == 401, f"Endpoint mutativo {method} {path} ha accettato il cookie invece di richiedere Bearer token!"
            assert "Token di autenticazione mancante" in resp.json()["detail"]
    finally:
        client.cookies.delete("armimarket_token")
