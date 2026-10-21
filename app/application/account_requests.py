"""Account approval use cases. All writes run inside the caller's transaction.

No route may insert a login identity. Guest/RSVP/QR paths never call this module.
A tracking capability is returned only to its holder, never to reviewers.
"""
from datetime import datetime, timedelta, timezone
import hashlib
import json
import secrets
import os

from sqlalchemy import insert, select, update, func, or_, text as sql_text

from app.account_requests_db import account_requests as ar, request_workflows as wf
from app.application.access import event_permissions, active_window, organization_visible
from app.application.audit_service import new_id, write_audit
from app.application.phone_accounts import contact_identity, find_contact_user, bind_phone
from app.core.security import digest, hash_password
from app.db import users, sites, memberships, assignments, organizations, event_participations, organization_people, signup_requests, requests
from app.domain import fail, now, text, default_config, stamp
from app.infrastructure.account_requests import add_pending_account_request, public_account_request


def expires(days=7):
    return (datetime.now(timezone.utc) + timedelta(days=days)).isoformat()


def expire_pending(conn):
    ids = conn.execute(select(ar.c.id).where(ar.c.status == 'pending', ar.c.expires_at <= now()).with_for_update()).scalars().all()
    for rid in ids:
        conn.execute(update(ar).where(ar.c.id == rid, ar.c.status == 'pending').values(status='expired', password_hash=None, reviewed_at=now()))
        sync_legacy(conn, rid, 'expired')
        write_audit(conn, None, None, 'account_request_expired', {'request_id': rid})
    return len(ids)


def org_reviewer(conn, actor, oid, sensitive=False):
    if actor['role'] == 'platform': return True
    if actor['role'] == 'organizer' and conn.execute(select(event_participations.c.id).where(
            event_participations.c.organization_id == oid, event_participations.c.event_id == actor['scope_id'], event_participations.c.status == 'active')).first(): return True
    return not sensitive and bool(conn.execute(select(memberships.c.user_id).where(
        memberships.c.user_id == actor['id'], memberships.c.organization_id == oid,
        memberships.c.role == 'owner', memberships.c.status == 'active')).first())


def authorized(conn, actor, record):
    if not actor or not actor['active']: return False
    if record['scope_type'] == 'organization':
        return org_reviewer(conn, actor, record['scope_id'], record.get('membership_role') in ('owner','admin'))
    site = conn.execute(select(sites).where(sites.c.id == record['scope_id'])).mappings().first()
    if not site: return False
    if record['requested_role'] in ('platform','organizer') or site['kind'] == 'platform':
        return actor['role'] == 'platform'
    event_id = site['id'] if site['kind'] == 'event' else site['event_id']
    if actor['role'] == 'platform': return True
    if record.get('assignment_role'):
        permissions = event_permissions(conn, actor, event_id)
        if 'committee.manage' not in permissions: return False
        # A delegated manager cannot grant a capability that they do not possess.
        from app.application.access import EVENT_ROLE_PERMISSIONS
        return EVENT_ROLE_PERMISSIONS[record['assignment_role']] <= permissions
    return actor['role'] == 'organizer' and actor['scope_id'] == event_id


def choose_supervisor(conn, record, actor=None):
    candidates = conn.execute(select(users).where(users.c.active == 1).order_by(users.c.id)).mappings().all()
    # Prefer a scoped owner/organizer, and an independent reviewer where available.
    candidates = sorted(candidates, key=lambda u: (u['id'] == (actor or {}).get('id'), 2 if u['role']=='platform' else 1 if u['role']=='organizer' else 0))
    for candidate in candidates:
        if candidate['id'] != (actor or {}).get('id') and candidate['id'] != record.get('existing_user_id') and candidate['email'].lower() != record['email'].lower() and authorized(conn, candidate, record):
            return candidate['id']
    fail('ACCOUNT_REQUEST_SUPERVISOR_UNAVAILABLE', 409)


