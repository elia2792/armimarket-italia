import io
import pytest
from httpx import AsyncClient
from PIL import Image
from sqlalchemy import select

from app.core.rate_limit import default_rate_limiter
from app.models.annuncio import Annuncio, ClassificazioneArma, CondizioneArma, StatoAnnuncio, TipologiaArma, TipologiaInserzionista
from app.models.user import RuoloUtente, User


@pytest.mark.asyncio
async def test_priorita1_privacy_mappa_nessun_privato_esposto(client: AsyncClient, db_session, private_token_headers):
    """
    PRIORITÀ 1 - PRIVACY MAPPA
    Verifica che il GeoJSON pubblico (/api/v1/annunci/mappa/geojson) NON esponga MAI:
    - nome e cognome di privati;
    - annunci o posizioni di venditori privati.
    Devono comparire solo armerie autorizzate e poligoni/TSN.
    """
    # 1. Recupera utente privato e armeria esistenti
    privato = (await db_session.execute(select(User).where(User.ruolo == RuoloUtente.PRIVATO))).scalar_one()
    armeria = (await db_session.execute(select(User).where(User.ruolo == RuoloUtente.ARMERIA))).scalar_one()

    # 2. Crea annuncio di un privato approvato/pubblicato
    ad_privato = Annuncio(
        titolo="Pistola Beretta 98FS Privato",
        slug="pistola-beretta-98fs-privato-unique1",
        descrizione="Ottime condizioni",
        prezzo=450.0,
        stato=StatoAnnuncio.PUBBLICATO,
        tipologia_inserzionista=TipologiaInserzionista.PRIVATO,
        tipologia_arma=TipologiaArma.ARMA_CORTA,
        classificazione=ClassificazioneArma.COMUNE,
        condizione=CondizioneArma.USATO_OTTIMO,
        marca="Beretta",
        modello="98FS",
        calibro="9x21",
        comune_id=1,
        utente_id=privato.id,
        email_contatto=privato.email
    )
    # 3. Crea annuncio di un'armeria commerciale
    ad_armeria = Annuncio(
        titolo="Carabina Winchester 70 Armeria",
        slug="carabina-winchester-70-armeria-unique1",
        descrizione="Nuova da vetrina",
        prezzo=1200.0,
        stato=StatoAnnuncio.PUBBLICATO,
        tipologia_inserzionista=TipologiaInserzionista.ARMERIA,
        tipologia_arma=TipologiaArma.ARMA_LUNGA_RIGATA,
        classificazione=ClassificazioneArma.CACCIA,
        condizione=CondizioneArma.NUOVO,
        marca="Winchester",
        modello="70",
        calibro=".308 Win",
        comune_id=1,
        utente_id=armeria.id,
        email_contatto=armeria.email
    )
    db_session.add_all([ad_privato, ad_armeria])
    await db_session.commit()

    # 4. Richiesta pubblica della mappa GeoJSON
    resp = await client.get("/api/v1/annunci/mappa/geojson")
    assert resp.status_code == 200
    data = resp.json()
    assert data["type"] == "FeatureCollection"

    features = data["features"]
    # Verifica che tra tutte le feature restituite non ci sia alcun riferimento all'annuncio del privato
    for f in features:
        props = f["properties"]
        tipo = props.get("tipo")
        titolo = props.get("titolo", "")
        # Nessun annuncio privato deve essere presente
        assert "Privato" not in titolo, f"Trovato annuncio privato nella mappa: {titolo}"
        assert props.get("tipologia_inserzionista") != "privato"
        assert props.get("tipologia_inserzionista") in ["armeria", "poligono"]

    # Verifica che compaia l'annuncio dell'armeria
    titoli = [f["properties"].get("titolo", "") for f in features]
    assert any("Carabina Winchester 70 Armeria" in t for t in titoli)


