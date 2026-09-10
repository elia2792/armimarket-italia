"""
Security Headers & Content Security Policy (CSP) Middleware.
Fornisce protezione completa da:
- Clickjacking (X-Frame-Options: DENY, frame-ancestors 'none')
- MIME sniffing (X-Content-Type-Options: nosniff)
- Cross-Site Scripting (CSP restrittiva con nonce crittografico per-request, nessun unsafe-inline in script-src)
- Referrer leakage (Referrer-Policy: strict-origin-when-cross-origin)
- Feature abuse (Permissions-Policy: geolocation per Leaflet 'Vicino a me', camera/microphone disabilitate)
- Downgrade HTTPS attacks (HSTS)
"""
import secrets
from starlette.types import ASGIApp, Receive, Scope, Send
from app.core.config import settings


class SecurityHeadersMiddleware:
    """Middleware ASGI puro ad alte prestazioni per l'iniezione degli header di sicurezza e nonce CSP."""
    def __init__(self, app: ASGIApp):
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send):
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        # Genera nonce crittografico per-request per autorizzare selettivamente gli script
        csp_nonce = secrets.token_urlsafe(16)
        scope["csp_nonce"] = csp_nonce

        async def send_with_security_headers(message):
            if message["type"] == "http.response.start":
                raw_headers = list(message.get("headers", []))

                # Content-Security-Policy di produzione hardened:
                # - script-src: NESSUN 'unsafe-inline'! Solo 'self', nonce per-request e unpkg.com per Leaflet
                # - style-src: 'self' 'unsafe-inline' (necessario per trasformazioni CSS Leaflet tiles nel DOM), unpkg, cdnjs, fonts.googleapis.com
                # - object-src 'none', frame-ancestors 'none', base-uri 'self', form-action 'self'
                csp = (
                    "default-src 'self'; "
                    f"script-src 'self' 'nonce-{csp_nonce}' https://unpkg.com; "
                    "style-src 'self' 'unsafe-inline' https://unpkg.com https://cdnjs.cloudflare.com https://fonts.googleapis.com; "
                    "font-src 'self' data: https://cdnjs.cloudflare.com https://fonts.gstatic.com; "
                    "img-src 'self' data: blob: https://*.tile.openstreetmap.org https://tile.openstreetmap.org https:; "
                    "connect-src 'self' https://*.tile.openstreetmap.org https://tile.openstreetmap.org https://nominatim.openstreetmap.org; "
                    "frame-src 'self' data: blob:; "
                    "frame-ancestors 'none'; "
                    "base-uri 'self'; "
                    "form-action 'self'; "
                    "object-src 'none';"
                )

                headers_to_add = [
                    (b"x-content-type-options", b"nosniff"),
                    (b"x-frame-options", b"DENY"),
                    (b"referrer-policy", b"strict-origin-when-cross-origin"),
                    (b"permissions-policy", b"geolocation=(self), camera=(), microphone=()"),
                    (b"content-security-policy", csp.encode("utf-8")),
                ]

                if not settings.DEBUG or scope.get("scheme") == "https":
                    headers_to_add.append(
                        (b"strict-transport-security", b"max-age=31536000; includeSubDomains")
                    )

                header_keys_to_add = {k.lower() for k, _ in headers_to_add}
                filtered_headers = [
                    (k, v) for k, v in raw_headers if k.lower() not in header_keys_to_add
                ]
                filtered_headers.extend(headers_to_add)
                message["headers"] = filtered_headers

            await send(message)

        await self.app(scope, receive, send_with_security_headers)
