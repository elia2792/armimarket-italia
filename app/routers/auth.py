import io
from datetime import datetime, timedelta, timezone
from typing import Optional
import shutil
import uuid
from pathlib import Path
from fastapi import APIRouter, Depends, HTTPException, Response, Security, UploadFile, File, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from PIL import Image, UnidentifiedImageError
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.database import get_db
from app.core.security import (
    create_access_token,
    decode_access_token,
    hash_password,
    verify_password,
)
from app.core.rate_limit import rate_limit
from app.models.password_reset import PasswordResetToken
from app.models.user import RuoloUtente, User
from app.services.email_service import EmailService
from app.schemas.user_schema import (
    PasswordResetConfirm,
    PasswordResetRequest,
    PasswordResetResponse,
    ContactAdminRequest,
    Token,
    UserCreate,
    UserLogin,
    UserOut,
    UserUpdateProfile,
)


router = APIRouter(prefix="/auth", tags=["Autenticazione & Profilo"])
security_scheme = HTTPBearer(auto_error=False)


async def get_current_user(
    credentials: Optional[HTTPAuthorizationCredentials] = Security(security_scheme),
    db: AsyncSession = Depends(get_db)
) -> User:
    """Dipendenza per estrarre l'utente autenticato dal token Bearer JWT."""
    if not credentials:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Token di autenticazione mancante.",
            headers={"WWW-Authenticate": "Bearer"},
        )

    token = credentials.credentials
    payload = decode_access_token(token)
    if not payload or "sub" not in payload:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Token non valido o scaduto.",
            headers={"WWW-Authenticate": "Bearer"},
        )

    try:
        user_id = int(payload["sub"])
    except (ValueError, TypeError, KeyError):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Token non valido o identificativo utente non valido.",
            headers={"WWW-Authenticate": "Bearer"},
        )
    stmt = select(User).where(User.id == user_id)
    result = await db.execute(stmt)
    user = result.scalar_one_or_none()

    if not user:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Utente associato al token non trovato."
        )
    if not user.is_active:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Account utente disabilitato."
        )

    return user


async def get_current_moderator(
    current_user: User = Depends(get_current_user)
) -> User:
    """Dipendenza che richiede ruolo ADMIN o MODERATORE."""
    if current_user.ruolo not in [RuoloUtente.ADMIN, RuoloUtente.MODERATORE]:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Accesso riservato ai moderatori o amministratori della piattaforma."
        )
    return current_user


async def get_current_admin(
    current_user: User = Depends(get_current_user)
) -> User:
    """Dipendenza che richiede ruolo ADMIN."""
    if current_user.ruolo != RuoloUtente.ADMIN:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Operazione riservata esclusivamente agli amministratori."
        )
    return current_user


async def get_optional_current_user(
    credentials: Optional[HTTPAuthorizationCredentials] = Security(security_scheme),
    db: AsyncSession = Depends(get_db)
) -> Optional[User]:
    """Restituisce l'utente autenticato se presente un Bearer token valido, altrimenti None."""
    if not credentials:
        return None
    try:
        token = credentials.credentials
        payload = decode_access_token(token)
        if not payload or "sub" not in payload:
            return None
        user_id = int(payload["sub"])
        stmt = select(User).where(User.id == user_id)
        result = await db.execute(stmt)
        user = result.scalar_one_or_none()
        if user and user.is_active:
            return user
        return None
    except Exception:
        return None


