import pytest


@pytest.mark.asyncio
async def test_html_views(client, db_session):
    # Test Home Page
    res_home = await client.get("/")
    assert res_home.status_code == 200
    assert "ArmiMarket" in res_home.text
    assert "T.U.L.P.S." in res_home.text

    # Test Mappa Interattiva
    res_map = await client.get("/mappa")
    assert res_map.status_code == 200
    assert "armimarket-map" in res_map.text
    assert "L.tileLayer" in res_map.text

    # Test Scheda Dettaglio
    res_scheda = await client.get("/scheda/1")
    # Scheda non trovata se db vuoto, o 200 se presente
    assert res_scheda.status_code in [200, 404]