def check_submitter(conn, actor, record):
    if actor is None: return
    if not actor['active']: fail('FORBIDDEN_ROLE', 403)
    if record['scope_type'] == 'organization':
        if not org_reviewer(conn, actor, record['scope_id'], False): fail('FORBIDDEN_SCOPE', 403)
    elif not authorized(conn, actor, record):
        # An organizer may submit organizer requests for platform review in their event.
        if not (record['requested_role'] == 'organizer' and actor['role'] == 'organizer' and actor['scope_id'] == record['scope_id']):
            fail('FORBIDDEN_SCOPE', 403)


def submit(conn, *, actor, body, purpose, scope_type, scope_id, role, membership_role=None,
           assignment_role=None, person_id=None, signup_id=None, access_id=None):
    if os.environ.get('ACCOUNT_REQUESTS_ACCEPTING','true').lower() not in ('true','1','yes'):fail('ACCOUNT_REQUESTS_PAUSED',503)
    expire_pending(conn)
    email, phone = contact_identity(body, preserve_email=True)
    initial_target=find_contact_user(conn,email,phone)
    name = text(body.get('name') or body.get('contact_name') or (initial_target['name'] if initial_target else None), 160, True)
    if role not in ('platform','organizer','agency','member'): fail('ACCOUNT_REQUEST_ROLE_INVALID')
    if membership_role not in (None,'owner','admin','editor','analyst'): fail('MEMBERSHIP_ROLE_INVALID')
    from app.application.access import EVENT_ROLE_PERMISSIONS
    if assignment_role is not None and assignment_role not in EVENT_ROLE_PERMISSIONS: fail('COMMITTEE_ROLE_INVALID')
    record = dict(email=email, requested_role=role, scope_type=scope_type, scope_id=scope_id,
                  membership_role=membership_role, assignment_role=assignment_role)
    check_submitter(conn, actor, record)
    target = find_contact_user(conn, email, phone)
    if role=='platform' and target and target['role']!='platform':fail('EXISTING_ACCOUNT_ROLE_CONFLICT',409)
    if purpose == 'personal' and target: fail('PHONE_ALREADY_REGISTERED', 409)
    if target and not target['active']: fail('ACCOUNT_SUSPENDED', 409)
    if body.get('user_id') and (not target or target['id'] != body['user_id']): fail('CONTACT_IDENTITIES_CONFLICT',409)
    password = body.get('password') if actor is None else None
    if password is not None and password != body.get('confirmation'): fail('PASSWORD_CONFIRMATION_MISMATCH')
    token = body.get('request_key') or secrets.token_urlsafe(32)
    if not isinstance(token, str) or not 32 <= len(token) <= 80 or not all(c.isalnum() or c in '_-' for c in token): fail('ACCOUNT_REQUEST_KEY_INVALID')
    key = digest(token)
    fingerprint = digest(json.dumps([email,phone,name,purpose,scope_type,scope_id,role,membership_role,assignment_role,person_id,body.get('valid_from'),body.get('valid_until'),body.get('organization_name') if purpose=='signup' else None,body.get('participation_type') if purpose=='signup' else None,body.get('wants_account',True) if purpose=='signup' else None,body.get('message') if purpose=='signup' else None], separators=(',',':')))
    old = conn.execute(select(ar, wf.c.payload_hash).join(wf, ar.c.id == wf.c.request_id).where(ar.c.request_key == key)).mappings().first()
    if old:
        if old['payload_hash'] != fingerprint: fail('ACCOUNT_REQUEST_KEY_EXISTS',409)
        return {**view(conn, old), 'tracking_token': token, 'already_pending': True, 'grants_access': False}
    start, end = stamp(body.get('valid_from')), stamp(body.get('valid_until'))
    start=datetime.fromisoformat(start).astimezone(timezone.utc).isoformat() if start else None
    end=datetime.fromisoformat(end).astimezone(timezone.utc).isoformat() if end else None
    if start and end and start >= end: fail('ASSIGNMENT_WINDOW_INVALID')
    supervisor = choose_supervisor(conn, {**record,'existing_user_id':target['id'] if target else None}, actor)
    saved = add_pending_account_request(conn, **record, name=name, phone=phone,
        supervisor_id=supervisor, requested_by=actor['id'] if actor else None,
        expires_at=expires(), request_key=key, source={'personal':'signup','site':'admin','signup':'signup','access':'access','committee':'committee','organization':'organization'}[purpose],
        password=password if not target else None, person_id=person_id, allow_existing=True)
    conn.execute(insert(wf).values(request_id=saved['id'], purpose=purpose, tracking_hash=key,
        payload_hash=fingerprint, existing_user_id=target['id'] if target else None,
        signup_id=signup_id, access_id=access_id, valid_from=start or None, valid_until=end or None))
    write_audit(conn, actor, scope_id if scope_type=='site' else None, 'account_request_submitted', {'request_id':saved['id'],'scope_type':scope_type,'scope_id':scope_id})
    return {**view(conn, saved), 'tracking_token':token, 'grants_access':False}


