"""Certificate use cases, distinct from RSVP and admission authority.

Templates are immutable versions; issuing freezes design and resolved data.
The hash detects accidental changes; it is NOT a digital issuer signature.
"""
from datetime import datetime, timezone
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError
from hashlib import sha256
from html import escape
import io
import re
import secrets
import qrcode
import qrcode.image.svg
from sqlalchemy import insert, select, update
from sqlalchemy.exc import IntegrityError
from app.certificates_db import certificate_templates, certificates, certificate_replacements
from app.core.serialization import canonical_json
from app.application.audit_service import new_id
from app.domain import fail, now, text, number, stamp
from app.application.certificate_rendering import image_data, font_hash, font_bytes, validate_layout
import base64

FIELDS = ('participant_name', 'course_title', 'issuer_name', 'grade', 'training_hours', 'issue_date', 'serial')
ALIASES = {'اسم_المشارك': 'participant_name', 'اسم_المتدرب': 'participant_name',
           'اسم_الدورة': 'course_title', 'الجهة_المصدرة': 'issuer_name', 'الدرجة': 'grade',
           'ساعات_التدريب': 'training_hours', 'تاريخ_الإصدار': 'issue_date', 'رقم_الشهادة': 'serial'}
PLACEHOLDER = re.compile(r'\{\{?\s*([^{}]+?)\s*\}\}?')


def fingerprint(value):
    return sha256(canonical_json(value).encode()).hexdigest()


def issue_timezone(value):
    name = text(value or 'UTC', 80, True)
    try: ZoneInfo(name)
    except (ZoneInfoNotFoundError, ValueError): fail('CERTIFICATE_TIMEZONE_INVALID')
    return name


def default_design():
    return {'width': 1120, 'height': 792, 'background': '#fffdf6', 'layers': [
        {'text': 'شهادة مشاركة', 'x': 560, 'y': 130, 'size': 48},
        {'text': '{{participant_name}}', 'x': 560, 'y': 300, 'size': 44},
        {'text': '{{course_title}}', 'x': 560, 'y': 415, 'size': 32},
        {'text': '{{issuer_name}}', 'x': 560, 'y': 500, 'size': 26},
        {'text': '{{issue_date}}', 'x': 560, 'y': 565, 'size': 22},
        {'text': '{{serial}}', 'x': 560, 'y': 690, 'size': 16, 'direction': 'ltr'},
    ], 'qr': {'x': 80, 'y': 580, 'size': 130}}


def color(value):
    if not isinstance(value, str) or not re.fullmatch(r'#[0-9a-fA-F]{6}', value):
        fail('CERTIFICATE_COLOR_INVALID')
    return value


def normalize_design(raw):
    if not isinstance(raw, dict): fail('CERTIFICATE_DESIGN_INVALID')
    w = number(raw.get('width'), 1120, 600, 2400)
    h = number(raw.get('height'), 792, 400, 2400)
    layers = raw.get('layers', [])
    if not isinstance(layers, list) or not 1 <= len(layers) <= 40: fail('CERTIFICATE_LAYERS_INVALID')
    clean = []
    for layer in layers:
        if not isinstance(layer, dict): fail('CERTIFICATE_LAYER_INVALID')
        if layer.get('kind') == 'image':
            iw = number(layer.get('width'), 160, 10, w)
            ih = number(layer.get('height'), 80, 10, h)
            clean.append({'kind': 'image', 'image_data': image_data(layer.get('image_data')),
                          'x': number(layer.get('x'), 0, 0, w-iw), 'y': number(layer.get('y'), 0, 0, h-ih),
                          'width': iw, 'height': ih})
            continue
        content = text(layer.get('text'), 600, True)
        for variable in PLACEHOLDER.findall(content):
            if ALIASES.get(variable, variable) not in FIELDS: fail('CERTIFICATE_VARIABLE_UNKNOWN')
        font = layer.get('font', 'Arial')
        if font not in ('DejaVu Sans', 'Arial', 'Times New Roman', 'serif', 'sans-serif'): fail('CERTIFICATE_FONT_INVALID')
        align = layer.get('align', 'middle')
        direction = layer.get('direction', 'rtl')
        if align not in ('start', 'middle', 'end') or direction not in ('rtl', 'ltr'): fail('CERTIFICATE_ALIGNMENT_INVALID')
        clean.append({'text': content, 'x': number(layer.get('x'), w/2, 0, w),
                      'y': number(layer.get('y'), h/2, 0, h), 'size': number(layer.get('size'), 28, 10, 100),
                      'color': color(layer.get('color', '#17313b')), 'font': 'DejaVu Sans', 'align': align, 'direction': direction})
    qr = raw.get('qr', {})
    if not isinstance(qr, dict): fail('CERTIFICATE_QR_INVALID')
    size = number(qr.get('size'), 130, 100, min(w, h)/2)
    result = {'width': w, 'height': h, 'background': color(raw.get('background', '#fffdf6')), 'layers': clean,
            'qr': {'x': number(qr.get('x'), 40, 0, w-size), 'y': number(qr.get('y'), h-size-40, 0, h-size), 'size': size}}
    if raw.get('background_image'): result['background_image'] = image_data(raw['background_image'])
    if len(canonical_json(result).encode()) > 3*1024*1024: fail('CERTIFICATE_DESIGN_SIZE_LIMIT')
    return result


