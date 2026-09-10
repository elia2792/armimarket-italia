"""
Modulo di conformità legale T.U.L.P.S. & D.Lgs. 104/2018 per ArmiMarket Italia.
Definisce disclaimer di legge obbligatori, informative di pubblica sicurezza
e liste nere per il controllo preventivo dei contenuti.
"""

from typing import Final, List

# Disclaimer vincolante da esporre obbligatoriamente su ogni scheda annuncio
LEGAL_DISCLAIMER_ANNUNCIO: Final[str] = (
    "AVVISO DI PUBBLICA SICUREZZA (T.U.L.P.S. Artt. 35-38, L. 110/1975 e D.Lgs. 104/2018): "
    "Questa piattaforma è una bacheca informativa di consultazione e contatto. "
    "È TASSATIVAMENTE VIETATA la spedizione o compravendita a distanza tra privati. "
    "La compravendita o cessione deve avvenire esclusivamente di persona previa verifica de visu "
    "di un titolo di polizia valido (Porto d'Armi / Nulla Osta all'acquisto rilasciato dalla Questura). "
    "L'acquirente e il cedente hanno l'obbligo inderogabile di denunciare la variazione di detenzione "
    "entro 72 ore dall'acquisizione materiale dell'arma presso i Carabinieri o la Questura competente per territorio."
)

# Disclaimer sintetico per footer, elenchi e popup mappa
LEGAL_DISCLAIMER_FOOTER: Final[str] = (
    "ArmiMarket Italia - Portale di annunci riservato a possessori di titolo valido. "
    "Nessuna vendita online diretta. Obbligo di denuncia di detenzione entro 72 ore (Art. 38 T.U.L.P.S.)."
)

# Informativa per la tutela della sicurezza e anti-clonazione matricola
MATRICOLA_MASK_POLICY: Final[str] = (
    "Ai sensi delle buone pratiche di sicurezza e per prevenire frodi, clonazioni o mappature illecite, "
    "la matricola identificativa dell'arma non viene mai resa pubblica."
)

# Blacklist termini vietati: armi da guerra, modifiche clandestine, silenziatori o munizioni bandite
BANNED_KEYWORDS: Final[List[str]] = [
    "full auto",
    "full-auto",
    "a raffica",
    "raffica",
    "arma da guerra",
    "silenziatore",
    "suppressor",
    "sound suppressor",
    "canna mozza",
    "canna tagliata",
    "matricola abrasa",
    "senza matricola",
    "senza banco",
    "munizioni perforanti",
    "proiettili perforanti",
    "dardo velenoso",
    "trasformazione a raffica",
    "modifica selettore",
    "auto sear",
    "lightning link",
    "drop-in auto sear",
    "dias",
    "glock switch",
    "spedizione postale arma",
    "vendo senza porto d'armi",
    "senza documenti",
    "senza denuncia"
]
