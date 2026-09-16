import pytest
from httpx import AsyncClient
from sqlalchemy import select

from app.core.security import create_access_token
from app.models.user import User, RuoloUtente


@pytest.mark.asyncio
async def test_lascia_valutazione_utente_registrato(client: AsyncClient, db_session):
    """Verifica che un utente autenticato possa valutare un altro utente privato registrato."""
    privato = (await db_session.execute(select(User).where(User.ruolo == RuoloUtente.PRIVATO))).scalar_one()
    admin = (await db_session.execute(select(User).where(User.ruolo == RuoloUtente.ADMIN))).scalar_one()

    # Admin recensisce Privato
    token_admin = create_access_token(subject=admin.id)

    resp = await client.post(
        "/api/v1/valutazioni",
        headers={"Authorization": f"Bearer {token_admin}"},
        json={
            "voto": 5,
            "titolo": "Ottima compravendita",
            "commento": "Venditore precisissimo e cordiale, arma esattamente come descritta.",
            "recensito_utente_id": privato.id
        }
    )
    assert resp.status_code == 200, resp.text
    data = resp.json()
    assert data["voto"] == 5
    assert data["titolo"] == "Ottima compravendita"
    assert data["recensito_utente_id"] == privato.id
    assert data["autore_id"] == admin.id

    # Query riepilogo per l'utente recensito
    resp_riepilogo = await client.get(f"/api/v1/valutazioni/utente/{privato.id}")
    assert resp_riepilogo.status_code == 200
    summary = resp_riepilogo.json()
    assert summary["totale_valutazioni"] == 1
    assert summary["media_voto"] == 5.0
    assert summary["distribuzione_voti"]["5"] == 1


@pytest.mark.asyncio
async def test_lascia_valutazione_armeria_esterna(client: AsyncClient, db_session):
    """Verifica che un utente possa valutare un'armeria esterna/scraped (senza utente fittizio)."""
    privato = (await db_session.execute(select(User).where(User.ruolo == RuoloUtente.PRIVATO))).scalar_one()
    token_privato = create_access_token(subject=privato.id)

    resp = await client.post(
        "/api/v1/valutazioni",
        headers={"Authorization": f"Bearer {token_privato}"},
        json={
            "voto": 4,
            "titolo": "Personale molto competente",
            "commento": "Armeria storica con ottimo assortimento e disponibilità di munizioni.",
            "fonte_esterna": "Armeria Regina"
        }
    )
    assert resp.status_code == 200, resp.text
    data = resp.json()
    assert data["voto"] == 4
    assert data["fonte_esterna"] == "Armeria Regina"
    assert data["recensito_utente_id"] is None

    # Query riepilogo armeria esterna
    resp_riepilogo = await client.get("/api/v1/valutazioni/fonte/Armeria Regina")
    assert resp_riepilogo.status_code == 200
    summary = resp_riepilogo.json()
    assert summary["totale_valutazioni"] == 1
    assert summary["media_voto"] == 4.0


@pytest.mark.asyncio
async def test_divieto_auto_valutazione(client: AsyncClient, db_session):
    """Verifica che un utente non possa valutare o recensire se stesso."""
    privato = (await db_session.execute(select(User).where(User.ruolo == RuoloUtente.PRIVATO))).scalar_one()
    token_privato = create_access_token(subject=privato.id)

    resp = await client.post(
        "/api/v1/valutazioni",
        headers={"Authorization": f"Bearer {token_privato}"},
        json={
            "voto": 5,
            "titolo": "Sono bravissimo",
            "commento": "Auto recensione non permessa dal sistema di affidabilità.",
            "recensito_utente_id": privato.id
        }
    )
    assert resp.status_code == 400
    assert "te stesso" in resp.json()["detail"].lower()


