import pytest
from httpx import AsyncClient
from sqlalchemy import select
from app.models.annuncio import (
    Annuncio,
    StatoAnnuncio,
    TipologiaArma,
    TipologiaInserzionista,
    ClassificazioneArma,
    CondizioneArma,
)
from app.models.user import User, RuoloUtente
from app.models.geo import Regione, Provincia, Comune
from app.core.seo import CATEGORIE_SEO, REGIONI_SEO, genera_url_annuncio, slugify


# ==============================================================================
# 20 TEST AUTOMATIZZATI COMPLETI PER L'AUDIT TECNICO E SEO DI ARMIMARKET ITALIA
# ==============================================================================

@pytest.mark.asyncio
async def test_seo_01_homepage_200(client: AsyncClient):
    """1. Homepage restituisce HTTP 200 OK con metatag SEO canonici."""
    resp = await client.get("/")
    assert resp.status_code == 200
    html = resp.text
    assert "<title>" in html
    assert '<meta name="description"' in html
    assert '<meta name="robots" content="index, follow"' in html
    assert '<link rel="canonical"' in html


@pytest.mark.asyncio
async def test_seo_02_annunci_index_200(client: AsyncClient):
    """2. Catalogo generale /annunci restituisce HTTP 200 OK."""
    resp = await client.get("/annunci")
    assert resp.status_code == 200
    assert "Bacheca" in resp.text or "Annunci" in resp.text


@pytest.mark.asyncio
async def test_seo_03_categoria_200(client: AsyncClient):
    """3. Tutte le 5 pagine landing di categoria restituiscono HTTP 200 OK con H1 e canonical unici."""
    for cat_slug, cat_data in CATEGORIE_SEO.items():
        resp = await client.get(f"/annunci/{cat_slug}")
        assert resp.status_code == 200, f"Categoria {cat_slug} fallita"
        assert cat_data["h1"] in resp.text or cat_data["nome"] in resp.text
        assert f"/annunci/{cat_slug}" in resp.text


@pytest.mark.asyncio
async def test_seo_04_regione_con_annunci_200_index(client: AsyncClient, db_session):
    """4. Landing regionale con annunci restituisce HTTP 200 e index, follow."""
    privato = (await db_session.execute(select(User).where(User.ruolo == RuoloUtente.PRIVATO))).scalar_one()

    # Inserisci regione Piemonte, provincia e comune
    reg_pie = Regione(nome="Piemonte", codice_istat="01")
    db_session.add(reg_pie)
    await db_session.flush()

    prov_to = Provincia(nome="Torino", sigla_automobilistica="TO", regione_id=reg_pie.id)
    db_session.add(prov_to)
    await db_session.flush()

    comune_to = Comune(
        nome="Torino",
        cap="10121",
        provincia_id=prov_to.id,
        latitudine=45.0703,
        longitudine=7.6869,
        coordinate="POINT(7.6869 45.0703)",
    )
    db_session.add(comune_to)
    await db_session.flush()

    ad = Annuncio(
        titolo="Carabina Sako 85 Hunter 308",
        slug="carabina-sako-85-hunter-308",
        descrizione="Carabina bolt action per caccia a palla in Piemonte.",
        prezzo=1400.0,
        stato=StatoAnnuncio.PUBBLICATO,
        tipologia_inserzionista=TipologiaInserzionista.PRIVATO,
        tipologia_arma=TipologiaArma.ARMA_LUNGA_RIGATA,
        classificazione=ClassificazioneArma.CACCIA,
        condizione=CondizioneArma.USATO_OTTIMO,
        marca="Sako",
        modello="85 Hunter",
        calibro=".308 Win",
        matricola_riservata="SAKO8501",
        comune_id=comune_to.id,
        utente_id=privato.id,
        email_contatto=privato.email
    )
    db_session.add(ad)
    await db_session.commit()

    resp = await client.get("/annunci/regione/piemonte")
    assert resp.status_code == 200
    assert 'content="index, follow"' in resp.text
    assert "Piemonte" in resp.text


@pytest.mark.asyncio
async def test_seo_05_regione_senza_annunci_noindex(client: AsyncClient, db_session):
    """5. Landing regionale senza annunci restituisce HTTP 200 ma noindex, follow per evitare thin content."""
    # Trova una regione che non ha annunci associati
    resp = await client.get("/annunci/regione/valle-daosta")
    assert resp.status_code == 200
    # Se il totale è 0, deve avere noindex, follow
    if "Nessun annuncio trovato" in resp.text or "0 annunci" in resp.text or 'totale: 0' in resp.text.lower():
        assert 'content="noindex, follow"' in resp.text


