"""
Rate Limiter distribuito ed atomico server-side per endpoint critici di ArmiMarket Italia.
Supporta:
- Backend Redis distribuito con script Lua atomico (RFC sliding window counter via Sorted Sets)
- Fallback trasparente in-memory (thread-safe) per sviluppo locale, offline e test
- Risoluzione sicura del client IP con policy anti-spoofing per reverse proxy e Render
- Risposta standard HTTP 429 Too Many Requests con header Retry-After
- Pulizia automatica della memoria e assenza di memory leaks
- Nessuna registrazione di password, token JWT o dati sensibili nei log
"""
import logging
import threading
import time
from typing import Callable, Optional, Tuple
from fastapi import HTTPException, Request, status

from app.core.config import settings

logger = logging.getLogger("app.core.rate_limit")

# Script Lua server-side per esecuzione atomica della sliding-window su Redis
# KEYS[1]: chiave rate limit (es. "ratelimit:auth_login:192.0.2.1")
# ARGV[1]: timestamp corrente (secondi float)
# ARGV[2]: finestra temporale in secondi (float)
# ARGV[3]: numero massimo di richieste consentite (int)
LUA_SLIDING_WINDOW_SCRIPT = """
local key = KEYS[1]
local now = tonumber(ARGV[1])
local window = tonumber(ARGV[2])
local max_req = tonumber(ARGV[3])
local clear_before = now - window

-- 1. Rimuovi le richieste antecedenti alla finestra scorrevole
redis.call('ZREMRANGEBYSCORE', key, '-inf', clear_before)

-- 2. Conta le richieste rimaste nella finestra corrente
local current_requests = redis.call('ZCARD', key)

if current_requests < max_req then
    -- Consenti la richiesta e registra il timestamp univoco
    redis.call('ZADD', key, now, now)
    redis.call('EXPIRE', key, math.ceil(window) + 2)
    return {1, 0}
else
    -- Limite superato: calcola il tempo esatto per il Retry-After
    local earliest = redis.call('ZRANGE', key, 0, 0, 'WITHSCORES')
    local retry_after = math.ceil(window)
    if earliest and #earliest >= 2 then
        local oldest_ts = tonumber(earliest[2])
        retry_after = math.max(1, math.ceil(oldest_ts + window - now))
    end
    return {0, retry_after}
end
"""


def get_client_ip(request: Request) -> str:
    """
    Risolve in modo sicuro l'IP del client prevenendo attacchi di spoofing tramite header HTTP:
    
    1. Se BEHIND_TRUSTED_PROXY è attivo (ambiente di produzione Render/Cloudflare)
       oppure l'indirizzo socket del peer (request.client.host) è presente in TRUSTED_PROXIES:
       - Verifica prioritariamente l'header 'cf-connecting-ip' (Cloudflare reverse proxy certificato).
       - In alternativa analizza 'x-forwarded-for': estrae il client IP reale dall'inizio della catena.
    2. Se la connessione NON proviene da un proxy fidato:
       - Gli header 'x-forwarded-for' o 'cf-connecting-ip' vengono considerati NON ATTENDIBILI e SCARTATI,
         in quanto controllabili dall'attaccante per aggirare il rate limiting.
       - Viene utilizzato esclusivamente il socket peer IP effettivo: request.client.host.
    3. Fallback locale: "127.0.0.1".
    """
    peer_ip = request.client.host if request.client and request.client.host else "127.0.0.1"

    # Determina se il peer immediato è un proxy fidato
    is_trusted_proxy = settings.BEHIND_TRUSTED_PROXY or (peer_ip in settings.TRUSTED_PROXIES)

    if is_trusted_proxy:
        cf_ip = request.headers.get("cf-connecting-ip")
        if cf_ip and cf_ip.strip():
            return cf_ip.strip()

        forwarded_for = request.headers.get("x-forwarded-for")
        if forwarded_for and forwarded_for.strip():
            # Il primo IP della catena è l'indirizzo originario del client inoltrato dal proxy fidato
            client_ip = forwarded_for.split(",")[0].strip()
            if client_ip:
                return client_ip

    # Se non siamo dietro un proxy fidato, usa unicamente l'IP del socket peer per prevenire spoofing
    return peer_ip


