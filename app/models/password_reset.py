import hashlib
import secrets
from datetime import datetime, timezone
from sqlalchemy import Boolean, Column, DateTime, ForeignKey, Integer, String
from app.core.database import Base


class PasswordResetToken(Base):
    __tablename__ = "password_reset_tokens"

    id = Column(Integer, primary_key=True, index=True, autoincrement=True)
    user_id = Column(Integer, ForeignKey("utenti.id", ondelete="CASCADE"), nullable=False, index=True)
    token_hash = Column(String(64), unique=True, index=True, nullable=False)
    expires_at = Column(DateTime(timezone=True), nullable=False)
    used = Column(Boolean, default=False, nullable=False)
    created_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), nullable=False)

    @classmethod
    def generate_token(cls) -> tuple[str, str]:
        """Genera un token URL-safe ad alta entropia (32 byte / 43 char) e il relativo hash SHA-256."""
        raw_token = secrets.token_urlsafe(32)
        token_hash = hashlib.sha256(raw_token.encode("utf-8")).hexdigest()
        return raw_token, token_hash

    @classmethod
    def hash_token(cls, raw_token: str) -> str:
        """Calcola l'hash SHA-256 deterministico del token grezzo."""
        return hashlib.sha256(raw_token.strip().encode("utf-8")).hexdigest()
