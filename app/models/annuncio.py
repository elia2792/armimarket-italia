import enum
from datetime import datetime, timezone
from sqlalchemy import (
    JSON,
    Boolean,
    Column,
    DateTime,
    Enum,
    Float,
    ForeignKey,
    Integer,
    String,
    Text,
)
from sqlalchemy.orm import relationship
from app.core.database import Base


class StatoAnnuncio(str, enum.Enum):
    BOZZA = "bozza"
    IN_MODERAZIONE = "in_moderazione"
    PUBBLICATO = "pubblicato"
    VENDUTO = "venduto"
    ARCHIVIATO = "archiviato"
    RIFIUTATO = "rifiutato"


class TipologiaInserzionista(str, enum.Enum):
    ARMERIA = "armeria"
    PRIVATO = "privato"


class TipologiaArma(str, enum.Enum):
    ARMA_CORTA = "arma_corta"
    ARMA_LUNGA_RIGATA = "arma_lunga_rigata"
    CANNA_LISCIA = "canna_liscia"
    ARIA_COMPRESSA_LIBERA = "aria_compressa_libera"  # < 7.5 Joule
    ARIA_COMPRESSA_PIENA = "aria_compressa_piena"    # Piena potenza (> 7.5 Joule)
    ACCESSORIO_OTTICA = "accessorio_ottica"


class ClassificazioneArma(str, enum.Enum):
    COMUNE = "comune"
    SPORTIVA = "sportiva"
    CACCIA = "caccia"
    NON_APPLICABILE = "non_applicabile"


class CondizioneArma(str, enum.Enum):
    NUOVO = "nuovo"
    USATO_OTTIMO = "usato_ottimo"
    USATO_BUONO = "usato_buono"
    DA_COLLEZIONE = "da_collezione"


class Annuncio(Base):
    __tablename__ = "annunci"

    id = Column(Integer, primary_key=True, index=True, autoincrement=True)
    titolo = Column(String(255), nullable=False, index=True)
    slug = Column(String(300), nullable=False, unique=True, index=True)
    descrizione = Column(Text, nullable=False)
    prezzo = Column(Float, nullable=False, index=True)  # Prezzo attuale in Euro
    prezzo_originale = Column(Float, nullable=True)     # Prezzo precedente prima di eventuali ribassi


    stato = Column(
        Enum(StatoAnnuncio),
        default=StatoAnnuncio.IN_MODERAZIONE,
        nullable=False,
        index=True
    )
    tipologia_inserzionista = Column(
        Enum(TipologiaInserzionista),
        nullable=False,
        index=True
    )

    # --- Sezione Arma e Specifiche Tecniche ---
    tipologia_arma = Column(Enum(TipologiaArma), nullable=False, index=True)
    marca = Column(String(100), nullable=False, index=True)
    modello = Column(String(100), nullable=False, index=True)
    calibro = Column(String(50), nullable=False, index=True)
    classificazione = Column(
        Enum(ClassificazioneArma),
        default=ClassificazioneArma.COMUNE,
        nullable=False,
        index=True
    )
    condizione = Column(
        Enum(CondizioneArma),
        default=CondizioneArma.USATO_OTTIMO,
        nullable=False,
        index=True
    )

    # Campo di sicurezza e conformità:
    # La matricola NON deve mai essere esposta in chiaro pubblicamente.
    # Viene salvata facoltativamente e usata solo per i controlli di moderazione.
    matricola_riservata = Column(String(100), nullable=True)

    # --- Relazioni Geografiche e Inserzionista ---
    comune_id = Column(Integer, ForeignKey("comuni.id", ondelete="RESTRICT"), nullable=False, index=True)
    utente_id = Column(Integer, ForeignKey("utenti.id", ondelete="CASCADE"), nullable=False, index=True)

    # --- Gallery Immagini (JSON array di URL) ---
    galleria_immagini = Column(JSON, default=list, nullable=False)

    # --- Contatti & Fonte Originale ---
    link_esterno = Column(String(500), nullable=True, index=True)  # URL originale sul sito dell'armeria
    email_contatto = Column(String(255), nullable=False)
    telefono_contatto = Column(String(50), nullable=True)
    mostra_telefono_pubblico = Column(Boolean, default=False, nullable=False)

    # --- Metadati & Statistiche ---
    visualizzazioni = Column(Integer, default=0, nullable=False)
    note_moderazione = Column(Text, nullable=True)
    data_creazione = Column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        nullable=False,
        index=True
    )
    data_aggiornamento = Column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
        nullable=False
    )

    # Relazioni ORM
    comune = relationship("Comune", back_populates="annunci")
    utente = relationship("User", back_populates="annunci")
    preferiti = relationship("Preferito", back_populates="annuncio", cascade="all, delete-orphan")

    @property
    def url_seo(self) -> str:
        s = self.slug or "annuncio"
        return f"/annuncio/{s}-{self.id}"

    def __repr__(self) -> str:
        return f"<Annuncio id={self.id} titolo='{self.titolo}' stato='{self.stato}'>"
