import pytest
from httpx import AsyncClient
from sqlalchemy import select, func

from app.core.geo_seed import seed_geo_if_empty
from app.core.security import create_access_token
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


@pytest.mark.asyncio
async def test_seed_geo_idempotence_and_relations(db_session):
    """Verifica che seed_geo_if_empty popoli 20 regioni, 107 province e sia 100% idempotente."""
    # Primo run
    res1 = await seed_geo_if_empty(db_session)
    assert res1["regioni"] == 20
    assert res1["province"] == 107
    assert res1["comuni"] >= 109

    # Verifica presenza Gardone Val Trompia e integrità FK
    stmt = (
        select(Comune)
        .where(Comune.nome == "Gardone Val Trompia")
    )
    gardone = (await db_session.execute(stmt)).scalar_one_or_none()
    assert gardone is not None
    assert gardone.cap == "25063"
    assert gardone.provincia is not None
    assert gardone.provincia.sigla_automobilistica == "BS"
    assert gardone.provincia.regione.nome == "Lombardia"

    # Secondo run (idempotenza rigorosa)
    res2 = await seed_geo_if_empty(db_session)
    assert res2["inserted_regioni"] == 0
    assert res2["inserted_province"] == 0
    assert res2["inserted_comuni"] == 0
    assert res2["regioni"] == 20
    assert res2["province"] == 107


@pytest.mark.asyncio
async def test_scheda_annuncio_protezione_stati(client: AsyncClient, db_session, admin_token_headers, private_token_headers):
    """
    Verifica protezione server-side per annunci non pubblicati:
    - IN_MODERAZIONE: visibile solo al proprietario (id=2) e all'admin (id=1), 404 per anonimi o altri utenti.
    - RIFIUTATO / SOSPESO: non visibile al pubblico (404 per anonimi).
    - PUBBLICATO: accessibile a chiunque (200 OK).
    """
    # 1. Crea annuncio in moderazione appartenente all'utente privato (id=2)
    annuncio_mod = Annuncio(
        titolo="Beretta Modello Riservato In Moderazione",
        slug="beretta-in-moderazione-test",
        descrizione="Descrizione riservata in fase di moderazione",
        prezzo=500.0,
        stato=StatoAnnuncio.IN_MODERAZIONE,
        tipologia_inserzionista=TipologiaInserzionista.PRIVATO,
        tipologia_arma=TipologiaArma.ARMA_CORTA,
        marca="Beretta",
        modello="98FS",
        calibro="9x21",
        classificazione=ClassificazioneArma.COMUNE,
        condizione=CondizioneArma.USATO_OTTIMO,
        matricola_riservata="SECRET123",
        comune_id=1,
        utente_id=2,  # Utente privato proprietario
        email_contatto="privato.test@armimarket.it",
    )
    # 2. Crea annuncio rifiutato
    annuncio_rif = Annuncio(
        titolo="Arma Sospesa o Rifiutata",
        slug="arma-sospesa-test",
        descrizione="Descrizione annuncio rifiutato",
        prezzo=300.0,
        stato=StatoAnnuncio.RIFIUTATO,
        tipologia_inserzionista=TipologiaInserzionista.PRIVATO,
        tipologia_arma=TipologiaArma.ARMA_CORTA,
        marca="Glock",
        modello="19",
        calibro="9x21",
        classificazione=ClassificazioneArma.COMUNE,
        condizione=CondizioneArma.USATO_BUONO,
        matricola_riservata="SECRET999",
        comune_id=1,
        utente_id=2,
        email_contatto="privato.test@armimarket.it",
    )
    # 3. Crea annuncio pubblicato
    annuncio_pub = Annuncio(
        titolo="Arma Pubblica Conforme",
        slug="arma-pubblica-conforme-test",
        descrizione="Descrizione arma pubblica visibile a tutti",
        prezzo=700.0,
        stato=StatoAnnuncio.PUBBLICATO,
        tipologia_inserzionista=TipologiaInserzionista.PRIVATO,
        tipologia_arma=TipologiaArma.ARMA_CORTA,
        marca="CZ",
        modello="Shadow 2",
        calibro="9x21",
        classificazione=ClassificazioneArma.SPORTIVA,
        condizione=CondizioneArma.NUOVO,
        matricola_riservata="PUB12345",
        comune_id=1,
        utente_id=2,
        email_contatto="privato.test@armimarket.it",
    )
    db_session.add_all([annuncio_mod, annuncio_rif, annuncio_pub])
    await db_session.commit()
    await db_session.refresh(annuncio_mod)
    await db_session.refresh(annuncio_rif)
    await db_session.refresh(annuncio_pub)

    # A) Test Accesso Anonimo a IN_MODERAZIONE
    resp_api_anon = await client.get(f"/api/v1/annunci/{annuncio_mod.id}")
    assert resp_api_anon.status_code == 404
    resp_view_anon = await client.get(f"/scheda/{annuncio_mod.id}")
    assert resp_view_anon.status_code == 404

    # B) Test Accesso da altro utente non proprietario e non admin (es. utente id=3 armeria)
    other_token = create_access_token(subject=3, extra_claims={"ruolo": "armeria"})
    other_headers = {"Authorization": f"Bearer {other_token}"}
    resp_api_other = await client.get(f"/api/v1/annunci/{annuncio_mod.id}", headers=other_headers)
    assert resp_api_other.status_code == 404

    # C) Test Accesso da proprietario (id=2)
    resp_api_owner = await client.get(f"/api/v1/annunci/{annuncio_mod.id}", headers=private_token_headers)
    assert resp_api_owner.status_code == 200
    assert resp_api_owner.json()["titolo"] == "Beretta Modello Riservato In Moderazione"

    # Test visualizzazione HTML con cookie per proprietario
    owner_raw_token = private_token_headers["Authorization"].split(" ")[1]
    client.cookies.set("armimarket_token", owner_raw_token)
    resp_view_owner = await client.get(f"/scheda/{annuncio_mod.id}")
    client.cookies.delete("armimarket_token")
    assert resp_view_owner.status_code == 200

    # D) Test Accesso da Amministratore (id=1)
    resp_api_admin = await client.get(f"/api/v1/annunci/{annuncio_mod.id}", headers=admin_token_headers)
    assert resp_api_admin.status_code == 200
    resp_view_admin = await client.get(f"/scheda/{annuncio_mod.id}", headers=admin_token_headers)
    assert resp_view_admin.status_code == 200

    # E) Test Annuncio RIFIUTATO: non accessibile al pubblico
    resp_rif_anon = await client.get(f"/api/v1/annunci/{annuncio_rif.id}")
    assert resp_rif_anon.status_code == 404
    resp_rif_view_anon = await client.get(f"/scheda/{annuncio_rif.id}")
    assert resp_rif_view_anon.status_code == 404

    # F) Test Annuncio PUBBLICATO: accessibile sia ad anonimi che a tutti
    resp_pub_anon = await client.get(f"/api/v1/annunci/{annuncio_pub.id}")
    assert resp_pub_anon.status_code == 200
    resp_pub_view_anon = await client.get(f"/scheda/{annuncio_pub.id}")
    assert resp_pub_view_anon.status_code == 200


