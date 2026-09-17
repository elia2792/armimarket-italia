from datetime import datetime
from typing import Any, Dict, List, Optional
from pydantic import BaseModel, ConfigDict, EmailStr, Field, field_validator
from app.core.legal import (
    BANNED_KEYWORDS,
    LEGAL_DISCLAIMER_ANNUNCIO,
    LEGAL_DISCLAIMER_FOOTER,
    MATRICOLA_MASK_POLICY,
)
from app.models.annuncio import (
    ClassificazioneArma,
    CondizioneArma,
    StatoAnnuncio,
    TipologiaArma,
    TipologiaInserzionista,
)
from app.schemas.geo_schema import ComuneOut


def check_banned_content(text: str) -> None:
    """Verifica e blocca la presenza di keyword vietate o illegali."""
    lowered = text.lower()
    for kw in BANNED_KEYWORDS:
        if kw in lowered:
            raise ValueError(
                f"Contenuto non conforme alla normativa T.U.L.P.S. / L. 110/1975: "
                f"rilevato termine non consentito ('{kw}'). "
                f"È vietata l'inserzione di armi da guerra, silenziatori, armi a raffica o modifiche clandestine."
            )


class AnnuncioBase(BaseModel):
    titolo: str = Field(..., min_length=5, max_length=255, description="Titolo chiaro dell'annuncio")
    descrizione: str = Field(..., min_length=20, description="Descrizione dettagliata dell'arma o accessorio")
    prezzo: float = Field(..., ge=0.0, description="Prezzo in Euro")
    tipologia_inserzionista: TipologiaInserzionista = TipologiaInserzionista.PRIVATO
    tipologia_arma: TipologiaArma
    marca: str = Field(..., min_length=2, max_length=100)
    modello: str = Field(..., min_length=1, max_length=100)
    calibro: str = Field(..., min_length=1, max_length=50)
    classificazione: ClassificazioneArma = ClassificazioneArma.COMUNE
    condizione: CondizioneArma = CondizioneArma.USATO_OTTIMO
    comune_id: int
    galleria_immagini: List[str] = Field(default_factory=list)
    email_contatto: EmailStr
    telefono_contatto: Optional[str] = Field(None, max_length=50)
    mostra_telefono_pubblico: bool = False

    @field_validator("titolo", "descrizione", mode="before")
    @classmethod
    def validate_prohibited_terms(cls, value: str) -> str:
        if isinstance(value, str):
            check_banned_content(value)
        return value


class AnnuncioCreate(AnnuncioBase):
    # La matricola è facoltativa e riservata ai controlli interni di moderazione
    matricola_riservata: Optional[str] = Field(
        None,
        max_length=100,
        description="Matricola dell'arma (riservata, MAI mostrata in chiaro al pubblico)"
    )


class AnnuncioUpdate(BaseModel):
    titolo: Optional[str] = Field(None, min_length=5, max_length=255)
    descrizione: Optional[str] = Field(None, min_length=20)
    prezzo: Optional[float] = Field(None, ge=0.0)
    condizione: Optional[CondizioneArma] = None
    galleria_immagini: Optional[List[str]] = None
    telefono_contatto: Optional[str] = None
    mostra_telefono_pubblico: Optional[bool] = None
    stato: Optional[StatoAnnuncio] = None

    @field_validator("titolo", "descrizione", mode="before")
    @classmethod
    def validate_prohibited_terms(cls, value: Optional[str]) -> Optional[str]:
        if value and isinstance(value, str):
            check_banned_content(value)
        return value


class AnnuncioPublicOut(BaseModel):
    id: int
    titolo: str
    slug: str
    url_seo: Optional[str] = None
    descrizione: str
    prezzo: float
    prezzo_originale: Optional[float] = None
    sconto_percentuale: Optional[int] = None
    stato: StatoAnnuncio

    tipologia_inserzionista: TipologiaInserzionista
    tipologia_arma: TipologiaArma
    marca: str
    modello: str
    calibro: str
    classificazione: ClassificazioneArma
    condizione: CondizioneArma
    comune_id: int
    galleria_immagini: List[str]
    link_esterno: Optional[str] = Field(None, description="Link diretto alla scheda prodotto sul sito originale dell'armeria")
    email_contatto: Optional[EmailStr] = Field(None, description="Email di contatto (omessa per venditori privati a tutela della privacy)")
    telefono_contatto: Optional[str] = None  # Popolato solo se mostra_telefono_pubblico è True
    visualizzazioni: int
    data_creazione: datetime
    data_aggiornamento: datetime

    # Informazioni geografiche
    comune: Optional[ComuneOut] = None

    # Distanza opzionale calcolata via PostGIS ST_DWithin / ST_Distance
    distanza_km: Optional[float] = Field(None, description="Distanza in km dal punto di ricerca")

    # Fonte esterna per annunci aggregati/scraped
    fonte_esterna: Optional[str] = Field(None, description="Nome dell'armeria o sito esterno se annuncio aggregato da scraping")
    is_scraped: bool = Field(False, description="True se l'annuncio proviene da scraping esterno")
    nome_inserzionista_reale: Optional[str] = None

    # Garanzia di Conformità & Privacy
    matricola_visibile: str = Field(
        default="[RISERVATA AI SENSI DEL REGOLAMENTO DI PUBBLICA SICUREZZA]",
        description="Informativa anti-clonazione matricola"
    )
    disclaimer_legale: str = Field(
        default=LEGAL_DISCLAIMER_ANNUNCIO,
        description="Avviso di conformità normativa T.U.L.P.S."
    )

    model_config = ConfigDict(from_attributes=True)


