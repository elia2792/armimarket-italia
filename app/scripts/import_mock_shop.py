import asyncio
import json
import os
import sys
from pathlib import Path

# Aggiungi cartella radice al PYTHONPATH
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from sqlalchemy import select
from app.core.database import async_session_factory
from app.models.geo import Comune
from app.models.user import RuoloUtente, User
from app.services.ingestion.mock_adapter import MockWooCommerceShopAdapter

# Mock feed esportato dal sistema WooCommerce / ERP di una reale armeria della provincia di Brescia
MOCK_ARMY_FEED = [
    {
        "id": 1001,
        "name": "Franchi Affinity 3 Black Synt Cal. 12/76",
        "description": "Fucile semiautomatico a funzionamento inerziale Front-Inertia di Franchi. Calibro 12 magnum, bindella ventilata, mirino in fibra ottica rosso, strozzatori intercambiabili.",
        "regular_price": "790.00",
        "category": "fucile semiautomatico caccia canna liscia",
        "brand": "FRANCHI S.P.A.",
        "model": "Affinity 3",
        "caliber": "cal 12/76",
        "classificazione": "caccia",
        "condizione": "nuovo",
        "serial_number": "FRA892109X",
        "images": ["https://images.unsplash.com/photo-1595590424283-b8f17842773f?w=800&q=80"],
    },
    {
        "id": 1002,
        "name": "Beretta BRX1 Calibro .308 Winchester Straight-Pull",
        "description": "Carabina da caccia e tiro a ripetizione lineare straight-pull Beretta BRX1. Canna rotomartellata a freddo filettata M14x1, testina rotante a 8 alette, scatto regolabile a tre pesi (950g, 1200g, 1500g).",
        "regular_price": "1450.00",
        "category": "carabina rigata straight pull",
        "brand": "PIETRO BERETTA ARMI",
        "model": "BRX1",
        "caliber": "308w",
        "classificazione": "caccia",
        "condizione": "nuovo",
        "serial_number": "BRX3088921",
        "images": ["https://images.unsplash.com/photo-1547628641-ec2098bb5812?w=800&q=80"],
    },
    {
        "id": 1003,
        "name": "Revolver Smith & Wesson 686 Plus 4 Pollici Calibro .357 Mag",
        "description": "Revolver a telaio medio L-Frame Smith & Wesson modello 686 Plus con tamburo a 7 colpi. Finitura in acciaio inox satinato, tacca di mira regolabile, guancette in gomma ergonomiche.",
        "regular_price": "1290.00",
        "category": "pistola revolver arma corta",
        "brand": "SMITH & WESSON INC.",
        "model": "686 Plus",
        "caliber": ".357 mag",
        "classificazione": "sportiva",
        "condizione": "nuovo",
        "serial_number": "SW686P7712",
        "images": ["https://images.unsplash.com/photo-1585589074491-38e9a2631557?w=800&q=80"],
    },
    {
        "id": 1004,
        "name": "Carabina Aria Compressa Weihrauch HW 977 Cal. 4.5mm (<7.5 Joule)",
        "description": "Carabina ad aria compressa a canna fissa con leva di caricamento inferiore sotto la canna. Libera vendita per maggiorenni (< 7.5 Joule). Famosa per l'eccezionale precisione e lo scatto Rekord match regolabile.",
        "regular_price": "560.00",
        "category": "aria compressa depotenziata libera vendita",
        "brand": "WEIHRAUCH SPORT",
        "model": "HW 977",
        "caliber": "4.5mm / .177",
        "classificazione": "non_applicabile",
        "condizione": "nuovo",
        "serial_number": "HW97701928",
        "images": ["https://images.unsplash.com/photo-1547628641-ec2098bb5812?w=800&q=80"],
    }
]


async def run_shop_import():
    print("Avvio sincronizzazione stock armeria partner...")

    async with async_session_factory() as session:
        # Cerca o crea l'utente armeria partner
        shop_email = "armeria.gardonese@example.it"
        stmt_user = select(User).where(User.email == shop_email)
        user = (await session.execute(stmt_user)).scalar_one_or_none()

        if not user:
            from app.core.security import hash_password
            user = User(
                email=shop_email,
                hashed_password=hash_password("GardoneArmi2026!"),
                nome="Titolare",
                cognome="Armeria Gardonese",
                ragione_sociale="Armeria Gardonese S.n.c.",
                partita_iva="09876543211",
                licenza_tulps="LIC-PS-BS-2023-112",
                ruolo=RuoloUtente.ARMERIA,
                telefono="+39 030 8919999",
                is_active=True,
                is_verified=True,
            )
            session.add(user)
            await session.commit()
            await session.refresh(user)

        # Associa al comune di Gardone Val Trompia (BS)
        stmt_comune = select(Comune).where(Comune.nome.ilike("%Gardone Val Trompia%"))
        comune = (await session.execute(stmt_comune)).scalar_one_or_none()
        comune_id = comune.id if comune else 1

        print(f"Armeria partner: {user.ragione_sociale} (ID #{user.id})")
        print(f"Comune associato: ID #{comune_id} (Gardone Val Trompia - BS)")

        adapter = MockWooCommerceShopAdapter()
        raw_items = adapter.fetch_feed(MOCK_ARMY_FEED)
        stats = await adapter.sync_inventory(session, user, comune_id, raw_items)

        print(f"Risultato sincronizzazione feed: {stats}")
        print("Sincronizzazione completata con successo!")


if __name__ == "__main__":
    asyncio.run(run_shop_import())
