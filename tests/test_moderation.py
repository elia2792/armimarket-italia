import pytest
from app.models.annuncio import Annuncio, ClassificazioneArma, CondizioneArma, StatoAnnuncio, TipologiaArma, TipologiaInserzionista
from app.services.moderation_service import mask_matricola


def test_mask_matricola_function():
    # Test vari formati di matricola
    assert mask_matricola(None) is None
    assert mask_matricola("") is None
    assert mask_matricola("123") == "***"
    assert mask_matricola("AB1234CD") == "AB****CD"
    assert mask_matricola("BER98FS2026") == "BE*******26"


@pytest.mark.asyncio
async def test_banned_keyword_prevention(client, private_token_headers):
    # Prova di caricamento annuncio contenente termine illegale "silenziatore"
    payload_illegale = {
        "titolo": "Vendo carabina con silenziatore integrato",
        "descrizione": "Arma da caccia con silenziatore fonoassorbente artigianale.",
        "prezzo": 1000.0,
        "tipologia_inserzionista": "privato",
        "tipologia_arma": "arma_lunga_rigata",
        "marca": "CZ",
        "modello": "457",
        "calibro": ".22 LR",
        "classificazione": "sportiva",
        "condizione": "usato_ottimo",
        "comune_id": 1,
        "email_contatto": "privato.test@armimarket.it",
    }

    response = await client.post("/api/v1/annunci", json=payload_illegale, headers=private_token_headers)
    # Deve essere bloccato preventivamente con HTTP 422 Unprocessable Entity
    assert response.status_code == 422
    err_msg = str(response.json())
    assert "silenziatore" in err_msg.lower() or "termine non consentito" in err_msg.lower()


@pytest.mark.asyncio
async def test_admin_moderation_flow(client, db_session, admin_token_headers):
    # Crea un annuncio in attesa di moderazione
    ad = Annuncio(
        titolo="Beretta APX Calibro 9x21",
        slug="beretta-apx-9x21-mod-test",
        descrizione="Pistola semiautomatica polimerica striker fired calibro 9x21 IMI.",
        prezzo=520.0,
        stato=StatoAnnuncio.IN_MODERAZIONE,
        tipologia_inserzionista=TipologiaInserzionista.PRIVATO,
        tipologia_arma=TipologiaArma.ARMA_CORTA,
        marca="Beretta",
        modello="APX",
        calibro="9x21",
        classificazione=ClassificazioneArma.COMUNE,
        condizione=CondizioneArma.USATO_OTTIMO,
        matricola_riservata="APX1234567",
        comune_id=1,
        utente_id=2,
        email_contatto="privato@test.it",
    )
    db_session.add(ad)
    await db_session.commit()
    await db_session.refresh(ad)

    # 1. Moderatore consulta la coda
    res_queue = await client.get("/api/v1/admin/moderazione", headers=admin_token_headers)
    assert res_queue.status_code == 200
    queue = res_queue.json()
    assert any(item["id"] == ad.id for item in queue)

    mod_item = next(item for item in queue if item["id"] == ad.id)
    # Verifica che la matricola per il moderatore sia mascherata e non mostrata in chiaro
    assert mod_item["matricola_mascherata"] == "AP******67"

    # 2. Moderatore approva l'annuncio
    res_approve = await client.post(
        f"/api/v1/admin/moderazione/{ad.id}/approva",
        json={"note": "Titolo e conformità verificati"},
        headers=admin_token_headers
    )
    assert res_approve.status_code == 200
    assert res_approve.json()["stato"] == "pubblicato"

    # 3. Ora l'annuncio deve essere visibile nella ricerca pubblica
    res_public = await client.get("/api/v1/annunci?marca=Beretta")
    assert res_public.status_code == 200
    pub_data = res_public.json()
    assert any(item["id"] == ad.id for item in pub_data["risultati"])