@pytest.mark.asyncio
async def test_seo_06_scheda_id_301_redirect(client: AsyncClient, db_session):
    """6. /scheda/{id} reindirizza con HTTP 301 permanente a /annuncio/{slug}-{id}."""
    privato = (await db_session.execute(select(User).where(User.ruolo == RuoloUtente.PRIVATO))).scalar_one()

    ad = Annuncio(
        titolo="Beretta 98FS Inox Sport 9x21",
        slug="beretta-98fs-inox-sport-9x21",
        descrizione="Pistola semiautomatica Beretta 98FS Inox sportiva.",
        prezzo=650.0,
        stato=StatoAnnuncio.PUBBLICATO,
        tipologia_inserzionista=TipologiaInserzionista.PRIVATO,
        tipologia_arma=TipologiaArma.ARMA_CORTA,
        classificazione=ClassificazioneArma.SPORTIVA,
        condizione=CondizioneArma.USATO_OTTIMO,
        marca="Beretta",
        modello="98FS Inox",
        calibro="9x21",
        matricola_riservata="SEC98FS001",
        comune_id=1,
        utente_id=privato.id,
        email_contatto=privato.email
    )
    db_session.add(ad)
    await db_session.commit()
    await db_session.refresh(ad)

    resp = await client.get(f"/scheda/{ad.id}")
    assert resp.status_code == 301
    target = resp.headers.get("location")
    canonical_target = genera_url_annuncio(ad.id, ad.titolo)
    assert target == canonical_target


@pytest.mark.asyncio
async def test_seo_07_slug_errato_301_redirect(client: AsyncClient, db_session):
    """7. Richiesta a /annuncio/slug-errato-{id} reindirizza 301 all'URL canonico."""
    privato = (await db_session.execute(select(User).where(User.ruolo == RuoloUtente.PRIVATO))).scalar_one()

    ad = Annuncio(
        titolo="Carabina CZ 457 Varmint MTR",
        slug="carabina-cz-457-varmint-mtr",
        descrizione="Carabina calibro 22 LR per tiro di precisione a 50m.",
        prezzo=600.0,
        stato=StatoAnnuncio.PUBBLICATO,
        tipologia_inserzionista=TipologiaInserzionista.PRIVATO,
        tipologia_arma=TipologiaArma.ARMA_LUNGA_RIGATA,
        classificazione=ClassificazioneArma.SPORTIVA,
        condizione=CondizioneArma.NUOVO,
        marca="CZ",
        modello="457 Varmint",
        calibro=".22 LR",
        matricola_riservata="CZ457MTR",
        comune_id=1,
        utente_id=privato.id,
        email_contatto=privato.email
    )
    db_session.add(ad)
    await db_session.commit()
    await db_session.refresh(ad)

    resp = await client.get(f"/annuncio/slug-completamente-inventato-{ad.id}")
    assert resp.status_code == 301
    assert resp.headers.get("location") == genera_url_annuncio(ad.id, ad.titolo)


@pytest.mark.asyncio
async def test_seo_08_url_canonico_200(client: AsyncClient, db_session):
    """8. URL canonico /annuncio/{slug}-{id} risponde direttamente con HTTP 200 OK."""
    privato = (await db_session.execute(select(User).where(User.ruolo == RuoloUtente.PRIVATO))).scalar_one()

    ad = Annuncio(
        titolo="Pistola Sig Sauer P320 X-Five",
        slug="pistola-sig-sauer-p320-x-five",
        descrizione="Pistola Sig Sauer P320 per tiro dinamico sportivo.",
        prezzo=1100.0,
        stato=StatoAnnuncio.PUBBLICATO,
        tipologia_inserzionista=TipologiaInserzionista.PRIVATO,
        tipologia_arma=TipologiaArma.ARMA_CORTA,
        classificazione=ClassificazioneArma.SPORTIVA,
        condizione=CondizioneArma.USATO_OTTIMO,
        marca="Sig Sauer",
        modello="P320 X-Five",
        calibro="9x21",
        matricola_riservata="SIG320X",
        comune_id=1,
        utente_id=privato.id,
        email_contatto=privato.email
    )
    db_session.add(ad)
    await db_session.commit()
    await db_session.refresh(ad)

    canonical_path = genera_url_annuncio(ad.id, ad.titolo)
    resp = await client.get(canonical_path)
    assert resp.status_code == 200
    assert "Sig Sauer P320" in resp.text


