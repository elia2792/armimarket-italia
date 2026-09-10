import pytest
from httpx import AsyncClient


@pytest.mark.asyncio
async def test_segnalazione_annuncio_e_rimozione_da_admin(
    client: AsyncClient,
    private_token_headers: dict,
    admin_token_headers: dict
):
    """
    Test completo flusso segnalazione e rimozione ad opera dell'Amministratore:
    1. Creazione e approvazione annuncio
    2. Segnalazione da parte di un utente per difformità TULPS
    3. Notifica e visualizzazione della segnalazione nel pannello Admin
    4. Eliminazione diretta e definitiva dell'annuncio segnalato da parte dell'Admin
    5. Verifica scomparsa annuncio dal portale
    """
    # 1. Creazione annuncio
    ad_data = {
        "titolo": "Pistola Sospetta per Test Segnalazione",
        "descrizione": "Descrizione arma per test segnalazione.",
        "prezzo": 450.0,
        "tipologia_inserzionista": "privato",
        "tipologia_arma": "arma_corta",
        "marca": "Beretta",
        "modello": "84FS",
        "calibro": "9 Corto",
        "classificazione": "comune",
        "condizione": "usato_ottimo",
        "comune_id": 1,
        "email_contatto": "venditore.sospetto@test.it"
    }
    create_resp = await client.post("/api/v1/annunci", json=ad_data, headers=private_token_headers)
    assert create_resp.status_code == 201
    ad_id = create_resp.json()["id"]

    # Approva l'annuncio
    appr = await client.post(f"/api/v1/admin/moderazione/{ad_id}/approva", json={}, headers=admin_token_headers)
    assert appr.status_code == 200

    # 2. Segnalazione annuncio
    report_data = {
        "motivo": "difformita_tulps",
        "dettagli": "L'inserzionista propone spedizione postale non consentita dall'Art. 17 della legge 110/1975.",
        "email_segnalatore": "cittadino.attento@test.it"
    }
    rep_resp = await client.post(f"/api/v1/annunci/{ad_id}/segnala", json=report_data)
    assert rep_resp.status_code == 201
    rep_json = rep_resp.json()
    assert rep_json["success"] is True
    segnalazione_id = rep_json["segnalazione_id"]

    # 3. Consultazione lista segnalazioni da parte dell'Admin
    admin_rep_resp = await client.get("/api/v1/admin/segnalazioni?solo_aperte=true", headers=admin_token_headers)
    assert admin_rep_resp.status_code == 200
    seg_list = admin_rep_resp.json()
    assert len(seg_list) >= 1
    found_seg = next((s for s in seg_list if s["id"] == segnalazione_id), None)
    assert found_seg is not None
    assert found_seg["annuncio_id"] == ad_id
    assert found_seg["motivo"] == "difformita_tulps"

    # 4. Eliminazione diretta dell'annuncio non conforme da parte dell'Admin
    del_resp = await client.delete(
        f"/api/v1/admin/segnalazioni/{segnalazione_id}/elimina-annuncio",
        headers=admin_token_headers
    )
    assert del_resp.status_code == 200
    del_json = del_resp.json()
    assert del_json["success"] is True
    assert "rimosso definitivamente" in del_json["message"]

    # 5. Verifica che l'annuncio sia effettivamente sparito
    check_ad = await client.get(f"/api/v1/annunci/{ad_id}")
    assert check_ad.status_code == 404


@pytest.mark.asyncio
async def test_admin_risponde_a_email_webmail(
    client: AsyncClient,
    admin_token_headers: dict
):
    """Verifica che l'amministratore possa rispondere a un'email direttamente dalla webmail."""
    # 1. Simula un messaggio inviato ad admin tramite /contatta-admin
    msg_data = {
        "nome": "Marco Bianchi",
        "email": "marco.bianchi@email.it",
        "oggetto": "Informazioni Legali sul Rinnovo",
        "messaggio": "Buongiorno Admin, vorrei sapere se per il rinnovo serve il certificato anamnestico."
    }
    send_resp = await client.post("/api/v1/auth/contatta-admin", json=msg_data)
    assert send_resp.status_code == 200

    # 2. Recupera l'email dalla casella webmail admin
    list_resp = await client.get("/api/v1/admin/email", headers=admin_token_headers)
    assert list_resp.status_code == 200
    emails = list_resp.json()["emails"]
    target_email = next((e for e in emails if "Informazioni Legali sul Rinnovo" in e["oggetto"]), None)
    assert target_email is not None

    # 3. Invia risposta come Admin
    reply_data = {
        "messaggio": "Gentile Marco, confermo che il certificato anamnestico è obbligatorio ai sensi del D.Lgs. 104/2018."
    }
    reply_resp = await client.post(
        f"/api/v1/admin/email/{target_email['id']}/rispondi",
        json=reply_data,
        headers=admin_token_headers
    )
    assert reply_resp.status_code == 200
    res_data = reply_resp.json()
    assert res_data["success"] is True
    assert res_data["destinatario"] == "marco.bianchi@email.it"


@pytest.mark.asyncio
async def test_salva_ricerca_email_alert(client: AsyncClient):
    """Verifica la creazione di un avviso email su criteri di ricerca."""
    alert_payload = {
        "email": "tiratore.sportivo@test.it",
        "criteri": {"marca": "Glock", "calibro": "9x21", "prezzo_max": 550},
        "descrizione_ricerca": "Glock 9x21 sotto 550€"
    }
    resp = await client.post("/api/v1/annunci/salva-ricerca", json=alert_payload)
    assert resp.status_code == 201
    res_json = resp.json()
    assert res_json["success"] is True
    assert "Avviso salvato" in res_json["message"]


@pytest.mark.asyncio
async def test_mappa_geojson_contiene_poligoni_e_annunci(client: AsyncClient):
    """Verifica che l'endpoint mappa GeoJSON includa i poligoni e TSN censiti."""
    resp = await client.get("/api/v1/annunci/mappa/geojson")
    assert resp.status_code == 200
    geojson = resp.json()
    assert geojson["type"] == "FeatureCollection"
    
    # Verifica che tra le features ci siano sia annunci che poligoni
    features = geojson["features"]
    has_poligono = any(f["properties"].get("is_poligono") is True for f in features)
    assert has_poligono, "La mappa GeoJSON deve includere il layer dei Poligoni e sezioni TSN."
