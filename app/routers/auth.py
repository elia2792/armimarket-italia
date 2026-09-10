from datetime import timedelta
from typing import Optional
import shutil
import uuid
from pathlib import Path
from fastapi import APIRouter, Depends, HTTPException, Security, UploadFile, File, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.database import get_db
from app.core.security import (
    create_access_token,
    create_password_reset_token,
    decode_access_token,
    hash_password,
    verify_password,
    verify_password_reset_token,
)
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

    user_id = int(payload["sub"])
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


@router.post("/register", response_model=UserOut, status_code=status.HTTP_201_CREATED)
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
        ruolo=user_in.ruolo,
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


@router.post("/login", response_model=Token)
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


@router.post("/forgot-password", response_model=PasswordResetResponse)
async def forgot_password(req: PasswordResetRequest, db: AsyncSession = Depends(get_db)):
    """
    Richiesta di recupero password:
    - Verifica che l'email esista nel database.
    - Genera un token temporaneo crittografato e univoco con validità di 30 minuti.
    - Restituisce il messaggio di conferma e il link di ripristino sicuro (utilizzato dal frontend e per invio email).
    """
    clean_email = req.email.lower().strip()
    stmt = select(User).where(User.email == clean_email)
    user = (await db.execute(stmt)).scalar_one_or_none()

    if not user:
        # Per sicurezza (anti user-enumeration) restituiamo un messaggio neutro o 404 controllato
        # In questo caso, per chiarezza all'utente segnaliamo se l'indirizzo non è registrato:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Nessun account registrato trovato con questo indirizzo email."
        )

    if not user.is_active:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="L'account associato a questa email risulta disattivato."
        )

    # Genera token crittografico di reset
    reset_token = create_password_reset_token(clean_email)
    reset_url = f"/reimposta-password?token={reset_token}"

    # Invio effettivo email tramite servizio email e persistenza su log casella postale
    email_sent = await EmailService.send_password_reset_email(clean_email, reset_url, db=db)

    msg = f"Ti abbiamo inviato un'email all'indirizzo {clean_email} con il link per reimpostare la tua password."
    if not email_sent and not settings.SMTP_HOST:
        msg = f"Richiesta registrata per {clean_email}. (SMTP di posta in uscita non configurato nel file .env: il link di ripristino è disponibile per il test)."

    return PasswordResetResponse(
        message=msg,
        reset_link=reset_url if (settings.DEBUG or not settings.SMTP_HOST) else None
    )


@router.post("/reset-password")
async def reset_password(req: PasswordResetConfirm, db: AsyncSession = Depends(get_db)):
    """
    Reimpostazione della password tramite token:
    - Valida la firma crittografica e la scadenza del token di reset.
    - Aggiorna la password dell'utente calcolando un nuovo hash bcrypt sicuro.
    """
    email = verify_password_reset_token(req.token)
    if not email:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Il link di recupero password è non valido o è scaduto. Richiedine uno nuovo."
        )

    stmt = select(User).where(User.email == email.lower().strip())
    user = (await db.execute(stmt)).scalar_one_or_none()

    if not user:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Utente associato al token non trovato."
        )

    user.hashed_password = hash_password(req.nuova_password)
    await db.commit()

    return {"message": "Password reimpostata con successo! Ora puoi effettuare l'accesso con la nuova password."}


@router.post("/contatta-admin")
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

    # Memorizza nella casella postale interna con tipologia "messaggio_admin"
    await EmailService.log_and_send_email(
        to_email="admin@armimarket.it",
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


# ──────────────────────────────────────────────────────────────
# UPLOAD FOTO PROFILO
# ──────────────────────────────────────────────────────────────

AVATAR_DIR = Path(__file__).resolve().parent.parent / "static" / "uploads" / "avatars"
ALLOWED_TYPES = {"image/jpeg", "image/png", "image/webp"}
MAX_AVATAR_BYTES = 3 * 1024 * 1024  # 3 MB


@router.post("/me/foto", response_model=UserOut, summary="Carica Foto Profilo")
async def upload_foto_profilo(
    file: UploadFile = File(..., description="Immagine JPG, PNG o WebP (max 3 MB)"),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """
    Carica o sostituisce la foto profilo dell'utente autenticato.
    Accetta JPG, PNG e WebP fino a 3 MB. La foto viene servita
    come file statico all'URL /static/uploads/avatars/<filename>.
    """
    if file.content_type not in ALLOWED_TYPES:
        raise HTTPException(
            status_code=status.HTTP_415_UNSUPPORTED_MEDIA_TYPE,
            detail="Formato non supportato. Usa JPG, PNG o WebP.",
        )

    # Leggi il contenuto e controlla la dimensione
    contents = await file.read()
    if len(contents) > MAX_AVATAR_BYTES:
        raise HTTPException(
            status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
            detail="L'immagine supera la dimensione massima consentita di 3 MB.",
        )

    # Genera nome univoco per evitare collisioni
    ext = file.filename.rsplit(".", 1)[-1].lower() if "." in file.filename else "jpg"
    filename = f"{current_user.id}_{uuid.uuid4().hex}.{ext}"
    AVATAR_DIR.mkdir(parents=True, exist_ok=True)
    dest = AVATAR_DIR / filename

    # Scrivi su disco
    with dest.open("wb") as f:
        f.write(contents)

    # Rimuovi vecchia foto se esisteva
    if current_user.foto_profilo:
        old_name = current_user.foto_profilo.split("/")[-1]
        old_path = AVATAR_DIR / old_name
        if old_path.exists():
            old_path.unlink(missing_ok=True)

    # Aggiorna DB
    current_user.foto_profilo = f"/static/uploads/avatars/{filename}"
    await db.commit()
    await db.refresh(current_user)

    return current_user
