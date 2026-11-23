"""Platform messaging provider choice: which service delivers verification messages. A registry, so a new provider is one entry."""
import ipaddress
import json
import re
from urllib.parse import urlsplit

from app.domain.errors import Forbidden, fail

KEY_REF = re.compile(r'env:[A-Z][A-Z0-9_]{2,63}')

# provider code -> fields it needs. Secrets are referenced (env:NAME), never stored.
PROVIDERS = {
    'none': {'title': 'Disabled', 'fields': ()},
    'channel_gateway': {'title': 'Channel Gateway', 'fields': ('url', 'key_ref')},
}
DEFAULT = {'provider': 'none', 'url': '', 'key_ref': ''}


def _loopback(host):
    try:
        return ipaddress.ip_address(host).is_loopback
    except ValueError:
        return False


def validate_url(url):
    parts = urlsplit(url)
    host = parts.hostname or ''
    ok = (parts.scheme == 'https' and host) or (parts.scheme == 'http' and _loopback(host))
    if not ok or parts.username or parts.password or parts.query or parts.fragment or parts.path not in ('', '/'):
        fail('MESSAGING_URL_INVALID')
    return url.rstrip('/')


def validate(body):
    """Return the normalized setting or raise InvalidInput. Unknown providers and unknown fields are refused."""
    if not isinstance(body, dict) or set(body) - {'provider', 'url', 'key_ref'}:
        fail('MESSAGING_SETTINGS_INVALID')
    provider = body.get('provider')
    if provider not in PROVIDERS:
        fail('MESSAGING_PROVIDER_UNKNOWN')
    out = dict(DEFAULT, provider=provider)
    if provider == 'channel_gateway':
        url, ref = body.get('url'), body.get('key_ref')
        if not isinstance(url, str) or len(url) > 300:
            fail('MESSAGING_URL_INVALID')
        out['url'] = validate_url(url.strip())
        if not isinstance(ref, str) or not KEY_REF.fullmatch(ref):
            fail('MESSAGING_KEY_REF_INVALID')
        out['key_ref'] = ref
    return out


def parse(raw):
    try:
        data = json.loads(raw)
        return validate(data)
    except Exception:
        return None


def require_platform(user):
    if user['role'] != 'platform':
        fail('FORBIDDEN', Forbidden)
