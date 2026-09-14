import re
from typing import Any, Dict, List, Optional, Tuple
from sqlalchemy import desc, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.core.legal import LEGAL_DISCLAIMER_FOOTER
from app.models.annuncio import (
    Annuncio,
    ClassificazioneArma,
    CondizioneArma,
    StatoAnnuncio,
    TipologiaArma,
    TipologiaInserzionista,
)
from app.models.geo import Comune, Provincia, Regione
from app.models.poligono import PoligonoTiro
from app.models.user import RuoloUtente, User
from app.schemas.annuncio_schema import (
    AnnuncioPublicOut,
    ComuneOut,
    GeoJSONFeature,
    GeoJSONFeatureCollection,
    GeoJSONGeometry,
    GeoJSONProperties,
)
from app.services.geo_service import GeoService


class SearchService:
    @staticmethod
    async def search_annunci(
        db: AsyncSession,
        q: Optional[str] = None,
        regione_id: Optional[int] = None,
        provincia_id: Optional[int] = None,
        comune_id: Optional[int] = None,
        lat: Optional[float] = None,
        lon: Optional[float] = None,
        raggio_km: Optional[float] = None,
        tipologia_inserzionista: Optional[TipologiaInserzionista] = None,
        tipologia_arma: Optional[TipologiaArma] = None,
        marca: Optional[str] = None,
        calibro: Optional[str] = None,
        classificazione: Optional[ClassificazioneArma] = None,
        condizione: Optional[CondizioneArma] = None,
        prezzo_min: Optional[float] = None,
        prezzo_max: Optional[float] = None,
        ordina_per: str = "data_desc",
        pagina: int = 1,
        elementi_per_pagina: int = 20,
        solo_pubblicati: bool = True
    ) -> Tuple[List[AnnuncioPublicOut], int]:
        """
        Motore di ricerca avanzato che combina filtri testuali, gerarchici,
        filtri di prossimità PostGIS e parametri tecnici dell'arma.
        """
        # Mappa delle distanze per comune_id se la ricerca geolocalizzata è attiva
        distanze_comuni: Dict[int, float] = {}

        # 1. Risoluzione Prossimità Geografica (PostGIS) se fornite coordinate
        comuni_in_raggio_ids: Optional[List[int]] = None
        if lat is not None and lon is not None and raggio_km is not None:
            comuni_distanze = await GeoService.get_comuni_entro_raggio(
                db=db,
                lat=lat,
                lon=lon,
                raggio_km=raggio_km
            )
            distanze_comuni = {c.id: dist for c, dist in comuni_distanze}
            comuni_in_raggio_ids = list(distanze_comuni.keys())
            if not comuni_in_raggio_ids:
                # Nessun comune nel raggio -> 0 risultati
                return [], 0

        # 2. Costruzione Query Base
        stmt = (
            select(Annuncio)
            .join(Comune, Annuncio.comune_id == Comune.id)
            .join(Provincia, Comune.provincia_id == Provincia.id)
            .options(
                selectinload(Annuncio.comune).selectinload(Comune.provincia).selectinload(Provincia.regione),
                selectinload(Annuncio.utente)
            )
        )

        count_stmt = (
            select(func.count(Annuncio.id))
            .join(Comune, Annuncio.comune_id == Comune.id)
            .join(Provincia, Comune.provincia_id == Provincia.id)
        )

        # 3. Applicazione Filtri di Stato
        if solo_pubblicati:
            stmt = stmt.where(Annuncio.stato == StatoAnnuncio.PUBBLICATO)
            count_stmt = count_stmt.where(Annuncio.stato == StatoAnnuncio.PUBBLICATO)

        # 4. Filtro Testo Libero (Full-Text Search)
        if q and q.strip():
            query_str = f"%{q.strip()}%"
            text_filter = or_(
                Annuncio.titolo.ilike(query_str),
                Annuncio.descrizione.ilike(query_str),
                Annuncio.marca.ilike(query_str),
                Annuncio.modello.ilike(query_str),
                Annuncio.calibro.ilike(query_str),
            )
            stmt = stmt.where(text_filter)
            count_stmt = count_stmt.where(text_filter)

        # 5. Filtro Geografico Gerarchico o Prossimità
        if comuni_in_raggio_ids is not None:
            stmt = stmt.where(Annuncio.comune_id.in_(comuni_in_raggio_ids))
            count_stmt = count_stmt.where(Annuncio.comune_id.in_(comuni_in_raggio_ids))
        else:
            if comune_id is not None:
                stmt = stmt.where(Annuncio.comune_id == comune_id)
                count_stmt = count_stmt.where(Annuncio.comune_id == comune_id)
            elif provincia_id is not None:
                stmt = stmt.where(Comune.provincia_id == provincia_id)
                count_stmt = count_stmt.where(Comune.provincia_id == provincia_id)
            elif regione_id is not None:
                stmt = stmt.where(Provincia.regione_id == regione_id)
                count_stmt = count_stmt.where(Provincia.regione_id == regione_id)

        # 6. Filtri Specifici Arma & Tipologia Inserzionista
        if tipologia_inserzionista:
            stmt = stmt.where(Annuncio.tipologia_inserzionista == tipologia_inserzionista)
            count_stmt = count_stmt.where(Annuncio.tipologia_inserzionista == tipologia_inserzionista)

        if tipologia_arma:
            stmt = stmt.where(Annuncio.tipologia_arma == tipologia_arma)
            count_stmt = count_stmt.where(Annuncio.tipologia_arma == tipologia_arma)

        if marca and marca.strip():
            stmt = stmt.where(Annuncio.marca.ilike(f"%{marca.strip()}%"))
            count_stmt = count_stmt.where(Annuncio.marca.ilike(f"%{marca.strip()}%"))

        if calibro and calibro.strip():
            stmt = stmt.where(Annuncio.calibro.ilike(f"%{calibro.strip()}%"))
            count_stmt = count_stmt.where(Annuncio.calibro.ilike(f"%{calibro.strip()}%"))

        if classificazione:
            stmt = stmt.where(Annuncio.classificazione == classificazione)
            count_stmt = count_stmt.where(Annuncio.classificazione == classificazione)

        if condizione:
            stmt = stmt.where(Annuncio.condizione == condizione)
            count_stmt = count_stmt.where(Annuncio.condizione == condizione)

        if prezzo_min is not None:
            stmt = stmt.where(Annuncio.prezzo >= prezzo_min)
            count_stmt = count_stmt.where(Annuncio.prezzo >= prezzo_min)

        if prezzo_max is not None:
            stmt = stmt.where(Annuncio.prezzo <= prezzo_max)
            count_stmt = count_stmt.where(Annuncio.prezzo <= prezzo_max)

        # 7. Conteggio Totale
        total_res = await db.execute(count_stmt)
        totale = total_res.scalar() or 0

        # 8. Ordinamento
        if ordina_per == "prezzo_asc":
            stmt = stmt.order_by(Annuncio.prezzo.asc(), Annuncio.id.desc())
        elif ordina_per == "prezzo_desc":
            stmt = stmt.order_by(Annuncio.prezzo.desc(), Annuncio.id.desc())
        else:
            # Default: più recenti prima
            stmt = stmt.order_by(Annuncio.data_creazione.desc(), Annuncio.id.desc())

        # 9. Paginazione
        offset = (pagina - 1) * elementi_per_pagina
        stmt = stmt.offset(offset).limit(elementi_per_pagina)

        exec_res = await db.execute(stmt)
        items = exec_res.scalars().all()

        # 10. Costruzione DTO con formattazione e rispetto privacy
        risultati: List[AnnuncioPublicOut] = []
        for a in items:
            comune_out = None
            if a.comune:
                sigla = a.comune.provincia.sigla_automobilistica if a.comune.provincia else None
                regione_nome = a.comune.provincia.regione.nome if a.comune.provincia and a.comune.provincia.regione else None
                comune_out = ComuneOut(
                    id=a.comune.id,
                    nome=a.comune.nome,
                    cap=a.comune.cap,
                    provincia_id=a.comune.provincia_id,
                    latitudine=a.comune.latitudine,
                    longitudine=a.comune.longitudine,
                    sigla_provincia=sigla,
                    nome_regione=regione_nome,
                )

            telefono_mostrato = a.telefono_contatto if a.mostra_telefono_pubblico else None
            dist_km = distanze_comuni.get(a.comune_id)

            ad_out = AnnuncioPublicOut(
                id=a.id,
                titolo=a.titolo,
                slug=a.slug,
                url_seo=a.url_seo,
                descrizione=a.descrizione,
                prezzo=a.prezzo,
                stato=a.stato,
                tipologia_inserzionista=a.tipologia_inserzionista,
                tipologia_arma=a.tipologia_arma,
                marca=a.marca,
                modello=a.modello,
                calibro=a.calibro,
                classificazione=a.classificazione,
                condizione=a.condizione,
                comune_id=a.comune_id,
                galleria_immagini=a.galleria_immagini or [],
                link_esterno=a.link_esterno,
                fonte_esterna=a.fonte_esterna,
                is_scraped=a.is_scraped,
                nome_inserzionista_reale=a.nome_inserzionista_reale,
                email_contatto=a.email_contatto if a.tipologia_inserzionista == TipologiaInserzionista.ARMERIA else None,
                telefono_contatto=telefono_mostrato,
                visualizzazioni=a.visualizzazioni,
                data_creazione=a.data_creazione,
                data_aggiornamento=a.data_aggiornamento,
                comune=comune_out,
                distanza_km=dist_km,
            )
            risultati.append(ad_out)

        # Se ordinamento per distanza specificato e distanze calcolate
        if ordina_per == "distanza" and distanze_comuni:
            risultati.sort(key=lambda x: (x.distanza_km if x.distanza_km is not None else float("inf")))

        return risultati, totale

    @staticmethod
    async def get_geojson_map(
        db: AsyncSession,
        tipologia_arma: Optional[TipologiaArma] = None,
        tipologia_inserzionista: Optional[TipologiaInserzionista] = None,
        max_items: int = 250
    ) -> GeoJSONFeatureCollection:
        """
        Genera la FeatureCollection GeoJSON per la visualizzazione sulla mappa interattiva.
        Risolve ogni annuncio con pin geolocalizzato e link diretto alla scheda.
        """
        features: List[GeoJSONFeature] = []

        # PRIORITÀ 1 — PRIVACY MAPPA:
        # La mappa pubblica NON deve esporre posizione, comune, nominativo o annunci di privati.
        # Mostra unicamente:
        # 1. Annunci pubblicati da ARMERIE autorizzate con sede commerciale
        # 2. Sedi di ARMERIE partner registrate
        # 3. Poligoni di tiro / Sezioni TSN
        if tipologia_inserzionista != TipologiaInserzionista.PRIVATO:
            stmt = (
                select(Annuncio)
                .join(Comune, Annuncio.comune_id == Comune.id)
                .join(Provincia, Comune.provincia_id == Provincia.id)
                .options(
                    selectinload(Annuncio.comune).selectinload(Comune.provincia)
                )
                .where(
                    Annuncio.stato == StatoAnnuncio.PUBBLICATO,
                    Annuncio.tipologia_inserzionista == TipologiaInserzionista.ARMERIA
                )
            )

            if tipologia_arma:
                stmt = stmt.where(Annuncio.tipologia_arma == tipologia_arma)

            stmt = stmt.order_by(Annuncio.id.desc()).limit(max_items)
            res = await db.execute(stmt)
            annunci = res.scalars().all()

            for a in annunci:
                if not a.comune:
                    continue

                copertina = a.galleria_immagini[0] if a.galleria_immagini else None
                sigla = a.comune.provincia.sigla_automobilistica if a.comune.provincia else ""

                geom = GeoJSONGeometry(
                    type="Point",
                    coordinates=[a.comune.longitudine, a.comune.latitudine]
                )

                props = GeoJSONProperties(
                    annuncio_id=a.id,
                    titolo=a.titolo,
                    slug=a.slug,
                    prezzo=a.prezzo,
                    marca=a.marca,
                    modello=a.modello,
                    calibro=a.calibro,
                    tipologia_arma=a.tipologia_arma.value,
                    tipologia_inserzionista=a.tipologia_inserzionista.value,
                    comune=a.comune.nome,
                    provincia=sigla,
                    immagine_copertina=copertina,
                    url_scheda=f"/scheda/{a.id}",
                    link_esterno=a.link_esterno,
                    disclaimer_sintetico=LEGAL_DISCLAIMER_FOOTER,
                )

                features.append(GeoJSONFeature(geometry=geom, properties=props))

            # Se non filtriamo per tipo d'arma, mostriamo le sedi fisiche delle sole ARMERIE commerciali
            if not tipologia_arma:
                stmt_users = (
                    select(User)
                    .join(Comune, User.comune_id == Comune.id)
                    .join(Provincia, Comune.provincia_id == Provincia.id)
                    .where(
                        User.comune_id.isnot(None),
                        User.is_active.is_(True),
                        User.ruolo == RuoloUtente.ARMERIA
                    )
                )

                res_users = await db.execute(stmt_users)
                users_list = res_users.scalars().all()

                comune_ids = {u.comune_id for u in users_list if u.comune_id}
                if comune_ids:
                    stmt_c = (
                        select(Comune)
                        .options(selectinload(Comune.provincia))
                        .where(Comune.id.in_(comune_ids))
                    )
                    comuni_map = {c.id: c for c in (await db.execute(stmt_c)).scalars().all()}

                    for u in users_list:
                        comune_obj = comuni_map.get(u.comune_id)
                        if not comune_obj:
                            continue
                        
                        sigla = comune_obj.provincia.sigla_automobilistica if comune_obj.provincia else ""
                        try:
                            u_lat = float(u.latitudine) if u.latitudine else comune_obj.latitudine
                            u_lon = float(u.longitudine) if u.longitudine else comune_obj.longitudine
                        except (ValueError, TypeError):
                            u_lat = comune_obj.latitudine
                            u_lon = comune_obj.longitudine

                        titolo_user = u.ragione_sociale if u.ragione_sociale else f"Armeria {u.nome}"
                        desc_role = "Armeria Autorizzata"

                        u_geom = GeoJSONGeometry(type="Point", coordinates=[u_lon, u_lat])
                        u_props = GeoJSONProperties(
                            user_id=u.id,
                            is_user_marker=True,
                            titolo=f"{titolo_user} ({desc_role})",
                            tipologia_inserzionista="armeria",
                            comune=comune_obj.nome,
                            provincia=sigla,
                            indirizzo=u.indirizzo,
                            url_scheda=None,
                            disclaimer_sintetico=LEGAL_DISCLAIMER_FOOTER,
                        )
                        features.append(GeoJSONFeature(geometry=u_geom, properties=u_props))

        # Includi poligoni di tiro e sezioni TSN censiti
        stmt_poligoni = select(PoligonoTiro).options(selectinload(PoligonoTiro.comune))
        res_pol = await db.execute(stmt_poligoni)
        for p in res_pol.scalars().all():
            p_geom = GeoJSONGeometry(type="Point", coordinates=[p.longitudine, p.latitudine])
            p_props = GeoJSONProperties(
                titolo=f"🎯 {p.nome}",
                tipologia_inserzionista="poligono",
                comune=p.comune.nome if p.comune else "",
                provincia=p.comune.provincia.sigla_automobilistica if (p.comune and p.comune.provincia) else "",
                indirizzo=p.indirizzo,
                is_poligono=True,
                tipo_poligono=p.tipologia,
                linee_tiro=p.linee_tiro,
                telefono=p.telefono,
                sito_web=p.sito_web,
                url_scheda=p.sito_web,
                disclaimer_sintetico="Struttura di tiro autorizzata UITS / FITAV"
            )
            features.append(GeoJSONFeature(geometry=p_geom, properties=p_props))

        return GeoJSONFeatureCollection(features=features)

