import os
from typing import Optional
from pydantic import Field, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

DEFAULT_DEV_SECRET = "super-secret-key-change-in-production-tulps-compliance-2026"
DEFAULT_SUPERUSER_DEV_PASSWORD = "AdminArmiMarket2026!"


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore"
    )

    PROJECT_NAME: str = "ArmiMarket Italia"
    VERSION: str = "1.0.0"
    ENVIRONMENT: str = "development"
    DEBUG: bool = True
    API_V1_STR: str = "/api/v1"

    # CORS
    ALLOWED_ORIGINS: list[str] = [
        "http://localhost:8000",
        "http://127.0.0.1:8000",
        "http://localhost:3000",
        "https://armimarket.onrender.com",
    ]

    # Sicurezza & JWT
    SECRET_KEY: str = DEFAULT_DEV_SECRET
    ALGORITHM: str = "HS256"
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 60 * 24  # 24 ore

    # Reverse Proxy & Client IP Handling
    TRUSTED_PROXIES: list[str] = ["127.0.0.1", "::1"]
    BEHIND_TRUSTED_PROXY: bool = False

    # Rate Limiting Distribuito (Redis / Upstash)
    REDIS_URL: Optional[str] = None

    # Database
    # Supporta PostgreSQL+PostGIS o SQLite in fallback/test
    DATABASE_URL: str = Field(
        default="sqlite+aiosqlite:///./armimarket_prod.db",
        description="Async database connection string"
    )

    UPLOAD_DIR: str = "./uploads"
    AVATAR_UPLOAD_DIR: Optional[str] = None
    MAX_UPLOAD_SIZE_MB: int = 10

    # Default Superuser & Amministratore
    FIRST_SUPERUSER_EMAIL: str = "admin@armimarket.it"
    FIRST_SUPERUSER_PASSWORD: str = DEFAULT_SUPERUSER_DEV_PASSWORD
    ADMIN_EMAIL: str = "admin@armimarket.it"


    # Dominio & Indirizzo Base Applicazione
    BASE_URL: str = "http://localhost:8000"
    GOOGLE_SITE_VERIFICATION: Optional[str] = "c4d8d72365b0f7d7"

    # Configurazione Invio Email SMTP
    SMTP_HOST: Optional[str] = None
    SMTP_PORT: int = 587
    SMTP_USER: Optional[str] = None
    SMTP_PASSWORD: Optional[str] = None
    SMTP_TLS: bool = True
    EMAILS_FROM_EMAIL: str = "no-reply@armimarket.it"
    EMAILS_FROM_NAME: str = "ArmiMarket Italia"

    @model_validator(mode="after")
    def validate_production_security(self) -> "Settings":
        env_clean = self.ENVIRONMENT.lower().strip()
        if env_clean in ("production", "prod"):
            # SEC-03: SECRET_KEY obbligatoria e ad alta entropia
            if not self.SECRET_KEY or self.SECRET_KEY == DEFAULT_DEV_SECRET:
                raise ValueError(
                    "In ambiente di produzione (ENVIRONMENT=production), la variabile d'ambiente SECRET_KEY "
                    "deve essere obbligatoriamente fornita e non può utilizzare il valore predefinito."
                )
            if len(self.SECRET_KEY) < 32:
                raise ValueError(
                    "In ambiente di produzione, la chiave SECRET_KEY deve avere una lunghezza minima di "
                    "almeno 32 caratteri per garantire sufficiente entropia crittografica (256 bit)."
                )

            # SEC-03: FIRST_SUPERUSER_PASSWORD obbligatoria e non default
            if not self.FIRST_SUPERUSER_PASSWORD or self.FIRST_SUPERUSER_PASSWORD == DEFAULT_SUPERUSER_DEV_PASSWORD:
                raise ValueError(
                    "In ambiente di produzione (ENVIRONMENT=production), la variabile d'ambiente "
                    "FIRST_SUPERUSER_PASSWORD deve essere obbligatoriamente impostata e non può "
                    "utilizzare la password predefinita di sviluppo."
                )
            if len(self.FIRST_SUPERUSER_PASSWORD) < 12:
                raise ValueError(
                    "In ambiente di produzione, la password FIRST_SUPERUSER_PASSWORD deve avere una "
                    "lunghezza minima di almeno 12 caratteri complessi."
                )

            # SEC-05: Purga origini insicure (localhost, 127.0.0.1, http://) in produzione
            safe_origins = [
                o for o in self.ALLOWED_ORIGINS
                if not ("localhost" in o or "127.0.0.1" in o or o.startswith("http://"))
            ]
            if not safe_origins:
                safe_origins = ["https://armimarket-italia.onrender.com"]
            self.ALLOWED_ORIGINS = safe_origins
        return self


settings = Settings()
