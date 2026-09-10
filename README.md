# 🎯 ArmiMarket Italia

> **Piattaforma Web Asincrona e Modulare per Annunci e Ricerca Geografica di Armi & Accessori di Tiro**  
> Progettata in conformità con la legislazione italiana in materia di Pubblica Sicurezza: **T.U.L.P.S. (Artt. 35-38)**, **Legge 18 aprile 1975 n. 110** e **D.Lgs. 10 agosto 2018 n. 104**.

---

## ⚖️ Conformità Legale & Domain Rules (T.U.L.P.S.)

1. **Nessuna Transazione Economica né E-Commerce Diretto**:
   - La piattaforma è **esclusivamente una bacheca telematica di consultazione e contatto** informativo tra parti autorizzate.
   - Non sono presenti carrelli, gateway di pagamento né logistica integrata.
   - È espressamente richiamato l'Art. 17 della Legge 110/1975 (divieto di vendita per corrispondenza tra privati senza il tramite di un'armeria autorizzata).

2. **Disclaimer di Pubblica Sicurezza Obbligatorio**:
   - Su ogni singola scheda annuncio, nel footer e in ogni payload API viene esposto l'avviso di legge vincolante:
     > *"La compravendita o cessione deve avvenire esclusivamente di persona previa verifica de visu di un titolo di polizia valido (Porto d'Armi / Nulla Osta rilasciato dalla Questura). Obbligo inderogabile di denunciare la variazione di detenzione entro 72 ore presso Carabinieri o Questura (Art. 38 T.U.L.P.S.)."*

3. **Privacy, Sicurezza & Tutela Antifurto**:
   - **Matricole Armi Protette**: la matricola identificativa dell'arma **non viene MAI mostrata in chiaro pubblicamente** né indicizzata, per prevenire frodi, clonazioni o falsificazioni. Viene conservata crittografata/riservata solo per la moderazione di Pubblica Sicurezza.
   - **Geolocalizzazione a Tutela Domiciliare**: per i venditori privati, il marker sulla mappa interattiva è centrato sull'area comunale/CAP (e non sul numero civico di residenza) per scongiurare furti mirati di armi custodite in casa. Per le armerie certificate, il marker corrisponde alla sede commerciale aperta al pubblico.

4. **Filtro Preventivo Anti-Illegalità**:
   - Blocco preventivo automatico (`HTTP 422 Unprocessable Entity`) per annunci contenenti armi da guerra, trasformazioni a raffica/full-auto, silenziatori, canne mozze non bancate o munizionamento perforante/vietato.

---

## 🏗️ Architettura dei 5 Moduli

### 1. Modello Dati Geografico ISTAT & PostGIS
- Tabelle gerarchiche amministrative italiane:
  - `regioni`: id, nome, codice ISTAT ufficiale (20 regioni).
  - `province`: id, nome, sigla automobilistica, regione_id.
  - `comuni`: id, nome, cap, provincia_id, latitudine, longitudine, `coordinate` (Point PostGIS WGS84 SRID 4326).
- **Ricerca per Raggio e Prossimità**:
  - Su PostgreSQL/PostGIS: utilizzo nativo di `ST_DWithin` e `ST_Distance` geodetico con indici spaziali GIST.
  - In ambiente locale/test: calcolo geodetico con formula di Haversine ad alte prestazioni.
- **Seed ISTAT (`scripts/seed_geo.py`)**: inserimento delle 20 regioni, province pilota e comuni strategici (Milano, Brescia, Gardone Val Trompia, Roma, Bologna, Firenze, Urbino, Torino, Napoli, ecc.).

### 2. Modello Annunci & Catalogo
- Modello `Annuncio` (SQLAlchemy 2.0 / Pydantic v2):
  - **Identificativi**: `id`, `titolo`, `slug` SEO-friendly, `descrizione`, `prezzo`, `stato` (`bozza`, `in_moderazione`, `pubblicato`, `venduto`, `archiviato`, `rifiutato`).
  - **Tipologia Venditore**: `armeria`, `privato`.
  - **Specifiche Tecniche Arma**:
    - Tipologia: `arma_corta`, `arma_lunga_rigata`, `canna_liscia`, `aria_compressa_libera`, `aria_compressa_piena`, `accessorio_ottica`.
    - Marca (es. Beretta, Glock, Benelli, CZ, Franchi, Smith & Wesson).
    - Modello (es. 98FS, 17 Gen 5, M4 Super 90, 457 Varmint, BRX1).
    - Calibro (es. 9x21, 9x19 Parabellum, .308 Win, 12/76, .22 LR, .357 Mag).
    - Classificazione: `comune`, `sportiva`, `caccia`, `non_applicabile`.
    - Condizione: `nuovo`, `usato_ottimo`, `usato_buono`, `da_collezione`.
  - **Sicurezza**: `matricola_riservata` (esclusa dai DTO pubblici), contatti con flag privacy telefono.

