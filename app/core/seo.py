"""
Modulo SEO per ArmiMarket Italia.
Contiene le utilità per:
- Generazione slug SEO-friendly per singoli annunci
- Normalizzazione e canonical URL
- Dati strutturati Schema.org JSON-LD (WebSite, Organization, Product, BreadcrumbList)
- Meta description e Title generator
- Mappe e definizioni categorie/regioni reali
- Generatore dinamico sitemap.xml e robots.txt
"""
import re
import html
from typing import Any, Dict, List, Optional, Set
from datetime import datetime, timezone
from app.core.config import settings

from app.models.annuncio import TipologiaArma

# Categorie reali supportate con slug SEO-friendly, titoli e descrizioni ricche
CATEGORIE_SEO: Dict[str, Dict[str, Any]] = {
    "armi-corte": {
        "enum": TipologiaArma.ARMA_CORTA,
        "slug": "armi-corte",
        "nome": "Armi Corte (Pistole e Revolver)",
        "titolo_seo": "Armi Corte Usate e Nuove — Pistole e Revolver | ArmiMarket Italia",
        "descrizione_seo": "Scopri annunci di armi corte usate e nuove: pistole semiautomatiche e revolver sportivi o da difesa personale delle migliori marche (Beretta, Glock, Colt, Smith & Wesson).",
        "h1": "Bacheca Armi Corte: Pistole Semiautomatiche e Revolver",
        "intro_testo": "Esplora la selezione di armi corte usate e nuove in vendita presso armerie autorizzate T.U.L.P.S. e collezionisti privati. Trovi pistole semiautomatiche per tiro dinamico, difesa personale o tiro a segno, e revolver in tutti i principali calibri (9x19, 9x21, .45 ACP, .357 Magnum, .38 Special)."
    },
    "carabine-fucili-rigati": {
        "enum": TipologiaArma.ARMA_LUNGA_RIGATA,
        "slug": "carabine-fucili-rigati",
        "nome": "Carabine e Fucili a Canna Rigata",
        "titolo_seo": "Carabine e Fucili a Canna Rigata Usati e Nuovi | ArmiMarket Italia",
        "descrizione_seo": "Annunci di carabine da caccia, tiro sportivo e fucili a canna rigata. Bolt action, semiautomatici e precisione (.308 Win, .223 Rem, .30-06, 6.5 Creedmoor).",
        "h1": "Carabine e Fucili a Canna Rigata",
        "intro_testo": "Tutte le proposte per carabine bolt action da caccia a palla, carabine semiautomatiche per tiro sportivo e fucili a canna rigata di precisione. Consulta offerte di privati verificati e negozi con foto reali e specifiche tecniche."
    },
    "fucili-canna-liscia": {
        "enum": TipologiaArma.CANNA_LISCIA,
        "slug": "fucili-canna-liscia",
        "nome": "Fucili a Canna Liscia (Sovrapposti, Semiautomatici, Doppiette)",
        "titolo_seo": "Fucili a Canna Liscia Usati e Nuovi: Sovrapposti e Semiautomatici | ArmiMarket",
        "descrizione_seo": "Bacheca annunci per fucili a canna liscia: sovrapposti da tiro a volo, semiautomatici da caccia e doppiette calibro 12, 20, 28 e 410 (Beretta, Benelli, Browning, Franchi).",
        "h1": "Fucili a Canna Liscia da Caccia e Tiro a Volo",
        "intro_testo": "Sezione dedicata ai fucili a canna liscia: sovrapposti per skeet e trap, semiautomatici inerziali e a recupero gas per attività venatoria, e raffinate doppiette artigianali. Verifica disponibilità e prezzi aggiornati."
    },
    "aria-compressa": {
        "enum": TipologiaArma.ARIA_COMPRESSA_LIBERA,
        "slug": "aria-compressa",
        "nome": "Aria Compressa (Libera Vendita < 7.5 Joule)",
        "titolo_seo": "Carabine e Pistole ad Aria Compressa Libera Vendita | ArmiMarket Italia",
        "descrizione_seo": "Armi ad aria compressa a modesta capacità offensiva (< 7.5 Joule) di libera vendita per maggiorenni. Carabine springer e PCP (Weihrauch, Diana, Gamo).",
        "h1": "Armi ad Aria Compressa di Libera Vendita",
        "intro_testo": "Catalogo annunci per carabine e pistole ad aria compressa a modesta capacità offensiva (energia cinetica non superiore a 7.5 Joule), acquistabili liberamente dai maggiorenni senza necessità di porto d'armi, ai sensi di legge."
    },
    "ottiche-accessori": {
        "enum": TipologiaArma.ACCESSORIO_OTTICA,
        "slug": "ottiche-accessori",
        "nome": "Ottiche, Cannocchiali e Accessori",
        "titolo_seo": "Ottiche da Tiro, Cannocchiali, Punti Rossi e Accessori | ArmiMarket Italia",
        "descrizione_seo": "Compra e vendi ottiche di puntamento, cannocchiali da caccia, collimatori red dot, attacchi e calciature per armi da fuoco e sportive.",
        "h1": "Ottiche di Puntamento, Mirini Red Dot e Accessori",
        "intro_testo": "Accessori e strumenti ottici per armi: cannocchiali a lungo raggio, reticoli illuminati, punti rossi e montaggi da tiro sportivo o caccia delle migliori marche (Zeiss, Swarovski, Vortex, Leupold, Holosun)."
    }
}

