"""Primitive value rules shared by every bounded context.

No arbitrary HTML, script expressions or trusted client roles are accepted.
Each helper either returns a normalized value or raises an InvalidInput error.
"""
from __future__ import annotations

import math
import re
import uuid
from datetime import datetime, timezone
from urllib.parse import urlparse

from app.domain.errors import fail

CODE = re.compile(r'^[A-Za-z0-9][A-Za-z0-9_.-]{0,63}$')
SLUG = re.compile(r'[a-z0-9][a-z0-9-]{1,70}')
EMAIL = re.compile(r'[^\s@]+@[^\s@]+\.[^\s@]+')
TRUE_VALUES = (1, '1', 'true', 'TRUE', 'نعم')
FALSE_VALUES = (None, '', 0, '0', 'false', 'FALSE', 'لا')


def new_id() -> str:
    return str(uuid.uuid4())


def now() -> str:
    return datetime.now(timezone.utc).isoformat()


def utc_timestamp() -> str:
    """Uniform microsecond UTC string (self-service certificate records)."""
    return datetime.now(timezone.utc).isoformat(timespec='microseconds')


def text(value, maximum=500, required=False) -> str:
    if value is None:
        value = ''
    if not isinstance(value, (str, int, float)) or isinstance(value, bool):
        fail('TEXT_REQUIRED')
    value = str(value).strip()
    if len(value) > maximum or '\x00' in value or (required and not value):
        fail('TEXT_LENGTH')
    return value


def boolean(value) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        value = value.strip().lower()
    if value in TRUE_VALUES:
        return True
    if value in FALSE_VALUES:
        return False
    fail('BOOLEAN_INVALID')


def number(value, default=0, low=-1e12, high=1e12):
    if value is None or value == '':
        return default
    if isinstance(value, bool):
        fail('NUMBER_INVALID')
    try:
        parsed = float(value)
    except (ValueError, TypeError):
        fail('NUMBER_INVALID')
    if not math.isfinite(parsed) or parsed < low or parsed > high:
        fail('NUMBER_RANGE')
    return int(parsed) if parsed.is_integer() else parsed


def url(value, contact=False) -> str:
    value = text(value, 2048)
    if not value:
        return ''
    if value.startswith('/media/') and '..' not in value:
        return value
    parsed = urlparse(value)
    if contact and parsed.scheme in ('mailto', 'tel'):
        return value
    if parsed.scheme != 'https' or not parsed.netloc or parsed.username or parsed.password:
        fail('HTTPS_URL_REQUIRED')
    return value


def stamp(value) -> str:
    """An ISO-8601 timestamp that must carry a time zone (or an empty string)."""
    value = text(value, 80)
    if value.startswith("'"):
        value = value[1:]
    if value:
        try:
            parsed = datetime.fromisoformat(value.replace('Z', '+00:00'))
            if parsed.tzinfo is None:
                fail('TIMEZONE_REQUIRED')
        except ValueError:
            fail('DATETIME_INVALID')
    return value


def code(value, maximum=64, error='CODE_INVALID') -> str:
    value = text(value, maximum, True)
    if not CODE.fullmatch(value):
        fail(error)
    return value


def slug(value) -> str:
    value = text(value, 80, True)
    if not SLUG.fullmatch(value):
        fail('SLUG_INVALID')
    return value


def email(value, maximum=200) -> str:
    """Optional e-mail address, lower-cased; empty string when absent."""
    value = text(value, maximum).lower()
    if value and not EMAIL.fullmatch(value):
        fail('EMAIL_INVALID')
    return value


def ordered_range(start: str, end: str, error: str) -> None:
    """Both bounds are optional; when both are present start must precede end."""
    if start and end and datetime.fromisoformat(start) >= datetime.fromisoformat(end):
        fail(error)


def parse_utc(raw) -> datetime | None:
    """Parse an ISO timestamp, assuming UTC when naive; None when not parseable."""
    try:
        value = datetime.fromisoformat(str(raw))
    except (TypeError, ValueError):
        return None
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    return value