@pytest.mark.asyncio
async def test_priorita2_upload_avatar_sicurezza(client: AsyncClient, private_token_headers):
    """
    PRIORITÀ 2 - UPLOAD AVATAR
    Verifica:
    - Accettazione e ricodifica JPEG, PNG, WebP validi.
    - Rifiuto categorico magic bytes non conformi (SVG, file HTML mascherato, PHP).
    - Rifiuto payload > 3 MB.
    - Salvataggio server-side protetto senza path traversal.
    """
    default_rate_limiter.clear()

    # Helper per creare immagini reali con Pillow
    def make_image_bytes(fmt: str, color="red") -> bytes:
        img = Image.new("RGB", (64, 64), color=color)
        buf = io.BytesIO()
        img.save(buf, format=fmt)
        return buf.getvalue()

    # A) Upload JPEG valido
    jpg_bytes = make_image_bytes("JPEG", "blue")
    resp_jpg = await client.post(
        "/api/v1/auth/me/foto",
        files={"file": ("test_avatar.jpg", jpg_bytes, "image/jpeg")},
        headers=private_token_headers
    )
    assert resp_jpg.status_code == 200
    user_data = resp_jpg.json()
    assert user_data["foto_profilo"] is not None
    assert user_data["foto_profilo"].startswith("/static/uploads/avatars/avatar_")
    assert user_data["foto_profilo"].endswith(".jpg")

    default_rate_limiter.clear()

    # B) Upload PNG valido
    png_bytes = make_image_bytes("PNG", "green")
    resp_png = await client.post(
        "/api/v1/auth/me/foto",
        files={"file": ("avatar.png", png_bytes, "image/png")},
        headers=private_token_headers
    )
    assert resp_png.status_code == 200
    assert resp_png.json()["foto_profilo"].endswith(".png")

    default_rate_limiter.clear()

    # C) Upload WebP valido
    webp_bytes = make_image_bytes("WEBP", "yellow")
    resp_webp = await client.post(
        "/api/v1/auth/me/foto",
        files={"file": ("avatar.webp", webp_bytes, "image/webp")},
        headers=private_token_headers
    )
    assert resp_webp.status_code == 200
    assert resp_webp.json()["foto_profilo"].endswith(".webp")

    default_rate_limiter.clear()

    # D) Rifiuto SVG mascherato da .jpg
    fake_svg = b"<?xml version='1.0'?><svg xmlns='http://www.w3.org/2000/svg'><script>alert('XSS')</script></svg>"
    resp_svg = await client.post(
        "/api/v1/auth/me/foto",
        files={"file": ("malicious.jpg", fake_svg, "image/jpeg")},
        headers=private_token_headers
    )
    assert resp_svg.status_code in [400, 415]

    default_rate_limiter.clear()

    # E) Rifiuto HTML mascherato da .png
    fake_html = b"<!DOCTYPE html><html><body><script>alert(1)</script></body></html>"
    resp_html = await client.post(
        "/api/v1/auth/me/foto",
        files={"file": ("exploit.png", fake_html, "image/png")},
        headers=private_token_headers
    )
    assert resp_html.status_code in [400, 415]

    default_rate_limiter.clear()

    # F) Rifiuto file superiore a 3 MB
    oversized = b"\xff\xd8\xff" + b"A" * (3 * 1024 * 1024 + 500)
    resp_oversized = await client.post(
        "/api/v1/auth/me/foto",
        files={"file": ("large.jpg", oversized, "image/jpeg")},
        headers=private_token_headers
    )
    assert resp_oversized.status_code in [400, 413]

    default_rate_limiter.clear()

    # G) Tentativo Path Traversal nel filename del client
    traversal_bytes = make_image_bytes("JPEG", "purple")
    resp_traversal = await client.post(
        "/api/v1/auth/me/foto",
        files={"file": ("../../../../etc/passwd.jpg", traversal_bytes, "image/jpeg")},
        headers=private_token_headers
    )
    assert resp_traversal.status_code == 200
    # Il server non usa il filename malevolo ma genera avatar_<id>_<uuid>.jpg
    saved_path = resp_traversal.json()["foto_profilo"]
    assert ".." not in saved_path
    assert saved_path.startswith("/static/uploads/avatars/avatar_")


@pytest.mark.asyncio
async def test_priorita4_cors_restrittivo(client: AsyncClient):
    """
    PRIORITÀ 4 - CORS RESTRITTIVO
    Verifica che il server non restituisca allow-origin '*' con credenziali abilitate.
    """
    # Invio richiesta con Origin localhost
    resp = await client.get("/health", headers={"Origin": "http://localhost:8000"})
    assert resp.status_code == 200
    allow_origin = resp.headers.get("access-control-allow-origin")
    assert allow_origin != "*"
    assert allow_origin in ["http://localhost:8000", "http://127.0.0.1:8000"]
    assert resp.headers.get("access-control-allow-credentials") == "true"