def context(conn, rid):
    row = conn.execute(select(wf).where(wf.c.request_id==rid)).mappings().first()
    if not row: fail('ACCOUNT_REQUEST_NOT_FOUND',404)
    return row


def view(conn, record):
    result=public_account_request(record)
    ctx=context(conn,record['id'])
    supervisor=conn.execute(select(users.c.name).where(users.c.id==record['supervisor_id'])).scalar()
    signup=conn.execute(select(signup_requests).where(signup_requests.c.id==ctx['signup_id'])).mappings().first() if ctx['signup_id'] else None
    if record['scope_type']=='organization':
        scope_name=conn.execute(select(organizations.c.name).where(organizations.c.id==record['scope_id'])).scalar()
    else:
        draft=conn.execute(select(sites.c.draft).where(sites.c.id==record['scope_id'])).scalar()
        scope_name=(draft or {}).get('title')
    result.update(account_requested=bool(signup['wants_account']) if signup else True,
                  organization_name=signup['organization_name'] if signup else None,scope_name=scope_name or record['scope_id'],
                  purpose=ctx['purpose'], user_id=ctx['user_id'], supervisor_name=supervisor,
                  setup_required=bool(ctx['setup_expires_at'] and record['status']=='approved'), setup_expired=bool(ctx['setup_expires_at'] and ctx['setup_expires_at']<=now()),
                  setup_expires_at=ctx['setup_expires_at'], result_site_id=ctx['result_site_id'], result_organization_id=ctx['result_organization_id'])
    if result['email'].startswith('tel:'):result['email']=None
    return result


def list_for_reviewer(conn, actor, status=None, scope_id=None):
    expire_pending(conn)
    q=select(ar).join(wf, ar.c.id==wf.c.request_id).where(ar.c.supervisor_id==actor['id']).order_by(ar.c.created_at)
    if status:q=q.where(ar.c.status==status)
    if scope_id:q=q.where(or_(ar.c.scope_id==scope_id, ar.c.organization_id.in_(select(event_participations.c.organization_id).where(event_participations.c.event_id==scope_id))))
    return [view(conn,r) for r in conn.execute(q).mappings() if authorized(conn,actor,r)]


def sync_legacy(conn, rid, status):
    ctx=conn.execute(select(wf).where(wf.c.request_id==rid)).mappings().first()
    if not ctx:return
    if ctx['signup_id']:conn.execute(update(signup_requests).where(signup_requests.c.id==ctx['signup_id']).values(status=status))
    if ctx['access_id']:conn.execute(update(requests).where(requests.c.id==ctx['access_id']).values(status=status))


def locked_identity(conn, record):
    if conn.dialect.name=='postgresql':
        for value in sorted({record['email'],record['phone'] or record['email']}):
            key=int.from_bytes(hashlib.sha256(value.encode()).digest()[:8], 'big', signed=True)
            conn.execute(sql_text('SELECT pg_advisory_xact_lock(:key)'),{'key':key})


