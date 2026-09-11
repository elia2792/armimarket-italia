"""
Test suite for Fase 5 - Security Remediation & Final Production Readiness.
Covers:
- SEC-01: Privilege Escalation on registration blocked
- SEC-02: Rate-limiting bypass header (X-Internal-Test-Bypass) ineffective
- SEC-03: Superuser password production validation
- SEC-04: DOM XSS mitigation in templates
- SEC-05: Production CORS origin hardening
- SEC-06: Base.metadata.create_all disabled in production
- SEC-07: Avatar storage configuration (Persistent Disk support)
- SEC-08: XML parser hardened against entity expansion (defusedxml)
- SEC-09: Invalid JWT sub handling returns 401
- SEC-10: JWT query parameter token ignored
- SEC-11: Dockerfile container hardening (non-root & no-server-header)
"""

import os
from pathlib import Path
from unittest.mock import patch, MagicMock
import pytest
from pydantic import ValidationError
from fastapi.security import HTTPAuthorizationCredentials

from app.core.config import Settings
from app.schemas.user_schema import UserCreate, RuoloRegistrazione
from app.core.security import create_access_token


# ==============================================================================
# SEC-01: Privilege Escalation blocked on registration
# ==============================================================================
def test_sec01_privilege_escalation_blocked():
    """Verify that UserCreate rejects roles other than 'privato' or 'armeria'."""
    # Allowed roles
    user_privato = UserCreate(
        email="test_privato@example.com",
        password="ValidPassword123!",
        nome="Mario",
        cognome="Rossi",
        ruolo=RuoloRegistrazione.PRIVATO,
    )
    assert user_privato.ruolo == RuoloRegistrazione.PRIVATO

    user_armeria = UserCreate(
        email="test_armeria@example.com",
        password="ValidPassword123!",
        nome="Armeria",
        cognome="Centrale",
        partita_iva="00811720580",
        ruolo=RuoloRegistrazione.ARMERIA,
    )
    assert user_armeria.ruolo == RuoloRegistrazione.ARMERIA

    # Forbidden roles: 'admin', 'moderatore', or any arbitrary role
    with pytest.raises(ValidationError):
        UserCreate(
            email="attacker@example.com",
            password="ValidPassword123!",
            nome="Attacker",
            cognome="Admin",
            ruolo="admin",  # type: ignore
        )

    with pytest.raises(ValidationError):
        UserCreate(
            email="attacker@example.com",
            password="ValidPassword123!",
            nome="Attacker",
            cognome="Mod",
            ruolo="moderatore",  # type: ignore
        )


# ==============================================================================
# SEC-02: Rate-limiting bypass header ineffective
# ==============================================================================
def test_sec02_rate_limit_bypass_header_ineffective():
    """Verify X-Internal-Test-Bypass header is not present in rate_limit source code."""
    rate_limit_file = Path("app/core/rate_limit.py")
    assert rate_limit_file.exists()
    content = rate_limit_file.read_text(encoding="utf-8")
    assert "X-Internal-Test-Bypass" not in content, (
        "Found X-Internal-Test-Bypass backdoor in app/core/rate_limit.py!"
    )


# ==============================================================================
# SEC-03: Superuser password production validation
# ==============================================================================
def test_sec03_superuser_password_production_validation():
    """Verify production security validation rejects weak or default superuser passwords."""
    # Production with default password must raise ValidationError/ValueError
    with pytest.raises((ValidationError, ValueError), match="FIRST_SUPERUSER_PASSWORD"):
        Settings(
            ENVIRONMENT="production",
            SECRET_KEY="A" * 32,
            FIRST_SUPERUSER_PASSWORD="AdminArmiMarket2026!",
            ALLOWED_ORIGINS=["https://armimarket.it"],
        )

    # Production with short password (< 12 chars) must raise ValidationError/ValueError
    with pytest.raises((ValidationError, ValueError), match="almeno 12 caratteri|at least 12 characters"):
        Settings(
            ENVIRONMENT="production",
            SECRET_KEY="A" * 32,
            FIRST_SUPERUSER_PASSWORD="Short1!",
            ALLOWED_ORIGINS=["https://armimarket.it"],
        )

    # Production with robust password and safe origins must pass
    prod_valid = Settings(
        ENVIRONMENT="production",
        SECRET_KEY="A" * 32,
        FIRST_SUPERUSER_PASSWORD="StrongProductionSecretPass2026!#",
        ALLOWED_ORIGINS=["https://armimarket.it"],
    )
    prod_valid.validate_production_security()


# ==============================================================================
# SEC-04: DOM XSS mitigation in templates
# ==============================================================================
def test_sec04_dom_xss_mitigation():
    """Verify templates escape dynamic server errors before inserting into DOM."""
    login_html = Path("app/templates/login.html").read_text(encoding="utf-8")
    assert "window.escapeHtml" in login_html
    assert "safeDetail" in login_html

    registrati_html = Path("app/templates/registrati.html").read_text(encoding="utf-8")
    assert "window.escapeHtml" in registrati_html
    assert "safeDetail" in registrati_html

    posta_html = Path("app/templates/admin_posta.html").read_text(encoding="utf-8")
    assert "escapeHtml(data.detail" in posta_html
    assert "escapeHtml(data.destinatario" in posta_html
    assert "escapeHtml(data.message" in posta_html