class InMemoryRateLimiter:
    """Rate limiter in-memory di fallback con sliding-window timestamp e pulizia periodica thread-safe."""

    def __init__(self):
        self._records: dict[str, list[float]] = {}
        self._lock = threading.Lock()
        self._last_cleanup = time.time()

    def is_allowed(self, key: str, max_requests: int, window_seconds: int) -> Tuple[bool, int]:
        now = time.time()
        with self._lock:
            # Pulizia automatica ogni 5 minuti
            if now - self._last_cleanup > 300:
                self._cleanup(now)

            timestamps = self._records.setdefault(key, [])
            cutoff = now - window_seconds
            timestamps = [t for t in timestamps if t > cutoff]
            self._records[key] = timestamps

            if len(timestamps) >= max_requests:
                earliest = timestamps[0]
                retry_after = max(1, int(earliest + window_seconds - now) + 1)
                return False, retry_after

            timestamps.append(now)
            return True, 0

    def _cleanup(self, now: float):
        expired = []
        for k, t_list in self._records.items():
            if not t_list or t_list[-1] < (now - 600):
                expired.append(k)
        for k in expired:
            del self._records[k]
        self._last_cleanup = now

    def clear(self):
        """Azzera la memoria (utilizzato nei test di isolamento)."""
        with self._lock:
            self._records.clear()


# Istanza singleton in-memory di fallback
default_rate_limiter = InMemoryRateLimiter()

# Client Redis asincrono lazy-initialized
_redis_client = None
_redis_script_sha = None
_redis_lock = threading.Lock()


def get_redis_client():
    """Restituisce il client Redis asincrono se configurato."""
    global _redis_client
    if not settings.REDIS_URL:
        return None
    if _redis_client is None:
        with _redis_lock:
            if _redis_client is None:
                try:
                    import redis.asyncio as aioredis
                    _redis_client = aioredis.from_url(
                        settings.REDIS_URL,
                        decode_responses=True,
                        socket_timeout=2.0,
                        socket_connect_timeout=2.0
                    )
                except Exception as e:
                    logger.warning(f"Inizializzazione Redis fallita, fallback in-memory: {e}")
                    _redis_client = None
    return _redis_client


async def check_rate_limit(key: str, max_requests: int, window_seconds: int) -> Tuple[bool, int]:
    """
    Verifica se la richiesta è consentita.
    Utilizza Redis distribuito con script Lua atomico se disponibile;
    in caso contrario esegue fallback trasparente a InMemoryRateLimiter.
    """
    redis_conn = get_redis_client()
    if redis_conn is not None:
        try:
            now = time.time()
            # Esegue lo script Lua atomico su Redis
            res = await redis_conn.eval(
                LUA_SLIDING_WINDOW_SCRIPT,
                1,
                key,
                str(now),
                str(window_seconds),
                str(max_requests)
            )
            # res: [allowed (1 o 0), retry_after (secondi)]
            allowed = bool(res[0])
            retry_after = int(res[1])
            return allowed, retry_after
        except Exception as e:
            logger.warning(f"Errore chiamata Redis per rate limit ({key}): {e}. Fallback in-memory attivo.")

    # Fallback in-memory
    return default_rate_limiter.is_allowed(key, max_requests, window_seconds)


def rate_limit(max_requests: int, window_seconds: int = 60, prefix: str = "endpoint") -> Callable:
    """
    Factory per dependency FastAPI di rate limiting distribuito / fallback.
    Soglie predefinite di produzione:
    - /auth/login: 5 / 60s
    - /auth/register: 3 / 60s
    - /auth/forgot-password: 3 / 60s
    - /auth/reset-password: 5 / 60s
    - /auth/contatta-admin: 5 / 60s
    - /auth/me/foto: 5 / 60s
    - creazione /annunci: 10 / 60s
    - /annunci/{id}/contatta: 5 / 60s
    - /annunci/{id}/segnala: 5 / 60s
    - /annunci/salva-ricerca: 10 / 60s
    """
    async def rate_limit_dependency(request: Request):
        ip = get_client_ip(request)
        key = f"ratelimit:{prefix}:{ip}"

        allowed, retry_after = await check_rate_limit(key, max_requests, window_seconds)
        if not allowed:
            raise HTTPException(
                status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                detail=f"Troppe richieste. Limite superato. Riprova tra {retry_after} secondi.",
                headers={"Retry-After": str(retry_after)}
            )

    return rate_limit_dependency
