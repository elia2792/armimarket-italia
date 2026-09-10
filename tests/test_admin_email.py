import pytest
from httpx import AsyncClient


@pytest.mark.asyncio
async def test_recupero_password_crea_email_log(client: AsyncClient, admin_token_headers: dict):
    # 1. Richiedi recupero password per l admin di test presente nei fixture
    req_data = {"email": "admin.test@armimarket.it"}
    resp = await client.post("/api/v1/auth/forgot-password", json=req_data)
    assert resp.status_code == 200
    res_json = resp.json()
    assert "inviato un'email" in res_json["message"] or "Richiesta registrata" in res_json["message"]

    # 2. Consultazione casella postale da parte dell admin
    resp_mail = await client.get("/api/v1/admin/email", headers=admin_token_headers)
    assert resp_mail.status_code == 200
    mail_data = resp_mail.json()
    assert mail_data["totale"] >= 1
    assert mail_data["conteggio_recupero"] >= 1
    
    # 3. Verifica presenza dell email di recupero con relativo link di azione
    found = any(
        e["destinatario"] == "admin.test@armimarket.it" and e["tipologia"] == "recupero_password"
        for e in mail_data["emails"]
    )
    assert found, "L email di recupero password deve comparire nel log della casella postale admin"

    # 4. Verifica dettaglio della singola email
    first_mail = mail_data["emails"][0]
    resp_detail = await client.get(f"/api/v1/admin/email/{first_mail['id']}", headers=admin_token_headers)
    assert resp_detail.status_code == 200
    detail = resp_detail.json()
    assert detail["destinatario"] == "admin.test@armimarket.it"
    assert "/reimposta-password?token=" in detail["link_azione"]
    assert "Reimposta la tua Password" in detail["corpo_html"]


@pytest.mark.asyncio
async def test_casella_email_protetta_da_non_admin(client: AsyncClient, private_token_headers: dict):
    # Un utente con ruolo privato NON deve poter consultare la casella email
    resp = await client.get("/api/v1/admin/email", headers=private_token_headers)
    assert resp.status_code == 403


@pytest.mark.asyncio
async def test_richiesta_contatto_registra_email_log(client: AsyncClient, private_token_headers: dict, admin_token_headers: dict):
    # 1. Crea un annuncio di prova con email specifica e tipologia valida (canna_liscia)
    new_ad = {
        "titolo": "Benelli Raffaello Test Posta",
        "descrizione": "Fucile semiautomatico calibro 12.",
        "prezzo": 900.0,
        "tipologia_inserzionista": "privato",
        "tipologia_arma": "canna_liscia",
        "marca": "Benelli",
        "modello": "Raffaello",
        "calibro": "12",
        "classificazione": "caccia",
        "condizione": "usato_ottimo",
        "comune_id": 1,
        "email_contatto": "armeria.destinataria@armimarket.it"
    }
    create_resp = await client.post("/api/v1/annunci", json=new_ad, headers=private_token_headers)
    assert create_resp.status_code == 201
    ad_id = create_resp.json()["id"]

    # Approva l annuncio per renderlo PUBBLICATO
    resp_approve = await client.post(f"/api/v1/admin/moderazione/{ad_id}/approva", json={}, headers=admin_token_headers)
    assert resp_approve.status_code == 200

    # 2. Invia modulo di contatto per l annuncio

    contact_data = {
        "nome_mittente": "Giuseppe Garibaldi",
        "email_mittente": "giuseppe@risorgimento.it",
        "titolo_di_polizia": "Porto d'Armi Uso Caccia",
        "messaggio": "Salve, vorrei visionare il Benelli Raffaello di persona.",
        "accetto_disclaimer_legale": True
    }
    resp_contact = await client.post(f"/api/v1/annunci/{ad_id}/contatta", json=contact_data)
    assert resp_contact.status_code == 200

    # 3. L admin deve trovare la notifica di contatto nella casella postale
    resp_mail = await client.get("/api/v1/admin/email?tipologia=richiesta_contatto", headers=admin_token_headers)
    assert resp_mail.status_code == 200
    mail_data = resp_mail.json()
    assert mail_data["totale"] >= 1
    
    found = any(
        e["destinatario"] == "armeria.destinataria@armimarket.it" and e["tipologia"] == "richiesta_contatto"
        for e in mail_data["emails"]
    )
    assert found, "La richiesta di contatto deve comparire nel log della casella postale"


@pytest.mark.asyncio
async def test_invio_email_test_admin(client: AsyncClient, admin_token_headers: dict):
    # Test invio email di prova
    resp = await client.post("/api/v1/admin/email/test", json={"destinatario": "verifica@collaudo.it"}, headers=admin_token_headers)
    assert resp.status_code == 200
    assert resp.json()["success"] is True

    # Verifica presenza nel log
    resp_list = await client.get("/api/v1/admin/email?search=verifica@collaudo.it", headers=admin_token_headers)
    assert resp_list.status_code == 200
    assert resp_list.json()["totale"] >= 1
