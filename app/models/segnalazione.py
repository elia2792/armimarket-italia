from datetime import datetime, timezone
from sqlalchemy import Boolean, Column, DateTime, Float, ForeignKey, Integer, String, Text
from sqlalchemy.orm import relationship
from app.core.database import Base


class SegnalazioneAnnuncio(Base):
    """
    Segnalazioni di annunci sospetti o non conformi T.U.L.P.S. inviate dagli utenti.
    Visibili e gestibili dall admin per la rimozione rapida.
    """
    __tablename__ = "segnalazioni_annunci"

    id = Column(Integer, primary_key=True, index=True, autoincrement=True)
    annuncio_id = Column(Integer, ForeignKey("annunci.id", ondelete="CASCADE"), nullable=False, index=True)
    motivo = Column(String(100), nullable=False)  # es. difformita_tulps, truffa, arma_non_comune, prezzo_anomalo
    dettagli = Column(Text, nullable=False)
    email_segnalatore = Column(String(255), nullable=True)
    risolta = Column(Boolean, default=False, nullable=False, index=True)
    azione_intrapresa = Column(String(100), nullable=True)  # es. annuncio_eliminato, respinta, archiviata
    data_creazione = Column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        nullable=False,
        index=True
    )

    annuncio = relationship("Annuncio")

    def __repr__(self) -> str:
        return f"<SegnalazioneAnnuncio id={self.id} annuncio_id={self.annuncio_id} motivo={self.motivo}>"
