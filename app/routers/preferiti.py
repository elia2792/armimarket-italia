from typing import List
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.core.database import get_db
from app.models.annuncio import Annuncio, StatoAnnuncio
from app.models.geo import Comune, Provincia
from app.models.preferito import Preferito
from app.models.user import User
from app.routers.auth import get_current_user
from app.schemas.annuncio_schema import AnnuncioPublicOut
from app.schemas.geo_schema import ComuneOut

router = APIRouter(prefix="/preferiti", tags=["Annunci Preferiti"])


@router.get("", response_model=List[AnnuncioPublicOut])
async def list_preferiti(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    """Restituisce l'elenco degli annunci salvati tra i preferiti dall'utente autenticato."""
    stmt = (
        select(Annuncio)
        .join(Preferito, Preferito.annuncio_id == Annuncio.id)
        .where(Preferito.utente_id == current_user.id)
        .options(
            selectinload(Annuncio.comune).selectinload(Comune.provincia).selectinload(Provincia.regione)
        )
        .order_by(Preferito.data_creazione.desc())
    )
    res = await db.execute(stmt)
    annunci = res.scalars().all()

    out = []
    for a in annunci:
        comune_out = None
        if a.comune:
            comune_out = ComuneOut(
                id=a.comune.id,
                nome=a.comune.nome,
                cap=a.comune.cap,
                provincia_id=a.comune.provincia_id,
                latitudine=a.comune.latitudine,
                longitudine=a.comune.longitudine,
                sigla_provincia=a.comune.provincia.sigla_automobilistica if a.comune.provincia else None,
                nome_regione=a.comune.provincia.regione.nome if a.comune.provincia and a.comune.provincia.regione else None
            )
        out.append(
            AnnuncioPublicOut(
                id=a.id,
                titolo=a.titolo,
                slug=a.slug,
                descrizione=a.descrizione,
                prezzo=a.prezzo,
                stato=a.stato,
                tipologia_inserzionista=a.tipologia_inserzionista,
                tipologia_arma=a.tipologia_arma,
                marca=a.marca,
                modello=a.modello,
                calibro=a.calibro,
                classificazione=a.classificazione,
                condizione=a.condizione,
                comune_id=a.comune_id,
                galleria_immagini=a.galleria_immagini or [],
                link_esterno=a.link_esterno,
                email_contatto=a.email_contatto,
                telefono_contatto=a.telefono_contatto if a.mostra_telefono_pubblico else None,
                visualizzazioni=a.visualizzazioni,
                data_creazione=a.data_creazione,
                data_aggiornamento=a.data_aggiornamento,
                comune=comune_out
            )
        )
    return out


@router.get("/ids", response_model=List[int])
async def list_preferiti_ids(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    """Restituisce solo gli ID degli annunci preferiti per aggiornare rapidamente l'icona a cuore nel frontend."""
    stmt = select(Preferito.annuncio_id).where(Preferito.utente_id == current_user.id)
    res = await db.execute(stmt)
    return list(res.scalars().all())


@router.post("/{annuncio_id}", status_code=status.HTTP_201_CREATED)
async def add_preferito(
    annuncio_id: int,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    """Aggiunge un annuncio ai preferiti."""
    # Verifica esistenza annuncio
    stmt_ad = select(Annuncio).where(Annuncio.id == annuncio_id)
    ad = (await db.execute(stmt_ad)).scalar_one_or_none()
    if not ad:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Annuncio non trovato."
        )

    # Verifica se già preferito
    stmt_check = select(Preferito).where(
        Preferito.utente_id == current_user.id,
        Preferito.annuncio_id == annuncio_id
    )
    existing = (await db.execute(stmt_check)).scalar_one_or_none()
    if existing:
        return {"message": "Annuncio già presente tra i preferiti.", "annuncio_id": annuncio_id}

    pref = Preferito(utente_id=current_user.id, annuncio_id=annuncio_id)
    db.add(pref)
    await db.commit()
    return {"message": "Annuncio aggiunto ai preferiti.", "annuncio_id": annuncio_id}


@router.delete("/{annuncio_id}", status_code=status.HTTP_200_OK)
async def remove_preferito(
    annuncio_id: int,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    """Rimuove un annuncio dai preferiti."""
    stmt = select(Preferito).where(
        Preferito.utente_id == current_user.id,
        Preferito.annuncio_id == annuncio_id
    )
    pref = (await db.execute(stmt)).scalar_one_or_none()
    if not pref:
        return {"message": "Annuncio non presente tra i preferiti.", "annuncio_id": annuncio_id}

    await db.delete(pref)
    await db.commit()
    return {"message": "Annuncio rimosso dai preferiti.", "annuncio_id": annuncio_id}
