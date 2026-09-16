import enum
from datetime import datetime, timezone
from sqlalchemy import Boolean, Column, DateTime, Enum, Integer, String, Text
from sqlalchemy.orm import relationship
from app.core.database import Base


class RuoloUtente(str, enum.Enum):
    PRIVATO = "privato"
    ARMERIA = "armeria"
    MODERATORE = "moderatore"
    ADMIN = "admin"


class User(Base):
    __tablename__ = "utenti"

    id = Column(Integer, primary_key=True, index=True, autoincrement=True)
    email = Column(String(255), unique=True, index=True, nullable=False)
    hashed_password = Column(String(255), nullable=False)
    nickname = Column(String(50), unique=True, index=True, nullable=True)  # Nome pubblico visibile / pseudonimo
    nome = Column(String(100), nullable=False)
    cognome = Column(String(100), nullable=True)
    ragione_sociale = Column(String(200), nullable=True)  # Per armerie
    partita_iva = Column(String(20), nullable=True)       # Per armerie
    codice_fiscale = Column(String(16), nullable=True)    # Per privati/titolari
    licenza_tulps = Column(String(100), nullable=True)    # Rif. Licenza Questura per armerie
    ruolo = Column(Enum(RuoloUtente), default=RuoloUtente.PRIVATO, nullable=False)
    telefono = Column(String(30), nullable=True)
    comune_id = Column(Integer, nullable=True, index=True)
    indirizzo = Column(String(255), nullable=True)
    sito_web = Column(String(255), nullable=True)  # URL e-commerce / catalogo armeria
    foto_profilo = Column(String(512), nullable=True)  # URL/path avatar utente
    search_url_custom = Column(String(255), nullable=True)  # Template ricerca personalizzato
    latitudine = Column(String(30), nullable=True)
    longitudine = Column(String(30), nullable=True)
    is_active = Column(Boolean, default=True, nullable=False)
    is_verified = Column(Boolean, default=False, nullable=False)  # Verifica identità/titolo
    data_registrazione = Column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        nullable=False
    )

    # Relazioni
    annunci = relationship("Annuncio", back_populates="utente", cascade="all, delete-orphan")
    preferiti = relationship("Preferito", back_populates="utente", cascade="all, delete-orphan")
    valutazioni_ricevute = relationship(
        "Valutazione",
        foreign_keys="Valutazione.recensito_utente_id",
        back_populates="recensito_utente",
        cascade="all, delete-orphan"
    )
    valutazioni_lasciate = relationship(
        "Valutazione",
        foreign_keys="Valutazione.autore_id",
        back_populates="autore",
        cascade="all, delete-orphan"
    )

    @property
    def display_name(self) -> str:
        """Restituisce il nome pubblico da mostrare: nickname se presente, altrimenti ragione sociale o 'Admin'."""
        if self.nickname:
            return self.nickname
        if self.ruolo == RuoloUtente.ADMIN:
            return "Admin"
        if self.ruolo == RuoloUtente.ARMERIA and self.ragione_sociale:
            return self.ragione_sociale
        return self.nome

    def __repr__(self) -> str:
        return f"<User id={self.id} email='{self.email}' nickname='{self.nickname}' ruolo='{self.ruolo}'>"

