from datetime import datetime
from typing import Optional
from pydantic import BaseModel, ConfigDict, EmailStr, Field, model_validator
import enum
from app.models.user import RuoloUtente
from app.core.validators import (
    validate_partita_iva,
    normalize_partita_iva,
    validate_codice_fiscale,
    normalize_codice_fiscale,
)


class RuoloRegistrazione(str, enum.Enum):
    PRIVATO = "privato"
    ARMERIA = "armeria"


class UserBase(BaseModel):
    email: EmailStr
    nickname: Optional[str] = Field(None, min_length=2, max_length=50, description="Nome utente pubblico / pseudonimo visibile")
    nome: str = Field(..., min_length=2, max_length=100)
    cognome: Optional[str] = Field(None, max_length=100)
    ragione_sociale: Optional[str] = Field(None, max_length=200)
    partita_iva: Optional[str] = Field(None, max_length=20)
    codice_fiscale: Optional[str] = Field(None, min_length=16, max_length=16)
    licenza_tulps: Optional[str] = Field(None, max_length=100, description="Rif. Licenza T.U.L.P.S. Questura")
    ruolo: RuoloRegistrazione = RuoloRegistrazione.PRIVATO
    telefono: Optional[str] = Field(None, max_length=30)
    comune_id: Optional[int] = Field(None, description="ID Comune di residenza o sede armeria")
    indirizzo: Optional[str] = Field(None, max_length=255, description="Indirizzo o via (facoltativo)")
    sito_web: Optional[str] = Field(None, max_length=255, description="Sito internet ufficiale dell'armeria")
    latitudine: Optional[str] = Field(None, max_length=30)
    longitudine: Optional[str] = Field(None, max_length=30)


class UserCreate(UserBase):
    password: str = Field(..., min_length=8, description="Password di almeno 8 caratteri")
    ruolo: RuoloRegistrazione = Field(
        default=RuoloRegistrazione.PRIVATO,
        description="Ruolo di registrazione (consentiti solo 'privato' o 'armeria')"
    )

    @model_validator(mode="after")
    def validate_anagrafica_ruolo(self):
        ruolo_val = getattr(self.ruolo, "value", self.ruolo)
        if ruolo_val == "armeria":
            clean_piva = normalize_partita_iva(self.partita_iva)
            if not clean_piva:
                raise ValueError("La Partita IVA è obbligatoria per gli utenti di tipo armeria.")
            if not validate_partita_iva(clean_piva):
                raise ValueError("La Partita IVA inserita non è formalmente valida (deve essere composta da 11 cifre con codice di controllo valido).")
            self.partita_iva = clean_piva
            self.codice_fiscale = None  # Il codice fiscale non si applica per le armerie
        else:
            if self.codice_fiscale:
                clean_cf = normalize_codice_fiscale(self.codice_fiscale)
                if not validate_codice_fiscale(clean_cf):
                    raise ValueError("Il Codice Fiscale inserito non è formalmente valido.")
                self.codice_fiscale = clean_cf
        if self.indirizzo:
            self.indirizzo = self.indirizzo.strip() or None
        return self


class UserUpdateProfile(BaseModel):
    nickname: Optional[str] = Field(None, min_length=2, max_length=50, description="Nuovo nickname pubblico")
    telefono: Optional[str] = Field(None, max_length=30)


class UserLogin(BaseModel):
    email: EmailStr
    password: str


class UserOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    email: EmailStr
    nickname: Optional[str] = None
    display_name: Optional[str] = None
    nome: str
    cognome: Optional[str] = None
    ragione_sociale: Optional[str] = None
    partita_iva: Optional[str] = None
    codice_fiscale: Optional[str] = None
    sito_web: Optional[str] = None
    foto_profilo: Optional[str] = None
    ruolo: RuoloUtente
    comune_id: Optional[int] = None
    indirizzo: Optional[str] = None
    latitudine: Optional[str] = None
    longitudine: Optional[str] = None
    is_active: bool
    is_verified: bool
    data_registrazione: datetime



class Token(BaseModel):
    access_token: str
    token_type: str = "bearer"
    user: UserOut


class TokenPayload(BaseModel):
    sub: Optional[str] = None
    exp: Optional[int] = None


class PasswordResetRequest(BaseModel):
    email: EmailStr


class PasswordResetConfirm(BaseModel):
    token: str
    nuova_password: str = Field(..., min_length=8, description="Nuova password di almeno 8 caratteri")


class PasswordResetResponse(BaseModel):
    message: str
    reset_link: Optional[str] = None  # Fornito anche in risposta per trasparenza e test locali immediati


class ContactAdminRequest(BaseModel):
    nome: str = Field(..., min_length=2, max_length=100)
    email: EmailStr
    oggetto: str = Field(..., min_length=3, max_length=255)
    messaggio: str = Field(..., min_length=10, max_length=3000)

