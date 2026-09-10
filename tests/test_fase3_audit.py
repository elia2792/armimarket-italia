import pytest
import jwt
from sqlalchemy import select

from app.core.network import validate_url_safe
from app.core.security import create_access_token
from app.models.annuncio import (
    Annuncio,
    ClassificazioneArma,
    CondizioneArma,
    StatoAnnuncio,
    TipologiaArma,
    TipologiaInserzionista,
)
from app.models.user import RuoloUtente, User


@pytest.mark.asyncio
async def test_idor_privato_non_puo_modificare_o_cancellare_annuncio_altrui(client, db_session):
    """
    Verifica Broken Access Control (IDOR):
    Un utente privato B non può modificare o eliminare un annuncio creato dall'utente privato A.
    """
    # 1. Recupera utente vittima (Privato A, id=2 creato da conftest)
    user_a = (await db_session.execute(select(User).where(User.id == 2))).scalar_one()

    # 2. Crea utente attaccante (Privato B)
    user_b = User(
        email="attaccante.b@example.com",
        hashed_password="hash",
        nome="Attaccante",
        cognome="B",
        ruolo=RuoloUtente.PRIVATO,
        is_active=True
    )
    db_session.add(user_b)
    await db_session.commit()
    await db_session.refresh(user_b)

    # 3. Crea annuncio appartenente a Privato A
    annuncio_a = Annuncio(
        titolo="Pistola Beretta 98FS Privato A",
        slug="pistola-beretta-98fs-privato-a",
        descrizione="Descrizione lecita",
        prezzo=650.0,
        stato=StatoAnnuncio.PUBBLICATO,
        tipologia_inserzionista=TipologiaInserzionista.PRIVATO,
        tipologia_arma=TipologiaArma.ARMA_CORTA,
        marca="Beretta",
        modello="98FS",
        calibro="9x21",
        classificazione=ClassificazioneArma.COMUNE,
        condizione=CondizioneArma.USATO_OTTIMO,
        matricola_riservata="A12345X",
        comune_id=1,
        utente_id=user_a.id,
        email_contatto=user_a.email
    )
    db_session.add(annuncio_a)
    await db_session.commit()
    await db_session.refresh(annuncio_a)

    # 4. Token per attaccante B
    token_b = create_access_token(subject=user_b.id, extra_claims={"ruolo": user_b.ruolo.value})
    headers_b = {"Authorization": f"Bearer {token_b}"}

    # Tentativo IDOR di modifica stato da parte di B
    patch_resp = await client.patch(
        f"/api/v1/annunci/{annuncio_a.id}/stato?nuovo_stato=archiviato",
        headers=headers_b
    )
    assert patch_resp.status_code == 403
    assert "Non hai i permessi per modificare questo annuncio" in patch_resp.json()["detail"]

    # Tentativo IDOR di eliminazione da parte di B
    del_resp = await client.delete(
        f"/api/v1/annunci/{annuncio_a.id}",
        headers=headers_b
    )
    assert del_resp.status_code == 403
    assert "Non hai i permessi per eliminare questo annuncio" in del_resp.json()["detail"]


@pytest.mark.asyncio
async def test_csrf_api_mutative_immuni_a_cookie(client, db_session):
    """
    Dimostrazione del modello di sicurezza CSRF:
    Gli endpoint mutativi (POST/PUT/PATCH/DELETE) richiedono strettamente l'header Bearer token.
    L'invio del solo cookie armimarket_token NON consente l'autenticazione alle API mutative (HTTP 401).
    Questo rende l'architettura intrinsecamente immune ad attacchi CSRF cross-origin.
    """
    user_a = (await db_session.execute(select(User).where(User.id == 2))).scalar_one()
    token = create_access_token(subject=user_a.id, extra_claims={"ruolo": user_a.ruolo.value})

    # 1. Chiamata mutativa POST /api/v1/annunci fornendo SOLO il cookie e NESSUN Bearer header
    resp = await client.post(
        "/api/v1/annunci",
        cookies={"armimarket_token": token},
        json={
            "titolo": "Tentativo CSRF Senza Header",
            "descrizione": "Questo annuncio non deve essere creato",
            "prezzo": 500.0,
            "tipologia_arma": "arma_corta",
            "marca": "Glock",
            "modello": "17",
            "calibro": "9x21",
            "classificazione": "sportiva",
            "condizione": "usato_ottimo",
            "comune_id": 1,
            "email_contatto": "csrf@example.com"
        }
    )
    # Deve essere respinto con 401 Unauthorized perché il cookie non è considerato da get_current_user
    assert resp.status_code == 401
    assert "Token di autenticazione mancante" in resp.json()["detail"]

    # 2. Chiamata mutativa PUT /api/v1/auth/me fornendo SOLO il cookie
    resp_profile = await client.put(
        "/api/v1/auth/me",
        cookies={"armimarket_token": token},
        json={"nickname": "CsrfHacker"}
    )
    assert resp_profile.status_code == 401