def signup_entities(conn, record, ctx):
    signup=conn.execute(select(signup_requests).where(signup_requests.c.id==ctx['signup_id'])).mappings().one()
    oid=new_id();slug='org-'+record['id'].replace('-','')[:16]
    conn.execute(insert(organizations).values(id=oid,slug=slug,name=signup['organization_name'],profile={'description':signup['details'].get('message','')},status='active',created_at=now()))
    sid=new_id();kind='event' if signup['requested_role']=='organizer' else 'agency'
    parent='platform' if kind=='event' else signup['event_id']
    if kind=='agency' and not parent:fail('EVENT_REQUIRED')
    conn.execute(insert(sites).values(id=sid,parent_id=parent,event_id=sid if kind=='event' else parent,kind=kind,slug=slug,draft=default_config(signup['organization_name'],kind),draft_rev=1,published_version=0))
    if kind=='agency':conn.execute(insert(event_participations).values(id=new_id(),event_id=parent,organization_id=oid,agency_site_id=sid,participation_type=signup['participation_type'] or 'exhibitor',status='active',services=[],created_at=now()))
    return sid, oid


def approve_links(conn, actor, record, ctx, target, sid, oid):
    uid=target['id']
    if oid:
        old=conn.execute(select(memberships).where(memberships.c.user_id==uid,memberships.c.organization_id==oid)).mappings().first()
        values=dict(role=record['membership_role'] or 'owner',status='active')
        if old:conn.execute(update(memberships).where(memberships.c.user_id==uid,memberships.c.organization_id==oid).values(**values))
        else:conn.execute(insert(memberships).values(user_id=uid,organization_id=oid,created_at=now(),**values))
    assignment_role=record['assignment_role']
    # Existing accounts keep their global role/scope; grant only the approved scope.
    if ctx['purpose']=='signup' and record['requested_role']=='organizer':assignment_role='event_manager'
    if not assignment_role and not oid and record['requested_role']!='platform' and ctx['purpose'] in ('site','access','signup'):
        assignment_role='event_manager' if record['requested_role']=='organizer' else 'site_manager'
    if assignment_role:
        old=conn.execute(select(assignments.c.id).where(assignments.c.user_id==uid,assignments.c.site_id==sid,assignments.c.role==assignment_role)).scalar()
        values=dict(status='active',valid_from=ctx['valid_from'],valid_until=ctx['valid_until'])
        if old:conn.execute(update(assignments).where(assignments.c.id==old).values(**values))
        else:conn.execute(insert(assignments).values(id=new_id(),user_id=uid,site_id=sid,role=assignment_role,created_at=now(),**values))
    if record['person_id']:
        person=conn.execute(select(organization_people).where(organization_people.c.id==record['person_id'])).mappings().first()
        if not person or person['organization_id']!=oid or person['user_id'] not in (None,uid):fail('PERSON_ACCOUNT_CONFLICT',409)
        conn.execute(update(organization_people).where(organization_people.c.id==person['id']).values(user_id=uid))