# Lookup inverso per Enum TipologiaArma -> slug
ENUM_TO_CAT_SLUG: Dict[TipologiaArma, str] = {
    v["enum"]: k for k, v in CATEGORIE_SEO.items()
}

# Regioni italiane con slug canonici e dati descrittivi
REGIONI_SEO: Dict[str, Dict[str, Any]] = {
    "abruzzo": {
        "id": 13,
        "slug": "abruzzo",
        "nome": "Abruzzo",
        "titolo_seo": "Annunci Armi Usate e Nuove in Abruzzo | ArmiMarket Italia",
        "descrizione_seo": "Scopri annunci di armi da fuoco usate e nuove in Abruzzo: pistole, carabine, fucili da caccia e armerie a L'Aquila, Pescara, Chieti, Teramo.",
        "h1": "Armi Usate e Nuove in Vendita in Abruzzo",
        "intro_testo": "Bacheca di annunci per armi sportive, da caccia e difesa in Abruzzo. Consulta le offerte di armerie locali e privati muniti di titolo abilitativo."
    },
    "basilicata": {
        "id": 17,
        "slug": "basilicata",
        "nome": "Basilicata",
        "titolo_seo": "Annunci Armi Usate e Nuove in Basilicata | ArmiMarket Italia",
        "descrizione_seo": "Bacheca annunci armi usate e nuove in Basilicata: disponibilità a Potenza, Matera e territorio lucano da armerie e privati autorizzati.",
        "h1": "Armi Usate e Nuove in Vendita in Basilicata",
        "intro_testo": "Cerca armi da caccia e tiro sportivo in Basilicata. Tutti gli annunci sono conformi al T.U.L.P.S. con passaggio materiale di persona o tramite armeria."
    },
    "calabria": {
        "id": 18,
        "slug": "calabria",
        "nome": "Calabria",
        "titolo_seo": "Annunci Armi Usate e Nuove in Calabria | ArmiMarket Italia",
        "descrizione_seo": "Consulta annunci di armi usate e nuove in Calabria: fucili da caccia, carabine e pistole a Catanzaro, Cosenza, Reggio Calabria, Crotone, Vibo Valentia.",
        "h1": "Armi Usate e Nuove in Vendita in Calabria",
        "intro_testo": "Tutte le proposte per armi da caccia e sportive in territorio calabrese da negozi online indicizzati e collezionisti muniti di regolare porto d'armi."
    },
    "campania": {
        "id": 15,
        "slug": "campania",
        "nome": "Campania",
        "titolo_seo": "Annunci Armi Usate e Nuove in Campania | ArmiMarket Italia",
        "descrizione_seo": "Annunci di armi usate e nuove in Campania: pistole, carabine, fucili a Napoli, Salerno, Caserta, Avellino, Benevento.",
        "h1": "Armi Usate e Nuove in Vendita in Campania",
        "intro_testo": "Esplora gli annunci disponibili in Campania. Trova pistole per tiro sportivo, fucili da caccia e accessori con contatti diretti dell'inserzionista."
    },
    "emilia-romagna": {
        "id": 8,
        "slug": "emilia-romagna",
        "nome": "Emilia-Romagna",
        "titolo_seo": "Annunci Armi Usate e Nuove in Emilia-Romagna | ArmiMarket Italia",
        "descrizione_seo": "Trova armi usate e nuove in Emilia-Romagna: pistole, fucili da tiro e caccia a Bologna, Modena, Parma, Reggio Emilia, Ravenna, Ferrara, Forlì-Cesena, Rimini, Piacenza.",
        "h1": "Armi Usate e Nuove in Vendita in Emilia-Romagna",
        "intro_testo": "Ampia scelta di armi sportive da tiro dinamico e caccia in Emilia-Romagna, con annunci da armerie storiche e tiratori sportivi della regione."
    },
    "friuli-venezia-giulia": {
        "id": 6,
        "slug": "friuli-venezia-giulia",
        "nome": "Friuli-Venezia Giulia",
        "titolo_seo": "Annunci Armi Usate e Nuove in Friuli-Venezia Giulia | ArmiMarket Italia",
        "descrizione_seo": "Bacheca armi usate e nuove in Friuli-Venezia Giulia: carabine da caccia, pistole e fucili a Trieste, Udine, Pordenone, Gorizia.",
        "h1": "Armi Usate e Nuove in Friuli-Venezia Giulia",
        "intro_testo": "Carabine a canna rigata da caccia alpina e tiro di precisione in Friuli-Venezia Giulia, conformemente alle normative vigenti di Pubblica Sicurezza."
    },
    "lazio": {
        "id": 12,
        "slug": "lazio",
        "nome": "Lazio",
        "titolo_seo": "Annunci Armi Usate e Nuove nel Lazio e Roma | ArmiMarket Italia",
        "descrizione_seo": "Bacheca annunci armi da fuoco a Roma e nel Lazio: pistole Beretta, Glock, fucili da caccia e tiro sportivo a Latina, Frosinone, Viterbo, Rieti.",
        "h1": "Armi Usate e Nuove in Vendita nel Lazio",
        "intro_testo": "Trova armi da sparo sportive e da caccia a Roma e in tutto il territorio laziale. Annunci dettagliati con foto reali, calibri e posizione."
    },
    "liguria": {
        "id": 7,
        "slug": "liguria",
        "nome": "Liguria",
        "titolo_seo": "Annunci Armi Usate e Nuove in Liguria | ArmiMarket Italia",
        "descrizione_seo": "Offerte armi da fuoco usate e nuove in Liguria: pistole, carabine e canna liscia a Genova, La Spezia, Savona, Imperia.",
        "h1": "Armi Usate e Nuove in Vendita in Liguria",
        "intro_testo": "Consulta gli annunci di armerie e privati in Liguria per tiro a segno, caccia e difesa personale."
    },
    "lombardia": {
        "id": 3,
        "slug": "lombardia",
        "nome": "Lombardia",
        "titolo_seo": "Annunci Armi Usate e Nuove in Lombardia e Milano | ArmiMarket Italia",
        "descrizione_seo": "Migliaia di annunci di armi in Lombardia: pistole, carabine da tiro, sovrapposti Beretta, Franchi, Benelli a Brescia, Milano, Bergamo, Monza, Como, Varese, Pavia, Cremona, Mantova, Lecco, Lodi, Sondrio.",
        "h1": "Armi Usate e Nuove in Vendita in Lombardia",
        "intro_testo": "La Lombardia e la Val Trompia sono il cuore della tradizione armiera italiana. Scopri le migliori offerte di pistole da tiro, sovrapposti da caccia e carabine rigate."
    },
    "marche": {
        "id": 11,
        "slug": "marche",
        "nome": "Marche",
        "titolo_seo": "Annunci Armi Usate e Nuove nelle Marche | ArmiMarket Italia",
        "descrizione_seo": "Annunci armi da fuoco usate e nuove nelle Marche: Urbino, Ancona, Pesaro, Macerata, Ascoli Piceno, Fermo da armerie e privati autorizzati.",
        "h1": "Armi Usate e Nuove in Vendita nelle Marche",
        "intro_testo": "Fucili Benelli e armi delle migliori marche disponibili nelle Marche per caccia e tiro sportivo con conformità T.U.L.P.S."
    },
    "molise": {
        "id": 14,
        "slug": "molise",
        "nome": "Molise",
        "titolo_seo": "Annunci Armi Usate e Nuove in Molise | ArmiMarket Italia",
        "descrizione_seo": "Bacheca armi usate e nuove in Molise: fucili da caccia e pistole a Campobasso e Isernia.",
        "h1": "Armi Usate e Nuove in Vendita in Molise",
        "intro_testo": "Offerte e annunci verificati di armi in Molise per appassionati di caccia e tiro a volo."
    },
    "piemonte": {
        "id": 1,
        "slug": "piemonte",
        "nome": "Piemonte",
        "titolo_seo": "Annunci Armi Usate e Nuove in Piemonte e Torino | ArmiMarket Italia",
        "descrizione_seo": "Annunci di pistole, fucili da caccia e carabine a Torino, Cuneo, Alessandria, Novara, Asti, Biella, Vercelli, Verbania.",
        "h1": "Armi Usate e Nuove in Vendita in Piemonte",
        "intro_testo": "Consulta centinaia di annunci per tiro sportivo e caccia in Piemonte da armerie storiche e tiratori accreditati."
    },
    "puglia": {
        "id": 16,
        "slug": "puglia",
        "nome": "Puglia",
        "titolo_seo": "Annunci Armi Usate e Nuove in Puglia | ArmiMarket Italia",
        "descrizione_seo": "Annunci armi in Puglia: pistole, semiautomatici da caccia e carabine a Bari, Lecce, Foggia, Taranto, Brindisi, Barletta-Andria-Trani.",
        "h1": "Armi Usate e Nuove in Vendita in Puglia",
        "intro_testo": "Bacheca annunci per caccia e tiro sportivo in Puglia con ricerca per provincia e calibro."
    },
    "sardegna": {
        "id": 20,
        "slug": "sardegna",
        "nome": "Sardegna",
        "titolo_seo": "Annunci Armi Usate e Nuove in Sardegna | ArmiMarket Italia",
        "descrizione_seo": "Compravendita armi lecite in Sardegna: fucili canna liscia e carabine da caccia al cinghiale a Cagliari, Sassari, Nuoro, Oristano, Olbia.",
        "h1": "Armi Usate e Nuove in Vendita in Sardegna",
        "intro_testo": "Grande selezione di fucili da caccia al cinghiale e tiro sportivo in Sardegna da armerie partner e privati."
    },
    "sicilia": {
        "id": 19,
        "slug": "sicilia",
        "nome": "Sicilia",
        "titolo_seo": "Annunci Armi Usate e Nuove in Sicilia | ArmiMarket Italia",
        "descrizione_seo": "Annunci di armi usate e nuove in Sicilia: pistole e fucili a Palermo, Catania, Messina, Agrigento, Siracusa, Trapani, Ragusa, Caltanissetta, Enna.",
        "h1": "Armi Usate e Nuove in Vendita in Sicilia",
        "intro_testo": "Trova armi da caccia e pistole sportive in Sicilia, con contatti diretti dell'armeria o del tiratore."
    },
    "toscana": {
        "id": 9,
        "slug": "toscana",
        "nome": "Toscana",
        "titolo_seo": "Annunci Armi Usate e Nuove in Toscana e Firenze | ArmiMarket Italia",
        "descrizione_seo": "Offerte armi in Toscana: carabine bolt action, sovrapposti e pistole a Firenze, Lucca, Pisa, Siena, Arezzo, Livorno, Pistoia, Grosseto, Prato, Massa-Carrara.",
        "h1": "Armi Usate e Nuove in Vendita in Toscana",
        "intro_testo": "Toscana: territorio a forte vocazione venatoria e sportiva. Scopri carabine e fucili da caccia da negozi e privati verificati."
    },
    "trentino-alto-adige": {
        "id": 4,
        "slug": "trentino-alto-adige",
        "nome": "Trentino-Alto Adige",
        "titolo_seo": "Annunci Armi Usate e Nuove in Trentino-Alto Adige | ArmiMarket Italia",
        "descrizione_seo": "Carabine da caccia di montagna, kipplauf e fucili di precisione a Trento e Bolzano da armerie e cacciatori alpini.",
        "h1": "Armi Usate e Nuove in Trentino-Alto Adige",
        "intro_testo": "Specializzati in carabine rigate da caccia a palla e ottiche di precisione a lungo raggio nel territorio trentino e altoatesino."
    },
    "umbria": {
        "id": 10,
        "slug": "umbria",
        "nome": "Umbria",
        "titolo_seo": "Annunci Armi Usate e Nuove in Umbria | ArmiMarket Italia",
        "descrizione_seo": "Bacheca armi da caccia e tiro sportivo in Umbria: offerte a Perugia e Terni con conformità di Pubblica Sicurezza.",
        "h1": "Armi Usate e Nuove in Vendita in Umbria",
        "intro_testo": "Caccia e tiro a volo in Umbria: sovrapposti, semiautomatici e pistole sportive con scheda tecnica e prezzo trasparente."
    },
    "valle-daosta": {
        "id": 2,
        "slug": "valle-daosta",
        "nome": "Valle d'Aosta",
        "titolo_seo": "Annunci Armi Usate e Nuove in Valle d'Aosta | ArmiMarket Italia",
        "descrizione_seo": "Carabine da caccia alpina e armi sportive ad Aosta e valli limitrofe con conformità T.U.L.P.S.",
        "h1": "Armi Usate e Nuove in Valle d'Aosta",
        "intro_testo": "Consulta gli annunci per carabine rigate di precisione e armi da collezione in Valle d'Aosta."
    },
    "veneto": {
        "id": 5,
        "slug": "veneto",
        "nome": "Veneto",
        "titolo_seo": "Annunci Armi Usate e Nuove in Veneto e Verona | ArmiMarket Italia",
        "descrizione_seo": "Migliaia di annunci armi in Veneto: Verona, Vicenza, Padova, Treviso, Venezia, Belluno, Rovigo. Pistole dinamiche, carabine e sovrapposti.",
        "h1": "Armi Usate e Nuove in Vendita in Veneto",
        "intro_testo": "Grande vivacità per il tiro dinamico, tiro a volo e attività venatoria in Veneto: scopri le migliori offerte con posizione su mappa."
    }
}