@pytest.mark.asyncio
async def test_jwt_alg_confusion_e_manomissione_signature(client, db_session):
    """
    Verifica sicurezza JWT:
    - Algoritmo none respinto.
    - Firma manipolata con chiave errata respinta (401).
    - Privilegio 'admin' iniettato nel token di un utente con ruolo 'privato' a DB non consente privilege escalation.
    """
    user_a = (await db_session.execute(select(User).where(User.id == 2))).scalar_one()

    # 1. Token firmato con algoritmo 'none' (alg-confusion)
    token_none = jwt.encode({"sub": str(user_a.id), "ruolo": "admin"}, key="", algorithm="none")
    resp_none = await client.get(
        "/api/v1/auth/me",
        headers={"Authorization": f"Bearer {token_none}"}
    )
    assert resp_none.status_code == 401

    # 2. Token con firma valida ma chiave segreta diversa
    token_fake_key = jwt.encode({"sub": str(user_a.id)}, key="chiave-falsa-attaccante", algorithm="HS256")
    resp_fake = await client.get(
        "/api/v1/auth/me",
        headers={"Authorization": f"Bearer {token_fake_key}"}
    )
    assert resp_fake.status_code == 401

    # 3. Token valido con claim ruolo: "admin", ma l'utente a database ha ruolo "privato"
    # Il sistema non deve fidarsi ciecamente dei claims: get_current_admin interroga il DB
    token_spoofed_claim = create_access_token(subject=user_a.id, extra_claims={"ruolo": "admin"})
    admin_resp = await client.get(
        "/api/v1/admin/utenti",
        headers={"Authorization": f"Bearer {token_spoofed_claim}"}
    )
    # Deve restituire 403 Forbidden perché user_a a DB è RuoloUtente.PRIVATO
    assert admin_resp.status_code == 403


@pytest.mark.asyncio
async def test_ssrf_validator_edge_cases():
    """
    Verifica analitica delle protezioni anti-SSRF:
    - Rifiuto IP privati, loopback, IPv6 link-local, cloud metadata e porte non standard.
    """
    # 1. Cloud Metadata (AWS / GCP / OpenStack / Render)
    with pytest.raises(ValueError, match="Accesso bloccato"):
        validate_url_safe("http://169.254.169.254/latest/meta-data/")

    # 2. Localhost e loopback
    with pytest.raises(ValueError, match="Accesso a localhost / loopback non consentito"):
        validate_url_safe("http://127.0.0.1:8080/internal")

    with pytest.raises(ValueError, match="Accesso a localhost / loopback non consentito"):
        validate_url_safe("http://localhost:8000/")

    # 3. Porta non consentita (es. porta Redis 6379 o SSH 22)
    with pytest.raises(ValueError, match="Porta di rete 6379 non consentita"):
        validate_url_safe("http://example.com:6379/test")

    with pytest.raises(ValueError, match="Porta di rete 22 non consentita"):
        validate_url_safe("http://example.com:22/test")

    # 4. Schemi non HTTP (file://, gopher://, ftp://)
    with pytest.raises(ValueError, match="Protocollo 'file' non consentito"):
        validate_url_safe("file:///etc/passwd")

    with pytest.raises(ValueError, match="Protocollo 'gopher' non consentito"):
        validate_url_safe("gopher://127.0.0.1:70/")


@pytest.mark.asyncio
async def test_disattivazione_account_blocca_autenticazione_e_sessioni_attive(client, db_session):
    """
    Verifica Business Logic:
    Un account disabilitato dall'admin (is_active=False):
    - Non può eseguire il login (HTTP 403)
    - Qualsiasi token precedentemente emesso viene respinto immediatamente da get_current_user (HTTP 403)
    """
    user_a = (await db_session.execute(select(User).where(User.id == 2))).scalar_one()

    # Genera token mentre l'utente è ancora attivo
    valid_token = create_access_token(subject=user_a.id, extra_claims={"ruolo": user_a.ruolo.value})

    # Disattiva account
    user_a.is_active = False
    await db_session.commit()

    # 1. Tentativo di accesso con token valido di utente disattivato
    resp_me = await client.get(
        "/api/v1/auth/me",
        headers={"Authorization": f"Bearer {valid_token}"}
    )
    assert resp_me.status_code == 403
    assert "Account utente disabilitato" in resp_me.json()["detail"]

    # 2. Tentativo di nuovo login
    resp_login = await client.post(
        "/api/v1/auth/login",
        json={"email": user_a.email, "password": "PrivatoTest123!"}
    )
    assert resp_login.status_code == 403
    assert "Account sospeso o disattivato" in resp_login.json()["detail"]
