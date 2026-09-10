import asyncio
import os
import sys
from pathlib import Path

# Aggiungi cartella radice al PYTHONPATH
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from geoalchemy2.elements import WKTElement
from sqlalchemy import select
from app.core.database import Base, async_session_factory, engine
from app.core.security import hash_password
from app.models.annuncio import (
    Annuncio,
    ClassificazioneArma,
    CondizioneArma,
    StatoAnnuncio,
    TipologiaArma,
    TipologiaInserzionista,
)
from app.models.geo import Comune, Provincia, Regione
from app.models.user import RuoloUtente, User

# Le 20 Regioni d'Italia con codici ISTAT ufficiali
REGIONI_DATA = [
    {"nome": "Piemonte", "codice_istat": "01"},
    {"nome": "Valle d'Aosta", "codice_istat": "02"},
    {"nome": "Lombardia", "codice_istat": "03"},
    {"nome": "Trentino-Alto Adige", "codice_istat": "04"},
    {"nome": "Veneto", "codice_istat": "05"},
    {"nome": "Friuli-Venezia Giulia", "codice_istat": "06"},
    {"nome": "Liguria", "codice_istat": "07"},
    {"nome": "Emilia-Romagna", "codice_istat": "08"},
    {"nome": "Toscana", "codice_istat": "09"},
    {"nome": "Umbria", "codice_istat": "10"},
    {"nome": "Marche", "codice_istat": "11"},
    {"nome": "Lazio", "codice_istat": "12"},
    {"nome": "Abruzzo", "codice_istat": "13"},
    {"nome": "Molise", "codice_istat": "14"},
    {"nome": "Campania", "codice_istat": "15"},
    {"nome": "Puglia", "codice_istat": "16"},
    {"nome": "Basilicata", "codice_istat": "17"},
    {"nome": "Calabria", "codice_istat": "18"},
    {"nome": "Sicilia", "codice_istat": "19"},
    {"nome": "Sardegna", "codice_istat": "20"},
]

# Province pilota con associazione regione
PROVINCE_DATA = [
    # Lombardia
    {"nome": "Milano", "sigla": "MI", "regione": "Lombardia"},
    {"nome": "Brescia", "sigla": "BS", "regione": "Lombardia"},
    {"nome": "Bergamo", "sigla": "BG", "regione": "Lombardia"},
    # Lazio
    {"nome": "Roma", "sigla": "RM", "regione": "Lazio"},
    {"nome": "Latina", "sigla": "LT", "regione": "Lazio"},
    # Piemonte
    {"nome": "Torino", "sigla": "TO", "regione": "Piemonte"},
    # Veneto
    {"nome": "Verona", "sigla": "VR", "regione": "Veneto"},
    {"nome": "Vicenza", "sigla": "VI", "regione": "Veneto"},
    # Emilia-Romagna
    {"nome": "Bologna", "sigla": "BO", "regione": "Emilia-Romagna"},
    {"nome": "Parma", "sigla": "PR", "regione": "Emilia-Romagna"},
    # Toscana
    {"nome": "Firenze", "sigla": "FI", "regione": "Toscana"},
    # Marche
    {"nome": "Pesaro e Urbino", "sigla": "PU", "regione": "Marche"},
    # Campania
    {"nome": "Napoli", "sigla": "NA", "regione": "Campania"},
    {"nome": "Salerno", "sigla": "SA", "regione": "Campania"},
    # Puglia
    {"nome": "Bari", "sigla": "BA", "regione": "Puglia"},
    # Sicilia
    {"nome": "Palermo", "sigla": "PA", "regione": "Sicilia"},
    {"nome": "Catania", "sigla": "CT", "regione": "Sicilia"},
    # Sardegna
    {"nome": "Cagliari", "sigla": "CA", "regione": "Sardegna"},
    # Liguria
    {"nome": "Genova", "sigla": "GE", "regione": "Liguria"},
    # Trentino-Alto Adige
    {"nome": "Trento", "sigla": "TN", "regione": "Trentino-Alto Adige"},
]

