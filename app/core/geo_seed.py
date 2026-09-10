"""
Anagrafica Geografica Nazionale Ufficiale ISTAT & PostGIS.
Idempotente, non distruttiva, ripetibile:
- Sincronizza 20 Regioni ISTAT ufficiali
- Sincronizza 107 Province ufficiali della Repubblica Italiana
- Mappa e preserva i comuni esistenti assegnando i rispettivi codici ISTAT stabili
- Importa l'elenco completo dei 7.896 comuni italiani ufficiali ISTAT da app/data/comuni_italiani_istat.json
- Calcola le geometrie PostGIS WKTElement(POINT(lon lat), 4326) su PostgreSQL e Point testuale su SQLite.
"""
import json
import logging
from pathlib import Path
from typing import Any, Dict, List, Optional, Set, Tuple

from geoalchemy2.elements import WKTElement
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.core.database import is_sqlite
from app.models.geo import Comune, Provincia, Regione

logger = logging.getLogger("app.geo_seed")

# 20 Regioni ISTAT ufficiali
REGIONI_DATA = [
    {"codice_istat": "01", "nome": "Piemonte"},
    {"codice_istat": "02", "nome": "Valle d'Aosta"},
    {"codice_istat": "03", "nome": "Lombardia"},
    {"codice_istat": "04", "nome": "Trentino-Alto Adige"},
    {"codice_istat": "05", "nome": "Veneto"},
    {"codice_istat": "06", "nome": "Friuli-Venezia Giulia"},
    {"codice_istat": "07", "nome": "Liguria"},
    {"codice_istat": "08", "nome": "Emilia-Romagna"},
    {"codice_istat": "09", "nome": "Toscana"},
    {"codice_istat": "10", "nome": "Umbria"},
    {"codice_istat": "11", "nome": "Marche"},
    {"codice_istat": "12", "nome": "Lazio"},
    {"codice_istat": "13", "nome": "Abruzzo"},
    {"codice_istat": "14", "nome": "Molise"},
    {"codice_istat": "15", "nome": "Campania"},
    {"codice_istat": "16", "nome": "Puglia"},
    {"codice_istat": "17", "nome": "Basilicata"},
    {"codice_istat": "18", "nome": "Calabria"},
    {"codice_istat": "19", "nome": "Sicilia"},
    {"codice_istat": "20", "nome": "Sardegna"},
]