def slugify(text: str) -> str:
    """Genera uno slug pulito e leggibile per URL SEO."""
    if not text:
        return "annuncio"
    s = text.lower().strip()
    s = re.sub(r"[àáâãäå]", "a", s)
    s = re.sub(r"[èéêë]", "e", s)
    s = re.sub(r"[ìíîï]", "i", s)
    s = re.sub(r"[òóôõö]", "o", s)
    s = re.sub(r"[ùúûü]", "u", s)
    s = re.sub(r"[^\w\s-]", "", s)
    s = re.sub(r"[-\s]+", "-", s)
    return s.strip("-") or "annuncio"


def genera_url_annuncio(annuncio_id: int, titolo: str, base_url: Optional[str] = None) -> str:
    """Genera l'URL canonico SEO del singolo annuncio: /annuncio/{slug}-{id}"""
    slug = slugify(titolo)
    path = f"/annuncio/{slug}-{annuncio_id}"
    if base_url:
        return f"{base_url.rstrip('/')}{path}"
    return path


def estrai_id_da_slug_annuncio(param: str) -> Optional[int]:
    """Estrae l'ID numerico finale da stringhe del tipo 'beretta-98fs-cal-9x21-12' o '12'."""
    if not param:
        return None
    m = re.search(r"(?:^|-)(\d+)$", param)
    if m:
        try:
            return int(m.group(1))
        except ValueError:
            return None
    return None


