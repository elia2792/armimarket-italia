import math
from typing import List, Optional, Tuple
from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from geoalchemy2.functions import ST_Distance, ST_DWithin, ST_MakePoint, ST_SetSRID

from sqlalchemy.orm import selectinload

from app.models.geo import Comune, Provincia, Regione


def haversine_distance_km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Calcola la distanza in chilometri tra due coordinate geografiche (WGS84)."""
    r = 6371.0  # Raggio terrestre in km
    phi1 = math.radians(lat1)
    phi2 = math.radians(lat2)
    delta_phi = math.radians(lat2 - lat1)
    delta_lambda = math.radians(lon2 - lon1)

    a = (
        math.sin(delta_phi / 2.0) ** 2
        + math.cos(phi1) * math.cos(phi2) * math.sin(delta_lambda / 2.0) ** 2
    )
    c = 2.0 * math.atan2(math.sqrt(a), math.sqrt(1.0 - a))
    return r * c


class GeoService:
    @staticmethod
    async def get_regioni(db: AsyncSession) -> List[Regione]:
        """Restituisce l'elenco di tutte le 20 regioni italiane ordinate alfabeticamente."""
        stmt = select(Regione).order_by(Regione.nome.asc())
        result = await db.execute(stmt)
        return list(result.scalars().all())

    @staticmethod
    async def get_province_by_regione(
        db: AsyncSession,
        regione_id: Optional[int] = None
    ) -> List[Provincia]:
        """Restituisce le province filtrate per regione (o tutte se non specificato)."""
        stmt = select(Provincia)
        if regione_id is not None:
            stmt = stmt.where(Provincia.regione_id == regione_id)
        stmt = stmt.order_by(Provincia.nome.asc())
        result = await db.execute(stmt)
        return list(result.scalars().all())

    @staticmethod
    async def get_comuni(
        db: AsyncSession,
        provincia_id: Optional[int] = None,
        search: Optional[str] = None,
        limit: int = 50
    ) -> List[Comune]:
        """Ricerca comuni con filtro provincia e autocomplete su nome o CAP."""
        stmt = select(Comune).options(
            selectinload(Comune.provincia).selectinload(Provincia.regione)
        )
        if provincia_id is not None:
            stmt = stmt.where(Comune.provincia_id == provincia_id)
        if search:
            pattern = f"%{search.strip()}%"
            stmt = stmt.where(
                or_(
                    Comune.nome.ilike(pattern),
                    Comune.cap.like(pattern)
                )
            )
        stmt = stmt.order_by(Comune.nome.asc()).limit(limit)
        result = await db.execute(stmt)
        return list(result.scalars().all())

    @staticmethod
    async def get_comuni_entro_raggio(
        db: AsyncSession,
        lat: float,
        lon: float,
        raggio_km: float
    ) -> List[Tuple[Comune, float]]:
        """
        Esegue la ricerca per prossimità chilometrica.
        Su PostgreSQL / PostGIS: utilizza l'indice spaziale GIST e ST_DWithin / ST_Distance.
        Su SQLite (ambiente di test locale): calcola la distanza geodesica in fallback.
        """
        is_sqlite = db.bind.dialect.name == "sqlite" if db.bind else False

        if not is_sqlite:
            # Query PostGIS nativa ad alte prestazioni:
            # ST_MakePoint accetta (longitudine, latitudine)
            # ST_DWithin su geography o con use_spheroid=True
            raggio_metri = raggio_km * 1000.0
            punto_ricerca = ST_SetSRID(ST_MakePoint(lon, lat), 4326)

            # Cast a geography per distanze geodetiche accurate in metri
            punto_geog = func.Cast(punto_ricerca, func.Geography)
            comune_geog = func.Cast(Comune.coordinate, func.Geography)

            stmt = (
                select(
                    Comune,
                    (ST_Distance(comune_geog, punto_geog) / 1000.0).label("distanza_km")
                )
                .where(ST_DWithin(comune_geog, punto_geog, raggio_metri))
                .order_by("distanza_km")
            )
            result = await db.execute(stmt)
            return [(row[0], round(row[1], 2)) for row in result.all()]
        else:
            # Fallback Geodesico per test/SQLite
            # Bounding box preliminare per minimizzare i record estratti
            delta_lat = raggio_km / 111.0
            delta_lon = raggio_km / (111.0 * math.cos(math.radians(lat)))

            stmt = select(Comune).where(
                Comune.latitudine.between(lat - delta_lat, lat + delta_lat),
                Comune.longitudine.between(lon - delta_lon, lon + delta_lon),
            )
            result = await db.execute(stmt)
            comuni = result.scalars().all()

            risultati = []
            for c in comuni:
                dist = haversine_distance_km(lat, lon, c.latitudine, c.longitudine)
                if dist <= raggio_km:
                    risultati.append((c, round(dist, 2)))

            risultati.sort(key=lambda x: x[1])
            return risultati