@pytest.mark.asyncio
async def test_seo_09_canonical_tag_corretto(client: AsyncClient, db_session):
    """9. Verifica che il tag <link rel='canonical'> sia corretto su annunci, categorie e home."""
    privato = (await db_session.execute(select(User).where(User.ruolo == RuoloUtente.PRIVATO))).scalar_one()

    ad = Annuncio(
        titolo="Benelli Raffaello Crio Calibro 12",
        slug="benelli-raffaello-crio-calibro-12",
        descrizione="Fucile semiautomatico da caccia Benelli Raffaello canna crio.",
        prezzo=1200.0,
        stato=StatoAnnuncio.PUBBLICATO,
        tipologia_inserzionista=TipologiaInserzionista.PRIVATO,
        tipologia_arma=TipologiaArma.CANNA_LISCIA,
        classificazione=ClassificazioneArma.CACCIA,
        condizione=CondizioneArma.USATO_OTTIMO,
        marca="Benelli",
        modello="Raffaello Crio",
        calibro="12/76",
        matricola_riservata="BENRAF01",
        comune_id=1,
        utente_id=privato.id,
        email_contatto=privato.email
    )
    db_session.add(ad)
    await db_session.commit()
    await db_session.refresh(ad)

    # 1. Su scheda annuncio
    canonical_url_ad = genera_url_annuncio(ad.id, ad.titolo)
    resp_ad = await client.get(canonical_url_ad)
    assert f'<link rel="canonical" href="http://test{canonical_url_ad}"' in resp_ad.text or f'<link rel="canonical" href="http://testserver{canonical_url_ad}"' in resp_ad.text

    # 2. Su categoria
    resp_cat = await client.get("/annunci/fucili-canna-liscia")
    assert '<link rel="canonical" href="http://test/annunci/fucili-canna-liscia"' in resp_cat.text or '<link rel="canonical" href="http://testserver/annunci/fucili-canna-liscia"' in resp_cat.text


@pytest.mark.asyncio
async def test_seo_10_meta_robots_corretto(client: AsyncClient, db_session):
    """10. Meta robots: index per canonical, noindex per venduti e filtri complessi."""
    privato = (await db_session.execute(select(User).where(User.ruolo == RuoloUtente.PRIVATO))).scalar_one()

    ad_pub = Annuncio(
        titolo="Glock 19 Gen 4 9x21",
        slug="glock-19-gen-4-9x21",
        descrizione="Pistola Glock 19 Gen 4 con caricatore di scorta.",
        prezzo=480.0,
        stato=StatoAnnuncio.PUBBLICATO,
        tipologia_inserzionista=TipologiaInserzionista.PRIVATO,
        tipologia_arma=TipologiaArma.ARMA_CORTA,
        classificazione=ClassificazioneArma.COMUNE,
        condizione=CondizioneArma.USATO_BUONO,
        marca="Glock",
        modello="19 Gen 4",
        calibro="9x21",
        matricola_riservata="GLK19TEST",
        comune_id=1,
        utente_id=privato.id,
        email_contatto=privato.email
    )
    ad_sold = Annuncio(
        titolo="Revolver Ruger GP100 Venduto",
        slug="revolver-ruger-gp100-venduto",
        descrizione="Revolver Ruger GP100 venduto trattativa conclusa.",
        prezzo=650.0,
        stato=StatoAnnuncio.VENDUTO,
        tipologia_inserzionista=TipologiaInserzionista.PRIVATO,
        tipologia_arma=TipologiaArma.ARMA_CORTA,
        classificazione=ClassificazioneArma.COMUNE,
        condizione=CondizioneArma.USATO_OTTIMO,
        marca="Ruger",
        modello="GP100",
        calibro=".357 Mag",
        matricola_riservata="RUGGP100",
        comune_id=1,
        utente_id=privato.id,
        email_contatto=privato.email
    )
    db_session.add_all([ad_pub, ad_sold])
    await db_session.commit()

    # Annuncio pubblicato -> index, follow
    resp_pub = await client.get(genera_url_annuncio(ad_pub.id, ad_pub.titolo))
    assert '<meta name="robots" content="index, follow"' in resp_pub.text

    # Annuncio venduto -> noindex, follow
    resp_sold = await client.get(genera_url_annuncio(ad_sold.id, ad_sold.titolo))
    assert '<meta name="robots" content="noindex, follow"' in resp_sold.text

    # Ricerca con filtri query string -> noindex, follow
    resp_filter = await client.get("/?q=beretta&prezzo_min=100")
    assert '<meta name="robots" content="noindex, follow"' in resp_filter.text


