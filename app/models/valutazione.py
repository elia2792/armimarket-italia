import enum
from datetime import datetime, timezone
from typing import Optional
from sqlalchemy import CheckConstraint, Column, DateTime, ForeignKey, Integer, String, Text
from sqlalchemy.orm import relationship

from app.core.database import Base


class Valutazione(Base):
    """
    Modello per le valutazioni e recensioni (1-5 stelle con commento).
    Supporta:
    1. Recensioni ad altri utenti registrati (privati o armerie): 'recensito_utente_id' valorizzato.
    2. Recensioni ad armerie esterne / fonti di scraping: 'fonte_esterna' valorizzato
       (senza creare account utente fittizi).
    """
    __tablename__ = "valutazioni"

    id = Column(Integer, primary_key=True, index=True, autoincrement=True)
    
    # Autore della recensione (utente registrato che valuta)
    autore_id = Column(Integer, ForeignKey("utenti.id", ondelete="CASCADE"), nullable=False, index=True)

    # Destinatario utente registrato (privato o armeria con account)
    recensito_utente_id = Column(Integer, ForeignKey("utenti.id", ondelete="CASCADE"), nullable=True, index=True)

    # Destinatario armeria esterna / scraped (es. 'Armeria Regina', 'Armeria Dionisi Sport Srl')
    fonte_esterna = Column(String(200), nullable=True, index=True)

    # Riferimento facoltativo all'annuncio oggetto della transazione/contatto
    annuncio_id = Column(Integer, ForeignKey("annunci.id", ondelete="SET NULL"), nullable=True, index=True)

    # Voto da 1 a 5 stelle
    voto = Column(Integer, nullable=False)
    
    # Titolo sintetico opzionale e commento testuale
    titolo = Column(String(150), nullable=True)
    commento = Column(Text, nullable=False)

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
    autore = relationship("User", foreign_keys=[autore_id], back_populates="valutazioni_lasciate")
    recensito_utente = relationship("User", foreign_keys=[recensito_utente_id], back_populates="valutazioni_ricevute")
    annuncio = relationship("Annuncio")

    __table_args__ = (
        CheckConstraint("voto >= 1 AND voto <= 5", name="check_voto_range"),
        CheckConstraint(
            "(recensito_utente_id IS NOT NULL) OR (fonte_esterna IS NOT NULL)",
            name="check_target_valutazione"
        ),
    )

    @property
    def nome_autore(self) -> str:
        """Restituisce il display name dell'autore della recensione."""
        if self.autore:
            return self.autore.display_name
        return "Utente ArmiMarket"

    def __repr__(self) -> str:
        target = f"user={self.recensito_utente_id}" if self.recensito_utente_id else f"fonte='{self.fonte_esterna}'"
        return f"<Valutazione id={self.id} autore={self.autore_id} target=({target}) voto={self.voto}>"
