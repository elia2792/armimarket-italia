import pytest
from httpx import AsyncClient
from sqlalchemy import select
from app.models.annuncio import (
    Annuncio,
    StatoAnnuncio,
    TipologiaArma,
    TipologiaInserzionista,
    ClassificazioneArma,
    CondizioneArma
)
from app.models.user import User, RuoloUtente
from app.models.geo import Regione, Provincia, Comune
from app.core.seo import CATEGORIE_SEO, REGIONI_SEO


@pytest.mark.asyncio
async def test_seo_sitemap_xml(client: AsyncClient, db_session):
    """Verifica che /sitemap.xml restituisca XML valido con le sezioni principali e gli annunci attivi."""
    resp = await client.get("/sitemap.xml")
    assert resp.status_code == 200
    assert "application/xml" in resp.headers.get("content-type", "")
    xml = resp.text
    assert "<?xml version=" in xml
    assert "<urlset xmlns=" in xml
    # Pagine fisse
    assert "<loc>" in xml
    assert "/annunci</loc>" in xml
    assert "/guide</loc>" in xml
    assert "/faq</loc>" in xml
    assert "/annunci/armi-corte</loc>" in xml
    assert "/annunci/regione/lombardia</loc>" in xml


@pytest.mark.asyncio
async def test_seo_robots_txt(client: AsyncClient):
    """Verifica che /robots.txt restituisca le direttive per il crawl budget e il link alla sitemap."""
    resp = await client.get("/robots.txt")
    assert resp.status_code == 200
    text = resp.text
    assert "User-agent: *" in text
    assert "Allow: /" in text
    assert "Allow: /annunci" in text
    assert "Allow: /annuncio/*" in text
    assert "Disallow: /admin" in text
    assert "Disallow: /api/" in text
    assert "Disallow: /profilo" in text
    assert "Sitemap:" in text
    assert "/sitemap.xml" in text