# 107 Province e Città Metropolitane ufficiali della Repubblica Italiana
PROVINCE_DATA = [
    # Piemonte (01)
    {"sigla": "TO", "nome": "Torino", "regione_cod": "01"},
    {"sigla": "VC", "nome": "Vercelli", "regione_cod": "01"},
    {"sigla": "NO", "nome": "Novara", "regione_cod": "01"},
    {"sigla": "CN", "nome": "Cuneo", "regione_cod": "01"},
    {"sigla": "AT", "nome": "Asti", "regione_cod": "01"},
    {"sigla": "AL", "nome": "Alessandria", "regione_cod": "01"},
    {"sigla": "BI", "nome": "Biella", "regione_cod": "01"},
    {"sigla": "VB", "nome": "Verbano-Cusio-Ossola", "regione_cod": "01"},
    # Valle d'Aosta (02)
    {"sigla": "AO", "nome": "Aosta", "regione_cod": "02"},
    # Lombardia (03)
    {"sigla": "VA", "nome": "Varese", "regione_cod": "03"},
    {"sigla": "CO", "nome": "Como", "regione_cod": "03"},
    {"sigla": "SO", "nome": "Sondrio", "regione_cod": "03"},
    {"sigla": "MI", "nome": "Milano", "regione_cod": "03"},
    {"sigla": "BG", "nome": "Bergamo", "regione_cod": "03"},
    {"sigla": "BS", "nome": "Brescia", "regione_cod": "03"},
    {"sigla": "PV", "nome": "Pavia", "regione_cod": "03"},
    {"sigla": "CR", "nome": "Cremona", "regione_cod": "03"},
    {"sigla": "MN", "nome": "Mantova", "regione_cod": "03"},
    {"sigla": "LC", "nome": "Lecco", "regione_cod": "03"},
    {"sigla": "LO", "nome": "Lodi", "regione_cod": "03"},
    {"sigla": "MB", "nome": "Monza e Brianza", "regione_cod": "03"},
    # Trentino-Alto Adige (04)
    {"sigla": "BZ", "nome": "Bolzano", "regione_cod": "04"},
    {"sigla": "TN", "nome": "Trento", "regione_cod": "04"},
    # Veneto (05)
    {"sigla": "VR", "nome": "Verona", "regione_cod": "05"},
    {"sigla": "VI", "nome": "Vicenza", "regione_cod": "05"},
    {"sigla": "BL", "nome": "Belluno", "regione_cod": "05"},
    {"sigla": "TV", "nome": "Treviso", "regione_cod": "05"},
    {"sigla": "VE", "nome": "Venezia", "regione_cod": "05"},
    {"sigla": "PD", "nome": "Padova", "regione_cod": "05"},
    {"sigla": "RO", "nome": "Rovigo", "regione_cod": "05"},
    # Friuli-Venezia Giulia (06)
    {"sigla": "UD", "nome": "Udine", "regione_cod": "06"},
    {"sigla": "GO", "nome": "Gorizia", "regione_cod": "06"},
    {"sigla": "TS", "nome": "Trieste", "regione_cod": "06"},
    {"sigla": "PN", "nome": "Pordenone", "regione_cod": "06"},
    # Liguria (07)
    {"sigla": "IM", "nome": "Imperia", "regione_cod": "07"},
    {"sigla": "SV", "nome": "Savona", "regione_cod": "07"},
    {"sigla": "GE", "nome": "Genova", "regione_cod": "07"},
    {"sigla": "SP", "nome": "La Spezia", "regione_cod": "07"},
    # Emilia-Romagna (08)
    {"sigla": "PC", "nome": "Piacenza", "regione_cod": "08"},
    {"sigla": "PR", "nome": "Parma", "regione_cod": "08"},
    {"sigla": "RE", "nome": "Reggio Emilia", "regione_cod": "08"},
    {"sigla": "MO", "nome": "Modena", "regione_cod": "08"},
    {"sigla": "BO", "nome": "Bologna", "regione_cod": "08"},
    {"sigla": "FE", "nome": "Ferrara", "regione_cod": "08"},
    {"sigla": "RA", "nome": "Ravenna", "regione_cod": "08"},
    {"sigla": "FC", "nome": "Forlì-Cesena", "regione_cod": "08"},
    {"sigla": "RN", "nome": "Rimini", "regione_cod": "08"},
    # Toscana (09)
    {"sigla": "MS", "nome": "Massa-Carrara", "regione_cod": "09"},
    {"sigla": "LU", "nome": "Lucca", "regione_cod": "09"},
    {"sigla": "PT", "nome": "Pistoia", "regione_cod": "09"},
    {"sigla": "FI", "nome": "Firenze", "regione_cod": "09"},
    {"sigla": "LI", "nome": "Livorno", "regione_cod": "09"},
    {"sigla": "PI", "nome": "Pisa", "regione_cod": "09"},
    {"sigla": "AR", "nome": "Arezzo", "regione_cod": "09"},
    {"sigla": "SI", "nome": "Siena", "regione_cod": "09"},
    {"sigla": "GR", "nome": "Grosseto", "regione_cod": "09"},
    {"sigla": "PO", "nome": "Prato", "regione_cod": "09"},
    # Umbria (10)
    {"sigla": "PG", "nome": "Perugia", "regione_cod": "10"},
    {"sigla": "TR", "nome": "Terni", "regione_cod": "10"},
    # Marche (11)
    {"sigla": "PU", "nome": "Pesaro e Urbino", "regione_cod": "11"},
    {"sigla": "AN", "nome": "Ancona", "regione_cod": "11"},
    {"sigla": "MC", "nome": "Macerata", "regione_cod": "11"},
    {"sigla": "AP", "nome": "Ascoli Piceno", "regione_cod": "11"},
    {"sigla": "FM", "nome": "Fermo", "regione_cod": "11"},
    # Lazio (12)
    {"sigla": "VT", "nome": "Viterbo", "regione_cod": "12"},
    {"sigla": "RI", "nome": "Rieti", "regione_cod": "12"},
    {"sigla": "RM", "nome": "Roma", "regione_cod": "12"},
    {"sigla": "LT", "nome": "Latina", "regione_cod": "12"},
    {"sigla": "FR", "nome": "Frosinone", "regione_cod": "12"},
    # Abruzzo (13)
    {"sigla": "AQ", "nome": "L'Aquila", "regione_cod": "13"},
    {"sigla": "TE", "nome": "Teramo", "regione_cod": "13"},
    {"sigla": "PE", "nome": "Pescara", "regione_cod": "13"},
    {"sigla": "CH", "nome": "Chieti", "regione_cod": "13"},
    # Molise (14)
    {"sigla": "CB", "nome": "Campobasso", "regione_cod": "14"},
    {"sigla": "IS", "nome": "Isernia", "regione_cod": "14"},
    # Campania (15)
    {"sigla": "CE", "nome": "Caserta", "regione_cod": "15"},
    {"sigla": "BN", "nome": "Benevento", "regione_cod": "15"},
    {"sigla": "NA", "nome": "Napoli", "regione_cod": "15"},
    {"sigla": "AV", "nome": "Avellino", "regione_cod": "15"},
    {"sigla": "SA", "nome": "Salerno", "regione_cod": "15"},
    # Puglia (16)
    {"sigla": "FG", "nome": "Foggia", "regione_cod": "16"},
    {"sigla": "BA", "nome": "Bari", "regione_cod": "16"},
    {"sigla": "TA", "nome": "Taranto", "regione_cod": "16"},
    {"sigla": "BR", "nome": "Brindisi", "regione_cod": "16"},
    {"sigla": "LE", "nome": "Lecce", "regione_cod": "16"},
    {"sigla": "BT", "nome": "Barletta-Andria-Trani", "regione_cod": "16"},
    # Basilicata (17)
    {"sigla": "PZ", "nome": "Potenza", "regione_cod": "17"},
    {"sigla": "MT", "nome": "Matera", "regione_cod": "17"},
    # Calabria (18)
    {"sigla": "CS", "nome": "Cosenza", "regione_cod": "18"},
    {"sigla": "CZ", "nome": "Catanzaro", "regione_cod": "18"},
    {"sigla": "RC", "nome": "Reggio Calabria", "regione_cod": "18"},
    {"sigla": "KR", "nome": "Crotone", "regione_cod": "18"},
    {"sigla": "VV", "nome": "Vibo Valentia", "regione_cod": "18"},
    # Sicilia (19)
    {"sigla": "TP", "nome": "Trapani", "regione_cod": "19"},
    {"sigla": "PA", "nome": "Palermo", "regione_cod": "19"},
    {"sigla": "ME", "nome": "Messina", "regione_cod": "19"},
    {"sigla": "AG", "nome": "Agrigento", "regione_cod": "19"},
    {"sigla": "CL", "nome": "Caltanissetta", "regione_cod": "19"},
    {"sigla": "EN", "nome": "Enna", "regione_cod": "19"},
    {"sigla": "CT", "nome": "Catania", "regione_cod": "19"},
    {"sigla": "RG", "nome": "Ragusa", "regione_cod": "19"},
    {"sigla": "SR", "nome": "Siracusa", "regione_cod": "19"},
    # Sardegna (20)
    {"sigla": "SS", "nome": "Sassari", "regione_cod": "20"},
    {"sigla": "NU", "nome": "Nuoro", "regione_cod": "20"},
    {"sigla": "CA", "nome": "Cagliari", "regione_cod": "20"},
    {"sigla": "OR", "nome": "Oristano", "regione_cod": "20"},
    {"sigla": "SU", "nome": "Sud Sardegna", "regione_cod": "20"},
]