def genera_meta_description_annuncio(a: Any) -> str:
    """Genera una meta description accurata basata SOLO sui dati reali dell'annuncio, senza claim indimostrabili."""
    parti = []
    if getattr(a, "marca", None) and getattr(a, "modello", None):
        parti.append(f"{a.marca} {a.modello}")
    elif getattr(a, "titolo", None):
        parti.append(a.titolo)

    if getattr(a, "calibro", None):
        parti.append(f"Calibro {a.calibro}")

    if getattr(a, "condizione", None):
        cond_val = a.condizione.value if hasattr(a.condizione, "value") else str(a.condizione)
        parti.append(f"Condizione: {cond_val.replace('_', ' ')}")

    prezzo_str = f"€ {a.prezzo:,.2f}" if getattr(a, "prezzo", None) is not None else ""
    if prezzo_str:
        parti.append(prezzo_str)

    if getattr(a, "comune", None):
        comune = a.comune
        sigla = getattr(comune, "sigla_provincia", "") or (comune.provincia.sigla_automobilistica if getattr(comune, "provincia", None) else "")
        if sigla:
            parti.append(f"Disponibile a {comune.nome} ({sigla})")
        else:
            parti.append(f"Disponibile a {comune.nome}")

    desc_base = " · ".join(parti)
    # Formulazione neutra e trasparente senza asserzioni indimostrabili
    full_desc = f"{desc_base}. Consulta dettagli tecnici, foto, prezzo e recapiti dell'inserzionista."
    if len(full_desc) > 160:
        return full_desc[:157] + "..."
    return full_desc


