"""Scoped certificate administration and deliberately minimal public verification."""
from hashlib import sha256
import base64
import secrets
from fastapi import Request
from fastapi.responses import Response
from sqlalchemy import select, update
from app.application import certificate_service as svc
from app.application.certificate_rendering import render as render_document
from app.application import certificate_batches as batches
from app.application.access import require_event_permission
from app.certificates_db import certificates, certificate_templates, certificate_replacements
from app.domain import fail, text


def install_certificate_routes(app, engine, public_origin, identify, log):
    origin = public_origin.rstrip('/')

    def permission(conn, request, event_id, action, write=False):
        user, _ = identify(request, conn, write)
        require_event_permission(conn, user, event_id, action)
        return user

    def staff(row):
        return {k: v for k, v in row.items() if k not in ('access_hash', 'request_hash')}

    def lookup(conn, column, value):
        if len(value) > 120: fail('CERTIFICATE_NOT_FOUND', 404)
        row = conn.execute(select(certificates).where(column == value)).mappings().first()
        if not row: fail('CERTIFICATE_NOT_FOUND', 404)
        return dict(row)

    @app.get('/api/admin/events/{event_id}/certificate-templates')
    def templates(event_id: str, request: Request):
        with engine.connect() as conn:
            permission(conn, request, event_id, 'certificates.manage')
            return {'items': [dict(r) for r in conn.execute(select(certificate_templates).where(
                certificate_templates.c.event_id == event_id).order_by(certificate_templates.c.created_at)).mappings()],
                'default_design': svc.default_design()}

    @app.post('/api/admin/events/{event_id}/certificate-templates')
    def create_template(event_id: str, body: dict, request: Request):
        with engine.begin() as conn:
            user = permission(conn, request, event_id, 'certificates.manage', True)
            row = svc.create_template(conn, event_id, body)
            log(conn, user, event_id, 'certificate_template_created', {'template_id': row['id']})
            return row

    @app.post('/api/admin/events/{event_id}/certificates/preview')
    def preview(event_id: str, body: dict, request: Request):
        with engine.connect() as conn:
            permission(conn, request, event_id, 'certificates.manage', True)
        design = svc.normalize_design(body.get('design', svc.default_design()))
        raw = body.get('data', {})
        if not isinstance(raw, dict): fail('CERTIFICATE_DATA_INVALID')
        data = {k: text(raw.get(k) or k, 250) for k in svc.FIELDS}
        data['serial'] = 'PREVIEW-NOT-ISSUED'
        design['layers'].append({'text': 'معاينة — غير صالحة', 'x': design['width']/2, 'y': 60,
                                 'size': 22, 'font': 'Arial', 'align': 'middle', 'direction': 'rtl', 'color': '#aa2222'})
        snapshot = {'design': design, 'data': data}
        row = {'status': 'issued', 'expires_at': None, 'snapshot': snapshot, 'snapshot_hash': svc.fingerprint(snapshot)}
        return {'svg': svc.render_svg(row, f'{origin}/verify/certificate/PREVIEW-NOT-ISSUED')}

    @app.post('/api/admin/events/{event_id}/certificates/import/preview')
    def import_preview(event_id: str, body: dict, request: Request):
        with engine.begin() as conn:
            user = permission(conn, request, event_id, 'certificates.issue', True)
            return batches.preview(conn, event_id, user['id'], body)

    @app.post('/api/admin/events/{event_id}/certificates/import/commit')
    def import_commit(event_id: str, body: dict, request: Request):
        with engine.begin() as conn:
            user = permission(conn, request, event_id, 'certificates.issue', True)
            result = batches.commit(conn, event_id, user['id'], body)
            log(conn, user, event_id, 'certificate_batch_queued', {'import_id': result['import_id']})
            return result

    @app.get('/api/admin/events/{event_id}/certificates/batches')
    def batch_progress(event_id: str, request: Request):
        with engine.connect() as conn:
            permission(conn, request, event_id, 'certificates.manage')
            return {'items': batches.progress(conn, event_id)}

    @app.get('/api/admin/events/{event_id}/certificates')
    def listing(event_id: str, request: Request, offset: int = 0, limit: int = 100):
        if offset < 0 or limit < 1 or limit > 200: fail('CERTIFICATE_PAGE_INVALID')
        with engine.connect() as conn:
            permission(conn, request, event_id, 'certificates.manage')
            rows = conn.execute(select(certificates).where(certificates.c.event_id == event_id)
                                .order_by(certificates.c.issued_at.desc(), certificates.c.id).offset(offset).limit(limit)).mappings()
            return {'items': [{**staff(dict(r)), 'snapshot': {'data': r['snapshot']['data'], 'template_id': r['template_id']},
                               'validity': svc.state(r)} for r in rows]}

    @app.post('/api/admin/events/{event_id}/certificates')
    def issue(event_id: str, body: dict, request: Request):
        with engine.begin() as conn:
            user = permission(conn, request, event_id, 'certificates.issue', True)
            row, token, created = svc.issue(conn, event_id, body)
            if created: log(conn, user, event_id, 'certificate_issued', {'certificate_id': row['id'], 'snapshot_hash': row['snapshot_hash']})
            return {'certificate': staff(row), 'created': created,
                    'access_url': f'{origin}/certificate/{token}' if token else None,
                    'verification_url': f'{origin}/verify/certificate/{row["serial"]}'}

    @app.post('/api/admin/events/{event_id}/certificates/{certificate_id}/revoke')
    def revoke(event_id: str, certificate_id: str, body: dict, request: Request):
        with engine.begin() as conn:
            user = permission(conn, request, event_id, 'certificates.revoke', True)
            row = svc.revoke(conn, event_id, certificate_id, body.get('reason'))
            log(conn, user, event_id, 'certificate_revoked', {'certificate_id': row['id']})
            return staff(row)

    @app.post('/api/admin/events/{event_id}/certificates/{certificate_id}/replace')
    def replace(event_id: str, certificate_id: str, body: dict, request: Request):
        with engine.begin() as conn:
            user = permission(conn, request, event_id, 'certificates.issue', True)
            permission(conn, request, event_id, 'certificates.revoke', True)
            row, token, created = svc.replace(conn, event_id, certificate_id, body)
            if created: log(conn, user, event_id, 'certificate_replaced', {'previous_id': certificate_id, 'replacement_id': row['id']})
            return {'certificate': staff(row), 'created': created, 'access_url': f'{origin}/certificate/{token}' if token else None}

    @app.post('/api/admin/events/{event_id}/certificates/{certificate_id}/access-link')
    def access_link(event_id: str, certificate_id: str, body: dict, request: Request):
        with engine.begin() as conn:
            user = permission(conn, request, event_id, 'certificates.issue', True)
            row = svc.get_certificate(conn, event_id, certificate_id)
            if svc.state(row) != 'valid': fail('CERTIFICATE_NOT_VALID', 410)
            token = secrets.token_urlsafe(32)
            conn.execute(update(certificates).where(certificates.c.id == row['id']).values(access_hash=sha256(token.encode()).hexdigest()))
            log(conn, user, event_id, 'certificate_access_rotated', {'certificate_id': row['id']})
            return {'access_url': f'{origin}/certificate/{token}'}

    @app.get('/api/public/certificates/verify/{serial}')
    def verify(serial: str):
        with engine.connect() as conn:
            row = lookup(conn, certificates.c.serial, serial)
            result = svc.public_view(row)
            replaced = conn.execute(select(certificate_replacements.c.replacement_id).where(certificate_replacements.c.previous_id == row['id'])).first()
            # Keep the new access token and recipient's download link private.
            if replaced: result['superseded'] = True
            return result

    @app.get('/api/public/certificates/access/{token}')
    def access(token: str):
        with engine.connect() as conn:
            row = lookup(conn, certificates.c.access_hash, sha256(token.encode()).hexdigest())
            return {**svc.public_view(row), 'verification_url': f'{origin}/verify/certificate/{row["serial"]}'}

    @app.get('/api/public/certificates/access/{token}/image.svg')
    def image(token: str):
        with engine.connect() as conn:
            row = lookup(conn, certificates.c.access_hash, sha256(token.encode()).hexdigest())
        link = f'{origin}/verify/certificate/{row["serial"]}'
        design = row['snapshot']['design']
        if design.get('background_image') or any(layer.get('kind') == 'image' for layer in design['layers']):
            # Recipient downloads must not disclose the original transparent
            # signature/stamp as a separately extractable embedded asset.
            png = render_document(row, link, 'PNG')
            uri = base64.b64encode(png).decode()
            w, h = design['width'], design['height']
            content = f'<svg xmlns="http://www.w3.org/2000/svg" width="{w}" height="{h}" viewBox="0 0 {w} {h}"><image width="{w}" height="{h}" href="data:image/png;base64,{uri}"/></svg>'
        else:
            content = svc.render_svg(row, link)
        return Response(content, media_type='image/svg+xml',
                            headers={'Content-Disposition': 'inline; filename="certificate.svg"', 'Cache-Control': 'no-store',
                                     'Referrer-Policy': 'no-referrer', 'X-Robots-Tag': 'noindex, nofollow'})

    @app.get('/api/public/certificates/access/{token}/download.{extension}')
    def download(token: str, extension: str):
        if extension not in ('png', 'pdf'): fail('CERTIFICATE_FORMAT_UNSUPPORTED', 404)
        with engine.connect() as conn:
            row = lookup(conn, certificates.c.access_hash, sha256(token.encode()).hexdigest())
        content = render_document(row, f'{origin}/verify/certificate/{row["serial"]}', extension.upper())
        return Response(content, media_type='application/pdf' if extension == 'pdf' else 'image/png',
                        headers={'Content-Disposition': f'attachment; filename="{row["serial"]}.{extension}"'})