# Mappatura varianti toponomastiche per record esistenti verso ISTAT ufficiale
NAME_VARIANTS_TO_ISTAT = {
    ("reggio emilia", "RE"): "035033",      # ISTAT: Reggio nell'Emilia
    ("reggio calabria", "RC"): "080063",    # ISTAT: Reggio di Calabria
    ("gardone val trompia", "BS"): "017075",
    ("urbino", "PU"): "041067",
}


async def seed_geo_if_empty(session: AsyncSession) -> Dict[str, Any]:
    """
    Popola l'anagrafica geografica ISTAT in modo strettamente idempotente e non distruttivo:
    1. 20 Regioni ISTAT
    2. 107 Province ufficiali
    3. Mappatura e arricchimento dei comuni già presenti nel DB con i loro codici ISTAT stabili
    4. Inserimento batch dei comuni mancanti dal dataset ufficiale app/data/comuni_italiani_istat.json
    Nessun dato esistente viene cancellato, duplicato o alterato.
    """
    logger.info("Inizio verifica e sincronizzazione anagrafica geografica ISTAT / PostGIS...")
    is_session_sqlite = session.bind.dialect.name == "sqlite" if session.bind else is_sqlite

    # 1. Sincronizzazione Regioni
    regione_map_by_codice: Dict[str, int] = {}
    stmt_reg = select(Regione)
    existing_regioni = (await session.execute(stmt_reg)).scalars().all()
    for reg in existing_regioni:
        regione_map_by_codice[reg.codice_istat] = reg.id

    inserted_regioni = 0
    for reg_data in REGIONI_DATA:
        if reg_data["codice_istat"] not in regione_map_by_codice:
            nuova_reg = Regione(
                nome=reg_data["nome"],
                codice_istat=reg_data["codice_istat"]
            )
            session.add(nuova_reg)
            await session.flush()
            regione_map_by_codice[reg_data["codice_istat"]] = nuova_reg.id
            inserted_regioni += 1

    # 2. Sincronizzazione Province (107)
    provincia_map_by_sigla: Dict[str, int] = {}
    stmt_prov = select(Provincia)
    existing_province = (await session.execute(stmt_prov)).scalars().all()
    for prov in existing_province:
        provincia_map_by_sigla[prov.sigla_automobilistica] = prov.id

    inserted_province = 0
    for prov_data in PROVINCE_DATA:
        sigla = prov_data["sigla"]
        if sigla not in provincia_map_by_sigla:
            reg_id = regione_map_by_codice.get(prov_data["regione_cod"])
            if not reg_id:
                continue
            nuova_prov = Provincia(
                nome=prov_data["nome"],
                sigla_automobilistica=sigla,
                regione_id=reg_id
            )
            session.add(nuova_prov)
            await session.flush()
            provincia_map_by_sigla[sigla] = nuova_prov.id
            inserted_province += 1

    # 3. Mappatura Comuni Esistenti
    stmt_existing = select(Comune).options(selectinload(Comune.provincia))
    existing_comuni_list = (await session.execute(stmt_existing)).scalars().all()

    existing_by_code: Dict[str, Comune] = {}
    existing_by_name_sigla: Dict[Tuple[str, str], Comune] = {}

    for c in existing_comuni_list:
        sigla = c.provincia.sigla_automobilistica.upper() if c.provincia else None
        if c.codice_istat:
            existing_by_code[c.codice_istat] = c
        if sigla:
            existing_by_name_sigla[(c.nome.lower().strip(), sigla)] = c

    # Arricchimento varianti toponomastiche dei comuni già esistenti (es. Reggio Emilia -> 035033)
    updated_existing_count = 0
    for (var_nome, var_sigla), istat_cod in NAME_VARIANTS_TO_ISTAT.items():
        key = (var_nome.lower(), var_sigla.upper())
        if key in existing_by_name_sigla:
            c = existing_by_name_sigla[key]
            if not c.codice_istat:
                c.codice_istat = istat_cod
                existing_by_code[istat_cod] = c
                updated_existing_count += 1

    # 4. Caricamento Dataset Completo Ufficiale ISTAT
    dataset_file = Path("app/data/comuni_italiani_istat.json")
    if not dataset_file.is_file():
        # Fallback percorso alternativo se eseguito da directory annidata
        alt_path = Path(__file__).resolve().parent.parent / "data" / "comuni_italiani_istat.json"
        if alt_path.is_file():
            dataset_file = alt_path

    inserted_comuni = 0
    matched_existing_count = 0

    if dataset_file.is_file():
        logger.info(f"Caricamento dataset ISTAT da {dataset_file}...")
        with open(dataset_file, "r", encoding="utf-8") as f:
            full_dataset = json.load(f)

        batch: List[Comune] = []
        batch_size = 500

        for item in full_dataset:
            istat_code = str(item["codice_istat"]).strip().zfill(6)
            nome = str(item["nome"]).strip()
            sigla = str(item["sigla_provincia"]).strip().upper()
            cap = str(item["cap"]).strip()[:5]
            lat = float(item["lat"])
            lon = float(item["lon"])

            prov_id = provincia_map_by_sigla.get(sigla)
            if not prov_id:
                logger.warning(f"Provincia con sigla {sigla} non trovata per comune {nome} ({istat_code}).")
                continue

            # Verifica se già presente nel DB (tramite codice ISTAT o coppia nome+provincia)
            existing_com = (
                existing_by_code.get(istat_code)
                or existing_by_name_sigla.get((nome.lower().strip(), sigla))
            )

            if existing_com:
                matched_existing_count += 1
                # Aggiorna codice ISTAT se era mancante nel record preesistente
                if not existing_com.codice_istat:
                    existing_com.codice_istat = istat_code
                    existing_by_code[istat_code] = existing_com
                    updated_existing_count += 1
                continue

            # Nuovo comune da inserire
            point = (
                f"POINT({lon} {lat})"
                if is_session_sqlite
                else WKTElement(f"POINT({lon} {lat})", srid=4326)
            )
            nuovo_comune = Comune(
                nome=nome,
                codice_istat=istat_code,
                cap=cap,
                provincia_id=prov_id,
                latitudine=lat,
                longitudine=lon,
                coordinate=point
            )
            batch.append(nuovo_comune)
            existing_by_code[istat_code] = nuovo_comune
            existing_by_name_sigla[(nome.lower().strip(), sigla)] = nuovo_comune

            if len(batch) >= batch_size:
                session.add_all(batch)
                await session.flush()
                inserted_comuni += len(batch)
                batch = []

        if batch:
            session.add_all(batch)
            await session.flush()
            inserted_comuni += len(batch)
            batch = []

    await session.commit()

    total_reg = (await session.execute(select(func.count(Regione.id)))).scalar() or 0
    total_prov = (await session.execute(select(func.count(Provincia.id)))).scalar() or 0
    total_comuni = (await session.execute(select(func.count(Comune.id)))).scalar() or 0

    logger.info(
        f"Anagrafica Geografica ISTAT sincronizzata con successo: "
        f"{total_reg} Regioni, {total_prov} Province, {total_comuni} Comuni. "
        f"(Nuovi inseriti: {inserted_comuni}, Preesistenti mappati/aggiornati: {matched_existing_count})"
    )

    return {
        "regioni": total_reg,
        "province": total_prov,
        "comuni": total_comuni,
        "inserted_regioni": inserted_regioni,
        "inserted_province": inserted_province,
        "inserted_comuni": inserted_comuni,
        "updated_existing_count": updated_existing_count,
        "matched_existing_count": matched_existing_count,
    }
