from datetime import datetime, timezone
from hashlib import sha256
from html import escape
import base64
import io
import secrets
from xml.etree import ElementTree

import qrcode
import qrcode.image.svg

from app.application.audit_service import new_id
from app.application.certificate_rendering import font_bytes, font_hash, image_data, validate_layout
from app.application.ports import persistence
from app.domain import now, text
from app.domain.certificates import (
    ALIASES, FIELDS, PLACEHOLDER, Certificate, CertificateDesign, IssueRequest, default_design, fingerprint,
    concurrent_issue_winner, issue_timezone, public_lookup_value, require_certificate, require_replacement_recorded,
    require_same_replacement, require_template, resolve_placeholders,
)

__all__ = [
    'ALIASES', 'FIELDS', 'PLACEHOLDER', 'create_template', 'default_design', 'find_certificate', 'fingerprint',
    'get_certificate', 'is_superseded', 'issue', 'issue_timezone', 'list_certificates', 'list_templates',
    'normalize_design', 'now', 'public_view', 'render_svg', 'replace', 'revoke', 'rotate_access', 'state',
]


def normalize_design(raw):
    return CertificateDesign.normalize(raw, image_data)


def state(row):
    return Certificate.state(row)


def create_template(tx, event_id, body):
    row = {'id': new_id(), 'event_id': event_id, 'name': text(body.get('name'), 160, True),
           'design': normalize_design(body.get('design', default_design())), 'created_at': now()}
    persistence.certificates.add_template(tx, row)
    return row


def get_certificate(tx, event_id, certificate_id):
    return require_certificate(persistence.certificates.certificate(tx, event_id, certificate_id))


def issue(tx, event_id, body):
    request = IssueRequest.parse(body)
    existing = persistence.certificates.by_request_key(tx, event_id, request.request_key)
    if existing:
        return dict(request.require_replay_of(existing)), None, False
    request.require_future_expiry(datetime.now(timezone.utc))
    template = require_template(persistence.certificates.template(tx, event_id, request.template_id))
    token = secrets.token_urlsafe(32)
    row = Certificate.issue(
        request, template, certificate_id=new_id(), event_id=event_id,
        serial='CERT-' + secrets.token_hex(16).upper(), access_hash=sha256(token.encode()).hexdigest(),
        issued_at=now(), font_hash=font_hash(), check_layout=validate_layout)
    if not persistence.certificates.add_if_absent(tx, row):
        # A concurrent retry returns the committed winner; different requests cannot duplicate an award.
        winner = persistence.certificates.by_request_key(tx, event_id, request.request_key)
        return concurrent_issue_winner(winner, request.request_hash), None, False
    return row, token, True


def public_view(row):
    data = row['snapshot']['data']
    return {'serial': row['serial'], 'status': state(row), 'participant_name': data['participant_name'],
            'course_title': data['course_title'], 'issuer_name': data['issuer_name'],
            'issued_at': row['issued_at'], 'expires_at': row['expires_at'], 'issue_date': data['issue_date'],
            'issue_timezone': row['snapshot'].get('issue_timezone', 'UTC')}


def revoke(tx, event_id, certificate_id, reason):
    reason = Certificate.revocation_reason(reason)
    row = get_certificate(tx, event_id, certificate_id)
    if Certificate.is_revoked(row):
        return row
    persistence.certificates.revoke(tx, certificate_id, now(), reason)
    return get_certificate(tx, event_id, certificate_id)


def replace(tx, event_id, certificate_id, body):
    original = get_certificate(tx, event_id, certificate_id)
    reason = Certificate.revocation_reason(body.get('reason'))
    # This internal award key represents a correction of this exact issue, not
    # another independent award. The immutable source snapshot remains intact.
    row, token, created = issue(tx, event_id, {**body, 'recipient_key': original['recipient_key'],
        'award_key': Certificate.replacement_award_key(original), 'template_id': body.get('template_id', original['template_id'])})
    link = persistence.certificates.replacement_of(tx, certificate_id)
    if link:
        require_same_replacement(link, row['id'])
        return row, token, created
    require_replacement_recorded(persistence.certificates.add_replacement_if_absent(
        tx, {'previous_id': certificate_id, 'replacement_id': row['id'], 'reason': reason, 'created_at': now()}))
    revoke(tx, event_id, certificate_id, reason)
    return row, token, created


def render_svg(row, verification_url):
    Certificate.require_valid(row)
    design, data = row['snapshot']['design'], row['snapshot']['data']
    w, h = design['width'], design['height']
    output = [f'<svg xmlns="http://www.w3.org/2000/svg" width="{w}" height="{h}" viewBox="0 0 {w} {h}">',
              '<defs><style>@font-face{font-family:CertificateSans;src:url(data:font/ttf;base64,' + base64.b64encode(font_bytes()).decode() + ')}</style></defs>',
              f'<rect width="{w}" height="{h}" fill="{design["background"]}"/>']
    if design.get('background_image'):
        output.append(f'<image width="{w}" height="{h}" href="{design["background_image"]}"/>')
    output.append(f'<rect x="24" y="24" width="{w-48}" height="{h-48}" fill="none" stroke="#b88a44" stroke-width="3"/>')
    for layer in design['layers']:
        if layer.get('kind') == 'image':
            output.append(f'<image x="{layer["x"]}" y="{layer["y"]}" width="{layer["width"]}" height="{layer["height"]}" href="{layer["image_data"]}"/>')
            continue
        content = resolve_placeholders(layer['text'], data)
        output.append(f'<text x="{layer["x"]}" y="{layer["y"]}" font-size="{layer["size"]}" '
                      f'fill="{layer["color"]}" font-family="CertificateSans" text-anchor="{layer["align"]}" '
                      f'direction="{layer["direction"]}" unicode-bidi="plaintext">{escape(content)}</text>')
    qr = qrcode.make(verification_url, image_factory=qrcode.image.svg.SvgPathImage)
    buffer = io.BytesIO(); qr.save(buffer)
    # Embed only the library-generated path, with a quiet zone retained in its viewBox.
    qr_root = ElementTree.fromstring(buffer.getvalue())
    pos = design['qr']
    output.append(f'<svg x="{pos["x"]}" y="{pos["y"]}" width="{pos["size"]}" height="{pos["size"]}" viewBox="{qr_root.attrib["viewBox"]}">')
    output.append('<rect width="100%" height="100%" fill="#ffffff"/>')
    output.extend(ElementTree.tostring(child, encoding='unicode') for child in qr_root)
    output.extend(['</svg>', '</svg>'])
    return ''.join(output)


def list_templates(tx, event_id):
    return persistence.certificates.templates(tx, event_id)


def list_certificates(tx, event_id, offset, limit):
    return persistence.certificates.page(tx, event_id, offset, limit)


def find_certificate(tx, field, value):
    """Public lookup by serial or by access-token hash; unknown values are concealed."""
    return require_certificate(persistence.certificates.find_by(tx, field, public_lookup_value(value)))


def is_superseded(tx, certificate_id):
    return persistence.certificates.replacement_of(tx, certificate_id) is not None


def rotate_access(tx, event_id, certificate_id):
    """Issue a new recipient access link; the previous link stops working."""
    row = get_certificate(tx, event_id, certificate_id)
    Certificate.require_valid(row)
    token = secrets.token_urlsafe(32)
    persistence.certificates.set_access_hash(tx, row['id'], sha256(token.encode()).hexdigest())
    return row, token
