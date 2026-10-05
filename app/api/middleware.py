from __future__ import annotations

import time
from collections import defaultdict, deque

from fastapi import Request
from fastapi.responses import JSONResponse

MAX_REQUEST_BYTES = 7 * 1024 * 1024


def install_security_middleware(app, public_origin: str) -> None:
    limits = defaultdict(deque)
    secure = public_origin.startswith('https://')
    app.state.cookie_secure = secure

    @app.middleware('http')
    async def security_guard(request: Request, call_next):
        try:
            content_length = int(request.headers.get('content-length', '0') or 0)
        except ValueError:
            return JSONResponse({'detail': 'CONTENT_LENGTH_INVALID'}, 400)
        if content_length > MAX_REQUEST_BYTES:
            return JSONResponse({'detail': 'REQUEST_LIMIT'}, 413)

        if request.method in ('POST', 'PUT', 'PATCH'):
            chunks = []
            size = 0
            async for chunk in request.stream():
                size += len(chunk)
                if size > MAX_REQUEST_BYTES:
                    return JSONResponse({'detail': 'REQUEST_LIMIT'}, 413)
                chunks.append(chunk)
            request._body = b''.join(chunks)

        if request.method not in ('GET', 'HEAD', 'OPTIONS'):
            request_origin = request.headers.get('origin')
            if request_origin and request_origin != public_origin:
                return JSONResponse({'detail': 'ORIGIN_FORBIDDEN'}, 403)

        if request.url.path.startswith('/api/'):
            ip = request.client.host if request.client else 'unknown'
            bucket = 'auth' if request.url.path.startswith('/api/auth/login') else 'api'
            key = (ip, bucket)
            queue = limits[key]
            current = time.monotonic()
            while queue and current - queue[0] > 60:
                queue.popleft()
            limit = 20 if bucket == 'auth' else 12000
            if len(queue) >= limit:
                return JSONResponse({'detail': 'RATE_LIMIT'}, 429, headers={'Retry-After': '60'})
            queue.append(current)
            if len(limits) > 5000:
                for old_key in list(limits):
                    if not limits[old_key] or current - limits[old_key][-1] > 120:
                        del limits[old_key]

        response = await call_next(request)
        response.headers['X-Content-Type-Options'] = 'nosniff'
        response.headers['Referrer-Policy'] = 'same-origin'
        response.headers['Permissions-Policy'] = 'camera=(self), microphone=(), geolocation=()'
        response.headers['Content-Security-Policy'] = (
            "default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline'; "
            "img-src 'self' https: data:; media-src 'self' https:; connect-src 'self'; "
            "frame-src 'self'; frame-ancestors 'self'; object-src 'none'; base-uri 'self'; form-action 'self'"
        )
        if secure:
            response.headers['Strict-Transport-Security'] = 'max-age=31536000; includeSubDomains'
        if request.url.path.startswith('/api/'):
            response.headers['Cache-Control'] = 'no-store'
            response.headers['X-PulseX-API-Version'] = '1'
        return response