def genera_alt_immagine_annuncio(a: Any, index: int = 1) -> str:
    """Genera un testo alternativo descrittivo e accessibile per le immagini dell'annuncio."""
    titolo = getattr(a, "titolo", "Arma")
    marca = getattr(a, "marca", "")
    modello = getattr(a, "modello", "")
    calibro = getattr(a, "calibro", "")
    parti = [p for p in [marca, modello, f"cal. {calibro}" if calibro else ""] if p]
    descr_arma = " ".join(parti) if parti else titolo
    return f"{descr_arma} - Foto {index} in vendita su ArmiMarket Italia"


def genera_schema_website(base_url: str) -> Dict[str, Any]:
    """Genera lo Schema.org WebSite con SearchAction integrata per la sitelinks search box di Google."""
    return {
        "@context": "https://schema.org",
        "@type": "WebSite",
        "name": "ArmiMarket Italia",
        "alternateName": "ArmiMarket",
        "url": base_url,
        "description": "Bacheca motore di ricerca e aggregatore di annunci per armi usate e nuove in Italia conforme al T.U.L.P.S.",
        "potentialAction": {
            "@type": "SearchAction",
            "target": {
                "@type": "EntryPoint",
                "urlTemplate": f"{base_url.rstrip('/')}/?q={{search_term_string}}"
            },
            "query-input": "required name=search_term_string"
        }
    }