@pytest.mark.asyncio
async def test_seo_legacy_scheda_redirect_301(client: AsyncClient, db_session):
    """Verifica che /scheda/{id} reindirizzi con HTTP 301 permanente a /annuncio/{slug}-{id}."""
    privato = (await db_session.execute(select(User).where(User.ruolo == RuoloUtente.PRIVATO))).scalar_one()

    ad = Annuncio(
        titolo="Beretta 98FS Inox Calibro 9x21",
        slug="beretta-98fs-inox-calibro-9x21",
        descrizione="Pistola Beretta 98FS Inox pari al nuovo, perfetta per tiro sportivo.",
        prezzo=650.0,
        stato=StatoAnnuncio.PUBBLICATO,
        tipologia_inserzionista=TipologiaInserzionista.PRIVATO,
        tipologia_arma=TipologiaArma.ARMA_CORTA,
        classificazione=ClassificazioneArma.COMUNE,
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

    # Richiesta a /scheda/{id} senza seguire i redirect
    resp = await client.get(f"/scheda/{ad.id}")
    assert resp.status_code == 301
    redirect_target = resp.headers.get("location")
    assert f"-{ad.id}" in redirect_target
    assert "beretta-98fs-inox" in redirect_target

    # Richiesta seguendo il redirect per verificare che la pagina finale risponda 200 OK
    resp_followed = await client.get(f"/scheda/{ad.id}", follow_redirects=True)
    assert resp_followed.status_code == 200
    assert "Beretta 98FS Inox" in resp_followed.text
    # Schema.org Product
    assert "IndividualProduct" in resp_followed.text
    assert '"price": "650.00"' in resp_followed.text
    # Canonical link
    assert f"/annuncio/beretta-98fs-inox-calibro-9x21-{ad.id}" in resp_followed.text


@pytest.mark.asyncio
async def test_seo_wrong_slug_canonical_redirect(client: AsyncClient, db_session):
    """Verifica che un URL con slug errato ma ID valido reindirizzi 301 allo slug canonico."""
    privato = (await db_session.execute(select(User).where(User.ruolo == RuoloUtente.PRIVATO))).scalar_one()

    ad = Annuncio(
        titolo="Carabina CZ 457 Varmint",
        slug="carabina-cz-457-varmint",
        descrizione="Carabina bolt action calibro .22 LR per tiro di precisione.",
        prezzo=580.0,
        stato=StatoAnnuncio.PUBBLICATO,
        tipologia_inserzionista=TipologiaInserzionista.PRIVATO,
        tipologia_arma=TipologiaArma.ARMA_LUNGA_RIGATA,
        classificazione=ClassificazioneArma.SPORTIVA,
        condizione=CondizioneArma.NUOVO,
        marca="CZ",
        modello="457 Varmint",
        calibro=".22 LR",
        matricola_riservata="CZ457TEST",
        comune_id=1,
        utente_id=privato.id,
        email_contatto=privato.email
    )
    db_session.add(ad)
    await db_session.commit()
    await db_session.refresh(ad)

    # Slug errato con ID corretto
    resp = await client.get(f"/annuncio/titolo-completamente-sbagliato-{ad.id}")
    assert resp.status_code == 301
    assert resp.headers.get("location") == f"/annuncio/carabina-cz-457-varmint-{ad.id}"


@pytest.mark.asyncio
async def test_seo_category_pages_with_ads(client: AsyncClient, db_session):
    """
    Verifica che le pagine di categoria /annunci/{categoria_slug} funzionino
    in presenza di annunci reali nel database e renderizzino correttamente:
    - Status 200 OK
    - H1 e intro
    - Canonical
    - BreadcrumbList Schema.org
    - Link SEO agli annunci nel formato /annuncio/{slug}-{id}
    - Tutte le 5 categorie SEO configurate rispondano 200 OK
    """
    privato = (await db_session.execute(select(User).where(User.ruolo == RuoloUtente.PRIVATO))).scalar_one()

    # Inserisci un annuncio per ciascuna categoria
    ad_corta = Annuncio(
        titolo="Glock 17 Gen 5 Calibro 9x19",
        slug="glock-17-gen-5-calibro-9x19",
        descrizione="Pistola semiautomatica Glock 17 Gen 5 in perfette condizioni.",
        prezzo=620.0,
        stato=StatoAnnuncio.PUBBLICATO,
        tipologia_inserzionista=TipologiaInserzionista.PRIVATO,
        tipologia_arma=TipologiaArma.ARMA_CORTA,
        classificazione=ClassificazioneArma.SPORTIVA,
        condizione=CondizioneArma.USATO_OTTIMO,
        marca="Glock",
        modello="17 Gen 5",
        calibro="9x19",
        matricola_riservata="GLK17TEST",
        comune_id=1,
        utente_id=privato.id,
        email_contatto=privato.email
    )
    db_session.add(ad_corta)
    await db_session.commit()
    await db_session.refresh(ad_corta)

    # Test specifico sulla categoria armi-corte
    resp = await client.get("/annunci/armi-corte")
    assert resp.status_code == 200
    html = resp.text

    # Verifica metadati e tag SEO
    assert "Bacheca Armi Corte" in html
    assert "BreadcrumbList" in html
    assert '<link rel="canonical" href="' in html
    assert "/annunci/armi-corte" in html
    # Verifica che il link all'annuncio sia presente e nel formato corretto
    assert f"/annuncio/glock-17-gen-5-calibro-9x19-{ad_corta.id}" in html

    # Test di verifica su TUTTE le 5 categorie SEO configurate
    for cat_slug, cat_data in CATEGORIE_SEO.items():
        r = await client.get(f"/annunci/{cat_slug}")
        assert r.status_code == 200, f"Categoria {cat_slug} ha restituito {r.status_code}"
        assert cat_data["h1"] in r.text or cat_data["nome"] in r.text
        assert f"/annunci/{cat_slug}" in r.text


@pytest.mark.asyncio
async def test_seo_regional_pages_with_ads(client: AsyncClient, db_session):
    """
    Verifica che le pagine territoriali /annunci/regione/{regione_slug} funzionino
    in presenza di annunci nel database e renderizzino correttamente:
    - Status 200 OK
    - H1 e intro
    - Canonical
    - Breadcrumbs
    - Tutte le 20 regioni d'Italia rispondano 200 OK
    """
    privato = (await db_session.execute(select(User).where(User.ruolo == RuoloUtente.PRIVATO))).scalar_one()

    # Comune 1 è in Piemonte (id=1)
    ad_geo = Annuncio(
        titolo="Carabina Tikka T3x Superlite 308",
        slug="carabina-tikka-t3x-superlite-308",
        descrizione="Carabina da caccia di precisione bolt action calibro 308 Winchester.",
        prezzo=1250.0,
        stato=StatoAnnuncio.PUBBLICATO,
        tipologia_inserzionista=TipologiaInserzionista.PRIVATO,
        tipologia_arma=TipologiaArma.ARMA_LUNGA_RIGATA,
        classificazione=ClassificazioneArma.CACCIA,
        condizione=CondizioneArma.NUOVO,
        marca="Tikka",
        modello="T3x Superlite",
        calibro=".308 Win",
        matricola_riservata="TK3X001",
        comune_id=1,
        utente_id=privato.id,
        email_contatto=privato.email
    )
    db_session.add(ad_geo)
    await db_session.commit()
    await db_session.refresh(ad_geo)

    # Test specifico sulla regione piemonte (dove si trova comune_id=1)
    resp = await client.get("/annunci/regione/piemonte")
    assert resp.status_code == 200
    html = resp.text
    assert "Piemonte" in html
    assert "BreadcrumbList" in html
    assert '<link rel="canonical" href="' in html
    assert "/annunci/regione/piemonte" in html
    assert f"/annuncio/carabina-tikka-t3x-superlite-308-{ad_geo.id}" in html

    # Test specifico sulla regione lombardia
    resp_lom = await client.get("/annunci/regione/lombardia")
    assert resp_lom.status_code == 200
    assert "Lombardia" in resp_lom.text
    assert "/annunci/regione/lombardia" in resp_lom.text

    # Test di verifica su TUTTE le 20 regioni d'Italia
    for reg_slug, reg_data in REGIONI_SEO.items():
        r = await client.get(f"/annunci/regione/{reg_slug}")
        assert r.status_code == 200, f"Regione {reg_slug} ha restituito {r.status_code}"
        assert (
            reg_data["nome"] in r.text
            or reg_data["nome"].replace("'", "&#39;") in r.text
            or reg_data["slug"] in r.text
        )
        assert f"/annunci/regione/{reg_slug}" in r.text


@pytest.mark.asyncio
async def test_seo_guide_and_faq(client: AsyncClient):
    """Verifica le pagine informative /guide e /faq con Schema.org FAQPage."""
    resp_guide = await client.get("/guide")
    assert resp_guide.status_code == 200
    assert "T.U.L.P.S." in resp_guide.text
    assert "Art. 17 Legge 110/1975" in resp_guide.text

    resp_faq = await client.get("/faq")
    assert resp_faq.status_code == 200
    assert "FAQPage" in resp_faq.text
    assert "Domande Frequenti" in resp_faq.text


@pytest.mark.asyncio
async def test_seo_sold_ad_noindex(client: AsyncClient, db_session):
    """Verifica che un annuncio venduto rimanga visibile con badge chiaro e metatag noindex."""
    privato = (await db_session.execute(select(User).where(User.ruolo == RuoloUtente.PRIVATO))).scalar_one()

    ad_sold = Annuncio(
        titolo="Pistola Smith & Wesson 686 Venduta",
        slug="pistola-smith-wesson-686-venduta",
        descrizione="Revolver calibro .357 Magnum venduto.",
        prezzo=800.0,
        stato=StatoAnnuncio.VENDUTO,
        tipologia_inserzionista=TipologiaInserzionista.PRIVATO,
        tipologia_arma=TipologiaArma.ARMA_CORTA,
        classificazione=ClassificazioneArma.COMUNE,
        condizione=CondizioneArma.USATO_OTTIMO,
        marca="Smith & Wesson",
        modello="686",
        calibro=".357 Mag",
        matricola_riservata="SW686VEND",
        comune_id=1,
        utente_id=privato.id,
        email_contatto=privato.email
    )
    db_session.add(ad_sold)
    await db_session.commit()
    await db_session.refresh(ad_sold)

    resp = await client.get(f"/annuncio/{ad_sold.slug}-{ad_sold.id}")
    assert resp.status_code == 200
    assert "noindex, follow" in resp.text
    assert "ANNUNCIO VENDUTO" in resp.text