### 3. API REST FastAPI & Mappa Interattiva
- **Router `/api/v1/geo`**:
  - `GET /regioni`: lista 20 regioni ISTAT.
  - `GET /province?regione_id=...`: province per regione.
  - `GET /comuni?provincia_id=...&q=...`: comuni con autocomplete su nome o CAP.
  - `GET /prossimita?lat=...&lon=...&raggio_km=...`: comuni entro raggio PostGIS.
- **Router `/api/v1/annunci`**:
  - `GET /annunci`: ricerca combinata (full-text, filtri tecnici, filtri ISTAT o raggio lat/lon).
  - `POST /annunci`: creazione annuncio con validazione Pydantic v2.
  - `GET /annunci/{id}`: dettaglio annuncio con contatore visualizzazioni e disclaimers.
  - `POST /annunci/{id}/contatta`: form di contatto con attestazione obbligatoria del titolo valido.
  - `GET /annunci/mappa/geojson`: FeatureCollection per il render cartografico.
- **Viste Web Interattive (Leaflet.js)**:
  - **`/mappa`**: mappa interattiva a schermo intero del territorio italiano. Mostra pin differenziati per armerie e privati. **Cliccando sul marker compare un popup con foto, prezzo, calibro, comune e pulsante diretto alla scheda annuncio**.
  - **`/scheda/{id}`**: scheda tecnica con galleria, disclaimers T.U.L.P.S., modulo contatto e **mappa Leaflet dedicata centrata sulla posizione dell'arma**.
  - **`/`**: home page moderna con filtri rapidi e grid annunci.

### 4. Sistema di Moderazione & Sicurezza
- Gli annunci inseriti da privati passano automaticamente allo stato `in_moderazione`.
- Le armerie verificate possono pubblicare direttamente allo stato `pubblicato`.
- Area riservata admin/moderatori:
  - `GET /api/v1/admin/moderazione`: coda di revisione.
  - `POST /api/v1/admin/moderazione/{id}/approva`: approvazione e pubblicazione.
  - `POST /api/v1/admin/moderazione/{id}/rifiuta`: rifiuto con motivazione tracciata.

### 5. Aggregatore Stock Armerie (Ingestion Layer)
- `BaseGunshopAdapter`: interfaccia per sincronizzare cataloghi esterni (WooCommerce, PrestaShop, gestionali).
- Funzioni di normalizzazione automatica dei brand (es. *"PIETRO BERETTA ARMI"* -> *"Beretta"*) e calibri (es. *"cal 12/76"* -> *"12/76"*, *"308w"* -> *".308 Win"*).
- Script `scripts/import_mock_shop.py`: importa un inventario realistico dimostrativo per un'armeria in provincia di Brescia.

---

## 🚀 Avvio Rapido

### Opzione 1: Con Docker & Docker Compose (Consigliato per Produzione)
Il servizio avvia un container **PostgreSQL 16 con estensione PostGIS 3.4** e il server FastAPI:

```bash
docker-compose up --build
```

L'applicazione sarà immediatamente disponibile su:
- Web App & Mappa: `http://localhost:8000/mappa`
- Documentazione API Swagger: `http://localhost:8000/docs`
- Documentazione ReDoc: `http://localhost:8000/redoc`

### Opzione 2: Sviluppo Locale con Virtualenv

1. **Creazione virtualenv e installazione dipendenze**:
```bash
python3.12 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

2. **Configurazione ambiente**:
```bash
cp .env.example .env
```

3. **Popolamento dati geografici ISTAT e stock di prova**:
```bash
python scripts/seed_geo.py
python scripts/import_mock_shop.py
```

4. **Avvio del server di sviluppo**:
```bash
uvicorn main:app --reload --port 8000
```

---

## 🧪 Esecuzione Suite di Test

I test automatizzati con `pytest` coprono la conformità legale, la ricerca geografica, i filtri di moderazione, il mascheramento delle matricole e le viste web:

```bash
pytest -v
```

Risultato collaudo:
```
tests/test_annunci.py::test_create_annuncio_as_private PASSED            [  9%]
tests/test_annunci.py::test_search_and_map_geojson PASSED                [ 18%]
tests/test_annunci.py::test_annuncio_detail_and_contact_form PASSED      [ 27%]
tests/test_geo.py::test_get_regioni PASSED                               [ 36%]
tests/test_geo.py::test_get_province_by_regione PASSED                   [ 45%]
tests/test_geo.py::test_get_comuni_autocomplete PASSED                   [ 54%]
tests/test_geo.py::test_prossimita_radius_search PASSED                  [ 63%]
tests/test_moderation.py::test_mask_matricola_function PASSED            [ 72%]
tests/test_moderation.py::test_banned_keyword_prevention PASSED          [ 81%]
tests/test_moderation.py::test_admin_moderation_flow PASSED              [ 90%]
tests/test_views.py::test_html_views PASSED                              [100%]

============================= 11 passed in 11.55s ==============================
```
