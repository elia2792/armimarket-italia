from typing import Optional
from pydantic import BaseModel, ConfigDict, Field


class RegioneOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    nome: str
    codice_istat: str


class ProvinciaOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    nome: str
    sigla_automobilistica: str
    regione_id: int


class ComuneOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    nome: str
    codice_istat: Optional[str] = None
    cap: str
    provincia_id: int
    latitudine: float
    longitudine: float
    sigla_provincia: Optional[str] = None
    nome_regione: Optional[str] = None


class CoordinateQuery(BaseModel):
    latitudine: float = Field(..., ge=35.0, le=48.0, description="Latitudine italiana compresa tra 35 e 48")
    longitudine: float = Field(..., ge=6.0, le=19.0, description="Longitudine italiana compresa tra 6 e 19")
    raggio_km: float = Field(default=50.0, ge=1.0, le=500.0, description="Raggio di ricerca in chilometri")