# ==============================================================================
# SEC-05: Production CORS origin hardening
# ==============================================================================
def test_sec05_cors_production_safety():
    """Verify validate_production_security strips insecure origins (localhost, 127.0.0.1, http://)."""
    prod_cors = Settings(
        ENVIRONMENT="production",
        SECRET_KEY="A" * 32,
        FIRST_SUPERUSER_PASSWORD="StrongProductionSecretPass2026!#",
        ALLOWED_ORIGINS=[
            "http://localhost:3000",
            "http://127.0.0.1:8000",
            "http://insecure-domain.it",
            "https://armimarket.it",
            "https://www.armimarket.it",
        ],
    )
    prod_cors.validate_production_security()
    # Insecure origins must be purged in production
    assert "http://localhost:3000" not in prod_cors.ALLOWED_ORIGINS
    assert "http://127.0.0.1:8000" not in prod_cors.ALLOWED_ORIGINS
    assert "http://insecure-domain.it" not in prod_cors.ALLOWED_ORIGINS
    # Secure https origins must be preserved
    assert "https://armimarket.it" in prod_cors.ALLOWED_ORIGINS
    assert "https://www.armimarket.it" in prod_cors.ALLOWED_ORIGINS


# ==============================================================================
# SEC-06: Base.metadata.create_all disabled in production
# ==============================================================================
def test_sec06_create_all_disabled_in_production():
    """Verify main.py lifespan checks is_production before executing create_all."""
    main_py = Path("app/main.py").read_text(encoding="utf-8")
    assert "if not is_production:" in main_py
    assert "Base.metadata.create_all" in main_py


# ==============================================================================
# SEC-07: Avatar storage configuration (Persistent Disk support)
# ==============================================================================
def test_sec07_avatar_storage_configuration(tmp_path):
    """Verify auth.py get_avatar_dir respects AVATAR_UPLOAD_DIR when set."""
    from app.routers.auth import get_avatar_dir
    from app.core.config import settings

    custom_dir = str(tmp_path / "custom_avatars")
    with patch.object(settings, "AVATAR_UPLOAD_DIR", custom_dir):
        resolved = get_avatar_dir()
        assert resolved == Path(custom_dir).resolve()

    with patch.object(settings, "AVATAR_UPLOAD_DIR", None):
        fallback = get_avatar_dir()
        assert fallback == (Path(__file__).resolve().parents[1] / "app" / "static" / "uploads" / "avatars").resolve()


# ==============================================================================
# SEC-08: XML parser hardened against entity expansion (defusedxml)
# ==============================================================================
def test_sec08_xml_defusedxml_bombs_blocked():
    """Verify XmlFeedAdapter uses defusedxml to parse XML safely and rejects XML entity bombs."""
    from app.services.ingestion.xml_adapter import XmlFeedAdapter
    import defusedxml.common

    adapter = XmlFeedAdapter()

    # XML Entity Expansion bomb (Billion Laughs / DTD entity)
    xml_bomb = """<?xml version="1.0"?>
    <!DOCTYPE lolz [
      <!ENTITY lol "lol">
      <!ELEMENT lolz (#PCDATA)>
      <!ENTITY lol1 "&lol;&lol;&lol;&lol;&lol;&lol;&lol;&lol;&lol;&lol;">
      <!ENTITY lol2 "&lol1;&lol1;&lol1;&lol1;&lol1;&lol1;&lol1;&lol1;&lol1;&lol1;">
    ]>
    <feed>
      <item>
        <title>&lol2;</title>
        <price>100</price>
      </item>
    </feed>
    """

    # defusedxml should raise DTDForbidden or EntitiesForbidden
    with pytest.raises((defusedxml.common.DefusedXmlException, ValueError)):
        adapter.fetch_feed(xml_bomb)


# ==============================================================================
# SEC-09: Invalid JWT sub handling returns 401
# ==============================================================================
@pytest.mark.asyncio
async def test_sec09_jwt_invalid_sub_returns_401():
    """Verify get_current_user returns 401 when JWT sub claim is not an integer."""
    from fastapi import HTTPException
    from app.routers.auth import get_current_user

    # Token with non-integer sub
    invalid_token = create_access_token(subject="not-an-int")
    creds = HTTPAuthorizationCredentials(scheme="Bearer", credentials=invalid_token)
    mock_db = MagicMock()

    with pytest.raises(HTTPException) as exc_info:
        await get_current_user(credentials=creds, db=mock_db)

    assert exc_info.value.status_code == 401
    assert "identificativo utente non valido" in exc_info.value.detail or "Invalid user ID" in exc_info.value.detail


# ==============================================================================
# SEC-10: JWT query parameter token ignored
# ==============================================================================
def test_sec10_jwt_query_param_ignored():
    """Verify views.py does not extract JWT tokens from URL query parameters (?token=)."""
    views_py = Path("app/routers/views.py").read_text(encoding="utf-8")
    assert 'request.query_params.get("token")' not in views_py


# ==============================================================================
# SEC-11: Dockerfile container hardening
# ==============================================================================
def test_sec11_dockerfile_non_root_and_no_server_header():
    """Verify Dockerfile creates non-root user and runs uvicorn with --no-server-header."""
    dockerfile = Path("Dockerfile").read_text(encoding="utf-8")
    assert "USER appuser" in dockerfile
    assert "--no-server-header" in dockerfile
