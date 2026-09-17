import pytest
from app.models.annuncio import Annuncio, ClassificazioneArma, CondizioneArma, StatoAnnuncio, TipologiaArma, TipologiaInserzionista


@pytest.mark.asyncio
async def test_create_annuncio_as_private(client, private_token_headers):
    payload = {
        "titolo": "Pistola Beretta 98FS Cal. 9x21",
        "descrizione": "Vendo pistola Beretta 98FS in condizioni perfette per passaggio ad altro calibro. Cessione solo a titolari di porto d'armi valido.",
        "prezzo": 750.0,
        "tipologia_inserzionista": "privato",
        "tipologia_arma": "arma_corta",
        "marca": "Beretta",
        "modello": "98FS",
        "calibro": "9x21",
        "classificazione": "comune",
        "condizione": "usato_ottimo",
        "comune_id": 1,
        "email_contatto": "privato.test@armimarket.it",
        "telefono_contatto": "+39 340 1234567",
        "mostra_telefono_pubblico": False,
        "matricola_riservata": "BER98FS12345",
    }

    response = await client.post("/api/v1/annunci", json=payload, headers=private_token_headers)
    assert response.status_code == 201
    data = response.json()
    assert data["titolo"] == payload["titolo"]
    # Per i privati, lo stato iniziale è 'in_moderazione'
    assert data["stato"] == "in_moderazione"
    # La matricola NON deve essere visibile in chiaro
    assert "BER98FS12345" not in str(data)
    assert data["matricola_visibile"] == "[RISERVATA AI SENSI DEL REGOLAMENTO DI PUBBLICA SICUREZZA]"
    # Il telefono NON deve essere mostrato perché mostra_telefono_pubblico è False
    assert data["telefono_contatto"] is None


@pytest.mark.asyncio
async def test_search_and_map_geojson(client, db_session):
    # Inserisce un annuncio pubblicato nel db
    ad = Annuncio(
        titolo="Glock 17 Gen 5 9x19",
        slug="glock-17-gen-5-9x19-test",
        descrizione="Pistola semiautomatica in calibro 9x19 con scatola e caricatori.",
        prezzo=650.0,
        stato=StatoAnnuncio.PUBBLICATO,
        tipologia_inserzionista=TipologiaInserzionista.ARMERIA,
        tipologia_arma=TipologiaArma.ARMA_CORTA,
        marca="Glock",
        modello="17 Gen 5",
        calibro="9x19 Parabellum",
        classificazione=ClassificazioneArma.SPORTIVA,
        condizione=CondizioneArma.NUOVO,
        matricola_riservata="GLK17G5TEST",
        comune_id=1,  # Milano
        utente_id=3,
        galleria_immagini=["https://example.com/glock.jpg"],
        email_contatto="armeria@test.it",
        mostra_telefono_pubblico=True,
    )
    db_session.add(ad)
    await db_session.commit()
    await db_session.refresh(ad)

    # 1. Test Ricerca Annunci con filtro marca
    res_search = await client.get("/api/v1/annunci?marca=Glock")
    assert res_search.status_code == 200
    search_data = res_search.json()
    assert search_data["totale"] >= 1
    assert search_data["risultati"][0]["marca"] == "Glock"

    # 2. Test FeatureCollection GeoJSON per Mappa Interattiva
    res_map = await client.get("/api/v1/annunci/mappa/geojson")
    assert res_map.status_code == 200
    map_data = res_map.json()
    assert map_data["type"] == "FeatureCollection"
    assert len(map_data["features"]) >= 1

    feature = map_data["features"][0]
    assert feature["geometry"]["type"] == "Point"
    # [longitudine, latitudine] di Milano
    assert feature["geometry"]["coordinates"][0] == pytest.approx(9.19, 0.01)
    assert feature["geometry"]["coordinates"][1] == pytest.approx(45.46, 0.01)
    # Link alla scheda annuncio
    assert feature["properties"]["url_scheda"] == f"/scheda/{ad.id}"
    assert feature["properties"]["titolo"] == "Glock 17 Gen 5 9x19"