@router.post(
    "/register",
    response_model=UserOut,
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(rate_limit(max_requests=3, window_seconds=60, prefix="auth_register"))]
)
async def register(user_in: UserCreate, db: AsyncSession = Depends(get_db)):
    """Registrazione di un nuovo privato o armeria autorizzata."""
    stmt = select(User).where(User.email == user_in.email.lower())
    existing = (await db.execute(stmt)).scalar_one_or_none()
    if existing:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Un utente con questo indirizzo email è già registrato."
        )

    clean_nick = None
    if user_in.nickname and user_in.nickname.strip():
        clean_nick = user_in.nickname.strip()
        stmt_nick = select(User).where(func.lower(User.nickname) == clean_nick.lower())
        if (await db.execute(stmt_nick)).scalar_one_or_none():
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Il nickname '{clean_nick}' è già utilizzato. Scegline un altro."
            )

    # Defense in depth: accetta esclusivamente ruoli non privilegiati (privato o armeria)
    requested_ruolo_str = str(getattr(user_in.ruolo, "value", user_in.ruolo)).lower()
    if requested_ruolo_str in ("admin", "moderatore"):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Non è consentito registrarsi con ruoli amministrativi o di moderazione."
        )

    assigned_ruolo = RuoloUtente.ARMERIA if requested_ruolo_str == "armeria" else RuoloUtente.PRIVATO

    new_user = User(
        email=user_in.email.lower(),
        hashed_password=hash_password(user_in.password),
        nickname=clean_nick,
        nome=user_in.nome,
        cognome=user_in.cognome,
        ragione_sociale=user_in.ragione_sociale,
        partita_iva=user_in.partita_iva,
        codice_fiscale=user_in.codice_fiscale.upper() if user_in.codice_fiscale else None,
        licenza_tulps=user_in.licenza_tulps,
        ruolo=assigned_ruolo,
        telefono=user_in.telefono,
        comune_id=user_in.comune_id,
        indirizzo=user_in.indirizzo,
        sito_web=user_in.sito_web.strip() if user_in.sito_web else None,
        latitudine=user_in.latitudine,
        longitudine=user_in.longitudine,
        is_active=True,
        # Le armerie con licenza TULPS dichiarata possono richiedere verifica documentale
        is_verified=False
    )

    # Se è un'armeria con sito web, genera template di ricerca predefinito per il motore
    if new_user.ruolo == RuoloUtente.ARMERIA and new_user.sito_web:
        clean_site = new_user.sito_web.rstrip('/')
        if not clean_site.startswith(('http://', 'https://')):
            clean_site = 'https://' + clean_site
            new_user.sito_web = clean_site
        new_user.search_url_custom = f"{clean_site}/?s={{query}}&post_type=product"

    db.add(new_user)
    await db.commit()
    await db.refresh(new_user)
    return new_user


@router.post(
    "/login",
    response_model=Token,
    dependencies=[Depends(rate_limit(max_requests=5, window_seconds=60, prefix="auth_login"))]
)
async def login(credentials: UserLogin, db: AsyncSession = Depends(get_db)):
    """Autenticazione con rilascio token JWT."""
    stmt = select(User).where(User.email == credentials.email.lower())
    user = (await db.execute(stmt)).scalar_one_or_none()

    if not user or not verify_password(credentials.password, user.hashed_password):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Credenziali email o password non valide."
        )

    if not user.is_active:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Account sospeso o disattivato."
        )

    token = create_access_token(
        subject=user.id,
        extra_claims={"email": user.email, "ruolo": user.ruolo.value}
    )

    return Token(access_token=token, token_type="bearer", user=UserOut.model_validate(user))


@router.get("/me", response_model=UserOut)
async def get_profile(current_user: User = Depends(get_current_user)):
    """Restituisce il profilo dell'utente attualmente autenticato."""
    return current_user


@router.put("/me", response_model=UserOut)
async def update_profile(
    update_data: UserUpdateProfile,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    """Aggiorna i dati del profilo (es. Nickname pubblico e recapito telefonico)."""
    if update_data.nickname is not None:
        clean_nick = update_data.nickname.strip() if update_data.nickname.strip() else None
        if clean_nick:
            # Verifica univocità nickname escludendo l'utente stesso
            stmt_nick = select(User).where(
                func.lower(User.nickname) == clean_nick.lower(),
                User.id != current_user.id
            )
            existing_nick = (await db.execute(stmt_nick)).scalar_one_or_none()
            if existing_nick:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail=f"Il nickname '{clean_nick}' è già utilizzato da un altro utente. Scegline uno diverso."
                )
            current_user.nickname = clean_nick
        else:
            current_user.nickname = None

    if update_data.telefono is not None:
        current_user.telefono = update_data.telefono.strip() if update_data.telefono.strip() else None

    await db.commit()
    await db.refresh(current_user)
    return current_user


