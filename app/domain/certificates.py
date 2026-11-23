"""Certificate rules: design validation, issuance request, immutable snapshot and lifecycle.

Issuing freezes the design and the resolved data into a snapshot; its hash detects
accidental changes and is NOT a digital issuer signature. A certificate is
``issued`` until revoked; its *validity* is derived (revoked, integrity_error,
expired or valid) from the stored row, never trusted from a client.

Image decoding and text-fit measurement need imaging libraries, so the two checks
are injected as callables by the use case (``normalize_image`` / ``check_layout``).
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass
from datetime import datetime, timezone
from hashlib import sha256
from typing import Callable
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from app.domain.errors import Conflict, Gone, fail
from app.domain.values import number, stamp, text

FIELDS = ('participant_name', 'course_title', 'issuer_name', 'grade', 'training_hours', 'issue_date', 'serial')
ALIASES = {
    'اسم_المشارك': 'participant_name', 'اسم_المتدرب': 'participant_name',
    'اسم_الدورة': 'course_title', 'الجهة_المصدرة': 'issuer_name', 'الدرجة': 'grade',
    'ساعات_التدريب': 'training_hours', 'تاريخ_الإصدار': 'issue_date', 'رقم_الشهادة': 'serial',
}
PLACEHOLDER = re.compile(r'\{\{?\s*([^{}]+?)\s*\}\}?')
FONT_FAMILIES = ('DejaVu Sans', 'Arial', 'Times New Roman', 'serif', 'sans-serif')
RENDERER = 'certificate-raster-v1'
MAX_DESIGN_BYTES = 3 * 1024 * 1024
HEX_COLOR = re.compile(r'#[0-9a-fA-F]{6}')

ISSUED = 'issued'
REVOKED = 'revoked'
VALID = 'valid'
EXPIRED = 'expired'
INTEGRITY_ERROR = 'integrity_error'


def fingerprint(value) -> str:
    canonical = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(',', ':'))
    return sha256(canonical.encode()).hexdigest()


def issue_timezone(value) -> str:
    name = text(value or 'UTC', 80, True)
    try:
        ZoneInfo(name)
    except (ZoneInfoNotFoundError, ValueError):
        fail('CERTIFICATE_TIMEZONE_INVALID')
    return name


def default_design() -> dict:
    return {
        'width': 1120, 'height': 792, 'background': '#fffdf6',
        'layers': [
            {'text': 'شهادة مشاركة', 'x': 560, 'y': 130, 'size': 48},
            {'text': '{{participant_name}}', 'x': 560, 'y': 300, 'size': 44},
            {'text': '{{course_title}}', 'x': 560, 'y': 415, 'size': 32},
            {'text': '{{issuer_name}}', 'x': 560, 'y': 500, 'size': 26},
            {'text': '{{issue_date}}', 'x': 560, 'y': 565, 'size': 22},
            {'text': '{{serial}}', 'x': 560, 'y': 690, 'size': 16, 'direction': 'ltr'},
        ],
        'qr': {'x': 80, 'y': 580, 'size': 130},
    }


def color(value) -> str:
    if not isinstance(value, str) or not HEX_COLOR.fullmatch(value):
        fail('CERTIFICATE_COLOR_INVALID')
    return value


def resolve_placeholders(template_text: str, data: dict) -> str:
    return PLACEHOLDER.sub(lambda match: data[ALIASES.get(match[1], match[1])], template_text)


class CertificateDesign:
    """Normalises an untrusted design document into the bounded canonical form."""

    @staticmethod
    def normalize(raw, normalize_image: Callable[[object], str]) -> dict:
        if not isinstance(raw, dict):
            fail('CERTIFICATE_DESIGN_INVALID')
        width = number(raw.get('width'), 1120, 600, 2400)
        height = number(raw.get('height'), 792, 400, 2400)
        layers = raw.get('layers', [])
        if not isinstance(layers, list) or not 1 <= len(layers) <= 40:
            fail('CERTIFICATE_LAYERS_INVALID')
        clean = [CertificateDesign._layer(layer, width, height, normalize_image) for layer in layers]
        qr = raw.get('qr', {})
        if not isinstance(qr, dict):
            fail('CERTIFICATE_QR_INVALID')
        size = number(qr.get('size'), 130, 100, min(width, height) / 2)
        result = {
            'width': width, 'height': height,
            'background': color(raw.get('background', '#fffdf6')),
            'layers': clean,
            'qr': {'x': number(qr.get('x'), 40, 0, width - size),
                   'y': number(qr.get('y'), height - size - 40, 0, height - size), 'size': size},
        }
        if raw.get('background_image'):
            result['background_image'] = normalize_image(raw['background_image'])
        if len(json.dumps(result, ensure_ascii=False, sort_keys=True, separators=(',', ':')).encode()) > MAX_DESIGN_BYTES:
            fail('CERTIFICATE_DESIGN_SIZE_LIMIT')
        return result

    @staticmethod
    def _layer(layer, width, height, normalize_image) -> dict:
        if not isinstance(layer, dict):
            fail('CERTIFICATE_LAYER_INVALID')
        if layer.get('kind') == 'image':
            image_width = number(layer.get('width'), 160, 10, width)
            image_height = number(layer.get('height'), 80, 10, height)
            return {
                'kind': 'image', 'image_data': normalize_image(layer.get('image_data')),
                'x': number(layer.get('x'), 0, 0, width - image_width),
                'y': number(layer.get('y'), 0, 0, height - image_height),
                'width': image_width, 'height': image_height,
            }
        content = text(layer.get('text'), 600, True)
        for variable in PLACEHOLDER.findall(content):
            if ALIASES.get(variable, variable) not in FIELDS:
                fail('CERTIFICATE_VARIABLE_UNKNOWN')
        if layer.get('font', 'Arial') not in FONT_FAMILIES:
            fail('CERTIFICATE_FONT_INVALID')
        align = layer.get('align', 'middle')
        direction = layer.get('direction', 'rtl')
        if align not in ('start', 'middle', 'end') or direction not in ('rtl', 'ltr'):
            fail('CERTIFICATE_ALIGNMENT_INVALID')
        return {
            'text': content, 'x': number(layer.get('x'), width / 2, 0, width),
            'y': number(layer.get('y'), height / 2, 0, height),
            'size': number(layer.get('size'), 28, 10, 100),
            'color': color(layer.get('color', '#17313b')), 'font': 'DejaVu Sans',
            'align': align, 'direction': direction,
        }


@dataclass(frozen=True)
class IssueRequest:
    """A validated request to issue one certificate (the idempotency unit)."""

    template_id: str
    request_key: str
    recipient_key: str
    award_key: str
    data: dict
    expires_at: str | None
    timezone: str

    @staticmethod
    def parse(body: dict) -> 'IssueRequest':
        template_id = text(body.get('template_id'), 64, True)
        request_key = text(body.get('request_key'), 80, True)
        recipient_key = text(body.get('recipient_key'), 160, True)
        award_key = text(body.get('award_key'), 80, True)
        data = body.get('data')
        if not isinstance(data, dict) or set(data) - set(FIELDS[:5]):
            fail('CERTIFICATE_DATA_INVALID')
        data = {key: text(data.get(key), 250, key in FIELDS[:3]) for key in FIELDS[:5]}
        if data['training_hours']:
            number(data['training_hours'], low=0, high=100000)
        expires_at = stamp(body.get('expires_at')) or None
        return IssueRequest(template_id, request_key, recipient_key, award_key, data, expires_at,
                            issue_timezone(body.get('timezone')))

    def _core(self) -> dict:
        return {'template_id': self.template_id, 'recipient_key': self.recipient_key,
                'award_key': self.award_key, 'data': self.data, 'expires_at': self.expires_at}

    @property
    def request_hash(self) -> str:
        return fingerprint({**self._core(), 'timezone': self.timezone})

    def matches(self, stored_hash: str) -> bool:
        """Same request, or a legacy UTC request stored before the timezone field existed."""
        if stored_hash == self.request_hash:
            return True
        return self.timezone == 'UTC' and stored_hash == fingerprint(self._core())

    def require_replay_of(self, existing: dict) -> dict:
        """The stored certificate for this key, or a conflict when the key was reused differently."""
        if not self.matches(existing['request_hash']):
            fail('CERTIFICATE_REQUEST_CONFLICT', Conflict)
        return existing

    def require_future_expiry(self, at: datetime) -> None:
        if self.expires_at and datetime.fromisoformat(self.expires_at) <= at:
            fail('CERTIFICATE_EXPIRY_INVALID')


class Certificate:
    """Issued-certificate rules over the stored row (a dict)."""

    @staticmethod
    def issue(request: IssueRequest, template: dict, *, certificate_id: str, event_id: str, serial: str,
              access_hash: str, issued_at: str, font_hash: str,
              check_layout: Callable[[dict, dict], None]) -> dict:
        data = dict(request.data)
        data.update(serial=serial, issue_date=datetime.fromisoformat(issued_at).astimezone(
            ZoneInfo(request.timezone)).date().isoformat())
        check_layout(template['design'], data)
        snapshot = {'design': template['design'], 'data': data, 'template_id': request.template_id,
                    'font_hash': font_hash, 'renderer': RENDERER, 'issue_timezone': request.timezone}
        return {
            'id': certificate_id, 'event_id': event_id, 'template_id': request.template_id,
            'request_key': request.request_key, 'request_hash': request.request_hash,
            'recipient_key': request.recipient_key, 'award_key': request.award_key,
            'serial': serial, 'access_hash': access_hash, 'snapshot': snapshot,
            'snapshot_hash': fingerprint(snapshot), 'status': ISSUED, 'issued_at': issued_at,
            'expires_at': request.expires_at, 'revoked_at': None, 'revoke_reason': None,
        }

    @staticmethod
    def state(row: dict, at: datetime | None = None) -> str:
        if row['status'] == REVOKED:
            return REVOKED
        if row['snapshot_hash'] != fingerprint(row['snapshot']):
            return INTEGRITY_ERROR
        at = at or datetime.now(timezone.utc)
        if row['expires_at'] and datetime.fromisoformat(row['expires_at']) <= at:
            return EXPIRED
        return VALID

    @staticmethod
    def require_valid(row: dict, at: datetime | None = None) -> None:
        if Certificate.state(row, at) != VALID:
            fail('CERTIFICATE_NOT_VALID', Gone)

    @staticmethod
    def revocation_reason(value) -> str:
        return text(value, 500, True)

    @staticmethod
    def is_revoked(row: dict) -> bool:
        return row['status'] == REVOKED

    @staticmethod
    def replacement_award_key(original: dict) -> str:
        """A correction of this exact issue, not another independent award."""
        return 'replacement/' + original['id']