@pytest.mark.asyncio
async def test_annuncio_detail_and_contact_form(client, db_session):
    ad = Annuncio(
        titolo="Benelli Raffaello Caccia 12/76",
        slug="benelli-raffaello-test",
        descrizione="Fucile semiautomatico da caccia calibro 12 magnum, legni pregiati.",
        prezzo=1200.0,
        stato=StatoAnnuncio.PUBBLICATO,
        tipologia_inserzionista=TipologiaInserzionista.PRIVATO,
        tipologia_arma=TipologiaArma.CANNA_LISCIA,
        marca="Benelli",
        modello="Raffaello",
        calibro="12/76",
        classificazione=ClassificazioneArma.CACCIA,
        condizione=CondizioneArma.USATO_OTTIMO,
        matricola_riservata="BNLRAF12345",
        comune_id=1,
        utente_id=2,
        email_contatto="venditore@test.it",
    )
    db_session.add(ad)
    await db_session.commit()
    await db_session.refresh(ad)

    # 1. Dettaglio annuncio
    res_detail = await client.get(f"/api/v1/annunci/{ad.id}")
    assert res_detail.status_code == 200
    detail = res_detail.json()
    assert detail["visualizzazioni"] >= 1
    assert "BNLRAF12345" not in str(detail)
    assert "T.U.L.P.S." in detail["disclaimer_legale"]
    assert detail["precisione_mappa"] == "comunale_protetta"
    assert detail["latitudine_mappa"] == pytest.approx(45.4642, 0.01)

    # 2. Form contatto - Fallimento se non accetta il disclaimer TULPS
    res_fail = await client.post(
        f"/api/v1/annunci/{ad.id}/contatta",
        json={
            "nome_mittente": "Luigi Verdi",
            "email_mittente": "luigi@example.com",
            "titolo_di_polizia": "Porto d'Armi Difesa",
            "messaggio": "Vorrei visionare l'arma di persona.",
            "accetto_disclaimer_legale": False
        }
    )
    assert res_fail.status_code == 422

    # 3. Form contatto - Successo con titolo valido e accettazione
    res_ok = await client.post(
        f"/api/v1/annunci/{ad.id}/contatta",
        json={
            "nome_mittente": "Luigi Verdi",
            "email_mittente": "luigi@example.com",
            "titolo_di_polizia": "Porto d'Armi Uso Sportivo",
            "messaggio": "Vorrei concordare una visione di persona presso un poligono o armeria.",
            "accetto_disclaimer_legale": True
        }
    )
    assert res_ok.status_code == 200
    assert res_ok.json()["success"] is True


@pytest.mark.asyncio
async def test_update_annuncio_comune(client, private_token_headers, db_session):
    # Annuncio creato con comune_id = 1 (Milano)
    ad = Annuncio(
        titolo="Carabina CZ 457 Varmint .22 LR",
        slug="cz-457-varmint-test",
        descrizione="Carabina a ripetizione semplice in condizioni eccellenti pari al nuovo.",
        prezzo=590.0,
        stato=StatoAnnuncio.PUBBLICATO,
        tipologia_inserzionista=TipologiaInserzionista.PRIVATO,
        tipologia_arma=TipologiaArma.ARMA_LUNGA_RIGATA,
        marca="CZ",
        modello="457 Varmint",
        calibro=".22 LR",
        classificazione=ClassificazioneArma.SPORTIVA,
        condizione=CondizioneArma.USATO_OTTIMO,
        matricola_riservata="CZ457TEST",
        comune_id=1,  # Inizialmente Milano
        utente_id=2,  # Utente privato nei fixture
        email_contatto="privato.test@armimarket.it",
    )
    db_session.add(ad)
    await db_session.commit()
    await db_session.refresh(ad)

    # 1. Aggiorna comune con successo a Roma (comune_id = 2 nel seed)
    res_patch = await client.patch(
        f"/api/v1/annunci/{ad.id}/comune",
        json={"comune_id": 2},
        headers=private_token_headers
    )
    assert res_patch.status_code == 200
    patch_data = res_patch.json()
    assert patch_data["comune_id"] == 2
    assert "comune_nome" in patch_data

    # 2. Comune inesistente -> 404
    res_404 = await client.patch(
        f"/api/v1/annunci/{ad.id}/comune",
        json={"comune_id": 999999},
        headers=private_token_headers
    )
    assert res_404.status_code == 404