@router.post(
    "/forgot-password",
    response_model=PasswordResetResponse,
    dependencies=[Depends(rate_limit(max_requests=3, window_seconds=60, prefix="auth_forgot"))]
)
async def forgot_password(req: PasswordResetRequest, db: AsyncSession = Depends(get_db)):
    """
    Richiesta di recupero password anti-enumeration:
    - Restituisce la medesima risposta generica sia per email esistenti che inesistenti (OWASP ASVS).
    - Non espone MAI token o reset_link nella risposta JSON o nei log.
    - Se l'account esiste ed è attivo, genera un token crittografico monouso ad alta entropia
      salvando l'hash SHA-256 nel database con validità di 30 minuti.
    """
    clean_email = req.email.lower().strip()
    stmt = select(User).where(User.email == clean_email)
    user = (await db.execute(stmt)).scalar_one_or_none()

    if user and user.is_active:
        # Genera token crittografico monouso (URL-safe ad alta entropia) e relativo hash SHA-256
        raw_token, token_hash = PasswordResetToken.generate_token()
        expires_at = datetime.now(timezone.utc) + timedelta(minutes=30)

        reset_entry = PasswordResetToken(
            user_id=user.id,
            token_hash=token_hash,
            expires_at=expires_at,
            used=False
        )
        db.add(reset_entry)
        await db.commit()

        reset_url = f"/reimposta-password?token={raw_token}"
        # Invia l'email sicura (o memorizza nel log della casella interna se SMTP non configurato)
        await EmailService.send_password_reset_email(clean_email, reset_url, db=db)

    # Risposta generica sempre identica: nessun token o link restituito nel JSON
    return PasswordResetResponse(
        message="Se l'indirizzo email fornito è associato a un account attivo, riceverai a breve le istruzioni per reimpostare la tua password.",
        reset_link=None
    )


@router.post(
    "/reset-password",
    dependencies=[Depends(rate_limit(max_requests=5, window_seconds=60, prefix="auth_reset"))]
)
async def reset_password(req: PasswordResetConfirm, db: AsyncSession = Depends(get_db)):
    """
    Reimpostazione della password tramite token monouso:
    - Verifica l'hash SHA-256 del token crittografico.
    - Verifica che il token non sia scaduto e non sia già stato utilizzato.
    - Aggiorna la password con hash bcrypt e marca immediatamente il token come utilizzato.
    """
    token_hash = PasswordResetToken.hash_token(req.token)
    now = datetime.now(timezone.utc)

    stmt = select(PasswordResetToken).where(
        PasswordResetToken.token_hash == token_hash,
        PasswordResetToken.used.is_(False),
        PasswordResetToken.expires_at > now
    )
    reset_entry = (await db.execute(stmt)).scalar_one_or_none()

    if not reset_entry:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Il link di recupero password è non valido o è scaduto. Richiedine uno nuovo."
        )

    user = (await db.execute(select(User).where(User.id == reset_entry.user_id))).scalar_one_or_none()
    if not user or not user.is_active:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Utente associato al token non trovato o account non attivo."
        )

    # Aggiorna password
    user.hashed_password = hash_password(req.nuova_password)
    # Invalida immediatamente il token (monouso)
    reset_entry.used = True
    await db.commit()

    return {"message": "Password reimpostata con successo! Ora puoi effettuare l'accesso con la nuova password."}


