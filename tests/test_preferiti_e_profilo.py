import pytest
from httpx import AsyncClient
from sqlalchemy import select


@pytest.mark.asyncio
async def test_preferiti_workflow(client: AsyncClient, private_token_headers: dict):
    # 1. Crea un annuncio di partenza
    new_ad = {
        "titolo": "Beretta 92FS Test Preferiti 9x21",
        "descrizione": "Pistola semiautomatica in condizioni da vetrina usata pochissimo.",
        "prezzo": 680.0,
        "tipologia_inserzionista": "privato",
        "tipologia_arma": "arma_corta",
        "marca": "Beretta",
        "modello": "92FS",
        "calibro": "9x21",
        "classificazione": "comune",
        "condizione": "usato_ottimo",
        "comune_id": 1,
        "email_contatto": "privato.test@armimarket.it"
    }
    create_resp = await client.post("/api/v1/annunci", json=new_ad, headers=private_token_headers)
    assert create_resp.status_code == 201
    ad_id = create_resp.json()["id"]

    # 2. Aggiungi annuncio ai preferiti
    resp_add = await client.post(f"/api/v1/preferiti/{ad_id}", headers=private_token_headers)
    assert resp_add.status_code == 201

    # 3. Verifica presenza negli ID preferiti
    resp_ids = await client.get("/api/v1/preferiti/ids", headers=private_token_headers)
    assert resp_ids.status_code == 200
    fav_ids = resp_ids.json()
    assert ad_id in fav_ids

    # 4. Verifica elenco completo preferiti
    resp_list = await client.get("/api/v1/preferiti", headers=private_token_headers)
    assert resp_list.status_code == 200
    fav_ads = resp_list.json()
    assert any(a["id"] == ad_id for a in fav_ads)

    # 5. Rimuovi dai preferiti
    resp_del = await client.delete(f"/api/v1/preferiti/{ad_id}", headers=private_token_headers)
    assert resp_del.status_code == 200

    # 6. Verifica che non sia più presente
    resp_ids_after = await client.get("/api/v1/preferiti/ids", headers=private_token_headers)
    assert resp_ids_after.status_code == 200
    assert ad_id not in resp_ids_after.json()


@pytest.mark.asyncio
async def test_gestione_venduto_e_rimozione(client: AsyncClient, private_token_headers: dict):
    # 1. Crea un annuncio di test
    new_ad = {
        "titolo": "Carabina Test Vendita 308 Win",
        "descrizione": "Descrizione accurata della carabina da caccia in condizioni perfette.",
        "prezzo": 1250.0,
        "tipologia_inserzionista": "privato",
        "tipologia_arma": "arma_lunga_rigata",
        "marca": "Tikka",
        "modello": "T3x",
        "calibro": ".308 Win",
        "classificazione": "caccia",
        "condizione": "usato_ottimo",
        "comune_id": 1,
        "email_contatto": "privato.test@armimarket.it"
    }
    create_resp = await client.post("/api/v1/annunci", json=new_ad, headers=private_token_headers)
    assert create_resp.status_code == 201
    created = create_resp.json()
    ad_id = created["id"]

    # 2. Recupera i miei annunci
    my_ads_resp = await client.get("/api/v1/annunci/utente/miei", headers=private_token_headers)
    assert my_ads_resp.status_code == 200
    my_ads = my_ads_resp.json()
    assert any(a["id"] == ad_id for a in my_ads)

    # 3. Segna come venduto
    sold_resp = await client.patch(f"/api/v1/annunci/{ad_id}/stato?nuovo_stato=venduto", headers=private_token_headers)
    assert sold_resp.status_code == 200
    assert sold_resp.json()["stato"] == "venduto"

    # 4. Rimuovi definitivamente l'annuncio venduto
    del_resp = await client.delete(f"/api/v1/annunci/{ad_id}", headers=private_token_headers)
    assert del_resp.status_code == 200

    # 5. Verifica che non esista più nei miei annunci
    my_ads_after = await client.get("/api/v1/annunci/utente/miei", headers=private_token_headers)
    assert my_ads_after.status_code == 200
    assert not any(a["id"] == ad_id for a in my_ads_after.json())


@pytest.mark.asyncio
async def test_email_duplicata_bloccata(client: AsyncClient):
    # 1. Tenta di registrare un account con email già presente
    existing_user_payload = {
        "email": "privato.test@armimarket.it",  # Creata nel fixture di test
        "password": "PasswordNuova123!",
        "nome": "Clone",
        "cognome": "Test",
        "ruolo": "privato",
        "comune_id": 1
    }
    resp = await client.post("/api/v1/auth/register", json=existing_user_payload)
    assert resp.status_code == 400
    assert "già registrato" in resp.json()["detail"].lower()