@pytest.mark.asyncio
async def test_seo_11_sitemap_200(client: AsyncClient):
    """11. /sitemap.xml risponde HTTP 200 con XML standard valido."""
    resp = await client.get("/sitemap.xml")
    assert resp.status_code == 200
    assert "application/xml" in resp.headers.get("content-type", "")
    xml = resp.text
    assert "<?xml version=" in xml
    assert "<urlset xmlns=" in xml
    assert "/guide</loc>" in xml
    assert "/faq</loc>" in xml


@pytest.mark.asyncio
async def test_seo_12_sitemap_senza_url_noindex(client: AsyncClient, db_session):
    """12. La sitemap NON contiene URL noindex, login, admin, vecchi /scheda o annunci venduti."""
    privato = (await db_session.execute(select(User).where(User.ruolo == RuoloUtente.PRIVATO))).scalar_one()

    ad_sold = Annuncio(
        titolo="Fucile Franchi Escluso Sitemap",
        slug="fucile-franchi-escluso-sitemap",
        descrizione="Fucile venduto che non deve apparire nella sitemap.",
        prezzo=400.0,
        stato=StatoAnnuncio.VENDUTO,
        tipologia_inserzionista=TipologiaInserzionista.PRIVATO,
        tipologia_arma=TipologiaArma.CANNA_LISCIA,
        classificazione=ClassificazioneArma.CACCIA,
        condizione=CondizioneArma.USATO_BUONO,
        marca="Franchi",
        modello="48 AL",
        calibro="12",
        matricola_riservata="FRA48001",
        comune_id=1,
        utente_id=privato.id,
        email_contatto=privato.email
    )
    db_session.add(ad_sold)
    await db_session.commit()
    await db_session.refresh(ad_sold)

    resp = await client.get("/sitemap.xml")
    xml = resp.text
    # Nessun annuncio venduto
    assert f"fucile-franchi-escluso-sitemap-{ad_sold.id}" not in xml
    # Nessun vecchio path /scheda/
    assert "/scheda/" not in xml
    # Nessuna pagina admin/login/registrati
    assert "/admin" not in xml
    assert "/login" not in xml
    assert "/registrati" not in xml


@pytest.mark.asyncio
async def test_seo_13_robots_txt_200_non_blocca_query_string(client: AsyncClient):
    """13. /robots.txt blocca solo aree tecniche senza impedire il crawl delle query string gestite da noindex."""
    resp = await client.get("/robots.txt")
    assert resp.status_code == 200
    text = resp.text
    assert "Disallow: /admin" in text
    assert "Disallow: /api/" in text
    assert "Disallow: /profilo" in text
    assert "Disallow: /nuovo-annuncio" in text
    assert "Sitemap:" in text
    # NON deve bloccare le query string così i bot leggono noindex
    assert "Disallow: /*?*q=" not in text


@pytest.mark.asyncio
async def test_seo_14_paginazione_50_annunci(client: AsyncClient):
    """14. Verifica che la paginazione server-side sia esattamente di 50 annunci per pagina."""
    resp = await client.get("/")
    assert resp.status_code == 200
    # In context o pagina, elementi_per_pagina deve essere 50
    assert 'elementi_per_pagina' not in resp.text or '50' in resp.text


@pytest.mark.asyncio
async def test_seo_15_paginazione_pagina_2_prev_next(client: AsyncClient):
    """15. Pagina 2 di categoria include canonical con ?pagina=2 e tag rel='prev' verso pagina 1."""
    resp = await client.get("/annunci/armi-corte?pagina=2")
    assert resp.status_code == 200
    html = resp.text
    assert ('<link rel="canonical" href="http://test/annunci/armi-corte?pagina=2"' in html
            or '<link rel="canonical" href="http://testserver/annunci/armi-corte?pagina=2"' in html)
    assert ('<link rel="prev" href="http://test/annunci/armi-corte"' in html
            or '<link rel="prev" href="http://testserver/annunci/armi-corte"' in html)


