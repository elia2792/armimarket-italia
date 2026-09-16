from typing import List, Optional
from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.rate_limit import rate_limit
from app.models.user import User
from app.routers.auth import get_current_user
from app.schemas.valutazione_schema import (
    RiepilogoValutazioniOut,
    ValutazioneCreate,
    ValutazioneOut,
)
from app.services.valutazione_service import ValutazioneService

router = APIRouter(prefix="/valutazioni", tags=["Valutazioni & Recensioni"])


@router.post(
    "",
    response_model=ValutazioneOut,
    status_code=status.HTTP_200_OK,
    dependencies=[Depends(rate_limit(max_requests=10, window_seconds=60, prefix="valutazioni_create"))]
)
async def lascia_o_aggiorna_valutazione(
    data: ValutazioneCreate,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    """
    Inserisce una nuova valutazione o aggiorna quella esistente per un utente o un'armeria esterna.
    Richiede autenticazione. Vietata l'auto-valutazione.
    """
    try:
        val, _ = await ValutazioneService.crea_o_aggiorna_valutazione(
            db=db,
            autore=current_user,
            data=data
        )
        return ValutazioneOut(
            id=val.id,
            voto=val.voto,
            titolo=val.titolo,
            commento=val.commento,
            data_creazione=val.data_creazione,
            data_aggiornamento=val.data_aggiornamento,
            autore_id=current_user.id,
            autore_display_name=current_user.display_name,
            autore_foto=current_user.foto_profilo,
            recensito_utente_id=val.recensito_utente_id,
            fonte_esterna=val.fonte_esterna,
            annuncio_id=val.annuncio_id
        )
    except ValueError as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(e)
        )
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Errore durante il salvataggio della valutazione: {str(e)}"
        )


@router.get("/utente/{utente_id}", response_model=RiepilogoValutazioniOut)
async def get_valutazioni_utente(
    utente_id: int,
    db: AsyncSession = Depends(get_db)
):
    """Restituisce la media, il conteggio e la lista delle valutazioni per un utente registrato."""
    return await ValutazioneService.get_riepilogo(db=db, utente_id=utente_id)


@router.get("/fonte/{fonte_esterna}", response_model=RiepilogoValutazioniOut)
async def get_valutazioni_fonte_esterna(
    fonte_esterna: str,
    db: AsyncSession = Depends(get_db)
):
    """Restituisce la media, il conteggio e la lista delle valutazioni per un'armeria esterna."""
    return await ValutazioneService.get_riepilogo(db=db, fonte_esterna=fonte_esterna)


@router.get("/mie-ricevute", response_model=List[ValutazioneOut])
async def get_mie_valutazioni_ricevute(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    """Restituisce tutte le recensioni ricevute dall'utente autenticato."""
    return await ValutazioneService.get_valutazioni_ricevute_utente(db=db, utente_id=current_user.id)


@router.delete("/{valutazione_id}")
async def elimina_valutazione(
    valutazione_id: int,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    """Elimina una valutazione (consentito solo all'autore o all'amministratore)."""
    try:
        success = await ValutazioneService.elimina_valutazione(
            db=db,
            valutazione_id=valutazione_id,
            user=current_user
        )
        if not success:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Valutazione non trovata."
            )
        return {"success": True, "message": "Valutazione eliminata con successo."}
    except PermissionError as e:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=str(e)
        )
