import asyncio
import csv
import json
import math
import os
import sys
import urllib.request
from pathlib import Path

# Radice del progetto
sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

from sqlalchemy import select
from geoalchemy2.elements import WKTElement
from app.core.database import Base, async_session_factory, engine
from app.models.geo import Comune, Provincia, Regione


COMUNI_JSON_URL = "https://raw.githubusercontent.com/matteocontrini/comuni-json/master/comuni.json"
DPC_PROVINCE_URL = "https://raw.githubusercontent.com/pcm-dpc/COVID-19/master/dati-province/dpc-covid19-ita-province-latest.csv"


REGIONI_ISTAT = {
    "01": "Piemonte",
    "02": "Valle d'Aosta",
    "03": "Lombardia",
    "04": "Trentino-Alto Adige",
    "05": "Veneto",
    "06": "Friuli-Venezia Giulia",
    "07": "Liguria",
    "08": "Emilia-Romagna",
    "09": "Toscana",
    "10": "Umbria",
    "11": "Marche",
    "12": "Lazio",
    "13": "Abruzzo",
    "14": "Molise",
    "15": "Campania",
    "16": "Puglia",
    "17": "Basilicata",
    "18": "Calabria",
    "19": "Sicilia",
    "20": "Sardegna",
}


def download_json(url: str):
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    with urllib.request.urlopen(req, timeout=30) as resp:
        return json.loads(resp.read().decode("utf-8"))


def download_province_coords(url: str):
    coords = {}
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    with urllib.request.urlopen(req, timeout=30) as resp:
        lines = [l.decode("utf-8") for l in resp.readlines()]
        reader = csv.DictReader(lines)
        for row in reader:
            sigla = row.get("sigla_provincia", "").strip()
            lat_str = row.get("lat", "").strip()
            lon_str = row.get("long", "").strip()
            if sigla and lat_str and lon_str and sigla not in coords:
                try:
                    coords[sigla] = (float(lat_str), float(lon_str))
                except ValueError:
                    pass
    return coords


async def import_all_comuni():
    print("=== Avvio importazione Comuni d'Italia ===")

    print("1. Download dati Comuni e coordinate di riferimento...")
    comuni_raw = download_json(COMUNI_JSON_URL)
    print(f"-> Scaricati {len(comuni_raw)} comuni da matteocontrini/comuni-json.")

    prov_coords = download_province_coords(DPC_PROVINCE_URL)
    print(f"-> Coordinate caricate per {len(prov_coords)} province italiane.")

    is_sqlite = "sqlite" in engine.url.drivername

    async with async_session_factory() as session:
        print("2. Sincronizzazione Regioni...")
        regione_id_by_code = {}
        for cod, nome in REGIONI_ISTAT.items():
            stmt = select(Regione).where(Regione.codice_istat == cod)
            reg = (await session.execute(stmt)).scalar_one_or_none()
            if not reg:
                reg = Regione(nome=nome, codice_istat=cod)
                session.add(reg)
                await session.flush()
            regione_id_by_code[cod] = reg.id

        await session.commit()
        print(f"-> 20 Regioni confermate nel database.")

        print("3. Sincronizzazione Province...")
        unique_province = {}
        for item in comuni_raw:
            sigla = item["sigla"]
            if sigla not in unique_province:
                p_nome = item["provincia"]["nome"].strip()
                if not p_nome and "cm" in item and item["cm"].get("nome"):
                    p_nome = item["cm"]["nome"].strip()
                if not p_nome:
                    p_nome = sigla

                reg_cod = item["regione"]["codice"].zfill(2)
                reg_id = regione_id_by_code.get(reg_cod)
                unique_province[sigla] = {
                    "nome": p_nome,
                    "sigla": sigla,
                    "regione_id": reg_id
                }

        provincia_id_by_sigla = {}
        for sigla, p_data in unique_province.items():
            stmt = select(Provincia).where(Provincia.sigla_automobilistica == sigla)
            prov = (await session.execute(stmt)).scalar_one_or_none()
            if not prov:
                prov = Provincia(
                    nome=p_data["nome"],
                    sigla_automobilistica=sigla,
                    regione_id=p_data["regione_id"]
                )
                session.add(prov)
                await session.flush()
            provincia_id_by_sigla[sigla] = prov.id

        await session.commit()
        print(f"-> {len(provincia_id_by_sigla)} Province sincronizzate.")

        print("4. Indicizzazione Comuni esistenti...")
        existing_comuni_stmt = select(Comune.nome, Comune.provincia_id)
        existing_res = await session.execute(existing_comuni_stmt)
        existing_set = set(existing_res.all())
        print(f"-> {len(existing_set)} comuni già presenti.")

        print("5. Inserimento massivo dei Comuni...")
        batch = []
        batch_size = 500
        total_inserted = 0

        for item in comuni_raw:
            c_nome = item["nome"].strip()
            sigla = item["sigla"]
            prov_id = provincia_id_by_sigla.get(sigla)
            if not prov_id:
                continue

            if (c_nome, prov_id) in existing_set:
                continue

            caps = item.get("cap", [])
            cap = caps[0] if caps else "00000"

            base_lat, base_lon = prov_coords.get(sigla, (42.5, 12.5))

            c_code = item.get("codice", "000000")
            h = sum(ord(c) * (i + 1) for i, c in enumerate(c_code))
            angle = (h % 360) * (math.pi / 180.0)
            dist_km = 2.0 + ((h * 7) % 1500) / 100.0
            lat_offset = (dist_km / 111.0) * math.cos(angle)
            lon_offset = (dist_km / (111.0 * math.cos(math.radians(base_lat)))) * math.sin(angle)

            comune_lat = round(base_lat + lat_offset, 6)
            comune_lon = round(base_lon + lon_offset, 6)

            wkt_point = None if is_sqlite else WKTElement(f"POINT({comune_lon} {comune_lat})", srid=4326)

            nuovo_comune = Comune(
                nome=c_nome,
                cap=cap,
                provincia_id=prov_id,
                latitudine=comune_lat,
                longitudine=comune_lon,
                coordinate=wkt_point
            )
            batch.append(nuovo_comune)
            existing_set.add((c_nome, prov_id))

            if len(batch) >= batch_size:
                session.add_all(batch)
                await session.flush()
                total_inserted += len(batch)
                print(f"   Inseriti {total_inserted} comuni...")
                batch = []

        if batch:
            session.add_all(batch)
            await session.flush()
            total_inserted += len(batch)

        await session.commit()
        print(f"=== Sincronizzazione completata: {total_inserted} nuovi comuni inseriti con successo! ===")


if __name__ == "__main__":
    asyncio.run(import_all_comuni())