def genera_schema_organization(base_url: str) -> Dict[str, Any]:
    """Genera lo Schema.org Organization per il publisher di ArmiMarket Italia."""
    return {
        "@context": "https://schema.org",
        "@type": "Organization",
        "name": "ArmiMarket Italia",
        "url": base_url,
        "logo": f"{base_url.rstrip('/')}/static/images/logo.png",
        "sameAs": []
    }


def genera_schema_breadcrumb(crumbs: List[Dict[str, str]]) -> Dict[str, Any]:
    """Genera i dati strutturati BreadcrumbList JSON-LD per la visualizzazione delle briciole di pane nei risultati SERP."""
    items = []
    for i, c in enumerate(crumbs, 1):
        items.append({
            "@type": "ListItem",
            "position": i,
            "name": c["name"],
            "item": c["url"]
        })
    return {
        "@context": "https://schema.org",
        "@type": "BreadcrumbList",
        "itemListElement": items
    }


def genera_schema_product_annuncio(
    a: Any,
    url_assoluto: str,
    base_url: str,
    valutazioni_riepilogo: Optional[Any] = None
) -> Dict[str, Any]:
    """Schema.org Product / IndividualProduct per la scheda annuncio con supporto a valutazioni e recensioni."""
    galleria = getattr(a, "galleria_immagini", []) or []
    immagini_assolute = []
    for img in galleria:
        if img.startswith("http://") or img.startswith("https://"):
            immagini_assolute.append(img)
        else:
            immagini_assolute.append(f"{base_url.rstrip('/')}/{img.lstrip('/')}")

    # ItemCondition
    cond_val = a.condizione.value if hasattr(a.condizione, "value") else str(getattr(a, "condizione", ""))
    schema_condition = "https://schema.org/UsedCondition"
    if cond_val == "nuovo":
        schema_condition = "https://schema.org/NewCondition"
    elif cond_val == "da_collezione":
        schema_condition = "https://schema.org/UsedCondition"

    # Availability
    stato_val = a.stato.value if hasattr(a.stato, "value") else str(getattr(a, "stato", ""))
    availability = "https://schema.org/InStock"
    if stato_val in ("venduto", "archiviato", "rifiutato"):
        availability = "https://schema.org/SoldOut"

    ins_type = getattr(a, "tipologia_inserzionista", None)
    ins_str = ins_type.value if hasattr(ins_type, "value") else str(ins_type or "")
    
    # Risoluzione seller trasparente: armeria o fonte esterna se scraped, privato altrimenti
    if getattr(a, "fonte_esterna", None):
        seller_name = a.fonte_esterna
        seller_type = "Organization"
    elif ins_str == "armeria":
        seller_name = getattr(a, "nome_inserzionista_reale", None) or (a.utente.ragione_sociale if getattr(a, "utente", None) and getattr(a.utente, "ragione_sociale", None) else "Armeria")
        seller_type = "Organization"
    else:
        seller_name = "Privato inserzionista"
        seller_type = "Person"

    product_schema: Dict[str, Any] = {
        "@context": "https://schema.org",
        "@type": "IndividualProduct",
        "name": a.titolo,
        "description": a.descrizione[:400] if getattr(a, "descrizione", None) else a.titolo,
        "url": url_assoluto,
        "category": a.tipologia_arma.value.replace("_", " ").title() if hasattr(a.tipologia_arma, "value") else str(a.tipologia_arma),
        "offers": {
            "@type": "Offer",
            "url": url_assoluto,
            "priceCurrency": "EUR",
            "price": f"{a.prezzo:.2f}",
            "itemCondition": schema_condition,
            "availability": availability,
            "seller": {
                "@type": seller_type,
                "name": seller_name
            }
        }
    }

    if immagini_assolute:
        product_schema["image"] = immagini_assolute

    if getattr(a, "marca", None):
        product_schema["brand"] = {
            "@type": "Brand",
            "name": a.marca
        }

    if getattr(a, "modello", None):
        product_schema["model"] = a.modello

    # Arricchimento Rich Snippet con AggregateRating e Reviews se disponibili
    if valutazioni_riepilogo and getattr(valutazioni_riepilogo, "totale_valutazioni", 0) > 0:
        product_schema["aggregateRating"] = {
            "@context": "https://schema.org",
            "@type": "AggregateRating",
            "ratingValue": f"{valutazioni_riepilogo.media_voto:.1f}",
            "reviewCount": str(valutazioni_riepilogo.totale_valutazioni),
            "bestRating": "5",
            "worstRating": "1"
        }
        reviews_list = []
        recensioni_raw = getattr(valutazioni_riepilogo, "valutazioni", []) or []
        for r in recensioni_raw[:5]:
            rev_item: Dict[str, Any] = {
                "@type": "Review",
                "reviewRating": {
                    "@type": "Rating",
                    "ratingValue": str(r.voto),
                    "bestRating": "5",
                    "worstRating": "1"
                },
                "author": {
                    "@type": "Person",
                    "name": getattr(r, "autore_display_name", "Utente Verificato")
                }
            }
            if getattr(r, "commento", None):
                rev_item["reviewBody"] = r.commento
            if getattr(r, "data_creazione", None):
                try:
                    rev_item["datePublished"] = r.data_creazione.strftime("%Y-%m-%d")
                except Exception:
                    pass
            reviews_list.append(rev_item)
        if reviews_list:
            product_schema["review"] = reviews_list

    return product_schema


