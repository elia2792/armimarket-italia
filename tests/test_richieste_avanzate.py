import io
import pytest
from httpx import AsyncClient
from PIL import Image

from app.services.scraper.directory import ARMERIE_TARGETS


@pytest.mark.asyncio
async def test_logout_endpoints(client: AsyncClient):
    """
    Verifica che sia GET /logout che POST /api/v1/auth/logout
    cancellino i cookie di sessione e consentano un'uscita pulita.
    """
    # 1. GET /logout (usato dai link HTML e click sui bottoni di uscita)
    resp_get = await client.get("/logout", follow_redirects=False)
    assert resp_get.status_code == 303
    assert resp_get.headers["location"] == "/"
    # Verifica rimozione cookie
    set_cookie = resp_get.headers.get("set-cookie", "")
    assert "armimarket_token" in set_cookie
    assert "Max-Age=0" in set_cookie or "expires=" in set_cookie.lower()

    # 2. POST /api/v1/auth/logout (usato dalle chiamate API/fetch)
    resp_post = await client.post("/api/v1/auth/logout")
    assert resp_post.status_code == 200
    assert resp_post.json().get("success") is True
    set_cookie_post = resp_post.headers.get("set-cookie", "")
    assert "armimarket_token" in set_cookie_post


@pytest.mark.asyncio
async def test_admin_utenti_non_mostra_armerie_scraping(client: AsyncClient, admin_token_headers: dict):
    """
    Verifica che il pannello admin /api/v1/admin/utenti elenchi solo gli account realmente registrati
    e NON contenga le armerie della directory di scraping o account bot di sistema.
    """
    resp = await client.get("/api/v1/admin/utenti?per_pagina=100", headers=admin_token_headers)
    assert resp.status_code == 200
    utenti = resp.json()

    user_emails = [u["email"].lower() for u in utenti]
    target_emails = [a["email"].lower() for a in ARMERIE_TARGETS]

    # Nessuna armeria della directory scraping deve comparire tra gli utenti registrati
    for t_email in target_emails:
        assert t_email not in user_emails, f"L'armeria di scraping {t_email} non dovrebbe comparire negli utenti!"

    # Il bot tecnico non deve comparire negli utenti registrati
    assert "indicizzatore.bot@armimarket.it" not in user_emails


@pytest.mark.asyncio
async def test_bacheca_paginazione_50_annunci(client: AsyncClient):
    """
    Verifica che la bacheca annunci sia configurata per mostrare fino a 50 annunci per pagina.
    """
    # 1. API endpoint /api/v1/annunci con default 50 elementi per pagina
    resp = await client.get("/api/v1/annunci")
    assert resp.status_code == 200
    data = resp.json()
    assert data["elementi_per_pagina"] == 50
    assert len(data["risultati"]) <= 50

    # 2. HTML View / (homepage)
    resp_html = await client.get("/?pagina=1")
    assert resp_html.status_code == 200
    # In assenza di annunci pubblicati nel DB vuoto del test, o in presenza di annunci, la vista risponde 200
    assert "ArmiMarket Italia" in resp_html.text


@pytest.mark.asyncio
async def test_upload_diretto_fotografie(client: AsyncClient, private_token_headers: dict):
    """
    Verifica l'upload diretto di fotografie da parte di un utente autenticato:
    - Immagine JPEG valida generata in memoria
    - Risposta 200 con array 'urls' contenente il path relativo /static/uploads/annunci/...
    - Rifiuto di file non validi o script camuffati
    """
    # Creazione immagine di test in memoria
    img_byte_arr = io.BytesIO()
    img = Image.new("RGB", (640, 480), color=(180, 150, 100))
    img.save(img_byte_arr, format="JPEG")
    img_bytes = img_byte_arr.getvalue()

    files = [
        ("files", ("foto_arma_test.jpg", img_bytes, "image/jpeg"))
    ]

    resp = await client.post("/api/v1/annunci/upload-foto", files=files, headers=private_token_headers)
    assert resp.status_code == 200, f"Errore upload foto: {resp.text}"
    data = resp.json()
    assert data["success"] is True
    assert len(data["urls"]) == 1
    assert data["urls"][0].startswith("/static/uploads/annunci/ad_")
    assert data["urls"][0].endswith(".jpg")

    # Test rifiuto script mascherato come immagine
    fake_files = [
        ("files", ("exploit.jpg", b"<?php echo 'malicious'; ?>", "image/jpeg"))
    ]
    resp_fake = await client.post("/api/v1/annunci/upload-foto", files=fake_files, headers=private_token_headers)
    assert resp_fake.status_code in (400, 415)
