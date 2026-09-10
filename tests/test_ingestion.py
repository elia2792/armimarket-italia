import pytest
from httpx import AsyncClient
from sqlalchemy import select
from app.models.annuncio import Annuncio, StatoAnnuncio
from app.models.user import RuoloUtente, User
from app.services.ingestion.xml_adapter import XmlFeedAdapter


@pytest.mark.asyncio
async def test_xml_feed_adapter_parsing():
    sample_xml = """<?xml version="1.0" encoding="UTF-8"?>
    <rss version="2.0">
        <channel>
            <item>
                <title>Beretta 92FS 9x21</title>
                <description>Pistola ordinanza calibro 9x21 IMI ottime condizioni</description>
                <price>650.00 EUR</price>
                <brand>Pietro Beretta</brand>
                <caliber>9x21</caliber>
                <category>Armi Corte</category>
            </item>
        </channel>
    </rss>"""
    
    adapter = XmlFeedAdapter()
    items = adapter.fetch_feed(sample_xml)
    assert len(items) == 1
    
    # Test validazione e normalizzazione
    valid_norm = adapter.normalize_item(items[0])
    assert valid_norm is not None
    assert valid_norm["marca"] == "Pietro Beretta"
    assert valid_norm["calibro"] == "9x21"
    assert valid_norm["prezzo"] == 650.0


@pytest.mark.asyncio
async def test_sync_file_endpoint(client: AsyncClient, db_session):
    # Recupera l'armeria creata nella fixture
    stmt = select(User).where(User.ruolo == RuoloUtente.ARMERIA)
    res = await db_session.execute(stmt)
    armeria = res.scalars().first()
    assert armeria is not None

    dummy_xml = f"""<?xml version="1.0" encoding="UTF-8"?>
    <rss version="2.0">
        <channel>
            <item>
                <title>Glock 17 Gen 5 9x21</title>
                <description>Pistola semiautomatica polimerica calibro 9x21</description>
                <price>720.00</price>
                <brand>Glock</brand>
                <caliber>9x21</caliber>
            </item>
        </channel>
    </rss>"""

    files = {
        "file": ("catalog.xml", dummy_xml.encode("utf-8"), "application/xml")
    }
    data = {
        "armeria_id": str(armeria.id),
        "comune_id": "1"
    }

    response = await client.post("/api/v1/ingestion/sync-file", data=data, files=files)
    assert response.status_code == 200
    res_data = response.json()
    assert res_data["success"] is True
    assert res_data["inseriti"] == 1
    assert res_data["armeria_nome"] == armeria.ragione_sociale

    # Verifica presenza nel database
    stmt = select(Annuncio).where(Annuncio.titolo.contains("Glock 17"))
    ann = (await db_session.execute(stmt)).scalar_one_or_none()
    assert ann is not None
    assert ann.stato == StatoAnnuncio.PUBBLICATO
    assert ann.prezzo == 720.0