@router.post(
    "/contatta-admin",
    dependencies=[Depends(rate_limit(max_requests=5, window_seconds=60, prefix="auth_contatta"))]
)
async def contatta_admin(req: ContactAdminRequest, db: AsyncSession = Depends(get_db)):
    """
    Consente a chiunque (iscritti o visitatori) di inviare un messaggio diretto all'amministratore (Admin).
    L'indirizzo email personale dell'amministratore non viene MAI esposto all'esterno.
    Il messaggio viene salvato nella casella postale interna (/admin/posta).
    """
    subject = f"[Messaggio per Admin] {req.oggetto}"
    text_body = (
        f"Nuovo messaggio inviato da un utente del sito per l'Amministratore (Admin):\n\n"
        f"Mittente: {req.nome} <{req.email}>\n"
        f"Oggetto: {req.oggetto}\n\n"
        f"Messaggio:\n{req.messaggio}\n\n"
        f"ArmiMarket Italia - Casella Amministratore"
    )

    html_body = f"""
    <div style="font-family: sans-serif; background-color: #020617; color: #f8fafc; padding: 24px; border-radius: 16px; border: 1px solid #1e293b; max-width: 600px;">
        <div style="border-bottom: 1px solid #334155; padding-bottom: 12px; margin-bottom: 16px;">
            <span style="background: #f59e0b; color: #020617; font-weight: 900; font-size: 11px; padding: 3px 8px; border-radius: 6px; text-transform: uppercase;">Messaggio per Admin</span>
            <h2 style="color: #ffffff; margin: 8px 0 0 0; font-size: 18px;">{req.oggetto}</h2>
        </div>
        <div style="font-size: 13px; color: #94a3b8; margin-bottom: 16px;">
            <p style="margin: 4px 0;"><strong>Mittente:</strong> <span style="color: #ffffff;">{req.nome}</span></p>
            <p style="margin: 4px 0;"><strong>Email per risposta:</strong> <a href="mailto:{req.email}" style="color: #38bdf8;">{req.email}</a></p>
        </div>
        <div style="background-color: #0f172a; border: 1px solid #334155; border-radius: 12px; padding: 16px; color: #f1f5f9; font-size: 14px; white-space: pre-wrap; line-height: 1.6;">
{req.messaggio}
        </div>
        <div style="margin-top: 20px; font-size: 11px; color: #64748b; border-top: 1px solid #1e293b; padding-top: 12px;">
            Messaggio recapitato tramite il modulo "Scrivi ad Admin" di ArmiMarket Italia.
        </div>
    </div>
    """

    # Memorizza nella casella postale interna con tipologia "richiesta_contatto" e inoltra via SMTP
    await EmailService.log_and_send_email(
        to_email=settings.ADMIN_EMAIL,
        subject=subject,
        html_body=html_body,
        text_body=text_body,
        tipologia="richiesta_contatto",
        from_email=f"{req.nome} <{req.email}>",
        db=db
    )

    return {
        "success": True,
        "message": "Il tuo messaggio è stato inviato con successo ad Admin. Riceverai risposta al tuo indirizzo email."
    }


def validate_image_magic_bytes(data: bytes) -> str:
    """
    Verifica i magic bytes effettivi del file:
    - JPEG: \\xFF\\xD8\\xFF
    - PNG:  \\x89PNG\\r\\n\\x1a\\n
    - WebP: RIFF....WEBP
    Rifiuta categoricamente SVG, file HTML, script PHP o JavaScript mascherati.
    """
    if len(data) < 12:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="File immagine troppo piccolo o incompleto."
        )

    prefix_lower = data[:256].lower()
    if (
        b"<?xml" in prefix_lower
        or b"<svg" in prefix_lower
        or b"<!doctype" in prefix_lower
        or b"<html" in prefix_lower
        or b"<script" in prefix_lower
        or b"<?php" in prefix_lower
    ):
        raise HTTPException(
            status_code=status.HTTP_415_UNSUPPORTED_MEDIA_TYPE,
            detail="Formato non consentito: file SVG, HTML, script o contenuti attivi sono vietati."
        )

    if data[:3] == b"\xff\xd8\xff":
        return "JPEG"
    if data[:8] == b"\x89PNG\r\n\x1a\n":
        return "PNG"
    if data[:4] == b"RIFF" and data[8:12] == b"WEBP":
        return "WEBP"

    raise HTTPException(
        status_code=status.HTTP_415_UNSUPPORTED_MEDIA_TYPE,
        detail="Formato non supportato. Sono accettati solo file JPG/JPEG, PNG o WebP autentici."
    )


MAX_AVATAR_BYTES = 3 * 1024 * 1024  # 3 MB


def get_avatar_dir() -> Path:
    """Restituisce la directory di salvataggio avatar (supporta persistent disk Render)."""
    if settings.AVATAR_UPLOAD_DIR:
        return Path(settings.AVATAR_UPLOAD_DIR).resolve()
    return (Path(__file__).resolve().parents[1] / "static" / "uploads" / "avatars").resolve()


