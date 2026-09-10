import pytest


@pytest.mark.asyncio
async def test_get_regioni(client):
    response = await client.get("/api/v1/geo/regioni")
    assert response.status_code == 200
    data = response.json()
    assert len(data) >= 1
    assert any(r["nome"] == "Lombardia" for r in data)


@pytest.mark.asyncio
async def test_get_province_by_regione(client):
    regioni_resp = await client.get("/api/v1/geo/regioni")
    reg_id = regioni_resp.json()[0]["id"]

    response = await client.get(f"/api/v1/geo/province?regione_id={reg_id}")
    assert response.status_code == 200
    data = response.json()
    assert len(data) >= 2
    assert any(p["sigla_automobilistica"] == "MI" for p in data)


@pytest.mark.asyncio
async def test_get_comuni_autocomplete(client):
    # Autocomplete su "Mil"
    response = await client.get("/api/v1/geo/comuni?q=Mil")
    assert response.status_code == 200
    data = response.json()
    assert len(data) == 1
    assert data[0]["nome"] == "Milano"
    assert data[0]["cap"] == "20121"
    assert data[0]["latitudine"] == pytest.approx(45.4642, 0.001)


@pytest.mark.asyncio
async def test_prossimita_radius_search(client):
    # Cerca comuni entro 25 km da Milano (45.4642, 9.1900) -> deve trovare Milano e Monza, ma non Gardone (BS) che dista ~75km
    response = await client.get("/api/v1/geo/prossimita?lat=45.4642&lon=9.1900&raggio_km=25.0")
    assert response.status_code == 200
    data = response.json()
    nomi = [c["nome"] for c in data]
    assert "Milano" in nomi
    assert "Monza" in nomi
    assert "Gardone Val Trompia" not in nomi

    # Distanza di Milano da se stessa ~0 km
    milano_entry = next(c for c in data if c["nome"] == "Milano")
    assert milano_entry["distanza_km"] < 1.0
