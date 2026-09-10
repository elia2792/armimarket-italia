import asyncio
import json
import logging
import re
import uuid
from typing import Any, Dict, List, Optional, Set
from urllib.parse import urljoin, urlparse

import httpx
from bs4 import BeautifulSoup
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload


from app.core.legal import BANNED_KEYWORDS
from app.models.annuncio import (
    Annuncio,
    ClassificazioneArma,
    CondizioneArma,
    StatoAnnuncio,
    TipologiaArma,
    TipologiaInserzionista,
)
from app.models.user import RuoloUtente, User
from app.services.ingestion.base_adapter import BaseGunshopAdapter

logger = logging.getLogger("scraper")


class UniversalArmeriaScraper:
    """
    Scraper universale ad alta resilienza per siti e cataloghi di armerie italiane.
    Estrae dati da:
    1. Microdati Schema.org (JSON-LD 'Product', presente su WooCommerce, PrestaShop, Shopify, Magento)
    2. OpenGraph Meta Tags (og:title, og:description, og:image, product:price:amount)
    3. Heuristics HTML (h1, selettori prezzo, gallerie img, canonical URL)
    """

    HEADERS = {
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/124.0.0.0 Safari/537.36"
        ),
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8",
        "Accept-Language": "it-IT,it;q=0.9,en-US;q=0.8,en;q=0.7",
    }

    @classmethod
    async def scrape_single_product_page(cls, product_url: str) -> Optional[Dict[str, Any]]:
        """
        Scarica una singola pagina prodotto ed estrae con precisione:
        - Titolo originale
        - Descrizione originale
        - Foto originali ad alta risoluzione
        - Prezzo reale
        - Link diretto originale all'armeria
        - Marca, calibro, categoria normalizzati
        """
        async with httpx.AsyncClient(timeout=20.0, follow_redirects=True, headers=cls.HEADERS) as client:
            try:
                resp = await client.get(product_url)
                if resp.status_code != 200:
                    logger.warning(f"Pagina non raggiungibile ({resp.status_code}): {product_url}")
                    return None
            except Exception as e:
                logger.error(f"Errore connessione a {product_url}: {e}")
                return None

        html = resp.text
        soup = BeautifulSoup(html, "html.parser")

        # 1. Tentativo Schema.org JSON-LD (il piu accurato su WooCommerce e PrestaShop)
        product_data = cls._extract_from_json_ld(soup, product_url)

        # 2. Se non completo, integra con OpenGraph
        if not product_data or not product_data.get("titolo") or not product_data.get("prezzo"):
            og_data = cls._extract_from_opengraph(soup, product_url)
            if not product_data:
                product_data = og_data
            else:
                for k, v in og_data.items():
                    if not product_data.get(k) and v:
                        product_data[k] = v

        # 3. Fallback Heuristics HTML
        if not product_data or not product_data.get("titolo"):
            h1 = soup.find("h1")
            titolo = h1.get_text(strip=True) if h1 else None
            if not titolo:
                return None
            product_data = product_data or {}
            product_data["titolo"] = titolo

        # Filtro sicurezza T.U.L.P.S. (blocca accessori vietati o armi da guerra clandestine)
        full_text = f"{product_data.get('titolo', '')} {product_data.get('descrizione', '')}".lower()
        if any(banned in full_text for banned in BANNED_KEYWORDS):
            logger.info(f"Articolo scartato per termine vietato: {product_data.get('titolo')}")
            return None

        # Arricchimento specifiche tecniche
        titolo = product_data.get("titolo", "Arma")
        product_data["link_originale"] = product_url
        product_data["marca"] = BaseGunshopAdapter.normalize_brand(product_data.get("marca") or titolo.split()[0])
        product_data["calibro"] = BaseGunshopAdapter.normalize_caliber(product_data.get("calibro") or cls._detect_caliber(titolo + " " + product_data.get("descrizione", "")))
        product_data["tipologia_arma"] = cls._detect_weapon_type(titolo, product_data.get("descrizione", ""))
        product_data["classificazione"] = cls._detect_classification(titolo, product_data.get("descrizione", ""))

        return product_data

    @classmethod
    def _extract_from_json_ld(cls, soup: BeautifulSoup, base_url: str) -> Optional[Dict[str, Any]]:
        """Parsa script type='application/ld+json'."""
        for script in soup.find_all("script", type="application/ld+json"):
            if not script.string:
                continue
            try:
                data = json.loads(script.string)
                nodes = []
                if isinstance(data, list):
                    nodes = data
                elif isinstance(data, dict):
                    if "@graph" in data and isinstance(data["@graph"], list):
                        nodes = data["@graph"]
                    else:
                        nodes = [data]

                for node in nodes:
                    if node.get("@type") == "Product":
                        titolo = node.get("name")
                        desc = node.get("description") or ""
                        clean_desc = re.sub(r"<[^>]+>", "", desc).strip()

                        # Immagini originali
                        raw_img = node.get("image")
                        immagini = []
                        if isinstance(raw_img, list):
                            immagini = [urljoin(base_url, img if isinstance(img, str) else img.get("url", "")) for img in raw_img]
                        elif isinstance(raw_img, str):
                            immagini = [urljoin(base_url, raw_img)]
                        elif isinstance(raw_img, dict) and raw_img.get("url"):
                            immagini = [urljoin(base_url, raw_img["url"])]

                        # Prezzo
                        offers = node.get("offers")
                        prezzo = 0.0
                        if isinstance(offers, dict):
                            price_val = offers.get("price") or offers.get("lowPrice") or 0
                            try:
                                prezzo = float(str(price_val).replace(",", "."))
                            except ValueError:
                                prezzo = 0.0
                        elif isinstance(offers, list) and len(offers) > 0:
                            price_val = offers[0].get("price") or 0
                            try:
                                prezzo = float(str(price_val).replace(",", "."))
                            except ValueError:
                                prezzo = 0.0

                        # Marca
                        brand_node = node.get("brand")
                        brand_name = brand_node.get("name") if isinstance(brand_node, dict) else (brand_node if isinstance(brand_node, str) else None)

                        return {
                            "titolo": titolo,
                            "descrizione": clean_desc,
                            "immagini": [img for img in immagini if img],
                            "prezzo": prezzo,
                            "marca": brand_name,
                            "matricola": node.get("mpn") or node.get("sku"),
                        }
            except Exception:
                continue
        return None

    @classmethod
    def _extract_from_opengraph(cls, soup: BeautifulSoup, base_url: str) -> Dict[str, Any]:
        """Estrae i metadati OpenGraph."""
        og_title = soup.find("meta", property="og:title")
        og_desc = soup.find("meta", property="og:description")
        og_img = soup.find("meta", property="og:image")
        og_price = soup.find("meta", property=re.compile(r"price:amount|product:price"))

        titolo = og_title["content"].strip() if og_title and og_title.get("content") else ""
        desc = og_desc["content"].strip() if og_desc and og_desc.get("content") else ""
        img = urljoin(base_url, og_img["content"].strip()) if og_img and og_img.get("content") else None

        prezzo = 0.0
        if og_price and og_price.get("content"):
            try:
                prezzo = float(re.sub(r"[^\d.]", "", og_price["content"].replace(",", ".")))
            except ValueError:
                pass
        
        # Se prezzo non trovato, cerca nel markup standard
        if prezzo == 0.0:
            price_tag = soup.find(class_=re.compile(r"price|prezzo|product-price|current-price", re.I))
            if price_tag:
                clean_p = re.sub(r"[^\d.,]", "", price_tag.get_text(strip=True)).replace(",", ".")
                try:
                    prezzo = float(clean_p)
                except ValueError:
                    pass

        # Se ancora 0, cerca pattern numerico preceduto da € (es. € 1.200 o €950) oppure seguito da €
        if prezzo == 0.0:
            text_to_search = f"{titolo} {desc}"
            # Prima cerca € 1200 / € 1.200,00
            m1 = re.search(r"€\s*(\d{2,}[\d.,]*)", text_to_search)
            # Altrimenti cerca 1200 € / 1.200,00 €
            m2 = re.search(r"(\d{2,}[\d.,]*)\s*€", text_to_search) if not m1 else None
            match_p = m1 or m2
            if match_p:
                val = match_p.group(1)
                try:
                    prezzo = float(val.replace(".", "").replace(",", ".")) if ("," in val and "." in val) else float(val.replace(",", "."))
                except ValueError:
                    pass

        return {
            "titolo": titolo,
            "descrizione": desc,
            "immagini": [img] if img else [],
            "prezzo": prezzo,
            "marca": None,
            "matricola": None,
        }

    @classmethod
    def _detect_caliber(cls, text: str) -> str:
        for pattern, canonical in BaseGunshopAdapter.CALIBER_MAP.items():
            if re.search(pattern, text, flags=re.IGNORECASE):
                return canonical
        return "N/D"

    @classmethod
    def _detect_weapon_type(cls, titolo: str, desc: str) -> TipologiaArma:
        t = f"{titolo} {desc}".lower()
        if any(w in t for w in ["carabina", "argo", "bolt action", "rigata", "express", "varmint", "sniper", "rifle", "carbine"]):
            return TipologiaArma.ARMA_LUNGA_RIGATA
        if any(w in t for w in ["fucile", "sovrapposto", "doppietta", "semiautomatico da caccia", "canna liscia", "cal. 12", "cal. 20", "calibro 12", "calibro 20"]):
            return TipologiaArma.CANNA_LISCIA
        if any(w in t for w in ["aria compressa", "depotenziata", "libera vendita", "pellet", "4.5mm", "5.5mm"]):
            return TipologiaArma.ARIA_COMPRESSA_LIBERA
        if any(w in t for w in ["pistola", "revolver", "corta", "defense", "compact", "glock", "beretta 92", "98fs"]):
            return TipologiaArma.ARMA_CORTA
        return TipologiaArma.ARMA_LUNGA_RIGATA if any(c in t for c in [".308", "30-06", "223", "6.5"]) else TipologiaArma.ARMA_CORTA

    @classmethod
    def _detect_classification(cls, titolo: str, desc: str) -> ClassificazioneArma:
        t = f"{titolo} {desc}".lower()
        if any(w in t for w in ["sportiv", "tiro a segno", "ipsc", "target", "match"]):
            return ClassificazioneArma.SPORTIVA
        if any(w in t for w in ["caccia", "hunting", "cinghiale"]):
            return ClassificazioneArma.CACCIA
        return ClassificazioneArma.COMUNE

    @classmethod
    async def discover_product_links_from_catalog(cls, catalog_url: str, max_links: int = 15) -> List[str]:
        """
        Esplora una pagina di categoria/catalogo di un'armeria ed estrae i link alle singole schede prodotto.
        """
        async with httpx.AsyncClient(timeout=25.0, follow_redirects=True, headers=cls.HEADERS) as client:
            try:
                resp = await client.get(catalog_url)
                if resp.status_code != 200:
                    return []
            except Exception as e:
                logger.error(f"Errore esplorazione catalogo {catalog_url}: {e}")
                return []

        soup = BeautifulSoup(resp.text, "html.parser")
        parsed_domain = urlparse(catalog_url).netloc
        found_links: Set[str] = set()

        for a in soup.find_all("a", href=True):
            href = a["href"].strip()
            full_url = urljoin(catalog_url, href)
            p = urlparse(full_url)
            # Solo link dello stesso dominio
            if p.netloc != parsed_domain:
                continue

            # Riconoscimento schede prodotto (pattern classici PrestaShop, WooCommerce, Shopify, Magento, custom)
            path = p.path.lower()
            if any(pattern in path for pattern in ["/prodotto/", "/products/", ".html", "/armi/", "/pistole/", "/fucili/", "/carabine/"]):
                # Esclude pagine di amministrazione, carrelli o categorie
                if not any(skip in path for skip in ["cart", "carrello", "checkout", "login", "account", "tag", "category", "categoria", "collections/page"]):
                    clean_url = full_url.split("#")[0]
                    found_links.add(clean_url)
                    if len(found_links) >= max_links:
                        break

        return list(found_links)

    @classmethod
    async def scrape_and_save_listings(
        cls,
        db: AsyncSession,
        product_urls: List[str],
        armeria_user: User,
        comune_id: int
    ) -> Dict[str, int]:
        """
        Scansiona una lista di link prodotto, estrae dati, foto originali e link diretto,
        salvando gli annunci reali nel database.
        """
        stats = {"inseriti": 0, "esistenti": 0, "scartati": 0}

        for url in product_urls:
            # Verifica se l'URL è già stato importato per evitare duplicati
            stmt_exists = select(Annuncio).where(Annuncio.link_esterno == url)
            existing = (await db.execute(stmt_exists)).scalar_one_or_none()
            if existing:
                stats["esistenti"] += 1
                continue

            data = await cls.scrape_single_product_page(url)
            if not data or not data.get("titolo") or data.get("prezzo", 0) <= 0:
                stats["scartati"] += 1
                continue

            titolo = data["titolo"]
            clean_slug = re.sub(r"[^\w\s-]", "", titolo.lower()).strip()
            slug = f"{re.sub(r'[-\s]+', '-', clean_slug)}-{uuid.uuid4().hex[:6]}"

            descrizione = data.get("descrizione") or f"Scheda originale dal catalogo di {armeria_user.ragione_sociale or armeria_user.nome}."

            nuovo_annuncio = Annuncio(
                titolo=titolo,
                slug=slug,
                descrizione=descrizione,
                prezzo=data["prezzo"],
                stato=StatoAnnuncio.PUBBLICATO,
                tipologia_inserzionista=TipologiaInserzionista.ARMERIA,
                tipologia_arma=data["tipologia_arma"],
                marca=data["marca"],
                modello=titolo,
                calibro=data["calibro"],
                classificazione=data["classificazione"],
                condizione=CondizioneArma.USATO_OTTIMO if "usat" in titolo.lower() else CondizioneArma.NUOVO,
                matricola_riservata=data.get("matricola"),
                comune_id=comune_id,
                utente_id=armeria_user.id,
                galleria_immagini=data.get("immagini", []),
                link_esterno=url,  # LINK DIRETTO ORIGINALE ALL'ARMERIA
                email_contatto=armeria_user.email,
                telefono_contatto=armeria_user.telefono,
                mostra_telefono_pubblico=True,
            )

            db.add(nuovo_annuncio)
            stats["inseriti"] += 1
            await asyncio.sleep(0.5)  # Rate limiting rispettoso del server remoto

        await db.commit()
        return stats


