from datetime import datetime
from typing import Dict, List, Optional
from pydantic import BaseModel, ConfigDict, Field, model_validator


class ValutazioneCreate(BaseModel):
    """Schema per l'invio o aggiornamento di una valutazione."""
    voto: int = Field(..., ge=1, le=5, description="Voto espresso in stelle da 1 a 5")
    titolo: Optional[str] = Field(None, max_length=150, description="Titolo sintetico opzionale della recensione")
    commento: str = Field(..., min_length=5, max_length=2000, description="Testo dettagliato del feedback")
    recensito_utente_id: Optional[int] = Field(None, description="ID dell'utente registrato recensito (se applicabile)")
    fonte_esterna: Optional[str] = Field(None, max_length=200, description="Nome dell'armeria esterna/scraped (se applicabile)")
    annuncio_id: Optional[int] = Field(None, description="ID dell'annuncio di riferimento (opzionale)")

    @model_validator(mode="after")
    def check_destinatario(self):
        if not self.recensito_utente_id and not (self.fonte_esterna and self.fonte_esterna.strip()):
            raise ValueError("È necessario specificare un utente destinatario o un'armeria esterna.")
        if self.recensito_utente_id and self.fonte_esterna:
            # Se entrambi sono forniti, normalizziamo dando priorità all'utente registrato
            pass
        return self


class ValutazioneOut(BaseModel):
    """Rappresentazione pubblica di una recensione."""
    model_config = ConfigDict(from_attributes=True)

    id: int
    voto: int
    titolo: Optional[str] = None
    commento: str
    data_creazione: datetime
    data_aggiornamento: datetime
    autore_id: int
    autore_display_name: str = "Utente ArmiMarket"
    autore_foto: Optional[str] = None
    recensito_utente_id: Optional[int] = None
    fonte_esterna: Optional[str] = None
    annuncio_id: Optional[int] = None


class RiepilogoValutazioniOut(BaseModel):
    """Riepilogo statistico delle valutazioni di un venditore (utente o armeria)."""
    media_voto: float = 0.0
    totale_valutazioni: int = 0
    distribuzione_voti: Dict[int, int] = Field(default_factory=lambda: {1: 0, 2: 0, 3: 0, 4: 0, 5: 0})
    valutazioni: List[ValutazioneOut] = Field(default_factory=list)
