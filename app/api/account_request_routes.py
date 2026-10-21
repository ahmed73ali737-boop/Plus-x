"""Thin HTTP boundary for scoped reviews and applicant capability links."""
from fastapi import Request, HTTPException
from app.application import account_requests as service
from app.application.audit_service import write_audit
from app.domain import fail


def install_account_request_routes(app, engine, identify):
    @app.post('/api/admin/platform-account-invites')
    def invite_platform(body: dict, request: Request):
        with engine.begin() as conn:
            actor,_=identify(request,conn,True)
            return service.invite_platform_candidate(conn,actor,body)

    @app.post('/api/account-invites/inspect')
    def inspect_invite(body: dict):
        with engine.connect() as conn:return service.inspect_platform_invite(conn,body.get('invitation_token'))

    @app.post('/api/account-invites/accept')
    def accept_invite(body: dict):
        with engine.begin() as conn:return service.accept_platform_invite(conn,body.get('invitation_token'),body)

    @app.post('/api/admin/platform-account-requests')
    def platform_request(body: dict, request: Request):
        with engine.begin() as conn:
            actor,_=identify(request,conn,True)
            if actor['role']!='platform':fail('FORBIDDEN_ROLE',403)
            return service.submit(conn,actor=actor,body=body,purpose='site',scope_type='site',scope_id='platform',role='platform')

    @app.post('/api/admin/account-requests/{rid}/setup-link')
    def renew(rid: str, request: Request):
        with engine.begin() as conn:
            actor,_=identify(request,conn,True)
            return service.renew_setup(conn,actor,rid)

    @app.get('/api/admin/account-requests')
    def list_requests(request: Request, status: str | None = None, scope_id: str | None = None):
        if status not in (None,'pending','approved','rejected','expired','cancelled'):fail('REQUEST_STATUS_INVALID')
        with engine.begin() as conn:
            actor,_=identify(request,conn)
            rows=service.list_for_reviewer(conn,actor,status,scope_id)
            return {'requests':rows,'submitted_requests':service.list_submitted(conn,actor,status),'counts':{state:sum(r['status']==state for r in rows) for state in ('pending','approved','rejected','expired','cancelled')}}

    @app.patch('/api/admin/account-requests/{rid}')
    def review(rid: str, body: dict, request: Request):
        actor=None
        try:
            with engine.begin() as conn:
                actor,_=identify(request,conn,True)
                return service.review(conn,actor,rid,body.get('status'),body.get('reason'))
        except HTTPException as error:
            if actor and error.status_code in (403,404):
                with engine.begin() as conn:
                    write_audit(conn,actor,None,'account_request_review_denied',{'request_id':rid[:64]})
            raise

    @app.post('/api/account-requests/status')
    def status(body: dict):
        with engine.begin() as conn:return service.status(conn,body.get('tracking_token'))

    @app.post('/api/account-requests/cancel')
    def cancel(body: dict):
        with engine.begin() as conn:return service.cancel(conn,body.get('tracking_token'))

    @app.post('/api/account-requests/password')
    def setup(body: dict):
        with engine.begin() as conn:return service.setup_password(conn,body.get('tracking_token'),body)
