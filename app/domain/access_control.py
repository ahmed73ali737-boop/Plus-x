"""Gate access policy of an event: guest types, checkpoints and re-entry rules.

The defaults are defined once here; both the site-configuration factory and the
gate read the same policy object.
"""
from __future__ import annotations

import copy
import hashlib
import json
from dataclasses import dataclass, field
from datetime import datetime, timezone

from app.domain.errors import fail
from app.domain.values import CODE, boolean, number, ordered_range, parse_utc, stamp, text

DEFAULT_GUEST_TYPES = (
    {'key': 'visitor', 'label': 'زائر'},
    {'key': 'vip', 'label': 'VIP'},
    {'key': 'staff', 'label': 'طاقم'},
    {'key': 'speaker', 'label': 'متحدث'},
    {'key': 'media', 'label': 'إعلام'},
    {'key': 'exhibitor', 'label': 'عارض'},
)
DEFAULT_CHECKPOINTS = (
    {'key': 'main', 'label': 'البوابة الرئيسية', 'enabled': True, 'allowed_guest_types': [], 'start': '', 'end': ''},
)
DEFAULT_MANIFEST_MAX_AGE_MINUTES = 7200
DEFAULT_GUEST_TYPE = 'visitor'


@dataclass(frozen=True)
class Checkpoint:
    """A gate checkpoint; a read-only view over one configured checkpoint."""

    key: str
    enabled: bool = True
    allowed_guest_types: tuple[str, ...] = ()
    start: str = ''
    end: str = ''

    @classmethod
    def from_dict(cls, item: dict) -> 'Checkpoint':
        return cls(
            key=item.get('key'),
            enabled=item.get('enabled') is not False,
            allowed_guest_types=tuple(item.get('allowed_guest_types') or ()),
            start=item.get('start') or '',
            end=item.get('end') or '',
        )

    def is_open(self, at: datetime | None = None) -> bool:
        """Inside the optional [start, end) window; an unreadable bound fails closed."""
        current = at or datetime.now(timezone.utc)
        if self.start:
            opens = parse_utc(self.start)
            if opens is None or current < opens:
                return False
        if self.end:
            closes = parse_utc(self.end)
            if closes is None or current >= closes:
                return False
        return True

    def admits(self, guest_type: str) -> bool:
        return not self.allowed_guest_types or guest_type in self.allowed_guest_types

    def denial_reason(self, guest_type: str, at: datetime | None = None) -> str | None:
        """Return the first rule that refuses this guest here, or None when admitted."""
        if not self.enabled:
            return 'CHECKPOINT_DISABLED'
        if not self.is_open(at):
            return 'CHECKPOINT_WINDOW_CLOSED'
        if not self.admits(guest_type):
            return 'GUEST_TYPE_NOT_ALLOWED'
        return None


