import os
from typing import Optional
from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


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

    # Sicurezza & JWT
    SECRET_KEY: str = "super-secret-key-change-in-production-tulps-compliance-2026"
    ALGORITHM: str = "HS256"
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 60 * 24  # 24 ore

    # Database
    # Supporta PostgreSQL+PostGIS o SQLite in fallback/test
    DATABASE_URL: str = Field(
        default="sqlite+aiosqlite:///./armimarket_prod.db",
        description="Async database connection string"
    )

    UPLOAD_DIR: str = "./uploads"
    MAX_UPLOAD_SIZE_MB: int = 10

    # Default Superuser & Amministratore
    FIRST_SUPERUSER_EMAIL: str = "admin@armimarket.it"
    FIRST_SUPERUSER_PASSWORD: str = "AdminArmiMarket2026!"
    ADMIN_EMAIL: str = "admin@armimarket.it"


    # Dominio & Indirizzo Base Applicazione
    BASE_URL: str = "http://localhost:8000"

    # Configurazione Invio Email SMTP
    SMTP_HOST: Optional[str] = None
    SMTP_PORT: int = 587
    SMTP_USER: Optional[str] = None
    SMTP_PASSWORD: Optional[str] = None
    SMTP_TLS: bool = True
    EMAILS_FROM_EMAIL: str = "no-reply@armimarket.it"
    EMAILS_FROM_NAME: str = "ArmiMarket Italia"


settings = Settings()