def create_template(conn, event_id, body):
    row = {'id': new_id(), 'event_id': event_id, 'name': text(body.get('name'), 160, True),
           'design': normalize_design(body.get('design', default_design())), 'created_at': now()}
    conn.execute(insert(certificate_templates).values(**row))
    return row


def get_certificate(conn, event_id, certificate_id):
    row = conn.execute(select(certificates).where(certificates.c.event_id == event_id,
                         certificates.c.id == certificate_id)).mappings().first()
    if not row: fail('CERTIFICATE_NOT_FOUND', 404)
    return dict(row)


def issue(conn, event_id, body):
    template_id = text(body.get('template_id'), 64, True)
    request_key = text(body.get('request_key'), 80, True)
    recipient_key = text(body.get('recipient_key'), 160, True)
    award_key = text(body.get('award_key'), 80, True)
    data = body.get('data')
    if not isinstance(data, dict) or set(data) - set(FIELDS[:5]): fail('CERTIFICATE_DATA_INVALID')
    data = {k: text(data.get(k), 250, k in FIELDS[:3]) for k in FIELDS[:5]}
    if data['training_hours']:
        number(data['training_hours'], low=0, high=100000)
    expiry = stamp(body.get('expires_at')) or None
    zone = issue_timezone(body.get('timezone'))
    request_data = {'template_id': template_id, 'recipient_key': recipient_key,
                    'award_key': award_key, 'data': data, 'expires_at': expiry}
    request_hash = fingerprint({**request_data, 'timezone': zone})
    existing = conn.execute(select(certificates).where(certificates.c.event_id == event_id,
                                    certificates.c.request_key == request_key)).mappings().first()
    if existing:
        legacy_retry = zone == 'UTC' and existing['request_hash'] == fingerprint(request_data)
        if existing['request_hash'] != request_hash and not legacy_retry: fail('CERTIFICATE_REQUEST_CONFLICT', 409)
        return dict(existing), None, False
    if expiry and datetime.fromisoformat(expiry) <= datetime.now(timezone.utc): fail('CERTIFICATE_EXPIRY_INVALID')
    template = conn.execute(select(certificate_templates).where(certificate_templates.c.id == template_id,
                                   certificate_templates.c.event_id == event_id)).mappings().first()
    if not template: fail('CERTIFICATE_TEMPLATE_NOT_FOUND', 404)
    serial = 'CERT-' + secrets.token_hex(16).upper()
    issued_at = now()
    data.update(serial=serial, issue_date=datetime.fromisoformat(issued_at).astimezone(ZoneInfo(zone)).date().isoformat())
    validate_layout(template['design'], data)
    snapshot = {'design': template['design'], 'data': data, 'template_id': template_id, 'font_hash': font_hash(), 'renderer': 'certificate-raster-v1', 'issue_timezone': zone}
    token = secrets.token_urlsafe(32)
    row = {'id': new_id(), 'event_id': event_id, 'template_id': template_id, 'request_key': request_key,
           'request_hash': request_hash, 'recipient_key': recipient_key, 'award_key': award_key,
           'serial': serial, 'access_hash': sha256(token.encode()).hexdigest(), 'snapshot': snapshot,
           'snapshot_hash': fingerprint(snapshot), 'status': 'issued', 'issued_at': issued_at,
           'expires_at': expiry, 'revoked_at': None, 'revoke_reason': None}
    try:
        with conn.begin_nested(): conn.execute(insert(certificates).values(**row))
    except IntegrityError:
        # A concurrent retry returns the committed winner; different requests cannot duplicate an award.
        winner = conn.execute(select(certificates).where(certificates.c.event_id == event_id,
                                      certificates.c.request_key == request_key)).mappings().first()
        if winner and winner['request_hash'] == request_hash: return dict(winner), None, False
        fail('CERTIFICATE_DUPLICATE_OR_CONCURRENT_REQUEST', 409)
    return row, token, True


