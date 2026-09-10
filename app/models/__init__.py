from app.models.base import Base
from app.models.user import User, RuoloUtente
from app.models.geo import Regione, Provincia, Comune
from app.models.annuncio import (
    Annuncio,
    StatoAnnuncio,
    TipologiaInserzionista,
    TipologiaArma,
    ClassificazioneArma,
    CondizioneArma,
)

from app.models.preferito import Preferito
from app.models.email_log import EmailLog, TipologiaEmail
from app.models.segnalazione import SegnalazioneAnnuncio
from app.models.poligono import PoligonoTiro, TipologiaPoligono
from app.models.ricerca_salvata import RicercaSalvata
from app.models.password_reset import PasswordResetToken

__all__ = [
    "Base",
    "User",
    "RuoloUtente",
    "Regione",
    "Provincia",
    "Comune",
    "Annuncio",
    "StatoAnnuncio",
    "TipologiaInserzionista",
    "TipologiaArma",
    "ClassificazioneArma",
    "CondizioneArma",
    "Preferito",
    "EmailLog",
    "TipologiaEmail",
    "SegnalazioneAnnuncio",
    "PoligonoTiro",
    "TipologiaPoligono",
    "RicercaSalvata",
    "PasswordResetToken",
]