class AnnuncioDetailOut(AnnuncioPublicOut):
    """Scheda di dettaglio con disclaimer esteso e coordinate per Leaflet map."""
    latitudine_mappa: float
    longitudine_mappa: float
    precisione_mappa: str = Field(
        default="comunale_protetta",
        description="'comunale_protetta' per venditori privati a tutela da furti, 'esatta_armeria' per negozi certificati"
    )
    disclaimer_footer: str = LEGAL_DISCLAIMER_FOOTER
    politica_privacy_matricola: str = MATRICOLA_MASK_POLICY


class AnnuncioAdminOut(AnnuncioPublicOut):
    """Schema per moderatori: visualizza matricola mascherata e note interne."""
    matricola_mascherata: Optional[str] = None
    matricola_originale_disponibile: bool = False
    note_moderazione: Optional[str] = None
    utente_id: Optional[int] = None



class AnnuncioListResponse(BaseModel):
    totale: int
    pagina: int
    pagine_totali: int
    elementi_per_pagina: int
    risultati: List[AnnuncioPublicOut]
    disclaimer_legale_generale: str = LEGAL_DISCLAIMER_FOOTER


# Feature GeoJSON per rendering diretto della Mappa
class GeoJSONGeometry(BaseModel):
    type: str = "Point"
    coordinates: List[float]  # [longitudine, latitudine]


class GeoJSONProperties(BaseModel):
    annuncio_id: Optional[int] = None
    user_id: Optional[int] = None
    is_user_marker: bool = False
    titolo: str
    slug: Optional[str] = None
    prezzo: Optional[float] = None
    marca: Optional[str] = None
    modello: Optional[str] = None
    calibro: Optional[str] = None
    tipologia_arma: Optional[str] = None
    tipologia_inserzionista: str
    comune: str
    provincia: str
    indirizzo: Optional[str] = None
    is_poligono: bool = False
    tipo_poligono: Optional[str] = None
    linee_tiro: Optional[str] = None
    telefono: Optional[str] = None
    sito_web: Optional[str] = None
    url_scheda: Optional[str] = None
    link_esterno: Optional[str] = None
    disclaimer_sintetico: str = ""


class SegnalazioneCreate(BaseModel):
    motivo: str = Field(..., min_length=3, max_length=100, description="es. difformita_tulps, truffa, arma_non_comune, prezzo_anomalo")
    dettagli: str = Field(..., min_length=5, max_length=2000, description="Dettagli specifici della segnalazione")
    email_segnalatore: Optional[EmailStr] = None


class RicercaSalvataCreate(BaseModel):
    email: EmailStr
    criteri: dict
    descrizione_ricerca: str = Field(..., min_length=3, max_length=255)



class GeoJSONFeature(BaseModel):
    type: str = "Feature"
    geometry: GeoJSONGeometry
    properties: GeoJSONProperties


class GeoJSONFeatureCollection(BaseModel):
    type: str = "FeatureCollection"
    features: List[GeoJSONFeature]


class ContactFormRequest(BaseModel):
    nome_mittente: str = Field(..., min_length=2, max_length=100)
    email_mittente: EmailStr
    telefono_mittente: Optional[str] = Field(None, max_length=30)
    titolo_di_polizia: str = Field(
        ...,
        description="Dichiarazione possesso titolo valido: es. 'Porto d'Armi Difesa / Tiro a Volo / Caccia valido'"
    )
    messaggio: str = Field(..., min_length=10, max_length=2000)
    accetto_disclaimer_legale: bool = Field(
        ...,
        description="Conferma di essere a conoscenza dell'obbligo di transazione di persona e denuncia entro 72h"
    )

    @field_validator("accetto_disclaimer_legale")
    @classmethod
    def validate_acceptance(cls, v: bool) -> bool:
        if not v:
            raise ValueError("È obbligatorio accettare le condizioni di legge T.U.L.P.S. prima di contattare il cedente.")
        return v


class ContactFormResponse(BaseModel):
    success: bool
    message: str
    disclaimer: str = LEGAL_DISCLAIMER_FOOTER


class UpdateComuneRequest(BaseModel):
    comune_id: int = Field(..., ge=1, description="ID del nuovo comune di riferimento ISTAT")


class UpdateComuneResponse(BaseModel):
    message: str
    id: int
    comune_id: int
    comune_nome: str
    sigla_provincia: str


class AdminAnnuncioUpdateRequest(BaseModel):
    titolo: Optional[str] = Field(None, min_length=3, max_length=255)
    descrizione: Optional[str] = Field(None, min_length=10)
    prezzo: Optional[float] = Field(None, ge=0.0)
    prezzo_originale: Optional[float] = Field(None, ge=0.0)
    marca: Optional[str] = Field(None, max_length=100)
    modello: Optional[str] = Field(None, max_length=100)
    calibro: Optional[str] = Field(None, max_length=50)
    tipologia_arma: Optional[TipologiaArma] = None
    classificazione: Optional[ClassificazioneArma] = None
    condizione: Optional[CondizioneArma] = None
    tipologia_inserzionista: Optional[TipologiaInserzionista] = None
    comune_id: Optional[int] = Field(None, ge=1)
    stato: Optional[StatoAnnuncio] = None
    email_contatto: Optional[EmailStr] = None
    telefono_contatto: Optional[str] = None
    mostra_telefono_pubblico: Optional[bool] = None
    galleria_immagini: Optional[List[str]] = None
    fonte_esterna: Optional[str] = Field(None, max_length=200)
    link_esterno: Optional[str] = None
    note_moderazione: Optional[str] = None


class AdminAnnunciListResponse(BaseModel):
    totale: int
    totale_privati: int
    totale_armerie: int
    totale_in_moderazione: int
    pagina: int
    elementi_per_pagina: int
    pagine_totali: int
    annunci: List[AnnuncioAdminOut]