@dataclass(frozen=True)
class AccessPolicy:
    """Value object for an event's access-control section."""

    anti_passback: bool = True
    allow_reentry: bool = True
    manifest_max_age_minutes: int = DEFAULT_MANIFEST_MAX_AGE_MINUTES
    guest_types: tuple[dict, ...] = field(default_factory=lambda: copy.deepcopy(DEFAULT_GUEST_TYPES))
    checkpoints: tuple[dict, ...] = field(default_factory=lambda: copy.deepcopy(DEFAULT_CHECKPOINTS))

    @classmethod
    def defaults(cls) -> 'AccessPolicy':
        return cls()

    @classmethod
    def from_site_config(cls, config) -> 'AccessPolicy':
        """Read a stored (already normalized or legacy) configuration leniently."""
        config = config if isinstance(config, dict) else {}
        raw = config.get('access_control') if isinstance(config.get('access_control'), dict) else {}
        guest_types = raw.get('guest_types')
        checkpoints = raw.get('checkpoints')
        return cls(
            anti_passback=raw.get('anti_passback', True) is not False,
            allow_reentry=raw.get('allow_reentry', True) is not False,
            manifest_max_age_minutes=int(raw.get('manifest_max_age_minutes') or DEFAULT_MANIFEST_MAX_AGE_MINUTES),
            guest_types=tuple(guest_types) if isinstance(guest_types, list) else copy.deepcopy(DEFAULT_GUEST_TYPES),
            checkpoints=tuple(checkpoints) if isinstance(checkpoints, list) else copy.deepcopy(DEFAULT_CHECKPOINTS),
        )

    @classmethod
    def parse(cls, raw) -> 'AccessPolicy':
        """Strictly validate an organizer-submitted access-control section."""
        defaults = cls.defaults()
        access = raw or defaults.to_dict()
        if not isinstance(access, dict):
            fail('ACCESS_CONTROL_INVALID')
        guest_types = _parse_guest_types(access.get('guest_types') or list(defaults.guest_types))
        type_keys = {item['key'] for item in guest_types}
        checkpoints = _parse_checkpoints(access.get('checkpoints') or list(defaults.checkpoints), type_keys)
        return cls(
            anti_passback=boolean(access.get('anti_passback', True)),
            allow_reentry=boolean(access.get('allow_reentry', True)),
            manifest_max_age_minutes=number(access.get('manifest_max_age_minutes'), DEFAULT_MANIFEST_MAX_AGE_MINUTES, 5, 10080),
            guest_types=tuple(guest_types),
            checkpoints=tuple(checkpoints),
        )

    def to_dict(self) -> dict:
        return {
            'anti_passback': self.anti_passback,
            'allow_reentry': self.allow_reentry,
            'manifest_max_age_minutes': self.manifest_max_age_minutes,
            'guest_types': [dict(item) if isinstance(item, dict) else item for item in self.guest_types],
            'checkpoints': [dict(item) if isinstance(item, dict) else item for item in self.checkpoints],
        }

    def version(self) -> str:
        """Short content hash; offline scanners must present the version they used."""
        source = json.dumps(self.to_dict(), ensure_ascii=False, sort_keys=True, separators=(',', ':'))
        return hashlib.sha256(source.encode('utf-8')).hexdigest()[:20]

    def checkpoint(self, key: str) -> Checkpoint | None:
        for item in self.checkpoints:
            if item.get('key') == key:
                return Checkpoint.from_dict(item)
        return None

    def checkpoint_dict(self, key: str) -> dict | None:
        for item in self.checkpoints:
            if item.get('key') == key:
                return item
        return None

    def guest_type_keys(self) -> set[str]:
        return {item.get('key') for item in self.guest_types if isinstance(item, dict)}


def _parse_guest_types(guest_types) -> list[dict]:
    if not isinstance(guest_types, list) or not guest_types or len(guest_types) > 20:
        fail('GUEST_TYPES_INVALID')
    clean, keys = [], set()
    for item in guest_types:
        if not isinstance(item, dict):
            fail('GUEST_TYPES_INVALID')
        key = text(item.get('key'), 40, True)
        label = text(item.get('label') or key, 100, True)
        if not CODE.fullmatch(key) or key in keys:
            fail('GUEST_TYPE_INVALID')
        keys.add(key)
        clean.append({'key': key, 'label': label})
    return clean


def _parse_checkpoints(checkpoints, type_keys: set[str]) -> list[dict]:
    if not isinstance(checkpoints, list) or not checkpoints or len(checkpoints) > 50:
        fail('CHECKPOINTS_INVALID')
    clean, keys = [], set()
    for item in checkpoints:
        if not isinstance(item, dict):
            fail('CHECKPOINT_INVALID')
        key = text(item.get('key'), 40, True)
        label = text(item.get('label') or key, 120, True)
        if not CODE.fullmatch(key) or key in keys:
            fail('CHECKPOINT_INVALID')
        keys.add(key)
        allowed = item.get('allowed_guest_types') or []
        if not isinstance(allowed, list) or len(allowed) > 20:
            fail('CHECKPOINT_GUEST_TYPES_INVALID')
        allowed = [text(value, 40, True) for value in allowed]
        if len(set(allowed)) != len(allowed) or any(value not in type_keys for value in allowed):
            fail('CHECKPOINT_GUEST_TYPES_INVALID')
        start, end = stamp(item.get('start')), stamp(item.get('end'))
        ordered_range(start, end, 'CHECKPOINT_DATE_RANGE')
        clean.append({
            'key': key,
            'label': label,
            'enabled': boolean(item.get('enabled', True)),
            'allowed_guest_types': allowed,
            'start': start,
            'end': end,
        })
    return clean