@pytest.mark.asyncio
async def test_author_can_update_own_annuncio(client, private_token_headers, db_session):
    ad = Annuncio(
        titolo="Carabina Ruger 10/22 .22 LR",
        slug="ruger-1022-test",
        descrizione="Carabina semiautomatica in perfetto stato con caricatore.",
        prezzo=450.0,
        stato=StatoAnnuncio.PUBBLICATO,
        tipologia_inserzionista=TipologiaInserzionista.PRIVATO,
        tipologia_arma=TipologiaArma.ARMA_LUNGA_RIGATA,
        marca="Ruger",
        modello="10/22",
        calibro=".22 LR",
        classificazione=ClassificazioneArma.SPORTIVA,
        condizione=CondizioneArma.USATO_OTTIMO,
        matricola_riservata="RUG1022TEST",
        comune_id=1,
        utente_id=2,  # Utente privato
        email_contatto="privato.test@armimarket.it",
    )
    db_session.add(ad)
    await db_session.commit()
    await db_session.refresh(ad)

    # Autore aggiorna prezzo, titolo e descrizione
    update_payload = {
        "titolo": "Carabina Ruger 10/22 .22 LR - Ribasso Prezzo",
        "prezzo": 399.0,
        "descrizione": "Carabina in ottimo stato, regalo borsa da trasporto.",
        "condizione": "usato_buono",
    }
    res = await client.put(
        f"/api/v1/annunci/{ad.id}",
        json=update_payload,
        headers=private_token_headers
    )
    assert res.status_code == 200
    data = res.json()
    assert data["titolo"] == "Carabina Ruger 10/22 .22 LR - Ribasso Prezzo"
    assert data["prezzo"] == 399.0
    assert data["condizione"] == "usato_buono"


@pytest.mark.asyncio
async def test_unauthorized_user_cannot_update_or_delete_annuncio(client, db_session):
    from app.core.security import create_access_token, hash_password
    from app.models.user import RuoloUtente, User

    other_user = User(
        email="altro.utente@armimarket.it",
        hashed_password=hash_password("PassAltro123!"),
        nome="Altro",
        cognome="Utente",
        ruolo=RuoloUtente.PRIVATO,
        is_active=True,
        is_verified=True,
    )
    db_session.add(other_user)
    await db_session.commit()
    await db_session.refresh(other_user)

    other_token = create_access_token(subject=other_user.id, extra_claims={"ruolo": "privato"})
    other_headers = {"Authorization": f"Bearer {other_token}"}

    ad = Annuncio(
        titolo="Beretta 92FS Brigadier",
        slug="beretta-brigadier-test",
        descrizione="Canna pesante, scatto accuratizzato, intonsa.",
        prezzo=900.0,
        stato=StatoAnnuncio.PUBBLICATO,
        tipologia_inserzionista=TipologiaInserzionista.PRIVATO,
        tipologia_arma=TipologiaArma.ARMA_CORTA,
        marca="Beretta",
        modello="92FS",
        calibro="9x21",
        classificazione=ClassificazioneArma.COMUNE,
        condizione=CondizioneArma.USATO_OTTIMO,
        matricola_riservata="BERBRIG123",
        comune_id=1,
        utente_id=2,  # Utente 2 è proprietario
        email_contatto="privato.test@armimarket.it",
    )
    db_session.add(ad)
    await db_session.commit()
    await db_session.refresh(ad)

    # Utente 999 tenta PUT -> 403 Forbidden
    res_put = await client.put(
        f"/api/v1/annunci/{ad.id}",
        json={"titolo": "Hacked Title", "prezzo": 10.0},
        headers=other_headers
    )
    assert res_put.status_code == 403

    # Utente 999 tenta DELETE -> 403 Forbidden
    res_del = await client.delete(
        f"/api/v1/annunci/{ad.id}",
        headers=other_headers
    )
    assert res_del.status_code == 403


@pytest.mark.asyncio
async def test_author_can_delete_own_annuncio(client, private_token_headers, db_session):
    ad = Annuncio(
        titolo="Glock 17 Gen 5 9x21",
        slug="glock-17-gen5-delete-test",
        descrizione="Come nuova con due caricatori e valigetta.",
        prezzo=620.0,
        stato=StatoAnnuncio.PUBBLICATO,
        tipologia_inserzionista=TipologiaInserzionista.PRIVATO,
        tipologia_arma=TipologiaArma.ARMA_CORTA,
        marca="Glock",
        modello="17 Gen 5",
        calibro="9x21",
        classificazione=ClassificazioneArma.COMUNE,
        condizione=CondizioneArma.USATO_OTTIMO,
        matricola_riservata="GLOCK17DEL",
        comune_id=1,
        utente_id=2,  # Utente privato
        email_contatto="privato.test@armimarket.it",
    )
    db_session.add(ad)
    await db_session.commit()
    await db_session.refresh(ad)

    # Autore elimina il proprio annuncio
    res = await client.delete(
        f"/api/v1/annunci/{ad.id}",
        headers=private_token_headers
    )
    assert res.status_code == 200
    assert res.json()["success"] is True

    # Verifica che ora l'annuncio non sia più reperibile o sia eliminato
    res_get = await client.get(f"/api/v1/annunci/{ad.id}")
    assert res_get.status_code == 404