def review(conn, actor, rid, action, reason=None):
    actor=conn.execute(select(users).where(users.c.id==actor['id']).with_for_update()).mappings().one()
    record=conn.execute(select(ar).where(ar.c.id==rid).with_for_update()).mappings().first()
    if not record or record['supervisor_id']!=actor['id'] or not authorized(conn,actor,record):fail('ACCOUNT_REQUEST_NOT_FOUND',404)
    ctx=context(conn,rid)
    if actor['id']==record['requested_by'] or actor['email'].lower()==record['email'].lower() or actor['id']==ctx['existing_user_id']:
        fail('ACCOUNT_REQUEST_SELF_REVIEW',403)
    if action not in ('approved','rejected'):fail('REQUEST_STATUS_INVALID')
    if record['status']!= 'pending':return {**view(conn,record),'already_reviewed':True}
    if record['expires_at']<=now():
        conn.execute(update(ar).where(ar.c.id==rid).values(status='expired',password_hash=None,reviewed_at=now()));sync_legacy(conn,rid,'expired')
        return view(conn,dict(record,status='expired',password_hash=None,reviewed_at=now()))
    reason=text(reason,500,action=='rejected') or None
    if action=='approved':
        signup=conn.execute(select(signup_requests).where(signup_requests.c.id==ctx['signup_id'])).mappings().first() if ctx['signup_id'] else None
        if signup is not None and not signup['wants_account']:
            sid,oid=signup_entities(conn,record,ctx)
            conn.execute(update(wf).where(wf.c.request_id==rid).values(result_site_id=sid,result_organization_id=oid))
        else:
            locked_identity(conn,record)
            target=find_contact_user(conn,record['email'],record['phone'])
            if ctx['purpose']=='personal' and target:fail('CONTACT_IDENTITIES_CONFLICT',409)
            if ctx['existing_user_id'] and (not target or target['id']!=ctx['existing_user_id']):fail('CONTACT_IDENTITIES_CONFLICT',409)
            sid=record['scope_id'] if record['scope_type']=='site' else None
            oid=record['organization_id']
            if ctx['purpose']=='signup':sid,oid=signup_entities(conn,record,ctx)
            if oid and not sid:
                sid=conn.execute(select(event_participations.c.agency_site_id).where(event_participations.c.organization_id==oid,event_participations.c.status=='active').order_by(event_participations.c.created_at.desc())).scalar()
            is_new=not target
            if target and not target['active']:fail('ACCOUNT_SUSPENDED',409)
            if not target:
                personal=ctx['purpose']=='personal'
                hashed=record['password_hash'] or hash_password(secrets.token_urlsafe(32))
                target=dict(id=new_id(),email=record['email'],name=record['name'],role='attendee' if personal else record['requested_role'],scope_id=None if personal else sid,
                            password_hash=hashed,active=1 if record['password_hash'] else 0,must_change_password=0)
                conn.execute(insert(users).values(**target))
                if record['phone']:bind_phone(conn,target['id'],record['phone'])
            approve_links(conn,actor,record,ctx,target,sid,oid)
            conn.execute(update(wf).where(wf.c.request_id==rid).values(user_id=target['id'],result_site_id=sid,result_organization_id=oid,
                setup_expires_at=expires(1) if is_new and not record['password_hash'] else None))
    conn.execute(update(ar).where(ar.c.id==rid,ar.c.status=='pending').values(status=action,password_hash=None,reviewed_by=actor['id'],reviewed_at=now(),decision_reason=reason))
    sync_legacy(conn,rid,action)
    write_audit(conn,actor,record['scope_id'] if record['scope_type']=='site' else None,'account_request_'+action,{'request_id':rid,'scope_type':record['scope_type'],'scope_id':record['scope_id'],'result':action})
    return view(conn,dict(record,status=action,password_hash=None,reviewed_by=actor['id'],reviewed_at=now(),decision_reason=reason))


def owned(conn, token, lock=False):
    if not isinstance(token,str) or not 32<=len(token)<=80:fail('ACCOUNT_REQUEST_NOT_FOUND',404)
    q=select(ar).join(wf,ar.c.id==wf.c.request_id).where(wf.c.tracking_hash==digest(token))
    if lock:q=q.with_for_update(of=ar)
    record=conn.execute(q).mappings().first()
    if not record:fail('ACCOUNT_REQUEST_NOT_FOUND',404)
    return record


def status(conn, token):
    expire_pending(conn)
    return view(conn,owned(conn,token))


def cancel(conn, token):
    expire_pending(conn)
    record=owned(conn,token,True)
    if record['status']!='pending':return view(conn,record)
    conn.execute(update(ar).where(ar.c.id==record['id']).values(status='cancelled',password_hash=None,reviewed_at=now()))
    sync_legacy(conn,record['id'],'cancelled')
    write_audit(conn,None,None,'account_request_cancelled',{'request_id':record['id']})
    return view(conn,dict(record,status='cancelled',password_hash=None,reviewed_at=now()))


def setup_password(conn, token, body):
    record=owned(conn,token,True);ctx=context(conn,record['id'])
    if record['status']!='approved' or not ctx['setup_expires_at'] or ctx['setup_expires_at']<=now():fail('ACCOUNT_SETUP_UNAVAILABLE',409)
    if body.get('password')!=body.get('confirmation'):fail('PASSWORD_CONFIRMATION_MISMATCH')
    hashed=hash_password(body.get('password'))
    changed=conn.execute(update(users).where(users.c.id==ctx['user_id'],users.c.active==0).values(password_hash=hashed,active=1)).rowcount
    if changed!=1:fail('ACCOUNT_SETUP_UNAVAILABLE',409)
    conn.execute(update(wf).where(wf.c.request_id==record['id']).values(setup_expires_at=None))
    write_audit(conn,None,None,'account_password_set',{'request_id':record['id']})
    return {'ok':True,'login_required':True}