@pytest.mark.asyncio
async def test_ingestion_auth_and_ssrf_protection(client: AsyncClient, admin_token_headers, private_token_headers):
    """
    Verifica protezione endpoint di ingestion:
    - Anonimi e privati bloccati (401 / 403).
    - Tentativi SSRF (localhost, 127.0.0.1, 169.254.x.x, RFC1918, schemi vietati) bloccati con 400.
    """
    # 1. GET /armerie
    # Anonimo -> 401
    resp_armerie_anon = await client.get("/api/v1/ingestion/armerie")
    assert resp_armerie_anon.status_code == 401

    # Privato -> 403
    resp_armerie_priv = await client.get("/api/v1/ingestion/armerie", headers=private_token_headers)
    assert resp_armerie_priv.status_code == 403

    # Admin -> 200
    resp_armerie_admin = await client.get("/api/v1/ingestion/armerie", headers=admin_token_headers)
    assert resp_armerie_admin.status_code == 200

    # 2. POST /sync-url
    # Anonimo -> 401
    resp_sync_anon = await client.post("/api/v1/ingestion/sync-url", json={"feed_url": "https://example.com"})
    assert resp_sync_anon.status_code == 401

    # Privato -> 403
    resp_sync_priv = await client.post("/api/v1/ingestion/sync-url", json={"feed_url": "https://example.com"}, headers=private_token_headers)
    assert resp_sync_priv.status_code == 403

    # 3. Test Anti-SSRF su POST /sync-url con utente Admin
    ssrf_payloads = [
        "http://127.0.0.1:8000/api/v1/admin",
        "http://localhost:8000/secret",
        "http://169.254.169.254/latest/meta-data/",
        "http://10.0.0.1/admin",
        "http://192.168.1.1/router",
        "http://172.16.0.1/internal",
        "file:///etc/passwd",
        "gopher://127.0.0.1:70",
        "https://example.com:22/feed",
    ]

    for malicious_url in ssrf_payloads:
        resp = await client.post(
            "/api/v1/ingestion/sync-url",
            json={"feed_url": malicious_url, "feed_type": "woocommerce"},
            headers=admin_token_headers
        )
        assert resp.status_code == 400, f"SSRF payload {malicious_url} non bloccato (status: {resp.status_code})"
        assert "non consentito" in resp.json()["detail"].lower() or "bloccato" in resp.json()["detail"].lower()

    # 4. Test Anti-SSRF su POST /scrape-url con utente Admin
    for malicious_url in ["http://localhost:8000", "http://127.0.0.1", "http://169.254.169.254"]:
        resp_scrape = await client.post(
            "/api/v1/ingestion/scrape-url",
            json={"url": malicious_url},
            headers=admin_token_headers
        )
        assert resp_scrape.status_code == 400