# Comuni pilota con coordinate reali WGS84
COMUNI_DATA = [
    {"nome": "Gardone Val Trompia", "cap": "25063", "provincia": "BS", "lat": 45.6936, "lon": 10.1839},
    {"nome": "Brescia", "cap": "25121", "provincia": "BS", "lat": 45.5416, "lon": 10.2118},
    {"nome": "Milano", "cap": "20121", "provincia": "MI", "lat": 45.4642, "lon": 9.1900},
    {"nome": "Monza", "cap": "20900", "provincia": "MI", "lat": 45.5845, "lon": 9.2744},
    {"nome": "Roma", "cap": "00187", "provincia": "RM", "lat": 41.9028, "lon": 12.4964},
    {"nome": "Torino", "cap": "10121", "provincia": "TO", "lat": 45.0703, "lon": 7.6869},
    {"nome": "Bologna", "cap": "40121", "provincia": "BO", "lat": 44.4949, "lon": 11.3426},
    {"nome": "Firenze", "cap": "50121", "provincia": "FI", "lat": 43.7696, "lon": 11.2558},
    {"nome": "Urbino", "cap": "61029", "provincia": "PU", "lat": 43.7262, "lon": 12.6366},
    {"nome": "Verona", "cap": "37121", "provincia": "VR", "lat": 45.4384, "lon": 10.9916},
    {"nome": "Napoli", "cap": "80121", "provincia": "NA", "lat": 40.8518, "lon": 14.2681},
    {"nome": "Bari", "cap": "70121", "provincia": "BA", "lat": 41.1171, "lon": 16.8719},
    {"nome": "Palermo", "cap": "90121", "provincia": "PA", "lat": 38.1157, "lon": 13.3615},
    {"nome": "Genova", "cap": "16121", "provincia": "GE", "lat": 44.4056, "lon": 8.9463},
]