@pytest.mark.asyncio
async def test_recupero_e_reimpostazione_password(client: AsyncClient, db_session):
    from app.models.email_log import EmailLog
    user_email = "privato.test@armimarket.it"

    # 1. Richiesta di recupero password: email esistente
    req_resp = await client.post("/api/v1/auth/forgot-password", json={"email": user_email})
    assert req_resp.status_code == 200
    data = req_resp.json()
    assert data.get("reset_link") is None, "Il link di reset NON deve mai comparire nella risposta JSON (anti-leak)"
    assert "istruzioni" in data["message"].lower()

    # 2. Richiesta con email inesistente: deve restituire ESATTAMENTE la stessa risposta 200 (anti user-enumeration)
    fake_resp = await client.post("/api/v1/auth/forgot-password", json={"email": "inesistente@test.it"})
    assert fake_resp.status_code == 200
    assert fake_resp.json()["message"] == data["message"], "La risposta deve essere uniforme per email esistente e inesistente"

    # 3. Recupero del token sicuro dall'email registrata internamente
    stmt = (
        select(EmailLog)
        .where(EmailLog.destinatario == user_email, EmailLog.tipologia == "recupero_password")
        .order_by(EmailLog.id.desc())
    )
    email_entry = (await db_session.execute(stmt)).scalars().first()
    assert email_entry is not None
    assert "token=" in email_entry.link_azione
    token = email_entry.link_azione.split("token=")[1]

    # 4. Reimposta la password
    new_password = "NuovaPasswordSicura2026!"
    reset_resp = await client.post("/api/v1/auth/reset-password", json={
        "token": token,
        "nuova_password": new_password
    })
    assert reset_resp.status_code == 200
    assert "successo" in reset_resp.json()["message"].lower()

    # 5. Verifica che il token sia strettamente monouso (secondo tentativo con stesso token deve fallire con 400)
    reuse_resp = await client.post("/api/v1/auth/reset-password", json={
        "token": token,
        "nuova_password": "TentativoRiutilizzo123!"
    })
    assert reuse_resp.status_code == 400
    assert "non valido o è scaduto" in reuse_resp.json()["detail"].lower()

    # 6. Verifica che il login funzioni con la NUOVA password
    login_resp = await client.post("/api/v1/auth/login", json={
        "email": user_email,
        "password": new_password
    })
    assert login_resp.status_code == 200
    assert "access_token" in login_resp.json()


@pytest.mark.asyncio
async def test_nickname_registrazione_univocita_e_aggiornamento(client: AsyncClient, private_token_headers: dict):
    # 1. Registra un utente con nickname personalizzato
    user_payload = {
        "email": "cecchino@armimarket.it",
        "password": "PasswordTest123!",
        "nickname": "CecchinoScelto",
        "nome": "Giovanni",
        "cognome": "Bianchi",
        "ruolo": "privato",
        "comune_id": 1
    }
    reg_resp = await client.post("/api/v1/auth/register", json=user_payload)
    assert reg_resp.status_code == 201
    user_data = reg_resp.json()
    assert user_data["nickname"] == "CecchinoScelto"
    assert user_data["display_name"] == "CecchinoScelto"

    # 2. Tenta di registrare un altro utente con lo STESSO nickname (case-insensitive)
    conflict_payload = {
        "email": "altro.cecchino@armimarket.it",
        "password": "PasswordTest123!",
        "nickname": "cecchinoscelto",
        "nome": "Altro",
        "cognome": "Verdi",
        "ruolo": "privato",
        "comune_id": 1
    }
    conflict_resp = await client.post("/api/v1/auth/register", json=conflict_payload)
    assert conflict_resp.status_code == 400
    assert "già utilizzato" in conflict_resp.json()["detail"].lower()

    # 3. Aggiorna il nickname dell'utente autenticato via PUT /auth/me
    update_resp = await client.put(
        "/api/v1/auth/me",
        json={"nickname": "NuovoNickTest"},
        headers=private_token_headers
    )
    assert update_resp.status_code == 200
    updated_data = update_resp.json()
    assert updated_data["nickname"] == "NuovoNickTest"
    assert updated_data["display_name"] == "NuovoNickTest"

    # 4. Tenta di cambiare il proprio nickname con quello già preso da CecchinoScelto
    dup_update = await client.put(
        "/api/v1/auth/me",
        json={"nickname": "CecchinoScelto"},
        headers=private_token_headers
    )
    assert dup_update.status_code == 400
    assert "già utilizzato" in dup_update.json()["detail"].lower()

