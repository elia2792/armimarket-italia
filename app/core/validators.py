import re
from typing import Optional


def normalize_partita_iva(piva: Optional[str]) -> Optional[str]:
    """Rimuove spazi e trattini dalla Partita IVA."""
    if not piva:
        return None
    cleaned = piva.strip().replace(" ", "").replace("-", "")
    return cleaned if cleaned else None


def validate_partita_iva(piva: Optional[str]) -> bool:
    """
    Valida formalmente una Partita IVA italiana secondo l'algoritmo ufficiale (11 cifre).
    - Lunghezza 11 cifre numeriche.
    - Prime 7 cifre: matricola soggetto (non tutte nulle).
    - Cifre 8-10: codice ufficio provinciale o agenzia entrate.
    - 11ª cifra: carattere di controllo calcolato tramite algoritmo di Luhn per P.IVA.
    """
    clean = normalize_partita_iva(piva)
    if not clean:
        return False
    if len(clean) != 11 or not clean.isdigit():
        return False
    if clean == "00000000000":
        return False

    # Somma cifre in posizione dispari (1ª, 3ª, 5ª, 7ª, 9ª -> indici 0, 2, 4, 6, 8)
    s1 = sum(int(clean[i]) for i in range(0, 10, 2))

    # Per le cifre in posizione pari (2ª, 4ª, 6ª, 8ª, 10ª -> indici 1, 3, 5, 7, 9):
    # moltiplica per 2; se > 9, sottrai 9 (equivalente alla somma delle cifre del prodotto)
    s2 = sum(
        (2 * int(clean[i])) - 9 if (2 * int(clean[i])) > 9 else 2 * int(clean[i])
        for i in range(1, 10, 2)
    )

    controllo = (10 - ((s1 + s2) % 10)) % 10
    return int(clean[10]) == controllo


def normalize_codice_fiscale(cf: Optional[str]) -> Optional[str]:
    """Normalizza il Codice Fiscale rimuovendo spazi e convertendo in maiuscolo."""
    if not cf:
        return None
    cleaned = cf.strip().replace(" ", "").upper()
    return cleaned if cleaned else None


def validate_codice_fiscale(cf: Optional[str]) -> bool:
    """
    Valida il formato di un Codice Fiscale standard per persone fisiche (16 caratteri alfanumerici).
    """
    clean = normalize_codice_fiscale(cf)
    if not clean:
        return False
    pattern = r"^[A-Z]{6}[0-9LMNPQRSTUV]{2}[A-EHLMPR-T][0-9LMNPQRSTUV]{2}[A-Z][0-9LMNPQRSTUV]{3}[A-Z]$"
    return bool(re.match(pattern, clean))
