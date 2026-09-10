from datetime import datetime, timezone
from sqlalchemy import Boolean, Column, DateTime, Integer, JSON, String
from app.core.database import Base


class RicercaSalvata(Base):
    """
    Ricerche salvate dagli utenti con notifica via email (alert nuovi annunci compatibili).
    """
    __tablename__ = "ricerche_salvate"

    id = Column(Integer, primary_key=True, index=True, autoincrement=True)
    email = Column(String(255), nullable=False, index=True)
    criteri = Column(JSON, nullable=False)  # es. {"marca": "Beretta", "calibro": "9x21", "prezzo_max": 700}
    descrizione_ricerca = Column(String(255), nullable=False)
    attiva = Column(Boolean, default=True, nullable=False)
    data_creazione = Column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        nullable=False
    )
    ultimo_invio = Column(DateTime(timezone=True), nullable=True)

    def __repr__(self) -> str:
        return f"<RicercaSalvata id={self.id} email={self.email} desc={self.descrizione_ricerca}>"