@router.post(
    "/me/foto",
    response_model=UserOut,
    summary="Carica Foto Profilo",
    dependencies=[Depends(rate_limit(max_requests=5, window_seconds=60, prefix="auth_avatar"))]
)
async def upload_foto_profilo(
    file: UploadFile = File(..., description="Immagine JPG, PNG o WebP (max 3 MB)"),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """
    Carica, valida e normalizza la foto profilo dell'utente autenticato:
    - Dimensione massima: 3 MB lato server.
    - Validazione magic bytes effettivi (blocco SVG, HTML, script).
    - Normalizzazione e ricodifica dell'immagine con Pillow (eliminazione EXIF e payload nascosti).
    - Nome file e percorso generati esclusivamente lato server (prevenzione path traversal).
    """
    # 1. Lettura buffer e verifica dimensione
    contents = await file.read()
    if len(contents) > MAX_AVATAR_BYTES:
        raise HTTPException(
            status_code=status.HTTP_413_CONTENT_TOO_LARGE,
            detail="L'immagine supera la dimensione massima consentita di 3 MB.",
        )

    # 2. Verifica magic bytes
    detected_format = validate_image_magic_bytes(contents)

    # 3. Verifica strutturale con Pillow e ricodifica sicura
    try:
        # Verifica integrità iniziale
        with Image.open(io.BytesIO(contents)) as img_check:
            img_check.verify()

        # Riapertura per sanitizzazione/ricodifica (verify invalida il puntatore)
        with Image.open(io.BytesIO(contents)) as img:
            real_format = (img.format or detected_format).upper()
            if real_format not in ("JPEG", "PNG", "WEBP"):
                raise HTTPException(
                    status_code=status.HTTP_415_UNSUPPORTED_MEDIA_TYPE,
                    detail="Formato immagine non supportato (consentiti solo JPEG, PNG, WebP)."
                )

            ext_map = {"JPEG": "jpg", "PNG": "png", "WEBP": "webp"}
            safe_ext = ext_map.get(real_format, "jpg")

            # Ricodifica in nuovo buffer pulito rimuovendo tutti i metadati EXIF
            output_buffer = io.BytesIO()
            if real_format == "JPEG":
                if img.mode in ("RGBA", "LA", "P"):
                    img = img.convert("RGB")
                img.save(output_buffer, format="JPEG", quality=85, optimize=True)
            elif real_format == "PNG":
                img.save(output_buffer, format="PNG", optimize=True)
            elif real_format == "WEBP":
                img.save(output_buffer, format="WEBP", quality=85)

            reencoded_bytes = output_buffer.getvalue()

    except HTTPException:
        raise
    except (UnidentifiedImageError, OSError, ValueError):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Il file caricato non è un'immagine valida o risulta corrotto."
        )

    # 4. Generazione nome univoco e path server-side protetto (il filename del client è scartato)
    filename = f"avatar_{current_user.id}_{uuid.uuid4().hex}.{safe_ext}"
    avatar_dir = get_avatar_dir()
    avatar_dir.mkdir(parents=True, exist_ok=True)
    dest = (avatar_dir / filename).resolve()

    if not dest.is_relative_to(avatar_dir):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Percorso di destinazione non valido."
        )

    # 5. Scrittura sicura su disco
    with dest.open("wb") as f:
        f.write(reencoded_bytes)

    # 6. Rimozione eventuale avatar precedente se risiede nella cartella avatar
    if current_user.foto_profilo:
        old_name = Path(current_user.foto_profilo).name
        old_path = (avatar_dir / old_name).resolve()
        if old_path.is_relative_to(avatar_dir) and old_path.exists():
            old_path.unlink(missing_ok=True)

    # 7. Aggiornamento record utente
    current_user.foto_profilo = f"/static/uploads/avatars/{filename}"
    await db.commit()
    await db.refresh(current_user)

    return current_user


@router.post(
    "/logout",
    summary="Logout utente e cancellazione cookie"
)
async def api_logout(response: Response):
    """Cancella i cookie di autenticazione lato server."""
    response.headers["Clear-Site-Data"] = '"cache", "cookies", "storage"'
    response.delete_cookie(key="armimarket_token", path="/")
    response.delete_cookie(key="access_token", path="/")
    response.delete_cookie(key="token", path="/")
    return {"success": True, "message": "Logout completato con successo."}

