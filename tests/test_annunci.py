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