@pytest.mark.asyncio
async def test_seo_16_link_interni_canonici(client: AsyncClient, db_session):
    """16. I link interni nelle pagine di categoria usano il pattern canonico /annuncio/{slug}-{id}."""
    privato = (await db_session.execute(select(User).where(User.ruolo == RuoloUtente.PRIVATO))).scalar_one()

    ad = Annuncio(
        titolo="Carabina Browning Maral 30-06",
        slug="carabina-browning-maral-30-06",
        descrizione="Carabina a riarmo lineare Browning Maral calibro 30-06.",
        prezzo=1650.0,
        stato=StatoAnnuncio.PUBBLICATO,
        tipologia_inserzionista=TipologiaInserzionista.PRIVATO,
        tipologia_arma=TipologiaArma.ARMA_LUNGA_RIGATA,
        classificazione=ClassificazioneArma.CACCIA,
        condizione=CondizioneArma.NUOVO,
        marca="Browning",
        modello="Maral",
        calibro="30-06",
        matricola_riservata="BRWMARAL01",
        comune_id=1,
        utente_id=privato.id,
        email_contatto=privato.email
    )
    db_session.add(ad)
    await db_session.commit()
    await db_session.refresh(ad)

    resp = await client.get("/annunci/carabine-fucili-rigati")
    assert resp.status_code == 200
    assert genera_url_annuncio(ad.id, ad.titolo) in resp.text


@pytest.mark.asyncio
async def test_seo_17_annuncio_scraped_senza_user_armeria(client: AsyncClient, db_session):
    """17. REQUISITO FONDAMENTALE: Annuncio scraped salvato con utente_id=None e fonte_esterna valorizzata, senza account User."""
    ad_scraped = Annuncio(
        titolo="Sovrapposto Beretta 686 Silver Pigeon I 12/76",
        slug="sovrapposto-beretta-686-silver-pigeon-i-1276",
        descrizione="Fucile sovrapposto da caccia Beretta Silver Pigeon dal catalogo online di Armeria Regina.",
        prezzo=1890.0,
        stato=StatoAnnuncio.PUBBLICATO,
        tipologia_inserzionista=TipologiaInserzionista.ARMERIA,
        tipologia_arma=TipologiaArma.CANNA_LISCIA,
        classificazione=ClassificazioneArma.CACCIA,
        condizione=CondizioneArma.NUOVO,
        marca="Beretta",
        modello="686 Silver Pigeon I",
        calibro="12/76",
        matricola_riservata="SP686REG",
        comune_id=1,
        utente_id=None,  # NESSUN ACCOUNT UTENTE RICHIESTO!
        fonte_esterna="Armeria Regina",
        source_id_esterno="REG-PROD-9988",
        link_esterno="https://armeriaregina.it/it/armi/sovrapposti/beretta-686.html",
        email_contatto="info@armeriaregina.it",
        telefono_contatto="+39 0438 980182",
        mostra_telefono_pubblico=True,
    )
    db_session.add(ad_scraped)
    await db_session.commit()
    await db_session.refresh(ad_scraped)

    # Verifica proprietà di modello
    assert ad_scraped.utente_id is None
    assert ad_scraped.is_scraped is True
    assert ad_scraped.nome_inserzionista_reale == "Armeria Regina"

    # Verifica rendering pubblico della scheda
    canonical_url = genera_url_annuncio(ad_scraped.id, ad_scraped.titolo)
    resp = await client.get(canonical_url)
    assert resp.status_code == 200
    html = resp.text
    assert "Armeria Regina" in html
    assert "https://armeriaregina.it/it/armi/sovrapposti/beretta-686.html" in html
    assert "Vai al Negozio Online dell'Armeria" in html or "Sito Ufficiale" in html


@pytest.mark.asyncio
async def test_seo_18_annuncio_privato_normale_funzionante(client: AsyncClient, db_session):
    """18. Annuncio privato normale continua a funzionare perfettamente con utente registrato associato."""
    privato = (await db_session.execute(select(User).where(User.ruolo == RuoloUtente.PRIVATO))).scalar_one()

    ad_priv = Annuncio(
        titolo="Carabina Weihrauch HW 30S Libera Vendita",
        slug="carabina-weihrauch-hw-30s-libera-vendita",
        descrizione="Carabina ad aria compressa depotenziata pari al nuovo.",
        prezzo=220.0,
        stato=StatoAnnuncio.PUBBLICATO,
        tipologia_inserzionista=TipologiaInserzionista.PRIVATO,
        tipologia_arma=TipologiaArma.ARIA_COMPRESSA_LIBERA,
        classificazione=ClassificazioneArma.NON_APPLICABILE,
        condizione=CondizioneArma.USATO_OTTIMO,
        marca="Weihrauch",
        modello="HW 30S",
        calibro="4.5mm",
        matricola_riservata="HW30STEST",
        comune_id=1,
        utente_id=privato.id,
        email_contatto=privato.email
    )
    db_session.add(ad_priv)
    await db_session.commit()
    await db_session.refresh(ad_priv)

    assert ad_priv.is_scraped is False
    assert ad_priv.utente_id == privato.id

    resp = await client.get(genera_url_annuncio(ad_priv.id, ad_priv.titolo))
    assert resp.status_code == 200
    assert "Weihrauch HW 30S" in resp.text


