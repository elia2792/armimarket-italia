import pytest
from httpx import AsyncClient


@pytest.mark.asyncio
async def test_utente_scrive_ad_admin_senza_vedere_email(client: AsyncClient, admin_token_headers: dict):
    # 1. Qualsiasi utente/visitatore invia un messaggio ad Admin
    msg_payload = {
        "nome": "Marco Cacciatore",
        "email": "marco.cacciatore@email.it",
        "oggetto": "Richiesta integrazione calibro",
        "messaggio": "Buongiorno Admin, vorrei chiedere se possibile aggiungere il calibro 6.5 Creedmoor nei filtri rapidi."
    }
    resp = await client.post("/api/v1/auth/contatta-admin", json=msg_payload)
    assert resp.status_code == 200
    assert resp.json()["success"] is True
    assert "inviato con successo ad Admin" in resp.json()["message"]

    # 2. L admin trova il messaggio nella casella postale interna
    resp_mail = await client.get("/api/v1/admin/email?search=Creedmoor", headers=admin_token_headers)
    assert resp_mail.status_code == 200
    data = resp_mail.json()
    assert data["totale"] >= 1
    found = any(
        "Marco Cacciatore" in e["corpo_testo"] and "6.5 Creedmoor" in e["corpo_testo"]
        for e in data["emails"]
    )
    assert found, "Il messaggio per Admin deve comparire nella webmail dell admin"