class MultiArmeriaSearchScraper:
    """
    Motore di ricerca automatico federato su scala nazionale:
    Accetta criteri di ricerca (marca, modello, calibro, regione, provincia, raggio km)
    e interroga in tempo reale i motori di ricerca interni delle armerie online italiane,
    estraendo solo i prodotti pertinenti con foto originale e link diretto.
    """

    @classmethod
    async def search_and_scrape_armerie(
        cls,
        db: AsyncSession,
        q: Optional[str] = None,
        marca: Optional[str] = None,
        modello: Optional[str] = None,
        calibro: Optional[str] = None,
        regione_nome: Optional[str] = None,
        provincia_sigla: Optional[str] = None,
        max_per_armeria: int = 4
    ) -> List[Annuncio]:
        """
        Interroga le armerie compatibili con i filtri geografici e tecnici specificati,
        raschiando le schede prodotto trovate e persistendole con stato PUBBLICATO.
        Restituisce gli annunci trovati/inseriti.
        """
        from app.services.scraper.directory import ARMERIE_TARGETS, build_search_url
        from app.models.geo import Comune, Provincia, Regione
        from app.core.security import hash_password

        # 1. Costruisce la query di ricerca unificata (es. 'Beretta 92FS 9x21')
        query_parts = []
        if marca:
            query_parts.append(marca.strip())
        if modello:
            query_parts.append(modello.strip())
        if calibro:
            query_parts.append(calibro.strip())
        if q and not any(part.lower() in q.lower() for part in query_parts):
            query_parts.append(q.strip())

        search_term = " ".join(query_parts).strip()
        if not search_term:
            search_term = "armi"

        # 2. Filtra la directory delle armerie in base alla posizione scelta dall'utente
        target_armerie = []
        for arm in ARMERIE_TARGETS:
            if regione_nome and arm["regione"].lower() != regione_nome.lower():
                continue
            if provincia_sigla and arm["provincia_sigla"].upper() != provincia_sigla.upper():
                continue
            target_armerie.append(arm)

        # Includi anche tutte le NUOVE ARMERIE REGISTRATE dagli utenti aventi un sito internet
        stmt_reg_armerie = (
            select(User)
            .join(Comune, User.comune_id == Comune.id)
            .join(Provincia, Comune.provincia_id == Provincia.id)
            .options(selectinload(User.annunci))
            .where(
                User.ruolo == RuoloUtente.ARMERIA,
                User.sito_web.isnot(None),
                User.is_active.is_(True)
            )
        )
        reg_armerie_users = (await db.execute(stmt_reg_armerie)).scalars().all()
        for u in reg_armerie_users:
            if not u.sito_web:
                continue
            # Evita duplicati con directory
            if any(a.get("email") == u.email.lower() for a in ARMERIE_TARGETS):
                continue

            search_tmpl = u.search_url_custom or f"{u.sito_web.rstrip('/')}/?s={{query}}&post_type=product"
            target_armerie.append({
                "id_slug": f"armeria-user-{u.id}",
                "nome": u.ragione_sociale or u.nome,
                "ragione_sociale": u.ragione_sociale or u.nome,
                "email": u.email,
                "telefono": u.telefono or "",
                "licenza_tulps": u.licenza_tulps or "Verifica in corso",
                "citta": "",
                "provincia_sigla": "",
                "regione": "",
                "latitudine": float(u.latitudine) if u.latitudine else 42.5,
                "longitudine": float(u.longitudine) if u.longitudine else 12.5,
                "piattaforma": "woocommerce",
                "base_url": u.sito_web,
                "search_url_template": search_tmpl,
                "link_pattern": "/prodotto/",
                "user_obj": u
            })

        # Se nessun'armeria corrisponde al filtro stretto, usa tutte le armerie della directory
        if not target_armerie:
            target_armerie = ARMERIE_TARGETS

        results: List[Annuncio] = []

        # 3. Interroga in parallelo le armerie selezionate
        for armeria_cfg in target_armerie:
            try:
                # Trova o crea utente armeria
                if armeria_cfg.get("user_obj"):
                    armeria_user = armeria_cfg["user_obj"]
                else:
                    stmt_u = select(User).where(User.email == armeria_cfg["email"].lower())
                    armeria_user = (await db.execute(stmt_u)).scalar_one_or_none()
                    if not armeria_user:
                        armeria_user = User(
                            email=armeria_cfg["email"].lower(),
                            hashed_password=hash_password("Partner123!"),
                            nome=armeria_cfg["nome"],
                            ragione_sociale=armeria_cfg["ragione_sociale"],
                            telefono=armeria_cfg["telefono"],
                            licenza_tulps=armeria_cfg["licenza_tulps"],
                            ruolo=RuoloUtente.ARMERIA,
                            sito_web=armeria_cfg.get("base_url"),
                            is_active=True,
                            is_verified=True,
                        )
                        db.add(armeria_user)
                        await db.commit()
                        await db.refresh(armeria_user)

                # Risolvi comune sede armeria per coordinate geografiche
                stmt_comune = select(Comune).where(Comune.nome.ilike(f"%{armeria_cfg['citta']}%"))
                comune = (await db.execute(stmt_comune)).scalars().first()
                comune_id = comune.id if comune else 1

                # Ricerca remota dei link prodotto
                search_url = build_search_url(armeria_cfg, search_term)
                logger.info(f"Interrogazione scraper per '{search_term}' su {armeria_cfg['nome']}: {search_url}")

                product_urls = await UniversalArmeriaScraper.discover_product_links_from_catalog(
                    catalog_url=search_url,
                    max_links=max_per_armeria
                )

                if product_urls:
                    stats = await UniversalArmeriaScraper.scrape_and_save_listings(
                        db=db,
                        product_urls=product_urls,
                        armeria_user=armeria_user,
                        comune_id=comune_id
                    )
                    logger.info(f"Scraper su {armeria_cfg['nome']}: {stats}")

            except Exception as e:
                logger.error(f"Errore durante lo scrape su {armeria_cfg.get('nome')}: {e}")
                continue

        return results
