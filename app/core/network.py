import ipaddress
import socket
from typing import Any, Dict, Optional
from urllib.parse import urljoin, urlparse

import httpx


# Indirizzi e range IP vietati (RFC 1918, RFC 3927, loopback, metadati cloud)
BLOCKED_IP_NETWORKS = [
    ipaddress.ip_network("127.0.0.0/8"),       # Loopback IPv4
    ipaddress.ip_network("10.0.0.0/8"),        # Private network RFC 1918
    ipaddress.ip_network("172.16.0.0/12"),     # Private network RFC 1918
    ipaddress.ip_network("192.168.0.0/16"),    # Private network RFC 1918
    ipaddress.ip_network("169.254.0.0/16"),    # Link-local / AWS / GCP / Render metadata
    ipaddress.ip_network("0.0.0.0/8"),         # Current network (only valid as source)
    ipaddress.ip_network("100.64.0.0/10"),     # Shared address space RFC 6598
    ipaddress.ip_network("198.18.0.0/15"),     # Benchmark testing
    ipaddress.ip_network("::1/128"),           # Loopback IPv6
    ipaddress.ip_network("fc00::/7"),          # Unique local address IPv6
    ipaddress.ip_network("fe80::/10"),         # Link-local unicast IPv6
]

ALLOWED_SCHEMES = {"http", "https"}
ALLOWED_PORTS = {80, 443, 8080, 8443}


def validate_url_safe(url: str) -> str:
    """
    Valida un URL per prevenire attacchi SSRF (Server-Side Request Forgery):
    - Verifica protocollo (solo HTTP/HTTPS, blocca file://, gopher://, ftp://, ecc.)
    - Risolve il dominio via DNS e analizza tutti gli indirizzi IP associati
    - Blocca localhost, 127.0.0.1, ::1
    - Blocca range privati (10.x, 172.16.x, 192.168.x)
    - Blocca link-local e metadati cloud (169.254.169.254)
    - Limita le porte ai servizi web standard (80, 443, 8080, 8443)
    
    Solleva ValueError se l'URL non è sicuro.
    Restituisce l'URL normalizzato se valido.
    """
    if not url or not isinstance(url, str):
        raise ValueError("URL non valido o vuoto.")

    parsed = urlparse(url.strip())
    if parsed.scheme.lower() not in ALLOWED_SCHEMES:
        raise ValueError(f"Protocollo '{parsed.scheme}' non consentito. Sono permessi solo HTTP e HTTPS.")

    hostname = parsed.hostname
    if not hostname:
        raise ValueError("Indirizzo host mancante nell'URL.")

    clean_host = hostname.lower().strip("[]")

    # Controllo immediato stringhe localhost / link-local note
    if clean_host in {"localhost", "localhost.localdomain", "0.0.0.0", "127.0.0.1", "::1"}:
        raise ValueError("Accesso a localhost / loopback non consentito per motivi di sicurezza.")

    # Controllo porta se specificata esplicitamente
    port = parsed.port
    if port is not None and port not in ALLOWED_PORTS:
        raise ValueError(f"Porta di rete {port} non consentita. Consentite solo: {ALLOWED_PORTS}.")

    # Risoluzione DNS e validazione dell'indirizzo IP effettivo
    try:
        addr_info = socket.getaddrinfo(clean_host, None, proto=socket.IPPROTO_TCP)
    except socket.gaierror as e:
        raise ValueError(f"Impossibile risolvere il dominio '{hostname}': {str(e)}")

    if not addr_info:
        raise ValueError(f"Nessun indirizzo IP associato al dominio '{hostname}'.")

    for entry in addr_info:
        ip_str = entry[4][0]
        try:
            ip_obj = ipaddress.ip_address(ip_str)
        except ValueError:
            raise ValueError(f"Indirizzo IP non valido rilevato: {ip_str}")

        # Se IPv4-mapped IPv6 (es. ::ffff:127.0.0.1), unwrap a IPv4 per controlli completi
        if getattr(ip_obj, "ipv4_mapped", None):
            ip_obj = ip_obj.ipv4_mapped

        # Controllo se l'IP appartiene a una rete bloccata o privata
        for blocked_net in BLOCKED_IP_NETWORKS:
            if ip_obj in blocked_net:
                raise ValueError(
                    f"Accesso bloccato: l'indirizzo IP {ip_str} appartiene a una rete privata o riservata."
                )

        if ip_obj.is_loopback or ip_obj.is_private or ip_obj.is_reserved or ip_obj.is_link_local or ip_obj.is_multicast:
            raise ValueError(f"Accesso bloccato: IP {ip_str} non consentito.")

    return url.strip()


async def safe_http_get(
    url: str,
    headers: Optional[Dict[str, str]] = None,
    params: Optional[Dict[str, Any]] = None,
    auth: Optional[Any] = None,
    max_redirects: int = 5,
    timeout: float = 20.0
) -> httpx.Response:
    """
    Esegue una richiesta HTTP GET protetta da SSRF:
    1. Valida l'URL iniziale con validate_url_safe.
    2. Disattiva il follow_redirects automatico del client.
    3. In caso di redirect (301, 302, 303, 307, 308), re-valida ogni singolo URL target con validate_url_safe prima di seguirlo.
    4. Blocca redirect verso indirizzi privati/loopback/cloud metadata.
    5. Impone timeout restrittivo e limite massimo sui redirect.
    """
    current_url = validate_url_safe(url)
    redirect_count = 0

    async with httpx.AsyncClient(timeout=timeout, follow_redirects=False) as client:
        while True:
            resp = await client.get(
                current_url,
                headers=headers,
                params=params if redirect_count == 0 else None,
                auth=auth
            )
            if resp.is_redirect:
                redirect_count += 1
                if redirect_count > max_redirects:
                    raise ValueError(f"Numero massimo di redirect superato ({max_redirects}). Possibile loop o tentativo di attacco.")
                location = resp.headers.get("Location")
                if not location:
                    return resp
                next_url = urljoin(current_url, location)
                # Validazione preventiva SSRF dell'URL di redirect
                current_url = validate_url_safe(next_url)
                continue
            return resp
