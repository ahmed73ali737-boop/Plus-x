from __future__ import annotations

import json
import urllib.error
import urllib.parse
import urllib.request
import http.cookiejar


class PulseXError(RuntimeError):
    def __init__(self, status: int, detail):
        super().__init__(f'PulseX API error {status}: {detail}')
        self.status = status
        self.detail = detail


class PulseXClient:
    """Small zero-dependency Python client for PulseX API v1 semantics.

    The current server keeps legacy `/api/...` URLs for compatibility while
    responses advertise `X-PulseX-API-Version: 1`.
    """

    def __init__(self, base_url: str, timeout: float = 20.0):
        self.base_url = base_url.rstrip('/')
        self.timeout = timeout
        self.cookies = http.cookiejar.CookieJar()
        self.opener = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(self.cookies))
        self.csrf: str | None = None

    def _request(self, method: str, path: str, payload=None, headers=None):
        body = None if payload is None else json.dumps(payload, ensure_ascii=False).encode('utf-8')
        req_headers = {'Accept': 'application/json'}
        if body is not None:
            req_headers['Content-Type'] = 'application/json'
        if self.csrf and method.upper() in {'POST','PUT','PATCH','DELETE'}:
            req_headers['X-CSRF'] = self.csrf
        if headers:
            req_headers.update(headers)
        req = urllib.request.Request(self.base_url + path, data=body, headers=req_headers, method=method.upper())
        try:
            with self.opener.open(req, timeout=self.timeout) as response:
                raw = response.read()
                return json.loads(raw.decode('utf-8')) if raw else None
        except urllib.error.HTTPError as exc:
            raw = exc.read()
            try:
                detail = json.loads(raw.decode('utf-8')).get('detail')
            except Exception:
                detail = raw.decode('utf-8', errors='replace')
            raise PulseXError(exc.code, detail) from exc

    def health(self):
        return self._request('GET', '/api/health')

    def login(self, email: str, password: str):
        data = self._request('POST', '/api/auth/login', {'email': email, 'password': password})
        self.csrf = data['csrf']
        return data['user']

    def me(self):
        data = self._request('GET', '/api/auth/me')
        self.csrf = data.get('csrf', self.csrf)
        return data

    def logout(self):
        data = self._request('POST', '/api/auth/logout', {})
        self.csrf = None
        return data

    def public_site(self, slug: str):
        return self._request('GET', f'/api/public/site/{urllib.parse.quote(slug)}')

    def public_results(self, slug: str):
        return self._request('GET', f'/api/public/site/{urllib.parse.quote(slug)}/results')

    def collect(self, items: list[dict]):
        return self._request('POST', '/api/collect', {'items': items})

    def guest_config(self, event_slug: str):
        return self._request('GET', f'/api/public/events/{urllib.parse.quote(event_slug)}/guest-config')

    def register_guest(self, event_slug: str, phone: str, country_code: str = '+967', **profile):
        payload={'phone': phone, 'country_code': country_code, 'consent': True, **profile}
        return self._request('POST', f'/api/public/events/{urllib.parse.quote(event_slug)}/guests/register', payload)

    def sync_guests(self, event_slug: str, items: list[dict]):
        return self._request('POST', f'/api/public/events/{urllib.parse.quote(event_slug)}/guests/sync', {'items': items})

    def public_guest(self, event_slug: str, guest_number: str):
        return self._request('GET', f'/api/public/events/{urllib.parse.quote(event_slug)}/guests/{urllib.parse.quote(guest_number)}')

    def admin_sites(self):
        return self._request('GET', '/api/admin/sites')

    def admin_site(self, site_id: str):
        return self._request('GET', f'/api/admin/sites/{urllib.parse.quote(site_id)}')

    def save_site(self, site_id: str, draft_rev: int, config: dict):
        return self._request('PUT', f'/api/admin/sites/{urllib.parse.quote(site_id)}', {'draft_rev': draft_rev, 'config': config})

    def publish_site(self, site_id: str, draft_rev: int):
        return self._request('POST', f'/api/admin/sites/{urllib.parse.quote(site_id)}/publish', {'draft_rev': draft_rev})

    def metrics(self, site_id: str):
        return self._request('GET', f'/api/admin/sites/{urllib.parse.quote(site_id)}/metrics')

    def organizations(self):
        return self._request('GET', '/api/admin/organizations')

    def devices(self, site_id: str):
        return self._request('GET', f'/api/admin/sites/{urllib.parse.quote(site_id)}/devices')

    def create_device(self, site_id: str, name: str, device_type: str, app_version: str = ''):
        return self._request('POST', f'/api/admin/sites/{urllib.parse.quote(site_id)}/devices', {'name': name, 'device_type': device_type, 'app_version': app_version})

    def update_device(self, site_id: str, device_id: str, **changes):
        return self._request('PATCH', f'/api/admin/sites/{urllib.parse.quote(site_id)}/devices/{urllib.parse.quote(device_id)}', changes)

    def review_access_request(self, site_id: str, request_id: str, status: str):
        return self._request('PATCH', f'/api/admin/sites/{urllib.parse.quote(site_id)}/access-requests/{urllib.parse.quote(request_id)}', {'status': status})


    def event_guests(self, event_id: str):
        return self._request('GET', f'/api/admin/events/{urllib.parse.quote(event_id)}/guests')

    def register_event_guest(self, event_id: str, payload: dict):
        return self._request('POST', f'/api/admin/events/{urllib.parse.quote(event_id)}/guests', payload)

    def guest_checkins(self, event_id: str):
        return self._request('GET', f'/api/admin/events/{urllib.parse.quote(event_id)}/guest-checkins')

    def checkin_guest(self, event_id: str, payload: dict):
        return self._request('POST', f'/api/admin/events/{urllib.parse.quote(event_id)}/guest-checkins', payload)

    def device_guest_manifest(self, event_id: str, device_token: str):
        return self._request('GET', f'/api/device/events/{urllib.parse.quote(event_id)}/guest-manifest', headers={'X-PulseX-Device-Token': device_token})

    def device_guest_checkins(self, event_id: str, device_token: str, items: list[dict]):
        return self._request('POST', f'/api/device/events/{urllib.parse.quote(event_id)}/guest-checkins', {'items': items}, headers={'X-PulseX-Device-Token': device_token})
