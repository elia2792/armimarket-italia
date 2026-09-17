import pytest
from httpx import AsyncClient


@pytest.mark.asyncio
async def test_admin_annunci_list_and_filters(client: AsyncClient, admin_token_headers: dict, private_token_headers: dict):
    # 1. Crea un annuncio come privato
    ad_privato = {
        "titolo": "Glock 17 Gen 5 Privato Test",
        "descrizione": "Pistola in perfette condizioni.",
        "prezzo": 550.0,
        "tipologia_inserzionista": "privato",
        "tipologia_arma": "arma_corta",
        "marca": "Glock",
        "modello": "17 Gen 5",
        "calibro": "9x21",
        "classificazione": "sportiva",
        "condizione": "usato_ottimo",
        "comune_id": 1,
        "email_contatto": "privato@test.it",
    }
    r_privato = await client.post("/api/v1/annunci", json=ad_privato, headers=private_token_headers)
    assert r_privato.status_code == 201
    ad_privato_id = r_privato.json()["id"]

    # 2. Richiesta lista completa da parte dell'admin
    resp = await client.get("/api/v1/admin/annunci", headers=admin_token_headers)
    assert resp.status_code == 200
    data = resp.json()
    assert data["totale"] >= 1
    assert "totale_privati" in data
    assert "totale_armerie" in data
    assert "totale_in_moderazione" in data

    # 3. Filtro per tipologia_inserzionista=privato
    resp_privati = await client.get("/api/v1/admin/annunci?tipologia_inserzionista=privato", headers=admin_token_headers)
    assert resp_privati.status_code == 200
    data_privati = resp_privati.json()
    assert any(a["id"] == ad_privato_id for a in data_privati["annunci"])
    assert all(a["tipologia_inserzionista"] == "privato" for a in data_privati["annunci"])


@pytest.mark.asyncio
async def test_admin_annuncio_detail_and_update(client: AsyncClient, admin_token_headers: dict, private_token_headers: dict):
    # 1. Crea annuncio
    ad_data = {
        "titolo": "Beretta 92FS Originale",
        "descrizione": "Descrizione iniziale.",
        "prezzo": 600.0,
        "tipologia_inserzionista": "privato",
        "tipologia_arma": "arma_corta",
        "marca": "Beretta",
        "modello": "92FS",
        "calibro": "9x21",
        "classificazione": "comune",
        "condizione": "usato_buono",
        "comune_id": 1,
        "email_contatto": "venditore@test.it",
    }
    create_resp = await client.post("/api/v1/annunci", json=ad_data, headers=private_token_headers)
    assert create_resp.status_code == 201
    ad_id = create_resp.json()["id"]

    # 2. Dettaglio annuncio da parte dell'admin
    get_resp = await client.get(f"/api/v1/admin/annunci/{ad_id}", headers=admin_token_headers)
    assert get_resp.status_code == 200
    detail = get_resp.json()
    assert detail["id"] == ad_id
    assert detail["titolo"] == "Beretta 92FS Originale"

    # 3. Modifica dell'annuncio da parte dell'admin (cambio titolo, prezzo, marca, stato)
    update_data = {
        "titolo": "Beretta 92FS Modificata dall'Admin",
        "prezzo": 680.0,
        "descrizione": "Descrizione corretta e revisionata dall'amministrazione.",
        "stato": "pubblicato",
        "marca": "Beretta Gardone",
    }
    put_resp = await client.put(f"/api/v1/admin/annunci/{ad_id}", json=update_data, headers=admin_token_headers)
    assert put_resp.status_code == 200
    updated = put_resp.json()
    assert updated["titolo"] == "Beretta 92FS Modificata dall'Admin"
    assert updated["prezzo"] == 680.0
    assert updated["marca"] == "Beretta Gardone"
    assert updated["stato"] == "pubblicato"


@pytest.mark.asyncio
async def test_admin_annunci_unauthorized(client: AsyncClient, private_token_headers: dict):
    # Un utente con ruolo 'privato' non può accedere alla gestione annunci admin
    resp = await client.get("/api/v1/admin/annunci", headers=private_token_headers)
    assert resp.status_code == 403

    resp_put = await client.put("/api/v1/admin/annunci/1", json={"titolo": "Hacked"}, headers=private_token_headers)
    assert resp_put.status_code == 403

    # Utente non autenticato
    resp_anon = await client.get("/api/v1/admin/annunci")
    assert resp_anon.status_code == 401


@pytest.mark.asyncio
async def test_admin_annuncio_delete(client: AsyncClient, admin_token_headers: dict, private_token_headers: dict):
    # 1. Crea annuncio da cancellare
    ad_data = {
        "titolo": "Annuncio Da Eliminare Admin",
        "descrizione": "Test eliminazione annuncio da parte admin.",
        "prezzo": 300.0,
        "tipologia_inserzionista": "privato",
        "tipologia_arma": "arma_corta",
        "marca": "Tanfoglio",
        "modello": "Force",
        "calibro": "9x21",
        "classificazione": "comune",
        "condizione": "usato_buono",
        "comune_id": 1,
        "email_contatto": "delete@test.it",
    }
    create_resp = await client.post("/api/v1/annunci", json=ad_data, headers=private_token_headers)
    assert create_resp.status_code == 201
    ad_id = create_resp.json()["id"]

    # 2. Admin elimina annuncio
    del_resp = await client.delete(f"/api/v1/admin/annunci/{ad_id}", headers=admin_token_headers)
    assert del_resp.status_code == 200
    assert del_resp.json()["status"] == "success"

    # 3. Verifica che non sia più presente
    get_resp = await client.get(f"/api/v1/admin/annunci/{ad_id}", headers=admin_token_headers)
    assert get_resp.status_code == 404