async def seed_database():
    print("Inizializzazione schema database...")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    async with async_session_factory() as session:
        print("Popolamento Regioni ISTAT...")
        regione_map = {}
        for reg in REGIONI_DATA:
            stmt = select(Regione).where(Regione.nome == reg["nome"])
            existing = (await session.execute(stmt)).scalar_one_or_none()
            if not existing:
                nuova_reg = Regione(nome=reg["nome"], codice_istat=reg["codice_istat"])
                session.add(nuova_reg)
                await session.flush()
                regione_map[reg["nome"]] = nuova_reg.id
            else:
                regione_map[reg["nome"]] = existing.id

        print(f"-> {len(regione_map)} Regioni sincronizzate.")

        print("Popolamento Province pilota...")
        provincia_map = {}
        for prov in PROVINCE_DATA:
            reg_id = regione_map.get(prov["regione"])
            if not reg_id:
                continue
            stmt = select(Provincia).where(Provincia.sigla_automobilistica == prov["sigla"])
            existing = (await session.execute(stmt)).scalar_one_or_none()
            if not existing:
                nuova_prov = Provincia(
                    nome=prov["nome"],
                    sigla_automobilistica=prov["sigla"],
                    regione_id=reg_id,
                )
                session.add(nuova_prov)
                await session.flush()
                provincia_map[prov["sigla"]] = nuova_prov.id
            else:
                provincia_map[prov["sigla"]] = existing.id

        print(f"-> {len(provincia_map)} Province sincronizzate.")

        is_sqlite = "sqlite" in engine.url.drivername
        print("Popolamento Comuni pilota con coordinate PostGIS...")
        comuni_map = {}
        for c in COMUNI_DATA:
            prov_id = provincia_map.get(c["provincia"])
            if not prov_id:
                continue
            stmt = select(Comune).where(Comune.nome == c["nome"], Comune.provincia_id == prov_id)
            existing = (await session.execute(stmt)).scalar_one_or_none()
            wkt_point = None if is_sqlite else WKTElement(f"POINT({c['lon']} {c['lat']})", srid=4326)
            if not existing:
                nuovo_comune = Comune(
                    nome=c["nome"],
                    cap=c["cap"],
                    provincia_id=prov_id,
                    latitudine=c["lat"],
                    longitudine=c["lon"],
                    coordinate=wkt_point,
                )
                session.add(nuovo_comune)
                await session.flush()
                comuni_map[c["nome"]] = nuovo_comune.id
            else:
                comuni_map[c["nome"]] = existing.id

        print(f"-> {len(comuni_map)} Comuni sincronizzati con coordinate geografiche.")

        # Inserimento Utenti Pilota (Armeria Certificata e Privato con Licenza)
        print("Creazione utenti di prova (Armeria Partner & Privato)...")
        stmt_shop = select(User).where(User.email == "armeria.valtrompia@example.it")
        armeria = (await session.execute(stmt_shop)).scalar_one_or_none()
        if not armeria:
            armeria = User(
                email="armeria.valtrompia@example.it",
                hashed_password=hash_password("ArmeriaValTrompia2026!"),
                nome="Armeria",
                cognome="Val Trompia",
                ragione_sociale="Armeria Val Trompia S.r.l.",
                partita_iva="01234567890",
                licenza_tulps="LIC-PS-BS-2024-889",
                ruolo=RuoloUtente.ARMERIA,
                telefono="+39 030 8912345",
                is_active=True,
                is_verified=True,
            )
            session.add(armeria)
            await session.flush()

        stmt_privato = select(User).where(User.email == "mario.rossi.sport@example.it")
        privato = (await session.execute(stmt_privato)).scalar_one_or_none()
        if not privato:
            privato = User(
                email="mario.rossi.sport@example.it",
                hashed_password=hash_password("MarioRossiTiro2026!"),
                nome="Mario",
                cognome="Rossi",
                codice_fiscale="RSSMRA80A01F205X",
                ruolo=RuoloUtente.PRIVATO,
                telefono="+39 340 1234567",
                is_active=True,
                is_verified=True,
            )
            session.add(privato)
            await session.flush()

        # Inserimento Annunci Pilota per collaudo Mappa & Ricerca
        print("Inserimento annunci pilota dimostrativi...")
        gardone_id = comuni_map.get("Gardone Val Trompia", 1)
        milano_id = comuni_map.get("Milano", 1)
        urbino_id = comuni_map.get("Urbino", 1)
        roma_id = comuni_map.get("Roma", 1)

        annunci_demo = [
            {
                "titolo": "Beretta 98FS Calibro 9x21 - Nuova di Fabbrica",
                "slug": "beretta-98fs-calibro-9x21-nuova-di-fabbrica-demo1",
                "descrizione": "Pistola semiautomatica Beretta 98FS in calibro 9x21 IMI. Canna da 4.9 pollici, fusto in lega leggera anodizzata, carrello in acciaio Bruniton. Dotata di due caricatori da 15 colpi, valigetta rigida originale e scovoli di pulizia. Disponibile in visione presso la nostra armeria.",
                "prezzo": 850.0,
                "stato": StatoAnnuncio.PUBBLICATO,
                "tipologia_inserzionista": TipologiaInserzionista.ARMERIA,
                "tipologia_arma": TipologiaArma.ARMA_CORTA,
                "marca": "Beretta",
                "modello": "98FS",
                "calibro": "9x21",
                "classificazione": ClassificazioneArma.COMUNE,
                "condizione": CondizioneArma.NUOVO,
                "matricola": "BER98FS2026",
                "comune_id": gardone_id,
                "utente_id": armeria.id,
                "immagini": ["https://images.unsplash.com/photo-1595590424283-b8f17842773f?w=800&q=80"],
                "email": armeria.email,
                "tel": armeria.telefono,
            },
            {
                "titolo": "Benelli M4 Super 90 Canna 47cm Calibro 12/76",
                "slug": "benelli-m4-super-90-canna-47cm-calibro-1276-demo2",
                "descrizione": "Fucile semiautomatico a presa di gas Benelli M4 Super 90 con sistema A.R.G.O., camerato magnum 12/76. Calcio telescopico regolabile, slitta Picatinny superiore con mire Ghost Ring al trizio. Utilizzato pochissimo per tiro dinamico sportivo.",
                "prezzo": 1750.0,
                "stato": StatoAnnuncio.PUBBLICATO,
                "tipologia_inserzionista": TipologiaInserzionista.PRIVATO,
                "tipologia_arma": TipologiaArma.CANNA_LISCIA,
                "marca": "Benelli",
                "modello": "M4 Super 90",
                "calibro": "12/76",
                "classificazione": ClassificazioneArma.CACCIA,
                "condizione": CondizioneArma.USATO_OTTIMO,
                "matricola": "BNM48932026",
                "comune_id": urbino_id,
                "utente_id": privato.id,
                "immagini": ["https://images.unsplash.com/photo-1584281722572-888915003c20?w=800&q=80"],
                "email": privato.email,
                "tel": "+39 340 9876543",
            },
            {
                "titolo": "Glock 17 Gen 5 Calibro 9x19 Parabellum",
                "slug": "glock-17-gen-5-calibro-9x19-parabellum-demo3",
                "descrizione": "Pistola semiautomatica Glock 17 quinta generazione, calibro 9x19. Canna Marksman (GMB), finitura nDLC antiriflesso e anticorrosione, pulsante sgancio caricatore reversibile e leva arresto otturatore ambidestra. Corredo completo con dorsalini intercambiabili.",
                "prezzo": 680.0,
                "stato": StatoAnnuncio.PUBBLICATO,
                "tipologia_inserzionista": TipologiaInserzionista.ARMERIA,
                "tipologia_arma": TipologiaArma.ARMA_CORTA,
                "marca": "Glock",
                "modello": "17 Gen 5",
                "calibro": "9x19 Parabellum",
                "classificazione": ClassificazioneArma.SPORTIVA,
                "condizione": CondizioneArma.NUOVO,
                "matricola": "GLK17G5892",
                "comune_id": milano_id,
                "utente_id": armeria.id,
                "immagini": ["https://images.unsplash.com/photo-1585589074491-38e9a2631557?w=800&q=80"],
                "email": armeria.email,
                "tel": armeria.telefono,
            },
            {
                "titolo": "Carabina CZ 457 Varmint Calibro .22 LR per Tiro di Precisione",
                "slug": "carabina-cz-457-varmint-calibro-22-lr-tiro-precisione-demo4",
                "descrizione": "Carabina a otturatore girevole scorrevole bolt-action CZ 457 Varmint in calibro .22 Long Rifle. Canna pesante scanalata da 20 pollici, calcio in noce selezionato, scatto regolabile tra 8 e 15 N. Ideale per la disciplina Production rimfire.",
                "prezzo": 620.0,
                "stato": StatoAnnuncio.PUBBLICATO,
                "tipologia_inserzionista": TipologiaInserzionista.PRIVATO,
                "tipologia_arma": TipologiaArma.ARMA_LUNGA_RIGATA,
                "marca": "CZ",
                "modello": "457 Varmint",
                "calibro": ".22 LR",
                "classificazione": ClassificazioneArma.SPORTIVA,
                "condizione": CondizioneArma.USATO_OTTIMO,
                "matricola": "CZ45799120",
                "comune_id": roma_id,
                "utente_id": privato.id,
                "immagini": ["https://images.unsplash.com/photo-1547628641-ec2098bb5812?w=800&q=80"],
                "email": privato.email,
                "tel": privato.telefono,
            }
        ]

        for ad_data in annunci_demo:
            stmt = select(Annuncio).where(Annuncio.slug == ad_data["slug"])
            existing_ad = (await session.execute(stmt)).scalar_one_or_none()
            if not existing_ad:
                new_ad = Annuncio(
                    titolo=ad_data["titolo"],
                    slug=ad_data["slug"],
                    descrizione=ad_data["descrizione"],
                    prezzo=ad_data["prezzo"],
                    stato=ad_data["stato"],
                    tipologia_inserzionista=ad_data["tipologia_inserzionista"],
                    tipologia_arma=ad_data["tipologia_arma"],
                    marca=ad_data["marca"],
                    modello=ad_data["modello"],
                    calibro=ad_data["calibro"],
                    classificazione=ad_data["classificazione"],
                    condizione=ad_data["condizione"],
                    matricola_riservata=ad_data["matricola"],
                    comune_id=ad_data["comune_id"],
                    utente_id=ad_data["utente_id"],
                    galleria_immagini=ad_data["immagini"],
                    email_contatto=ad_data["email"],
                    telefono_contatto=ad_data["tel"],
                    mostra_telefono_pubblico=True,
                )
                session.add(new_ad)

        await session.commit()
        print("Popolamento mock completato con successo!")


if __name__ == "__main__":
    asyncio.run(seed_database())