def renew_setup(conn, actor, rid):
    record=conn.execute(select(ar).where(ar.c.id==rid).with_for_update()).mappings().first()
    if not record or record['supervisor_id']!=actor['id'] or not authorized(conn,actor,record):fail('ACCOUNT_REQUEST_NOT_FOUND',404)
    if record['requested_by']==actor['id']:fail('ACCOUNT_REQUEST_SELF_REVIEW',403)
    ctx=context(conn,rid)
    target=conn.execute(select(users).where(users.c.id==ctx['user_id'])).mappings().first()
    if record['status']!='approved' or not ctx['setup_expires_at'] or not target or target['active']:fail('ACCOUNT_SETUP_UNAVAILABLE',409)
    conn.execute(update(wf).where(wf.c.request_id==rid).values(setup_expires_at=expires(1)))
    write_audit(conn,actor,None,'account_setup_renewed',{'request_id':rid})
    return view(conn,record)


def list_submitted(conn, actor, status=None):
    q=select(ar).join(wf,ar.c.id==wf.c.request_id).where(ar.c.requested_by==actor['id']).order_by(ar.c.created_at)
    if status:q=q.where(ar.c.status==status)
    return [view(conn,r) for r in conn.execute(q).mappings()]


def invite_platform_candidate(conn, actor, body):
    from app.account_requests_db import platform_account_invites as invites
    if actor['role']!='platform' or not actor['active']:fail('FORBIDDEN_ROLE',403)
    email,phone=contact_identity(body,preserve_email=True)
    if find_contact_user(conn,email,phone):fail('ACCOUNT_ALREADY_EXISTS',409)
    token=secrets.token_urlsafe(32);rid=new_id();end=expires(1)
    conn.execute(insert(invites).values(id=rid,token_hash=digest(token),email=email,phone=phone,name=text(body.get('name'),160,True),
        created_by=actor['id'],created_at=now(),expires_at=end))
    write_audit(conn,actor,'platform','platform_account_invitation_created',{'invitation_id':rid})
    return {'id':rid,'status':'invited','invitation_token':token,'expires_at':end,'grants_access':False}


def platform_invite(conn, token, lock=False):
    from app.account_requests_db import platform_account_invites as invites
    if not isinstance(token,str) or not 32<=len(token)<=80:fail('ACCOUNT_REQUEST_NOT_FOUND',404)
    q=select(invites).where(invites.c.token_hash==digest(token))
    if lock:q=q.with_for_update()
    row=conn.execute(q).mappings().first()
    if not row:fail('ACCOUNT_REQUEST_NOT_FOUND',404)
    if not row['request_id'] and row['expires_at']<=now():fail('ACCOUNT_INVITATION_EXPIRED',409)
    return row


def inspect_platform_invite(conn, token):
    row=platform_invite(conn,token)
    return {'name':row['name'],'email':None if row['email'].startswith('tel:') else row['email'],'phone':row['phone'],
            'expires_at':row['expires_at'],'submitted':bool(row['request_id'])}


def accept_platform_invite(conn, token, body):
    from app.account_requests_db import platform_account_invites as invites
    row=platform_invite(conn,token,True)
    if row['request_id']:return {**view(conn,owned(conn,token)), 'tracking_token':token,'already_pending':True,'grants_access':False}
    result=submit(conn,actor=None,body={'email':None if row['email'].startswith('tel:') else row['email'],'phone':row['phone'],
        'name':row['name'],'password':body.get('password'),'confirmation':body.get('confirmation'),'request_key':token},purpose='site',scope_type='site',scope_id='platform',role='platform')
    conn.execute(update(invites).where(invites.c.id==row['id']).values(request_id=result['id']))
    return result