@pytest.mark.asyncio
async def test_aggiornamento_valutazione_esistente(client: AsyncClient, db_session):
    """Verifica che una successiva recensione dello stesso autore verso lo stesso target aggiorni la precedente."""
    privato = (await db_session.execute(select(User).where(User.ruolo == RuoloUtente.PRIVATO))).scalar_one()
    armeria = (await db_session.execute(select(User).where(User.ruolo == RuoloUtente.ARMERIA))).scalar_one()
    token_privato = create_access_token(subject=privato.id)

    # Prima recensione: voto 3
    await client.post(
        "/api/v1/valutazioni",
        headers={"Authorization": f"Bearer {token_privato}"},
        json={
            "voto": 3,
            "titolo": "Normale",
            "commento": "Transazione regolare ma tempi di risposta lenti.",
            "recensito_utente_id": armeria.id
        }
    )

    # Seconda recensione: voto aggiornato a 5
    resp_up = await client.post(
        "/api/v1/valutazioni",
        headers={"Authorization": f"Bearer {token_privato}"},
        json={
            "voto": 5,
            "titolo": "Risolto tutto al meglio",
            "commento": "Problema chiarito e super disponibile di persona, consigliatissimo!",
            "recensito_utente_id": armeria.id
        }
    )
    assert resp_up.status_code == 200

    # Il totale delle recensioni deve rimanere 1 con media 5.0
    resp_riepilogo = await client.get(f"/api/v1/valutazioni/utente/{armeria.id}")
    summary = resp_riepilogo.json()
    assert summary["totale_valutazioni"] == 1
    assert summary["media_voto"] == 5.0
    assert summary["valutazioni"][0]["commento"] == "Problema chiarito e super disponibile di persona, consigliatissimo!"


@pytest.mark.asyncio
async def test_mie_valutazioni_ricevute(client: AsyncClient, db_session):
    """Verifica che l'utente possa interrogare le recensioni ricevute per il proprio profilo."""
    privato = (await db_session.execute(select(User).where(User.ruolo == RuoloUtente.PRIVATO))).scalar_one()
    armeria = (await db_session.execute(select(User).where(User.ruolo == RuoloUtente.ARMERIA))).scalar_one()
    token_privato = create_access_token(subject=privato.id)
    token_armeria = create_access_token(subject=armeria.id)

    # Privato recensisce Armeria
    await client.post(
        "/api/v1/valutazioni",
        headers={"Authorization": f"Bearer {token_privato}"},
        json={
            "voto": 5,
            "titolo": "Persona seria",
            "commento": "Trattativa perfetta di persona in sede.",
            "recensito_utente_id": armeria.id
        }
    )

    # Armeria legge le proprie recensioni ricevute
    resp_mie = await client.get(
        "/api/v1/valutazioni/mie-ricevute",
        headers={"Authorization": f"Bearer {token_armeria}"}
    )
    assert resp_mie.status_code == 200
    data = resp_mie.json()
    assert len(data) == 1
    assert data[0]["autore_display_name"] == privato.display_name
    assert data[0]["voto"] == 5


@pytest.mark.asyncio
async def test_eliminazione_valutazione_permessi(client: AsyncClient, db_session):
    """Verifica i permessi di cancellazione di una valutazione (autore o admin)."""
    privato = (await db_session.execute(select(User).where(User.ruolo == RuoloUtente.PRIVATO))).scalar_one()
    armeria = (await db_session.execute(select(User).where(User.ruolo == RuoloUtente.ARMERIA))).scalar_one()
    admin = (await db_session.execute(select(User).where(User.ruolo == RuoloUtente.ADMIN))).scalar_one()

    token_privato = create_access_token(subject=privato.id)
    token_armeria = create_access_token(subject=armeria.id)
    token_admin = create_access_token(subject=admin.id)

    # Privato recensisce Armeria
    resp = await client.post(
        "/api/v1/valutazioni",
        headers={"Authorization": f"Bearer {token_privato}"},
        json={
            "voto": 2,
            "titolo": "Trattativa annullata",
            "commento": "Non ci siamo accordati sui dettagli.",
            "recensito_utente_id": armeria.id
        }
    )
    val_id = resp.json()["id"]

    # Armeria (recensita) tenta di cancellarla -> vietato (403)
    resp_del_unauth = await client.delete(
        f"/api/v1/valutazioni/{val_id}",
        headers={"Authorization": f"Bearer {token_armeria}"}
    )
    assert resp_del_unauth.status_code == 403

    # Admin può cancellarla -> 200
    resp_del_admin = await client.delete(
        f"/api/v1/valutazioni/{val_id}",
        headers={"Authorization": f"Bearer {token_admin}"}
    )
    assert resp_del_admin.status_code == 200
    assert resp_del_admin.json()["success"] is True