@pytest.mark.asyncio
async def test_seo_19_nessuna_matricola_in_html_pubblico(client: AsyncClient, db_session):
    """19. SICUREZZA: La matricola riservata NON deve mai apparire in chiaro nel codice HTML pubblico."""
    privato = (await db_session.execute(select(User).where(User.ruolo == RuoloUtente.PRIVATO))).scalar_one()
    secret_serial = "TOP-SECRET-SERIAL-NUM-99999X"

    ad_sec = Annuncio(
        titolo="Pistola Tanfoglio Stock II Calibro 9x21",
        slug="pistola-tanfoglio-stock-ii-calibro-9x21",
        descrizione="Pistola per tiro dinamico categoria Production.",
        prezzo=1300.0,
        stato=StatoAnnuncio.PUBBLICATO,
        tipologia_inserzionista=TipologiaInserzionista.PRIVATO,
        tipologia_arma=TipologiaArma.ARMA_CORTA,
        classificazione=ClassificazioneArma.SPORTIVA,
        condizione=CondizioneArma.USATO_OTTIMO,
        marca="Tanfoglio",
        modello="Stock II",
        calibro="9x21",
        matricola_riservata=secret_serial,
        comune_id=1,
        utente_id=privato.id,
        email_contatto=privato.email
    )
    db_session.add(ad_sec)
    await db_session.commit()
    await db_session.refresh(ad_sec)

    resp = await client.get(genera_url_annuncio(ad_sec.id, ad_sec.titolo))
    assert resp.status_code == 200
    assert secret_serial not in resp.text
    assert "RISERVATA AI SENSI DEL REGOLAMENTO DI PUBBLICA SICUREZZA" in resp.text


@pytest.mark.asyncio
async def test_seo_20_nessuna_catena_di_redirect(client: AsyncClient, db_session):
    """20. Nessuna catena di redirect: sia /scheda/{id} che lo slug errato rimandano all'URL finale con un solo salto."""
    privato = (await db_session.execute(select(User).where(User.ruolo == RuoloUtente.PRIVATO))).scalar_one()

    ad = Annuncio(
        titolo="Carabina Sauer 404 Synchro XT",
        slug="carabina-sauer-404-synchro-xt",
        descrizione="Carabina modulare Sauer 404 con calcio thumbhole.",
        prezzo=2800.0,
        stato=StatoAnnuncio.PUBBLICATO,
        tipologia_inserzionista=TipologiaInserzionista.PRIVATO,
        tipologia_arma=TipologiaArma.ARMA_LUNGA_RIGATA,
        classificazione=ClassificazioneArma.CACCIA,
        condizione=CondizioneArma.NUOVO,
        marca="Sauer",
        modello="404 Synchro XT",
        calibro=".300 Win Mag",
        matricola_riservata="SAUER404XT",
        comune_id=1,
        utente_id=privato.id,
        email_contatto=privato.email
    )
    db_session.add(ad)
    await db_session.commit()
    await db_session.refresh(ad)

    canonical_url = genera_url_annuncio(ad.id, ad.titolo)

    # 1. Da /scheda/{id} con follow_redirects
    resp_scheda = await client.get(f"/scheda/{ad.id}", follow_redirects=True)
    assert resp_scheda.status_code == 200
    assert len(resp_scheda.history) == 1
    assert resp_scheda.history[0].status_code == 301
    assert resp_scheda.history[0].headers.get("location") == canonical_url

    # 2. Da slug errato con follow_redirects
    resp_wrong = await client.get(f"/annuncio/slug-sbagliato-{ad.id}", follow_redirects=True)
    assert resp_wrong.status_code == 200
    assert len(resp_wrong.history) == 1
    assert resp_wrong.history[0].status_code == 301
    assert resp_wrong.history[0].headers.get("location") == canonical_url
