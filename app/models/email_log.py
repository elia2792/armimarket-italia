import enum
from datetime import datetime, timezone
from sqlalchemy import Boolean, Column, DateTime, Integer, String, Text
from app.core.database import Base


class TipologiaEmail(str, enum.Enum):
    RECUPERO_PASSWORD = "recupero_password"
    RICHIESTA_CONTATTO = "richiesta_contatto"
    MODERAZIONE = "moderazione"
    SEGNALAZIONE = "segnalazione"
    RISPOSTA_ADMIN = "risposta_admin"
    ALERT_RICERCA = "alert_ricerca"
    SISTEMA = "sistema"
    TEST = "test"
    IN_ARRIVO = "in_arrivo"


class EmailLog(Base):
    """
    Rappresenta un email inviata o registrata dal sistema ArmiMarket Italia.
    Consultabile direttamente dall amministratore nella webmail interna (/admin/posta).
    """
    __tablename__ = "email_logs"


    id = Column(Integer, primary_key=True, index=True, autoincrement=True)
    mittente = Column(String(255), nullable=False)
    destinatario = Column(String(255), nullable=False, index=True)
    oggetto = Column(String(300), nullable=False)
    corpo_html = Column(Text, nullable=False)
    corpo_testo = Column(Text, nullable=False)
    tipologia = Column(String(50), default=TipologiaEmail.RECUPERO_PASSWORD.value, nullable=False, index=True)
    
    inviata = Column(Boolean, default=False, nullable=False)
    errore = Column(Text, nullable=True)
    link_azione = Column(String(500), nullable=True)
    data_invio = Column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        nullable=False,
        index=True
    )

    def __repr__(self) -> str:
        return f"<EmailLog id={self.id} to='{self.destinatario}' subj='{self.oggetto[:30]}' inviata={self.inviata}>"
