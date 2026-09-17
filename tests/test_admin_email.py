import pytest
from httpx import AsyncClient


@pytest.mark.asyncio
async def test_recupero_password_crea_email_log(client: AsyncClient, admin_token_headers: dict):
    # 1. Richiedi recupero password per l admin di test presente nei fixture
    req_data = {"email": "admin.test@armimarket.it"}
    resp = await client.post("/api/v1/auth/forgot-password", json=req_data)
    assert resp.status_code == 200
    res_json = resp.json()
    assert "istruzioni" in res_json["message"].lower()
    assert res_json.get("reset_link") is None, "Nessun link di reset deve comparire nel JSON"

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


@pytest.mark.asyncio
async def test_conversazioni_email_raggruppamento_e_risposta(client: AsyncClient, admin_token_headers: dict):
    user_target = "cacciatore.lombardo@test.it"

    # Invia due email di test allo stesso utente
    await client.post("/api/v1/admin/email/test", json={"destinatario": user_target}, headers=admin_token_headers)
    await client.post("/api/v1/admin/email/test", json={"destinatario": user_target}, headers=admin_token_headers)

    # 1. Recupera lista conversazioni: deve esserci una singola conversazione per l'utente con 2 messaggi
    resp_conv = await client.get("/api/v1/admin/email/conversazioni", headers=admin_token_headers)
    assert resp_conv.status_code == 200
    data = resp_conv.json()
    assert data["totale"] >= 1

    user_conv = next((c for c in data["conversazioni"] if c["user_email"] == user_target), None)
    assert user_conv is not None, "La conversazione per l'utente deve essere presente"
    assert user_conv["totale_messaggi"] >= 2

    # 2. Recupera il dettaglio cronologico del thread
    resp_detail = await client.get(f"/api/v1/admin/email/conversazioni/{user_target}", headers=admin_token_headers)
    assert resp_detail.status_code == 200
    detail = resp_detail.json()
    assert detail["user_email"] == user_target
    assert len(detail["messaggi"]) >= 2

    # 3. Rispondi alla conversazione
    reply_resp = await client.post(
        f"/api/v1/admin/email/conversazioni/{user_target}/rispondi",
        json={"messaggio": "Risposta di chiarimento dall'amministratore."},
        headers=admin_token_headers
    )
    assert reply_resp.status_code == 200
    assert reply_resp.json()["success"] is True

    # 4. Verifica che il thread ora contenga il nuovo messaggio
    resp_detail2 = await client.get(f"/api/v1/admin/email/conversazioni/{user_target}", headers=admin_token_headers)
    assert resp_detail2.status_code == 200
    assert len(resp_detail2.json()["messaggi"]) >= 3


@pytest.mark.asyncio
async def test_gestione_errori_invio_e_risoluzione(client: AsyncClient, admin_token_headers: dict):
    # Esegui risoluzione globale degli errori
    resp_res = await client.post("/api/v1/admin/email/errori/risolvi-tutti", headers=admin_token_headers)
    assert resp_res.status_code == 200
    assert resp_res.json()["success"] is True

    # Verifica che le conversazioni non abbiano più errori pendenti
    resp_conv = await client.get("/api/v1/admin/email/conversazioni", headers=admin_token_headers)
    assert resp_conv.status_code == 200
    assert resp_conv.json()["conteggio_errori"] == 0


@pytest.mark.asyncio
async def test_invio_email_brevo_http(monkeypatch):
    from app.core.config import settings
    from app.services.email_service import EmailService
    import httpx

    monkeypatch.setattr(settings, "BREVO_API_KEY", "xkeysib-test-key-123")
    monkeypatch.setattr(settings, "RESEND_API_KEY", None)

    called_url = []

    async def mock_post(self, url, *args, **kwargs):
        called_url.append(str(url))
        return httpx.Response(201, json={"messageId": "brevo-msg-123"})

    monkeypatch.setattr(httpx.AsyncClient, "post", mock_post)

    success, err = await EmailService._send_http_email(
        to_email="utente@destinatario.it",
        subject="Oggetto Test",
        html_body="<p>Test</p>",
        text_body="Test"
    )
    assert success is True
    assert err is None
    assert any("api.brevo.com" in u for u in called_url)


@pytest.mark.asyncio
async def test_invio_email_resend_http(monkeypatch):
    from app.core.config import settings
    from app.services.email_service import EmailService
    import httpx

    monkeypatch.setattr(settings, "BREVO_API_KEY", None)
    monkeypatch.setattr(settings, "RESEND_API_KEY", "re_test_key_123")

    called_url = []

    async def mock_post(self, url, *args, **kwargs):
        called_url.append(str(url))
        return httpx.Response(200, json={"id": "resend-msg-123"})

    monkeypatch.setattr(httpx.AsyncClient, "post", mock_post)

    success, err = await EmailService._send_http_email(
        to_email="utente@destinatario.it",
        subject="Oggetto Test",
        html_body="<p>Test</p>",
        text_body="Test"
    )
    assert success is True
    assert err is None
    assert any("api.resend.com" in u for u in called_url)


@pytest.mark.asyncio
async def test_invio_email_smtp2go_http(monkeypatch):
    from app.core.config import settings
    from app.services.email_service import EmailService
    import httpx

    monkeypatch.setattr(settings, "BREVO_API_KEY", None)
    monkeypatch.setattr(settings, "RESEND_API_KEY", None)
    monkeypatch.setattr(settings, "SMTP2GO_API_KEY", "api-smtp2go-test-key-123")

    called_url = []

    async def mock_post(self, url, *args, **kwargs):
        called_url.append(str(url))
        return httpx.Response(200, json={
            "request_id": "req-123",
            "data": {
                "succeeded": 1,
                "failed": 0,
                "failures": []
            }
        })

    monkeypatch.setattr(httpx.AsyncClient, "post", mock_post)

    success, err = await EmailService._send_http_email(
        to_email="utente@destinatario.it",
        subject="Oggetto Test SMTP2GO",
        html_body="<p>Test</p>",
        text_body="Test"
    )
    assert success is True
    assert err is None
    assert any("api.smtp2go.com" in u for u in called_url)


