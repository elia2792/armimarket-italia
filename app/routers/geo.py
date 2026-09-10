from typing import List, Optional
from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession
from app.core.database import get_db
from app.schemas.geo_schema import ComuneOut, ProvinciaOut, RegioneOut
from app.services.geo_service import GeoService

router = APIRouter(prefix="/geo", tags=["Anagrafica Geografica ISTAT & PostGIS"])


@router.get("/regioni", response_model=List[RegioneOut])
async def list_regioni(db: AsyncSession = Depends(get_db)):
    """Restituisce l'elenco completo delle 20 regioni italiane con codice ISTAT."""
    return await GeoService.get_regioni(db)


@router.get("/province", response_model=List[ProvinciaOut])
async def list_province(
    regione_id: Optional[int] = Query(None, description="Filtra per ID regione ISTAT"),
    db: AsyncSession = Depends(get_db)
):
    """Restituisce le province italiane, eventualmente filtrate per regione."""
    return await GeoService.get_province_by_regione(db, regione_id=regione_id)


@router.get("/comuni", response_model=List[ComuneOut])
async def list_comuni(
    provincia_id: Optional[int] = Query(None, description="Filtra per ID provincia"),
    q: Optional[str] = Query(None, description="Autocomplete per nome comune o CAP"),
    limit: int = Query(100, ge=1, le=10000, description="Massimo numero di risultati"),
    db: AsyncSession = Depends(get_db)
):
    """Ricerca comuni italiani con filtro provincia e autocomplete per digitazione parziale."""
    comuni = await GeoService.get_comuni(db, provincia_id=provincia_id, search=q, limit=limit)
    return [
        ComuneOut(
            id=c.id,
            nome=c.nome,
            codice_istat=c.codice_istat,
            cap=c.cap,
            provincia_id=c.provincia_id,
            latitudine=c.latitudine,
            longitudine=c.longitudine,
            sigla_provincia=c.provincia.sigla_automobilistica if c.provincia else None,
            nome_regione=c.provincia.regione.nome if c.provincia and c.provincia.regione else None
        )
        for c in comuni
    ]


@router.get("/prossimita")
async def comuni_per_prossimita(
    lat: float = Query(..., ge=35.0, le=48.0, description="Latitudine del punto di riferimento"),
    lon: float = Query(..., ge=6.0, le=19.0, description="Longitudine del punto di riferimento"),
    raggio_km: float = Query(50.0, ge=1.0, le=500.0, description="Raggio di ricerca in chilometri"),
    db: AsyncSession = Depends(get_db)
):
    """
    Ricerca per raggio chilometrico (PostGIS ST_DWithin).
    Restituisce i comuni situati entro il raggio specificato con la distanza calcolata in km.
    """
    comuni_dist = await GeoService.get_comuni_entro_raggio(db, lat=lat, lon=lon, raggio_km=raggio_km)
    return [
        {
            "id": c.id,
            "nome": c.nome,
            "cap": c.cap,
            "latitudine": c.latitudine,
            "longitudine": c.longitudine,
            "sigla_provincia": c.provincia.sigla_automobilistica if c.provincia else None,
            "distanza_km": dist,
        }
        for c, dist in comuni_dist
    ]
