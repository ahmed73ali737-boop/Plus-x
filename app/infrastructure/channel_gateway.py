"""Client for the Channel Gateway's verification API (standard library only).

The gateway generates, delivers, stores (as a salted HMAC only) and compares the one-time code, limits attempts and sends per
recipient, and expires it; Pulse X keeps only the opaque verificationId. Disabled unless PULSEX_CHANNELS_URL and
PULSEX_CHANNELS_API_KEY are both set. The key is read from the environment at call time and is never logged or returned.
"""
import json
import os
import uuid
import urllib.error
import urllib.parse
import urllib.request


class GatewayUnavailable(Exception):
    """The gateway could not be reached or failed with a server error."""


class GatewayRefused(Exception):
    def __init__(self, status, code):
        super().__init__("%s %s" % (status, code))
        self.status, self.code = status, code


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *a, **k):  # a redirect would carry the API key to another host
        return None


def config():
    url, key = os.environ.get("PULSEX_CHANNELS_URL", "").strip(), os.environ.get("PULSEX_CHANNELS_API_KEY", "").strip()
    return (url.rstrip("/"), key) if url and key else None


def enabled():
    return config() is not None


def _call(path, body, idempotency_key=None, timeout=10, cfg=None):
    cfg = cfg or config()
    if not cfg:
        raise GatewayUnavailable("not configured")
    url, key = cfg
    headers = {"X-Api-Key": key, "Content-Type": "application/json", "Accept": "application/json", "User-Agent": "pulsex-channels/1"}
    if idempotency_key:
        headers["Idempotency-Key"] = idempotency_key
    handlers = [_NoRedirect()]
    if (urllib.parse.urlsplit(url).hostname or "") in ("127.0.0.1", "localhost", "::1"):
        handlers.append(urllib.request.ProxyHandler({}))
    req = urllib.request.Request(url + path, data=json.dumps(body).encode(), headers=headers, method="POST")
    try:
        with urllib.request.build_opener(*handlers).open(req, timeout=timeout) as r:
            return json.loads(r.read(1 << 20) or b"{}")
    except urllib.error.HTTPError as e:
        try:
            code = json.loads(e.read(1 << 16)).get("error", "")
        except Exception:
            code = ""
        if e.code >= 500 or e.code in (408, 429) and code == "":
            raise GatewayUnavailable("HTTP %s" % e.code) from None
        raise GatewayRefused(e.code, code) from None
    except Exception:
        raise GatewayUnavailable("network") from None


def start_verification(phone, locale="ar", cfg=None):
    """Sends a code by SMS. Returns {'verificationId', 'expiresAt', 'attemptsLeft'}; raises GatewayRefused/GatewayUnavailable."""
    out = _call("/api/channels/v1/verify", {"to": phone, "channel": "SMS", "codeLength": 6, "ttlSeconds": 300, "locale": locale,
                                           "originSystem": "pulsex", "metadata": {"purpose": "verify_phone"}}, "pulsex-" + uuid.uuid4().hex, cfg=cfg)
    return {"verificationId": out["verificationId"], "expiresAt": out.get("expiresAt"), "attemptsLeft": out.get("attemptsLeft")}


def check_verification(verification_id, code, cfg=None):
    """True only for an approved code. A wrong code is (False, attemptsLeft); a spent/expired/unknown verification raises GatewayRefused."""
    out = _call("/api/channels/v1/verify/check", {"verificationId": verification_id, "code": code}, cfg=cfg)
    return bool(out.get("valid")) and out.get("status") == "APPROVED", out.get("attemptsLeft")


def resolve_key_ref(ref):
    """A key reference is `env:NAME`; the secret itself is never stored in the database."""
    name = ref[4:] if isinstance(ref, str) and ref.startswith("env:") else ""
    return os.environ.get(name, "").strip()


def probe(cfg, timeout=5):
    """Unauthenticated reachability check (GET /api/health). Sends no message."""
    url = cfg[0]
    handlers = [_NoRedirect()]
    if (urllib.parse.urlsplit(url).hostname or "") in ("127.0.0.1", "localhost", "::1"):
        handlers.append(urllib.request.ProxyHandler({}))
    try:
        with urllib.request.build_opener(*handlers).open(urllib.request.Request(url + "/api/health", method="GET"), timeout=timeout) as r:
            return {"reachable": 200 <= r.status < 300}
    except urllib.error.HTTPError as e:
        return {"reachable": e.code < 500}
    except Exception:
        return {"reachable": False}


class ChannelGatewayPhoneVerifier:
    """Adapter for the application port; `cfg` is (url, key) resolved by the application from settings, else the environment."""

    def environment_config(self):
        return config()

    def key_from_ref(self, ref):
        return resolve_key_ref(ref)

    def probe(self, cfg):
        return probe(cfg)

    def start(self, cfg, phone):
        try:
            return start_verification(phone, cfg=cfg)
        except GatewayRefused as e:
            return {"refused": e.status, "code": e.code}
        except GatewayUnavailable:
            return {"unavailable": True}

    def check(self, cfg, verification_id, code):
        try:
            ok, left = check_verification(verification_id, code, cfg=cfg)
            return {"valid": ok, "attemptsLeft": left}
        except GatewayRefused as e:
            return {"refused": e.status, "code": e.code}
        except GatewayUnavailable:
            return {"unavailable": True}
