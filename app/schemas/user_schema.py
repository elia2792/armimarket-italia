from datetime import datetime
from typing import Optional
from pydantic import BaseModel, ConfigDict, EmailStr, Field
from app.models.user import RuoloUtente


class UserBase(BaseModel):
    email: EmailStr
    nickname: Optional[str] = Field(None, min_length=2, max_length=50, description="Nome utente pubblico / pseudonimo visibile")
    nome: str = Field(..., min_length=2, max_length=100)
    cognome: Optional[str] = Field(None, max_length=100)
    ragione_sociale: Optional[str] = Field(None, max_length=200)
    partita_iva: Optional[str] = Field(None, max_length=20)
    codice_fiscale: Optional[str] = Field(None, min_length=16, max_length=16)
    licenza_tulps: Optional[str] = Field(None, max_length=100, description="Rif. Licenza T.U.L.P.S. Questura")
    ruolo: RuoloUtente = RuoloUtente.PRIVATO
    telefono: Optional[str] = Field(None, max_length=30)
    comune_id: Optional[int] = Field(None, description="ID Comune di residenza o sede armeria")
    indirizzo: Optional[str] = Field(None, max_length=255, description="Indirizzo o via (sede per armerie)")
    sito_web: Optional[str] = Field(None, max_length=255, description="Sito internet ufficiale dell'armeria")
    latitudine: Optional[str] = Field(None, max_length=30)
    longitudine: Optional[str] = Field(None, max_length=30)


class UserCreate(UserBase):
    password: str = Field(..., min_length=8, description="Password di almeno 8 caratteri")


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