def state(row):
    if row['status'] == 'revoked': return 'revoked'
    if row['snapshot_hash'] != fingerprint(row['snapshot']): return 'integrity_error'
    if row['expires_at'] and datetime.fromisoformat(row['expires_at']) <= datetime.now(timezone.utc): return 'expired'
    return 'valid'


def public_view(row):
    data = row['snapshot']['data']
    return {'serial': row['serial'], 'status': state(row), 'participant_name': data['participant_name'],
            'course_title': data['course_title'], 'issuer_name': data['issuer_name'],
            'issued_at': row['issued_at'], 'expires_at': row['expires_at'], 'issue_date': data['issue_date'],
            'issue_timezone': row['snapshot'].get('issue_timezone', 'UTC')}


def revoke(conn, event_id, certificate_id, reason):
    reason = text(reason, 500, True)
    row = get_certificate(conn, event_id, certificate_id)
    if row['status'] == 'revoked': return row
    conn.execute(update(certificates).where(certificates.c.id == certificate_id, certificates.c.status == 'issued')
                 .values(status='revoked', revoked_at=now(), revoke_reason=reason))
    return get_certificate(conn, event_id, certificate_id)


def replace(conn, event_id, certificate_id, body):
    original = get_certificate(conn, event_id, certificate_id)
    reason = text(body.get('reason'), 500, True)
    # This internal award key represents a correction of this exact issue, not
    # another independent award. The immutable source snapshot remains intact.
    row, token, created = issue(conn, event_id, {**body, 'recipient_key': original['recipient_key'],
        'award_key': 'replacement/'+original['id'], 'template_id': body.get('template_id', original['template_id'])})
    link = conn.execute(select(certificate_replacements).where(certificate_replacements.c.previous_id == certificate_id)).mappings().first()
    if link:
        if link['replacement_id'] != row['id']: fail('CERTIFICATE_ALREADY_REPLACED', 409)
        return row, token, created
    try:
        with conn.begin_nested():
            conn.execute(insert(certificate_replacements).values(previous_id=certificate_id, replacement_id=row['id'], reason=reason, created_at=now()))
    except IntegrityError: fail('CERTIFICATE_ALREADY_REPLACED', 409)
    revoke(conn, event_id, certificate_id, reason)
    return row, token, created


def render_svg(row, verification_url):
    if state(row) != 'valid': fail('CERTIFICATE_NOT_VALID', 410)
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
        content = PLACEHOLDER.sub(lambda m: data[ALIASES.get(m[1], m[1])], layer['text'])
        output.append(f'<text x="{layer["x"]}" y="{layer["y"]}" font-size="{layer["size"]}" '
                      f'fill="{layer["color"]}" font-family="CertificateSans" text-anchor="{layer["align"]}" '
                      f'direction="{layer["direction"]}" unicode-bidi="plaintext">{escape(content)}</text>')
    qr = qrcode.make(verification_url, image_factory=qrcode.image.svg.SvgPathImage)
    buffer = io.BytesIO(); qr.save(buffer)
    # Embed only the library-generated path, with a quiet zone retained in its viewBox.
    from xml.etree import ElementTree as ET
    qr_root = ET.fromstring(buffer.getvalue())
    pos = design['qr']
    output.append(f'<svg x="{pos["x"]}" y="{pos["y"]}" width="{pos["size"]}" height="{pos["size"]}" viewBox="{qr_root.attrib["viewBox"]}">')
    output.append('<rect width="100%" height="100%" fill="#ffffff"/>')
    output.extend(ET.tostring(child, encoding='unicode') for child in qr_root)
    output.extend(['</svg>', '</svg>'])
    return ''.join(output)