@pytest.mark.asyncio
async def test_priorita5_security_headers_and_csp(client: AsyncClient):
    """
    PRIORITÀ 5 - SECURITY HEADERS & CSP
    Verifica la presenza degli header difensivi:
    - X-Content-Type-Options: nosniff
    - X-Frame-Options: DENY
    - Referrer-Policy: strict-origin-when-cross-origin
    - Permissions-Policy
    - Content-Security-Policy valida e restrittiva
    """
    resp = await client.get("/health")
    assert resp.status_code == 200

    headers = resp.headers
    assert headers.get("x-content-type-options") == "nosniff"
    assert headers.get("x-frame-options") == "DENY"
    assert headers.get("referrer-policy") == "strict-origin-when-cross-origin"
    assert "geolocation" in headers.get("permissions-policy", "")

    csp = headers.get("content-security-policy", "")
    assert "default-src 'self'" in csp
    assert "frame-ancestors 'none'" in csp
    assert "https://unpkg.com" in csp
    assert "https://cdn.tailwindcss.com" not in csp
    script_directive = [d for d in csp.split(";") if "script-src" in d][0]
    assert "'unsafe-inline'" not in script_directive


@pytest.mark.asyncio
async def test_priorita6_password_reset_anti_enumeration_e_monouso(client: AsyncClient, db_session):
    """
    PRIORITÀ 6 - PASSWORD RESET HARDENING
    Verifica:
    - Risposta identica sia per email registrata che inesistente (anti-user enumeration).
    - Nessun token o link restituito nella risposta JSON.
    - Token monouso: dopo il primo utilizzo, qualsiasi secondo tentativo viene rigettato.
    """
    default_rate_limiter.clear()

    # 1. Forgot password con email inesistente
    resp_fake = await client.post(
        "/api/v1/auth/forgot-password",
        json={"email": "non_esisto_mai_9999@dominio.it"}
    )
    assert resp_fake.status_code == 200
    data_fake = resp_fake.json()
    assert data_fake["reset_link"] is None

    default_rate_limiter.clear()

    # 2. Forgot password con email esistente
    resp_real = await client.post(
        "/api/v1/auth/forgot-password",
        json={"email": "privato.test@armimarket.it"}
    )
    assert resp_real.status_code == 200
    data_real = resp_real.json()
    assert data_real["reset_link"] is None
    # Entrambe le risposte devono avere lo stesso messaggio generico
    assert data_fake["message"] == data_real["message"]

    # 3. Recupera il token generato dal database
    from app.models.password_reset import PasswordResetToken
    stmt = select(PasswordResetToken).order_by(PasswordResetToken.id.desc()).limit(1)
    reset_entry = (await db_session.execute(stmt)).scalar_one_or_none()
    assert reset_entry is not None
    assert reset_entry.used is False

    # 4. Creiamo un token simulato e ne calcoliamo l'hash
    raw_test_token, hash_test_token = PasswordResetToken.generate_token()
    reset_test = PasswordResetToken(
        user_id=2,  # privato
        token_hash=hash_test_token,
        expires_at=reset_entry.expires_at,
        used=False
    )
    db_session.add(reset_test)
    await db_session.commit()

    default_rate_limiter.clear()

    # 5. Primo utilizzo del token -> Successo 200
    resp_reset1 = await client.post(
        "/api/v1/auth/reset-password",
        json={"token": raw_test_token, "nuova_password": "NuovaPasswordSicura2026!"}
    )
    assert resp_reset1.status_code == 200

    # 6. Secondo utilizzo dello stesso token -> Errore 400 (token già consumato)
    resp_reset2 = await client.post(
        "/api/v1/auth/reset-password",
        json={"token": raw_test_token, "nuova_password": "AltraPassword2026!"}
    )
    assert resp_reset2.status_code == 400
    assert "non valido" in resp_reset2.json()["detail"].lower() or "scaduto" in resp_reset2.json()["detail"].lower()


@pytest.mark.asyncio
async def test_priorita7_rate_limiting_sliding_window(client: AsyncClient):
    """
    PRIORITÀ 7 - RATE LIMITING SERVER-SIDE
    Verifica che il superamento della soglia (es. 5 tentativi di login) blocchi
    le richieste successive con HTTP 429 Too Many Requests e header Retry-After.
    """
    default_rate_limiter.clear()

    # Invia 5 tentativi di login (limite per /login: 5/min)
    for _ in range(5):
        resp = await client.post(
            "/api/v1/auth/login",
            json={"email": "wrong@armimarket.it", "password": "WrongPassword!"}
        )
        assert resp.status_code == 401

    # Il 6° tentativo dallo stesso client deve ricevere 429
    resp_blocked = await client.post(
        "/api/v1/auth/login",
        json={"email": "wrong@armimarket.it", "password": "WrongPassword!"}
    )
    assert resp_blocked.status_code == 429
    assert "Retry-After" in resp_blocked.headers
    assert "Troppe richieste" in resp_blocked.json()["detail"]


