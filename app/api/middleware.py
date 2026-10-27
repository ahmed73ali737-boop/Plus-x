from __future__ import annotations

import re
import time
from collections import defaultdict, deque
from urllib.parse import urlsplit

from fastapi import Request
from fastapi.responses import JSONResponse

MAX_REQUEST_BYTES = 7 * 1024 * 1024
_HOST_RE = re.compile(r"^(?:\[[0-9A-Fa-f:.%]+\]|[A-Za-z0-9.-]+)(?::([0-9]{1,5}))?$")


def _valid_host_header(value: str | None) -> bool:
    """Validate Host as an HTTP authority without ever reconstructing request.url."""
    if not value or any(ch.isspace() or ord(ch) < 32 or ord(ch) == 127 for ch in value):
        return False
    if any(ch in value for ch in "/\\?#@"):
        return False
    match = _HOST_RE.fullmatch(value)
    if not match:
        return False
    port = match.group(1)
    return port is None or 0 < int(port) <= 65535


def _origin_matches(request_origin: str, public_origin: str, allow_local_loopback_origins: bool) -> bool:
    if request_origin == public_origin:
        return True
    if not allow_local_loopback_origins:
        return False
    try:
        requested = urlsplit(request_origin)
        public = urlsplit(public_origin)
        requested_port = requested.port or (443 if requested.scheme == "https" else 80)
        public_port = public.port or (443 if public.scheme == "https" else 80)
    except ValueError:
        return False
    loopback_hosts = {"localhost", "127.0.0.1", "::1"}
    if (requested.scheme != public.scheme or requested.hostname not in loopback_hosts or
            public.hostname not in loopback_hosts or requested.username is not None or
            requested.password is not None or requested.path or requested.query or requested.fragment):
        return False
    # The local Compose setup publishes the app on 2282 and its proxy on 2283.
    # Accept either loopback entry point locally; production remains exact-origin only.
    return requested_port == public_port or requested_port in {2282, 2283}


def install_security_middleware(app, public_origin: str, *, allow_local_loopback_origins: bool = False) -> None:
    limits = defaultdict(deque)
    secure = public_origin.startswith("https://")
    app.state.cookie_secure = secure

    def harden(response, path: str):
        response.headers["X-Content-Type-Options"] = "nosniff"
        if response.status_code==429:response.headers.setdefault("Retry-After","60")
        response.headers["Referrer-Policy"] = "same-origin"
        response.headers["Permissions-Policy"] = "camera=(self), microphone=(), geolocation=()"
        response.headers["Content-Security-Policy"] = (
            "default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline'; "
            "img-src 'self' https: data: blob:; media-src 'self' https:; connect-src 'self'; "
            "frame-src 'self'; frame-ancestors 'self'; object-src 'none'; base-uri 'self'; form-action 'self'"
        )
        if secure:
            response.headers["Strict-Transport-Security"] = "max-age=31536000; includeSubDomains"
        if path.startswith("/api/"):
            response.headers["Cache-Control"] = "no-store"
            response.headers["X-PulseX-API-Version"] = "1"
        if path.startswith(('/certificate/', '/verify/certificate/', '/api/public/certificates/', '/certificates', '/api/self-certificates', '/api/public/self-certificates')):
            response.headers['Cache-Control'] = 'no-store'
            response.headers['Referrer-Policy'] = 'no-referrer'
            response.headers['X-Robots-Tag'] = 'noindex, nofollow'
        return response

    @app.middleware("http")
    async def security_guard(request: Request, call_next):
        # Security decisions must use the path selected by the ASGI router, not
        # request.url, because older Starlette releases allowed Host to poison
        # reconstructed URL components.
        path = request.scope.get("path") or "/"

        if not _valid_host_header(request.headers.get("host")):
            return harden(JSONResponse({"detail": "HOST_INVALID"}, 400), path)

        try:
            content_length = int(request.headers.get("content-length", "0") or 0)
        except ValueError:
            return harden(JSONResponse({"detail": "CONTENT_LENGTH_INVALID"}, 400), path)
        request_limit = (999999 if request.query_params.get('kind')=='stamp' else 3000000) if path=='/api/self-certificates/assets' else 32768 if path.startswith(('/api/public/self-certificates/','/api/self-certificates/')) else MAX_REQUEST_BYTES
        if content_length > request_limit:
            return harden(JSONResponse({"detail": "REQUEST_LIMIT"}, 413), path)

        if request.method in ("POST", "PUT", "PATCH"):
            chunks = []
            size = 0
            async for chunk in request.stream():
                size += len(chunk)
                if size > request_limit:
                    return harden(JSONResponse({"detail": "REQUEST_LIMIT"}, 413), path)
                chunks.append(chunk)
            request._body = b"".join(chunks)

        if request.method not in ("GET", "HEAD", "OPTIONS"):
            request_origin = request.headers.get("origin")
            if request_origin and not _origin_matches(request_origin, public_origin, allow_local_loopback_origins):
                return harden(JSONResponse({"detail": "ORIGIN_FORBIDDEN"}, 403), path)

        if path.startswith("/api/"):
            ip = request.client.host if request.client else "unknown"
            bucket = (
                "self-certificate" if path.startswith("/api/public/self-certificates/") else "auth"
                if path.startswith("/api/auth/") and request.method != "GET"
                else "signup"
                if path in ("/api/signup-request", "/api/access-request")
                else "account-read"
                if path in ("/api/account-requests/status", "/api/account-invites/inspect")
                else "account-write"
                if path.startswith("/api/account-requests/") or path.startswith("/api/account-invites/")
                else "guest"
                if path.startswith("/api/public/events/") and "/guests" in path
                else "certificate-render"
                if path.startswith('/api/public/certificates/') and ('/download.' in path or path.endswith('/image.svg'))
                else "certificate"
                if path.startswith('/api/public/certificates/')
                else "api"
            )
            key = (ip, bucket)
            queue = limits[key]
            current = time.monotonic()
            while queue and current - queue[0] > 60:
                queue.popleft()
            limit = 120000 if bucket == "self-certificate" else 60 if bucket == "account-read" else 20 if bucket == "account-write" else 20 if bucket == "auth" else 10 if bucket == "signup" else 15 if bucket == "certificate-render" else 300 if bucket in ("guest", "certificate") else 12000
            if len(queue) >= limit:
                return harden(
                    JSONResponse({"detail": "RATE_LIMIT"}, 429, headers={"Retry-After": "60"}),
                    path,
                )
            queue.append(current)
            if len(limits) > 5000:
                for old_key in list(limits):
                    if not limits[old_key] or current - limits[old_key][-1] > 120:
                        del limits[old_key]

        response = await call_next(request)
        return harden(response, path)
