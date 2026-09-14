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
async def test_seo_category_pages(client: AsyncClient, db_session):
    """Verifica la pagina dedicata di categoria /annunci/{categoria_slug}."""
    resp = await client.get("/annunci/armi-corte")
    assert resp.status_code == 200
    html = resp.text
    assert "Pistole" in html or "Armi Corte" in html
    assert "BreadcrumbList" in html
    assert "/annunci/armi-corte" in html


@pytest.mark.asyncio
async def test_seo_regional_pages(client: AsyncClient, db_session):
    """Verifica la pagina dedicata territoriale /annunci/regione/{regione_slug}."""
    resp = await client.get("/annunci/regione/lombardia")
    assert resp.status_code == 200
    html = resp.text
    assert "Lombardia" in html
    assert "BreadcrumbList" in html
    assert "/annunci/regione/lombardia" in html


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
