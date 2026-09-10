import enum
from datetime import datetime, timezone
from sqlalchemy import Boolean, Column, DateTime, Float, ForeignKey, Integer, String
from sqlalchemy.orm import relationship
from app.core.database import Base


class TipologiaPoligono(str, enum.Enum):
    TSN = "tsn"  # Tiro a Segno Nazionale (UITS)
    PRIVATO = "privato"  # Campo tiro dinamico / TAV privato
    TIRO_A_VOLO = "tiro_a_volo"  # FITAV Fossa / Skeet / Compak


class PoligonoTiro(Base):
    """
    Poligoni di tiro, sezioni TSN e campi di tiro a volo in Italia.
    Consultabili sulla mappa per agevolare tiratori e cacciatori.
    """
    __tablename__ = "poligoni_tiro"

    id = Column(Integer, primary_key=True, index=True, autoincrement=True)
    nome = Column(String(200), nullable=False, index=True)
    tipologia = Column(String(50), default=TipologiaPoligono.TSN.value, nullable=False, index=True)
    comune_id = Column(Integer, ForeignKey("comuni.id", ondelete="RESTRICT"), nullable=True, index=True)
    indirizzo = Column(String(255), nullable=True)
    latitudine = Column(Float, nullable=False)
    longitudine = Column(Float, nullable=False)
    telefono = Column(String(50), nullable=True)
    sito_web = Column(String(255), nullable=True)
    email = Column(String(255), nullable=True)
    linee_tiro = Column(String(255), nullable=True)  # es. "10m, 25m, 50m, 100m, 300m"
    data_inserimento = Column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        nullable=False
    )

    comune = relationship("Comune")

    def __repr__(self) -> str:
        return f"<PoligonoTiro id={self.id} nome='{self.nome}' tipo={self.tipologia}>"
