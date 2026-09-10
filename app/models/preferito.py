from datetime import datetime, timezone
from sqlalchemy import Column, DateTime, ForeignKey, Integer, UniqueConstraint
from sqlalchemy.orm import relationship
from app.core.database import Base


class Preferito(Base):
    __tablename__ = "preferiti"
    __table_args__ = (
        UniqueConstraint("utente_id", "annuncio_id", name="uq_utente_annuncio_preferito"),
    )

    id = Column(Integer, primary_key=True, index=True, autoincrement=True)
    utente_id = Column(Integer, ForeignKey("utenti.id", ondelete="CASCADE"), nullable=False, index=True)
    annuncio_id = Column(Integer, ForeignKey("annunci.id", ondelete="CASCADE"), nullable=False, index=True)
    data_creazione = Column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        nullable=False
    )

    # Relazioni
    utente = relationship("User", back_populates="preferiti")
    annuncio = relationship("Annuncio", back_populates="preferiti")

    def __repr__(self) -> str:
        return f"<Preferito utente_id={self.utente_id} annuncio_id={self.annuncio_id}>"