def genera_schema_item_list(annunci: List[Any], base_url: str, nome_elenco: str) -> Dict[str, Any]:
    """Genera i dati strutturati ItemList JSON-LD per pagine catalogo, elenchi categorie e territori."""
    base = base_url.rstrip("/")
    items = []
    for i, a in enumerate(annunci, 1):
        url_canonico = genera_url_annuncio(a.id, a.titolo, base_url=base)
        item_entry: Dict[str, Any] = {
            "@type": "ListItem",
            "position": i,
            "url": url_canonico,
            "name": a.titolo
        }
        if getattr(a, "galleria_immagini", None) and a.galleria_immagini:
            first_img = a.galleria_immagini[0]
            if first_img.startswith("http://") or first_img.startswith("https://"):
                item_entry["image"] = first_img
            else:
                item_entry["image"] = f"{base}/{first_img.lstrip('/')}"
        items.append(item_entry)

    return {
        "@context": "https://schema.org",
        "@type": "ItemList",
        "name": nome_elenco,
        "itemListElement": items
    }


def genera_sitemap_xml(base_url: str, annunci_attivi: List[Any], regioni_attive: Optional[Set[str]] = None) -> str:
    """
    Genera il file XML standard sitemap.xml conforme al protocollo sitemaps.org con estensione Google Image Sitemap.
    Include:
    - Homepage e catalogo generale
    - Pagine di categoria SEO
    - Pagine regionali SEO SOLO se hanno annunci attivi
    - Pagine informative e legali (guide, faq, mappa)
    - Tutti i singoli annunci attivi e pubblicati con URL canonico, data di aggiornamento/pubblicazione e immagini associate
    Esclude tassativamente pagine sotto noindex, admin, autenticazione e parametri di ricerca.
    """
    base = base_url.rstrip("/")
    oggi = datetime.now(timezone.utc).strftime("%Y-%m-%d")

    urls: List[Dict[str, Any]] = [
        {"loc": f"{base}/", "lastmod": oggi, "changefreq": "daily", "priority": "1.0"},
        {"loc": f"{base}/annunci", "lastmod": oggi, "changefreq": "daily", "priority": "0.9"},
        {"loc": f"{base}/guide", "lastmod": "2026-09-14", "changefreq": "monthly", "priority": "0.7"},
        {"loc": f"{base}/faq", "lastmod": "2026-09-14", "changefreq": "monthly", "priority": "0.7"},
        {"loc": f"{base}/mappa", "lastmod": oggi, "changefreq": "weekly", "priority": "0.6"},
    ]

    # Categorie SEO
    for cat_slug in CATEGORIE_SEO.keys():
        urls.append({
            "loc": f"{base}/annunci/{cat_slug}",
            "lastmod": oggi,
            "changefreq": "daily",
            "priority": "0.8"
        })

    # Regioni SEO: includi solo se indicate come attive (o se non specificato, se presenti in annunci_attivi)
    if regioni_attive is None:
        regioni_attive = set()
        for a in annunci_attivi:
            reg_slug = None
            if getattr(a, "comune", None) and getattr(a.comune, "provincia", None) and getattr(a.comune.provincia, "regione", None):
                reg_slug = getattr(a.comune.provincia.regione, "slug", None)
            if reg_slug:
                regioni_attive.add(reg_slug)

    for reg_slug in sorted(regioni_attive):
        if reg_slug in REGIONI_SEO:
            urls.append({
                "loc": f"{base}/annunci/regione/{reg_slug}",
                "lastmod": oggi,
                "changefreq": "daily",
                "priority": "0.7"
            })

    # Annunci attivi con immagini (Google Image Sitemap)
    for a in annunci_attivi:
        url_ad = genera_url_annuncio(a.id, a.titolo, base_url=base)
        data_mod = getattr(a, "data_aggiornamento", None) or getattr(a, "data_pubblicazione", None)
        lastmod_str = data_mod.strftime("%Y-%m-%d") if data_mod else oggi

        ad_images = []
        galleria = getattr(a, "galleria_immagini", []) or []
        for idx, img in enumerate(galleria[:6], 1):
            img_clean = img if (img.startswith("http://") or img.startswith("https://")) else f"{base}/{img.lstrip('/')}"
            ad_images.append({
                "loc": img_clean,
                "title": f"{a.titolo} - Foto {idx}"
            })

        urls.append({
            "loc": url_ad,
            "lastmod": lastmod_str,
            "changefreq": "weekly",
            "priority": "0.7",
            "images": ad_images
        })

    # Composizione XML con supporto a Google Image Sitemap
    xml_lines = [
        '<?xml version="1.0" encoding="UTF-8"?>',
        '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9" xmlns:image="http://www.google.com/schemas/sitemap-image/1.1">'
    ]
    for u in urls:
        xml_lines.append("  <url>")
        xml_lines.append(f"    <loc>{html.escape(u['loc'])}</loc>")
        xml_lines.append(f"    <lastmod>{u['lastmod']}</lastmod>")
        xml_lines.append(f"    <changefreq>{u['changefreq']}</changefreq>")
        xml_lines.append(f"    <priority>{u['priority']}</priority>")
        for img in u.get("images", []):
            xml_lines.append("    <image:image>")
            xml_lines.append(f"      <image:loc>{html.escape(img['loc'])}</image:loc>")
            xml_lines.append(f"      <image:title>{html.escape(img['title'])}</image:title>")
            xml_lines.append("    </image:image>")
        xml_lines.append("  </url>")
    xml_lines.append("</urlset>")

    return "\n".join(xml_lines)


def genera_robots_txt(base_url: str) -> str:
    """Genera il file robots.txt ottimizzato: blocca le aree riservate senza impedire il crawling dei meta noindex."""
    base = base_url.rstrip("/")
    return f"""# robots.txt per ArmiMarket Italia
User-agent: *
Allow: /
Allow: /annunci
Allow: /annunci/*
Allow: /annuncio/*
Allow: /guide
Allow: /faq
Allow: /mappa
Allow: /static/

# Blocco pagine private, autenticazione e pannelli gestionali
Disallow: /admin
Disallow: /admin/*
Disallow: /api/
Disallow: /profilo
Disallow: /nuovo-annuncio
Disallow: /login
Disallow: /registrati
Disallow: /recupera-password
Disallow: /reimposta-password
Disallow: /contatta-admin
Disallow: /sincronizza
Disallow: /logout

# Riferimento alla sitemap canonica
Sitemap: {base}/sitemap.xml
"""