@pytest.mark.asyncio
async def test_priorita8_moderation_bypass_prevention(client: AsyncClient, db_session, private_token_headers, admin_token_headers):
    """
    PRIORITÀ 8 - BLOCCO MODERATION BYPASS
    Verifica che un inserzionista non possa forzare arbitrariamente lo stato
    del proprio annuncio a 'pubblicato' tramite PATCH /annunci/{id}/stato,
    scavalcando la moderazione amministrativa.
    """
    privato = (await db_session.execute(select(User).where(User.ruolo == RuoloUtente.PRIVATO))).scalar_one()

    # 1. Crea annuncio in moderazione
    ad = Annuncio(
        titolo="Carabina da revisionare",
        slug="carabina-da-revisionare-cz-unique2",
        descrizione="Descrizione lecita",
        prezzo=300.0,
        stato=StatoAnnuncio.IN_MODERAZIONE,
        tipologia_inserzionista=TipologiaInserzionista.PRIVATO,
        tipologia_arma=TipologiaArma.ARMA_LUNGA_RIGATA,
        classificazione=ClassificazioneArma.COMUNE,
        condizione=CondizioneArma.USATO_BUONO,
        marca="CZ",
        modello="455",
        calibro=".22 LR",
        comune_id=1,
        utente_id=privato.id,
        email_contatto=privato.email
    )
    db_session.add(ad)
    await db_session.commit()
    await db_session.refresh(ad)

    # 2. Il privato tenta di forzare lo stato a 'pubblicato' -> Deve essere bloccato (403 Forbidden)
    resp_bypass = await client.patch(
        f"/api/v1/annunci/{ad.id}/stato?nuovo_stato=pubblicato",
        headers=private_token_headers
    )
    assert resp_bypass.status_code == 403
    assert "amministratore" in resp_bypass.json()["detail"].lower()

    # 3. L'annuncio rimane in moderazione
    await db_session.refresh(ad)
    assert ad.stato == StatoAnnuncio.IN_MODERAZIONE

    # 4. Il privato può invece segnarlo come VENDUTO o ARCHIVIATO
    resp_venduto = await client.patch(
        f"/api/v1/annunci/{ad.id}/stato?nuovo_stato=venduto",
        headers=private_token_headers
    )
    assert resp_venduto.status_code == 200
    await db_session.refresh(ad)
    assert ad.stato == StatoAnnuncio.VENDUTO


@pytest.mark.asyncio
async def test_priorita3_stored_xss_output_encoding(client: AsyncClient, db_session):
    """
    PRIORITÀ 3 - STORED XSS & OUTPUT ENCODING
    Verifica che stringhe malevole contenenti tag <script> e attributi inline
    vengano correttamente sottoposte a escaping nei template Jinja2 e nelle viste HTML.
    """
    privato = (await db_session.execute(select(User).where(User.ruolo == RuoloUtente.PRIVATO))).scalar_one()

    xss_payload = "<script>alert('XSS-TEST')</script>"
    xss_desc = "<img src=x onerror=alert('XSS-IMG')>"

    ad_xss = Annuncio(
        titolo=f"Pistola Beretta {xss_payload}",
        slug="pistola-beretta-xss-test-slug",
        descrizione=f"Descrizione con payload {xss_desc}",
        prezzo=500.0,
        stato=StatoAnnuncio.PUBBLICATO,
        tipologia_inserzionista=TipologiaInserzionista.PRIVATO,
        tipologia_arma=TipologiaArma.ARMA_CORTA,
        classificazione=ClassificazioneArma.COMUNE,
        condizione=CondizioneArma.USATO_OTTIMO,
        marca="Beretta",
        modello="98FS",
        calibro="9x21",
        comune_id=1,
        utente_id=privato.id,
        email_contatto=privato.email
    )
    db_session.add(ad_xss)
    await db_session.commit()
    await db_session.refresh(ad_xss)

    # Richiedi la scheda annuncio HTML
    resp = await client.get(f"/scheda/{ad_xss.id}", follow_redirects=True)
    assert resp.status_code == 200
    html_content = resp.text

    # Il tag script NON deve essere interpretato liberamente ma convertito in entity HTML
    assert "<script>alert('XSS-TEST')</script>" not in html_content
    assert "&lt;script&gt;alert(&#39;XSS-TEST&#39;)&lt;/script&gt;" in html_content or "&lt;script&gt;" in html_content
    assert "<img src=x onerror=alert('XSS-IMG')>" not in html_content
    assert "&lt;img src=x onerror=alert(&#39;XSS-IMG&#39;)&gt;" in html_content or "&lt;img" in html_content

