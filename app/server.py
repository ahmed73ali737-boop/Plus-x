"""PulseX HTTP composition root.

SQLite remains the local QA backend; PostgreSQL requires native acceptance before production.
Delivery endpoints delegate security, access, publishing and collection rules to dedicated modules.
Build identity is centralized in app.core.build_info.
"""
from __future__ import annotations
import base64, copy, hashlib, io, json, mimetypes, os, re, secrets, uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path
from fastapi import FastAPI, Request, HTTPException
from fastapi.responses import FileResponse, JSONResponse, Response
from fastapi.staticfiles import StaticFiles
from sqlalchemy import select, update, insert, delete, func
from sqlalchemy.exc import IntegrityError
from .db import make_engine, metadata, ensure_compat_schema, sites, versions, users, sessions, imports, submissions, requests, audit, organizations, organization_people, memberships, event_participations, assignments, devices, signup_requests
from .domain import fail, now, text, number, boolean, normalize_config, normalize_record, default_config, survey_answers, answer_value, stamp, KINDS, QTYPES, SECTIONS
from .imports import parse as parse_import
from .core.security import digest, hash_password as password_hash, verify_password as password_ok, new_session_token, new_csrf_token, new_temporary_password
from .core.serialization import canonical_json as canon
from .core.build_info import APP_NAME, APP_VERSION
from .infrastructure.repository import fetch_one as row, get_site as site_row
from .application.access import can_manage, require_scope, organization_visible
from .application.audit_service import new_id as uid, write_audit as log
from .application.publishing import publish_site_version as publish, get_site_version as get_version
from .infrastructure.seed import seed_demo_data as seed
from .api.middleware import install_security_middleware
from .api.routers.health import create_health_router
from .application.auth_service import identify_request
from .application.collection_service import validate_submission, build_metrics
from .application.device_service import create_device, list_devices, update_device, heartbeat as device_heartbeat
from .application.access_request_service import list_requests, set_request_status
from .application.public_service import build_public_bundle, build_public_poll_results
from .api.guest_routes import install_guest_routes
from tools.production_gate import assert_production_ready

ROOT=Path(__file__).resolve().parent.parent
# Do not inherit OS-specific MIME registry drift for browser module assets.
# Chromium refuses ES modules unless .mjs is served with a JavaScript MIME type.
mimetypes.add_type("application/javascript", ".mjs")
mimetypes.add_type("application/manifest+json", ".webmanifest")

def create_app(database_url=None,origin=None,seed_demo=False,credentials_path=None):
    production_mode=(
        os.environ.get('PULSEX_ENV','').strip().lower()=='production'
        or os.environ.get('REQUIRE_POSTGRES','false').lower()=='true'
    )
    if production_mode:
        # Enforce release conditions inside the application factory as well as
        # deployment scripts, so direct uvicorn/run.py starts cannot bypass them.
        assert_production_ready()
    engine=make_engine(database_url);metadata.create_all(engine);ensure_compat_schema(engine)
    app=FastAPI(title=APP_NAME,version=APP_VERSION,docs_url=None,redoc_url=None)
    app.state.engine=engine;app.state.seed_credentials=seed(engine,credentials_path) if seed_demo else []
    public_origin=(origin or os.environ.get('PUBLIC_ORIGIN','http://127.0.0.1:4310')).rstrip('/')
    media_dir=Path(os.environ.get('MEDIA_DIR',str(ROOT/'data/media')));media_dir.mkdir(parents=True,exist_ok=True)
    dummy=password_hash(secrets.token_urlsafe(20))

    install_security_middleware(app, public_origin)

    app.include_router(create_health_router(engine))

    def identify(req,c,write=False):
        u,sess=identify_request(req,c,write)
        path=req.scope.get('path') or '/'
        if u.get('must_change_password') and path not in ('/api/auth/me','/api/auth/password','/api/auth/logout'):
            fail('PASSWORD_CHANGE_REQUIRED',428)
        return u,sess

    install_guest_routes(app, engine, public_origin, identify=identify, site_row=site_row, log=log)


    @app.post('/api/auth/login')
    def login(body:dict,request:Request):
        email=text(body.get('email'),200).lower()
        with engine.begin() as c:
            u=row(c,users,'email',email)
            valid=password_ok(body.get('password'),u['password_hash'] if u else dummy)
            if not u or not valid or not u['active']:fail('INVALID_CREDENTIALS',401)
            token=new_session_token();csrf=new_csrf_token()
            c.execute(insert(sessions).values(token_hash=digest(token),user_id=u['id'],csrf=csrf,expires_at=(datetime.now(timezone.utc)+timedelta(hours=8)).isoformat()))
            log(c,u,u['scope_id'],'login')
            response=JSONResponse({'user':{**{k:u[k] for k in ('id','email','name','role','scope_id')},'must_change_password':bool(u.get('must_change_password'))},'csrf':csrf})
            response.set_cookie('px_session',token,httponly=True,secure=app.state.cookie_secure,samesite='strict',max_age=28800,path='/')
            return response

    @app.get('/api/auth/me')
    def me(request:Request):
        with engine.connect() as c:
            u,s=identify(request,c);return {'user':{**{k:u[k] for k in ('id','email','name','role','scope_id')},'must_change_password':bool(u.get('must_change_password'))},'csrf':s['csrf']}

    @app.post('/api/auth/logout')
    def logout(request:Request):
        with engine.begin() as c:
            u,s=identify(request,c,True);c.execute(delete(sessions).where(sessions.c.token_hash==s['token_hash']))
        r=JSONResponse({'ok':True});r.delete_cookie('px_session',path='/');return r

    @app.post('/api/auth/password')
    def change_password(body:dict,request:Request):
        with engine.begin() as c:
            u,s=identify(request,c,True)
            if not password_ok(body.get('current'),u['password_hash']):fail('INVALID_CREDENTIALS',401)
            hashed=password_hash(body.get('password'));c.execute(update(users).where(users.c.id==u['id']).values(password_hash=hashed,must_change_password=0));c.execute(delete(sessions).where(sessions.c.user_id==u['id']));log(c,u,u['scope_id'],'password_changed')
        r=JSONResponse({'ok':True});r.delete_cookie('px_session',path='/');return r

    @app.post('/api/access-request')
    def access_request(body:dict):
        with engine.begin() as c:
            sid=text(body.get('site_id'),64,True);site_row(c,sid);email=text(body.get('email'),200,True).lower()
            if not re.fullmatch(r'[^\s@]+@[^\s@]+\.[^\s@]+',email):fail('EMAIL_INVALID')
            c.execute(insert(requests).values(id=uid(),site_id=sid,email=email,name=text(body.get('name'),160,True),created_at=now(),status='pending'))
        return {'status':'pending_approval','grants_access':False}

    @app.post('/api/signup-request')
    def signup_request(body:dict):
        with engine.begin() as c:
            sid=text(body.get('site_id'),64,True);site=site_row(c,sid)
            role=body.get('requested_role')
            if role not in ('organizer','participant'):fail('REQUESTED_ROLE_INVALID')
            email=text(body.get('email'),200,True).lower()
            if not re.fullmatch(r'[^\s@]+@[^\s@]+\.[^\s@]+',email):fail('EMAIL_INVALID')
            org_name=text(body.get('organization_name'),200,True)
            contact=text(body.get('contact_name') or org_name,160,True)
            phone=text(body.get('phone'),60)
            ptype=body.get('participation_type') if body.get('participation_type') in ('exhibitor','sponsor','partner','speaker','media','vendor') else 'exhibitor'
            event_id=site['id'] if site['kind']=='event' else site.get('event_id') if role=='participant' else None
            rid=uid()
            c.execute(insert(signup_requests).values(id=rid,site_id=sid,event_id=event_id,requested_role=role,organization_name=org_name,contact_name=contact,email=email,phone=phone,participation_type=ptype,wants_account=1 if boolean(body.get('wants_account',True)) else 0,status='pending',details={'message':text(body.get('message'),1500)},created_at=now()))
        return {'id':rid,'status':'pending','requested_role':role,'grants_access':False}

    @app.get('/api/admin/signup-requests')
    def admin_signup_requests(request:Request, site_id:str|None=None):
        with engine.connect() as c:
            u,_=identify(request,c)
            if u['role']=='agency':fail('FORBIDDEN_ROLE',403)
            q=select(signup_requests).order_by(signup_requests.c.created_at.desc())
            rows=[dict(x) for x in c.execute(q).mappings()]
            if u['role']=='organizer':rows=[x for x in rows if x.get('event_id')==u['scope_id']]
            if site_id:rows=[x for x in rows if x.get('site_id')==site_id or x.get('event_id')==site_id]
            return {'requests':rows}

    @app.patch('/api/admin/signup-requests/{rid}')
    def review_signup_request(rid:str,body:dict,request:Request):
        with engine.begin() as c:
            u,_=identify(request,c,True)
            req=c.execute(select(signup_requests).where(signup_requests.c.id==rid)).mappings().first()
            if not req:fail('SIGNUP_REQUEST_NOT_FOUND',404)
            if u['role']=='agency' or (u['role']=='organizer' and req.get('event_id')!=u['scope_id']):fail('FORBIDDEN_ROLE',403)
            action=body.get('status')
            if action=='rejected':
                c.execute(update(signup_requests).where(signup_requests.c.id==rid).values(status='rejected'));log(c,u,req['site_id'],'signup_request_rejected',{'request_id':rid});return {'status':'rejected'}
            if action!='approved':fail('REQUEST_STATUS_INVALID')
            slug=(re.sub(r'[^a-z0-9]+','-',text(body.get('organization_slug') or '',80).lower()).strip('-') or ('org-'+rid[:8]))[:70]
            if row(c,organizations,'slug',slug):slug=(slug+'-'+secrets.token_hex(2))[:70]
            oid=uid();profile={'description':text(body.get('description') or req['details'].get('message'),3000),'logo':'','primary':'#176B73','website':''}
            c.execute(insert(organizations).values(id=oid,slug=slug,name=req['organization_name'],profile=profile,status='active',created_at=now()))
            agency_sid=None
            if req['requested_role']=='participant' and req.get('event_id'):
                event=site_row(c,req['event_id']);agency_slug=(slug+'-'+event['slug'])[:70]
                if row(c,sites,'slug',agency_slug):agency_slug=(slug+'-'+secrets.token_hex(2))[:70]
                agency_sid=uid();cfg=default_config(req['organization_name'],'agency');cfg['description']=profile['description']
                c.execute(insert(sites).values(id=agency_sid,parent_id=event['id'],event_id=event['id'],kind='agency',slug=agency_slug,draft=cfg,draft_rev=1,published_version=0))
                c.execute(insert(event_participations).values(id=uid(),event_id=event['id'],organization_id=oid,agency_site_id=agency_sid,participation_type=req['participation_type'],status='active',booth='',summary='',services=[],valid_from=event['draft'].get('start') or '',valid_until=event['draft'].get('end') or '',created_at=now()))
            temp=None; account_deferred=False
            if req['wants_account'] and agency_sid:
                existing=row(c,users,'email',req['email'])
                if existing:uid_user=existing['id']
                else:
                    temp=new_temporary_password();uid_user=uid();c.execute(insert(users).values(id=uid_user,email=req['email'],name=req['contact_name'],role='agency',scope_id=agency_sid,password_hash=password_hash(temp),active=1,must_change_password=1))
                if not c.execute(select(memberships).where(memberships.c.user_id==uid_user,memberships.c.organization_id==oid)).first():c.execute(insert(memberships).values(user_id=uid_user,organization_id=oid,role='owner',status='active',created_at=now()))
            elif req['wants_account']:
                account_deferred=True
            c.execute(update(signup_requests).where(signup_requests.c.id==rid).values(status='approved'));log(c,u,req['site_id'],'signup_request_approved',{'request_id':rid,'organization_id':oid,'agency_site_id':agency_sid,'account_deferred':account_deferred})
            return {'status':'approved','organization_id':oid,'agency_site_id':agency_sid,'temporary_password':temp,'email':req['email'],'account_deferred_until_assignment':account_deferred}

    @app.get('/api/admin/sites')
    def list_admin_sites(request:Request):
        with engine.connect() as c:
            u,s=identify(request,c)
            result=c.execute(select(sites)).mappings()
            return {'sites':[{'id':x['id'],'slug':x['slug'],'kind':x['kind'],'event_id':x['event_id'],'title':x['draft']['title'],'draft_rev':x['draft_rev'],'published_version':x['published_version']} for x in result if can_manage(c,u,x)],'types':QTYPES,'kinds':KINDS,'sections':SECTIONS}

    @app.post('/api/admin/sites')
    def create_site(body:dict,request:Request):
        with engine.begin() as c:
            u,_=identify(request,c,True);kind=body.get('kind');parent=require_scope(c,u,body.get('parent_id'))
            if kind=='event' and (u['role']!='platform' or parent['kind']!='platform'):fail('FORBIDDEN_ROLE',403)
            if kind=='agency' and (u['role'] not in ('platform','organizer') or parent['kind']!='event'):fail('FORBIDDEN_ROLE',403)
            if kind not in ('agency','event'):fail('SITE_KIND')
            slug=text(body.get('slug'),80,True)
            if not re.fullmatch(r'[a-z0-9][a-z0-9-]{1,70}',slug):fail('SLUG_INVALID')
            if row(c,sites,'slug',slug):fail('SLUG_EXISTS',409)
            sid=uid();cfg=default_config(text(body.get('title'),160,True),kind)
            c.execute(insert(sites).values(id=sid,parent_id=parent['id'],event_id=sid if kind=='event' else parent['id'],kind=kind,slug=slug,draft=cfg,draft_rev=1,published_version=0));log(c,u,sid,'site_created')
        return {'id':sid,'draft_rev':1}

    @app.get('/api/admin/sites/{sid}')
    def get_admin_site(sid:str,request:Request):
        with engine.connect() as c:
            u,_=identify(request,c);s=dict(require_scope(c,u,sid));s['event_slug']=site_row(c,s['event_id'])['slug'] if s['event_id'] else None;return s

    @app.put('/api/admin/sites/{sid}')
    def save_site(sid:str,body:dict,request:Request):
        cfg=normalize_config(body.get('config'))
        with engine.begin() as c:
            u,_=identify(request,c,True);s=require_scope(c,u,sid)
            rev=body.get('draft_rev')
            if not isinstance(rev,int) or rev!=s['draft_rev']:fail('DRAFT_CHANGED_REFRESH_REQUIRED',409)
            result=c.execute(update(sites).where(sites.c.id==sid,sites.c.draft_rev==rev).values(draft=cfg,draft_rev=rev+1))
            if result.rowcount!=1:fail('DRAFT_CHANGED_REFRESH_REQUIRED',409)
            log(c,u,sid,'draft_saved',{'revision':rev+1})
        return {'draft_rev':rev+1}

    @app.post('/api/admin/sites/{sid}/publish')
    def publish_site(sid:str,body:dict,request:Request):
        with engine.begin() as c:
            u,_=identify(request,c,True);s=require_scope(c,u,sid)
            if body.get('draft_rev')!=s['draft_rev']:fail('DRAFT_CHANGED_REFRESH_REQUIRED',409)
            version=publish(c,s,u)
        return {'published_version':version}

    @app.get('/api/public/site/{slug}')
    def public_site(slug:str):
        with engine.connect() as c:
            s=row(c,sites,'slug',slug)
            if not s:fail('SITE_NOT_FOUND',404)
            return build_public_bundle(c,s,public_origin)

    @app.get('/api/admin/sites/{sid}/preview')
    def preview_site(sid:str,request:Request):
        with engine.connect() as c:
            u,_=identify(request,c);s=require_scope(c,u,sid);return build_public_bundle(c,s,public_origin,True)

    @app.get('/api/admin/sites/{sid}/users')
    def list_users(sid:str,request:Request):
        with engine.connect() as c:
            u,_=identify(request,c);s=require_scope(c,u,sid)
            if u['role']=='agency':fail('FORBIDDEN_ROLE',403)
            return {'users':[dict(x) for x in c.execute(select(users.c.id,users.c.email,users.c.name,users.c.role,users.c.scope_id,users.c.active).where(users.c.scope_id==sid)).mappings()], 'requests':list_requests(c,sid)}

    @app.post('/api/admin/sites/{sid}/users')
    def add_user(sid:str,body:dict,request:Request):
        with engine.begin() as c:
            u,_=identify(request,c,True);s=require_scope(c,u,sid)
            if u['role']=='agency' or s['kind']=='platform':fail('FORBIDDEN_ROLE',403)
            role='organizer' if s['kind']=='event' else 'agency'
            if role=='organizer' and u['role']!='platform':fail('FORBIDDEN_ROLE',403)
            email=text(body.get('email'),200,True).lower()
            if not re.fullmatch(r'[^\s@]+@[^\s@]+\.[^\s@]+',email):fail('EMAIL_INVALID')
            if row(c,users,'email',email):fail('EMAIL_EXISTS',409)
            pw=new_temporary_password()
            c.execute(insert(users).values(id=uid(),email=email,name=text(body.get('name'),160,True),role=role,scope_id=sid,password_hash=password_hash(pw),active=1,must_change_password=1))
            c.execute(update(requests).where(requests.c.site_id==sid,requests.c.email==email).values(status='approved'))
            log(c,u,sid,'user_created',{'email':email})
        return {'email':email,'temporary_password':pw,'role':role,'change_password_required_by_operator':True}

    @app.patch('/api/admin/sites/{sid}/access-requests/{rid}')
    def review_access_request(sid:str,rid:str,body:dict,request:Request):
        with engine.begin() as c:
            u,_=identify(request,c,True);require_scope(c,u,sid)
            if u['role']=='agency':fail('FORBIDDEN_ROLE',403)
            item=set_request_status(c,sid,rid,body.get('status'))
            log(c,u,sid,'access_request_'+item['status'],{'request_id':rid,'email':item['email']})
            return item

    @app.get('/api/admin/sites/{sid}/devices')
    def admin_devices(sid:str,request:Request):
        with engine.connect() as c:
            u,_=identify(request,c);require_scope(c,u,sid)
            return {'devices':list_devices(c,sid)}

    @app.post('/api/admin/sites/{sid}/devices')
    def add_device(sid:str,body:dict,request:Request):
        with engine.begin() as c:
            u,_=identify(request,c,True);require_scope(c,u,sid)
            if u['role']=='agency' and body.get('device_type')=='operator':fail('FORBIDDEN_ROLE',403)
            token=secrets.token_urlsafe(32)
            did=create_device(c,sid,body.get('name'),body.get('device_type'),token,body.get('app_version',''),body.get('metadata'))
            log(c,u,sid,'device_created',{'device_id':did,'device_type':body.get('device_type')})
            return {'id':did,'device_token':token,'token_shown_once':True}

    @app.patch('/api/admin/sites/{sid}/devices/{did}')
    def patch_device(sid:str,did:str,body:dict,request:Request):
        with engine.begin() as c:
            u,_=identify(request,c,True);require_scope(c,u,sid)
            d=row(c,devices,'id',did)
            if not d or d['site_id']!=sid:fail('DEVICE_NOT_FOUND',404)
            result=update_device(c,did,status=body.get('status'),name=body.get('name'),app_version=body.get('app_version'),metadata_json=body.get('metadata'))
            log(c,u,sid,'device_updated',{'device_id':did,'status':result['status']})
            return {'id':did,'status':result['status'],'name':result['name']}

    @app.post('/api/device/heartbeat')
    def heartbeat_endpoint(body:dict,request:Request):
        raw=request.headers.get('X-PulseX-Device-Token','')
        with engine.begin() as c:
            return device_heartbeat(c,raw,body)

    @app.patch('/api/admin/sites/{sid}/users/{user_id}')
    def update_site_user(sid:str,user_id:str,body:dict,request:Request):
        with engine.begin() as c:
            actor,_=identify(request,c,True);require_scope(c,actor,sid)
            if actor['role']=='agency':fail('FORBIDDEN_ROLE',403)
            target=row(c,users,'id',user_id)
            if not target or target['scope_id']!=sid:fail('USER_NOT_FOUND',404)
            active=body.get('active')
            if active not in (True,False,0,1):fail('USER_STATUS_INVALID')
            c.execute(update(users).where(users.c.id==user_id).values(active=1 if active else 0))
            if not active:c.execute(delete(sessions).where(sessions.c.user_id==user_id))
            log(c,actor,sid,'user_status_changed',{'user_id':user_id,'active':bool(active)})
            return {'id':user_id,'active':bool(active),'sessions_revoked':not bool(active)}

    @app.get('/api/admin/organizations')
    def list_organizations(request:Request):
        with engine.connect() as c:
            u,_=identify(request,c); rows=c.execute(select(organizations).order_by(organizations.c.name)).mappings().all();out=[]
            for o in rows:
                if not organization_visible(c,u,o['id']):continue
                ps=c.execute(select(event_participations).where(event_participations.c.organization_id==o['id'])).mappings().all()
                out.append({**dict(o),'participations':[dict(x) for x in ps]})
            return {'organizations':out}

    @app.post('/api/admin/organizations')
    def create_organization(body:dict,request:Request):
        with engine.begin() as c:
            u,_=identify(request,c,True)
            if u['role'] not in ('platform','organizer'):fail('FORBIDDEN_ROLE',403)
            name=text(body.get('name'),200,True);slug=text(body.get('slug'),80,True).lower()
            if not re.fullmatch(r'[a-z0-9][a-z0-9-]{1,70}',slug):fail('SLUG_INVALID')
            if row(c,organizations,'slug',slug):fail('ORGANIZATION_SLUG_EXISTS',409)
            oid=uid();profile={'description':text(body.get('description'),3000),'logo':'','primary':'#176B73','website':''}
            c.execute(insert(organizations).values(id=oid,slug=slug,name=name,profile=profile,status='active',created_at=now()));log(c,u,u['scope_id'],'organization_created',{'organization_id':oid,'name':name})
            if u['role']=='organizer':
                event=site_row(c,u['scope_id']); agency_slug=(slug+'-'+event['slug'])[:70]
                if row(c,sites,'slug',agency_slug):agency_slug=(slug+'-'+secrets.token_hex(3))[:70]
                sid=uid();cfg=default_config(name,'agency');cfg['description']=profile['description']
                c.execute(insert(sites).values(id=sid,parent_id=event['id'],event_id=event['id'],kind='agency',slug=agency_slug,draft=cfg,draft_rev=1,published_version=0))
                c.execute(insert(event_participations).values(id=uid(),event_id=event['id'],organization_id=oid,agency_site_id=sid,participation_type=text(body.get('participation_type') or 'exhibitor',40),status='active',booth=text(body.get('booth'),120),summary=text(body.get('summary'),2000),services=[],valid_from=event['draft'].get('start') or '',valid_until=event['draft'].get('end') or '',created_at=now()))
            return {'id':oid,'name':name,'slug':slug}

    @app.get('/api/admin/events/{event_id}/participations')
    def list_participations(event_id:str,request:Request):
        with engine.connect() as c:
            u,_=identify(request,c); event=require_scope(c,u,event_id)
            if event['kind']!='event':fail('EVENT_REQUIRED')
            rows=c.execute(select(event_participations,organizations.c.name,organizations.c.slug).join(organizations,event_participations.c.organization_id==organizations.c.id).where(event_participations.c.event_id==event_id)).mappings().all()
            return {'participations':[dict(x) for x in rows]}

    @app.post('/api/admin/events/{event_id}/participations')
    def add_participation(event_id:str,body:dict,request:Request):
        with engine.begin() as c:
            u,_=identify(request,c,True); event=require_scope(c,u,event_id)
            if event['kind']!='event' or u['role'] not in ('platform','organizer'):fail('FORBIDDEN_ROLE',403)
            oid=text(body.get('organization_id'),64,True); org=row(c,organizations,'id',oid)
            if not org:fail('ORGANIZATION_NOT_FOUND',404)
            if c.execute(select(event_participations).where(event_participations.c.event_id==event_id,event_participations.c.organization_id==oid)).first():fail('PARTICIPATION_EXISTS',409)
            agency_slug=(org['slug']+'-'+event['slug'])[:70]
            if row(c,sites,'slug',agency_slug):agency_slug=(org['slug']+'-'+secrets.token_hex(3))[:70]
            sid=uid();cfg=default_config(org['name'],'agency');cfg['description']=org['profile'].get('description','');cfg['logo']=org['profile'].get('logo','');cfg['primary']=org['profile'].get('primary','#176B73')
            c.execute(insert(sites).values(id=sid,parent_id=event_id,event_id=event_id,kind='agency',slug=agency_slug,draft=normalize_config(cfg),draft_rev=1,published_version=0))
            pid=uid();c.execute(insert(event_participations).values(id=pid,event_id=event_id,organization_id=oid,agency_site_id=sid,participation_type=text(body.get('participation_type') or 'exhibitor',40),status='active',booth=text(body.get('booth'),120),summary=text(body.get('summary'),2000),services=[],valid_from=event['draft'].get('start') or '',valid_until=event['draft'].get('end') or '',created_at=now()));log(c,u,event_id,'participation_added',{'organization_id':oid,'agency_site_id':sid})
            return {'id':pid,'agency_site_id':sid}

    def _can_manage_org_people(c,u,oid):
        if u['role'] in ('platform','organizer') and organization_visible(c,u,oid):
            return True
        role=c.execute(select(memberships.c.role).where(memberships.c.user_id==u['id'],memberships.c.organization_id==oid,memberships.c.status=='active')).scalar()
        return role in ('owner','admin')

    @app.get('/api/admin/organizations/{oid}/people')
    def list_organization_people(oid:str,request:Request):
        with engine.connect() as c:
            u,_=identify(request,c);org=row(c,organizations,'id',oid)
            if not org or not organization_visible(c,u,oid):fail('ORGANIZATION_NOT_FOUND',404)
            q=select(organization_people).where(organization_people.c.organization_id==oid).order_by(organization_people.c.name)
            return {'people':[dict(x) for x in c.execute(q).mappings()]}

    @app.post('/api/admin/organizations/{oid}/people')
    def add_organization_person(oid:str,body:dict,request:Request):
        with engine.begin() as c:
            u,_=identify(request,c,True);org=row(c,organizations,'id',oid)
            if not org or not organization_visible(c,u,oid):fail('ORGANIZATION_NOT_FOUND',404)
            if not _can_manage_org_people(c,u,oid):fail('FORBIDDEN_ROLE',403)
            email=text(body.get('email'),200).lower(); phone=text(body.get('phone'),60)
            if email and not re.fullmatch(r'[^\s@]+@[^\s@]+\.[^\s@]+',email):fail('EMAIL_INVALID')
            person_role=body.get('person_role') if body.get('person_role') in ('owner','manager','member','representative','staff','speaker') else 'member'
            pid=uid(); c.execute(insert(organization_people).values(id=pid,organization_id=oid,user_id=None,name=text(body.get('name'),160,True),email=email,phone=phone,job_title=text(body.get('job_title'),160),person_role=person_role,public_visible=1 if boolean(body.get('public_visible',False)) else 0,status='active',created_at=now()))
            log(c,u,u['scope_id'],'organization_person_added',{'organization_id':oid,'person_id':pid,'has_account':False})
            return {'id':pid,'organization_id':oid,'has_account':False}

    @app.patch('/api/admin/organizations/{oid}/people/{pid}')
    def update_organization_person(oid:str,pid:str,body:dict,request:Request):
        with engine.begin() as c:
            u,_=identify(request,c,True);org=row(c,organizations,'id',oid);person=row(c,organization_people,'id',pid)
            if not org or not person or person['organization_id']!=oid or not organization_visible(c,u,oid):fail('PERSON_NOT_FOUND',404)
            if not _can_manage_org_people(c,u,oid):fail('FORBIDDEN_ROLE',403)
            vals={}
            for key,limit in [('name',160),('email',200),('phone',60),('job_title',160)]:
                if key in body:vals[key]=text(body.get(key),limit,key=='name')
            if 'email' in vals and vals['email'] and not re.fullmatch(r'[^\s@]+@[^\s@]+\.[^\s@]+',vals['email']):fail('EMAIL_INVALID')
            if body.get('person_role') in ('owner','manager','member','representative','staff','speaker'):vals['person_role']=body['person_role']
            if body.get('status') in ('active','inactive','archived'):vals['status']=body['status']
            if 'public_visible' in body:vals['public_visible']=1 if boolean(body.get('public_visible')) else 0
            if not vals:fail('NO_CHANGES')
            c.execute(update(organization_people).where(organization_people.c.id==pid).values(**vals));log(c,u,u['scope_id'],'organization_person_updated',{'organization_id':oid,'person_id':pid,**vals})
            return {'id':pid,**vals}

    @app.post('/api/admin/organizations/{oid}/people/{pid}/account')
    def create_person_account(oid:str,pid:str,body:dict,request:Request):
        with engine.begin() as c:
            u,_=identify(request,c,True);org=row(c,organizations,'id',oid);person=row(c,organization_people,'id',pid)
            if not org or not person or person['organization_id']!=oid or not organization_visible(c,u,oid):fail('PERSON_NOT_FOUND',404)
            if not _can_manage_org_people(c,u,oid):fail('FORBIDDEN_ROLE',403)
            if person['user_id']:
                existing=row(c,users,'id',person['user_id']);return {'email':existing['email'],'temporary_password':None,'already_linked':True,'organization_id':oid}
            email=text(body.get('email') or person['email'],200,True).lower()
            if not re.fullmatch(r'[^\s@]+@[^\s@]+\.[^\s@]+',email):fail('EMAIL_INVALID')
            existing=row(c,users,'email',email);pw=None
            if existing:user_id=existing['id']
            else:
                pw=new_temporary_password();user_id=uid();scope=c.execute(select(event_participations.c.agency_site_id).where(event_participations.c.organization_id==oid,event_participations.c.status=='active').order_by(event_participations.c.created_at.desc())).scalar()
                c.execute(insert(users).values(id=user_id,email=email,name=person['name'],role='agency',scope_id=scope,password_hash=password_hash(pw),active=1,must_change_password=1))
            role=body.get('role') if body.get('role') in ('owner','admin','editor','analyst') else 'editor'
            if not c.execute(select(memberships).where(memberships.c.user_id==user_id,memberships.c.organization_id==oid)).first():c.execute(insert(memberships).values(user_id=user_id,organization_id=oid,role=role,status='active',created_at=now()))
            c.execute(update(organization_people).where(organization_people.c.id==pid).values(user_id=user_id,email=email))
            log(c,u,u['scope_id'],'organization_person_account_created',{'organization_id':oid,'person_id':pid,'email':email,'new_account':bool(pw)})
            return {'email':email,'temporary_password':pw,'already_linked':False,'organization_id':oid,'permanent_membership':True}

    @app.post('/api/admin/organizations/{oid}/users')
    def add_organization_user(oid:str,body:dict,request:Request):
        with engine.begin() as c:
            u,_=identify(request,c,True);org=row(c,organizations,'id',oid)
            if not org or not organization_visible(c,u,oid):fail('ORGANIZATION_NOT_FOUND',404)
            if u['role']=='agency' and not c.execute(select(memberships).where(memberships.c.user_id==u['id'],memberships.c.organization_id==oid,memberships.c.role=='owner')).first():fail('FORBIDDEN_ROLE',403)
            email=text(body.get('email'),200,True).lower()
            if not re.fullmatch(r'[^\s@]+@[^\s@]+\.[^\s@]+',email):fail('EMAIL_INVALID')
            existing=row(c,users,'email',email);pw=None
            if existing:user_id=existing['id']
            else:
                pw=new_temporary_password();user_id=uid();scope=c.execute(select(event_participations.c.agency_site_id).where(event_participations.c.organization_id==oid).order_by(event_participations.c.created_at.desc())).scalar()
                c.execute(insert(users).values(id=user_id,email=email,name=text(body.get('name'),160,True),role='agency',scope_id=scope,password_hash=password_hash(pw),active=1,must_change_password=1))
            if not c.execute(select(memberships).where(memberships.c.user_id==user_id,memberships.c.organization_id==oid)).first():c.execute(insert(memberships).values(user_id=user_id,organization_id=oid,role=body.get('role') if body.get('role') in ('owner','admin','editor','analyst') else 'admin',status='active',created_at=now()))
            log(c,u,u['scope_id'],'organization_user_added',{'organization_id':oid,'email':email})
            return {'email':email,'temporary_password':pw,'organization_id':oid,'permanent_membership':True}

    @app.get('/api/admin/organizations/{oid}/members')
    def list_organization_members(oid:str,request:Request):
        with engine.connect() as c:
            u,_=identify(request,c);org=row(c,organizations,'id',oid)
            if not org or not organization_visible(c,u,oid):fail('ORGANIZATION_NOT_FOUND',404)
            q=select(memberships,users.c.email,users.c.name,users.c.active).join(users,memberships.c.user_id==users.c.id).where(memberships.c.organization_id==oid)
            return {'members':[dict(x) for x in c.execute(q).mappings()]}

    @app.patch('/api/admin/organizations/{oid}/members/{member_id}')
    def update_organization_member(oid:str,member_id:str,body:dict,request:Request):
        with engine.begin() as c:
            u,_=identify(request,c,True);org=row(c,organizations,'id',oid)
            if not org or not organization_visible(c,u,oid):fail('ORGANIZATION_NOT_FOUND',404)
            is_owner=bool(c.execute(select(memberships).where(memberships.c.user_id==u['id'],memberships.c.organization_id==oid,memberships.c.role=='owner',memberships.c.status=='active')).first())
            if u['role'] not in ('platform','organizer') and not is_owner:fail('FORBIDDEN_ROLE',403)
            mem=c.execute(select(memberships).where(memberships.c.user_id==member_id,memberships.c.organization_id==oid)).mappings().first()
            if not mem:fail('MEMBERSHIP_NOT_FOUND',404)
            vals={}
            if body.get('role') in ('owner','admin','editor','analyst'):vals['role']=body['role']
            if body.get('status') in ('active','suspended','archived'):vals['status']=body['status']
            if not vals:fail('NO_CHANGES')
            c.execute(update(memberships).where(memberships.c.user_id==member_id,memberships.c.organization_id==oid).values(**vals));log(c,u,u['scope_id'],'membership_updated',{'organization_id':oid,'member_id':member_id,**vals})
            return {'ok':True,**vals}

    @app.patch('/api/admin/participations/{pid}')
    def update_participation(pid:str,body:dict,request:Request):
        with engine.begin() as c:
            u,_=identify(request,c,True);part=row(c,event_participations,'id',pid)
            if not part:fail('PARTICIPATION_NOT_FOUND',404)
            event=require_scope(c,u,part['event_id'])
            if event['kind']!='event' or u['role'] not in ('platform','organizer'):fail('FORBIDDEN_ROLE',403)
            vals={}
            if body.get('status') in ('pending','active','suspended','expired','archived'):vals['status']=body['status']
            if body.get('participation_type') in ('exhibitor','sponsor','partner','speaker','media','staff','vendor'):vals['participation_type']=body['participation_type']
            for key,limit in [('booth',120),('summary',2000),('valid_from',64),('valid_until',64)]:
                if key in body:vals[key]=text(body.get(key),limit)
            if not vals:fail('NO_CHANGES')
            c.execute(update(event_participations).where(event_participations.c.id==pid).values(**vals));log(c,u,part['event_id'],'participation_updated',{'participation_id':pid,**vals})
            return {'ok':True,**vals}

    @app.get('/api/admin/audit')
    def audit_log(request:Request,site_id:str|None=None,limit:int=200):
        with engine.connect() as c:
            u,_=identify(request,c); limit=max(1,min(limit,500)); stmt=select(audit).order_by(audit.c.at.desc()).limit(limit)
            if site_id:
                require_scope(c,u,site_id);stmt=stmt.where(audit.c.site_id==site_id)
            elif u['role']!='platform':
                manageable=[x['id'] for x in c.execute(select(sites)).mappings() if can_manage(c,u,x)]
                stmt=stmt.where(audit.c.site_id.in_(manageable or ['__none__']))
            return {'entries':[dict(x) for x in c.execute(stmt).mappings()]}

    @app.post('/api/admin/sites/{sid}/imports/preview')
    def import_preview(sid:str,body:dict,request:Request):
        with engine.begin() as c:
            u,_=identify(request,c,True);s=require_scope(c,u,sid)
            recs,errors,unknown=parse_import(body)
            existing={r['code'] for r in s['draft']['records']}
            for r in recs:
                if r['code'] in existing:errors.append({'sheet':'','row':0,'error':'CODE_EXISTS:'+r['code']})
            if not errors:
                try:normalize_config({**s['draft'],'records':s['draft']['records']+recs})
                except HTTPException as e:errors.append({'sheet':'','row':0,'error':e.detail})
            iid=uid();c.execute(insert(imports).values(id=iid,site_id=sid,user_id=u['id'],base_rev=s['draft_rev'],records=recs,errors=errors,state='preview',created_at=now()))
            return {'id':iid,'records':recs,'errors':errors,'ignored_sheets':unknown,'base_rev':s['draft_rev'],'valid':not errors}

    @app.post('/api/admin/sites/{sid}/imports/{iid}/commit')
    def import_commit(sid:str,iid:str,request:Request):
        with engine.begin() as c:
            u,_=identify(request,c,True);s=require_scope(c,u,sid);job=row(c,imports,'id',iid)
            if not job or job['site_id']!=sid or job['user_id']!=u['id']:fail('IMPORT_NOT_FOUND',404)
            if job['state']=='committed':return {'status':'already_committed','added':len(job['records'])}
            if job['errors']:fail('IMPORT_HAS_ERRORS')
            if job['base_rev']!=s['draft_rev']:fail('DRAFT_CHANGED_REPREVIEW_REQUIRED',409)
            cfg=normalize_config({**s['draft'],'records':s['draft']['records']+job['records']})
            result=c.execute(update(sites).where(sites.c.id==sid,sites.c.draft_rev==job['base_rev']).values(draft=cfg,draft_rev=s['draft_rev']+1))
            if result.rowcount!=1:fail('DRAFT_CHANGED_REPREVIEW_REQUIRED',409)
            c.execute(update(imports).where(imports.c.id==iid).values(state='committed'));log(c,u,sid,'import_committed',{'job':iid,'records':len(job['records'])})
        return {'status':'committed','added':len(job['records'])}

    @app.post('/api/admin/media')
    def upload_media(body:dict,request:Request):
        with engine.connect() as c:identify(request,c,True)
        try:data=base64.b64decode(body.get('base64',''),validate=True)
        except Exception:fail('MEDIA_INVALID')
        if not data or len(data)>4*1024*1024:fail('MEDIA_MAX_4_MB')
        ext=''
        if data.startswith(b'\x89PNG\r\n\x1a\n'):ext='png'
        elif data.startswith(b'\xff\xd8\xff'):ext='jpg'
        elif data.startswith(b'RIFF') and data[8:12]==b'WEBP':ext='webp'
        elif len(data)>12 and data[4:8]==b'ftyp':ext='mp4'
        if not ext:fail('MEDIA_PNG_JPEG_WEBP_MP4_ONLY')
        name=hashlib.sha256(data).hexdigest()+'.'+ext;(media_dir/name).write_bytes(data)
        return {'url':'/media/'+name,'bytes':len(data),'type':'video' if ext=='mp4' else 'image'}


    @app.post('/api/collect')
    def collect(body:dict):
        entries=body.get('items')
        if not isinstance(entries,list) or not entries or len(entries)>50:fail('BATCH_1_TO_50_ITEMS')
        out=[]
        for b in entries:
            sid=b.get('id','') if isinstance(b,dict) else ''
            try:
                with engine.begin() as c:
                    old=row(c,submissions,'id',sid)
                    if old:
                        if old['fingerprint']!=digest(canon(b)):fail('IDEMPOTENCY_BODY_CONFLICT',409)
                        out.append({'id':sid,'status':'duplicate'});continue
                    clean=validate_submission(c,b)
                    c.execute(insert(submissions).values(**clean));out.append({'id':sid,'status':'accepted'})
            except HTTPException as e:out.append({'id':sid,'status':'rejected','error':e.detail})
            except IntegrityError:
                with engine.connect() as c:
                    old=row(c,submissions,'id',sid)
                    if old and old['fingerprint']==digest(canon(b)):out.append({'id':sid,'status':'duplicate'})
                    else:out.append({'id':sid,'status':'rejected','error':'ALREADY_VOTED_OR_RECORDED'})
        return {'receipts':out,'server_time':now()}


    @app.get('/api/admin/sites/{sid}/metrics')
    def admin_metrics(sid:str,request:Request):
        with engine.connect() as c:
            u,_=identify(request,c);s=require_scope(c,u,sid);return build_metrics(c,s,True)

    @app.get('/api/public/site/{slug}/results')
    def public_results(slug:str):
        with engine.connect() as c:
            s=row(c,sites,'slug',slug)
            if not s:fail('SITE_NOT_FOUND',404)
            return build_public_poll_results(c,s)

    @app.get('/api/admin/sites/{sid}/export')
    def export(sid:str,request:Request):
        import csv
        with engine.begin() as c:
            u,_=identify(request,c);require_scope(c,u,sid)
            # Organizer aggregates do not imply access to exhibitors' raw contact details.
            entries=c.execute(select(submissions).where(submissions.c.site_id==sid)).mappings().all();log(c,u,sid,'raw_export',{'rows':len(entries)})
        buff=io.StringIO();w=csv.writer(buff);columns=['id','site_id','version','kind','source','target','payload','client_time','received_at'];w.writerow(columns)
        for entry in entries:
            vals=[]
            for key in columns:
                val=canon(entry[key]) if isinstance(entry[key],dict) else str(entry[key] or '')
                if re.match(r'^[\s\x00-\x1f]*[=+@-]',val):val="'"+val
                vals.append(val)
            w.writerow(vals)
        return Response('\ufeff'+buff.getvalue(),media_type='text/csv; charset=utf-8',headers={'Content-Disposition':f'attachment; filename="pulsex-{sid}-responses.csv"'})

    @app.get('/api/admin/sites/{sid}/qr')
    def qr(sid:str,request:Request):
        import qrcode
        with engine.connect() as c:
            u,_=identify(request,c);s=require_scope(c,u,sid);slug=s['slug']
            if s['kind']=='platform':path='/'
            elif s['kind']=='event':path='/e/'+slug
            else:path='/e/'+site_row(c,s['event_id'])['slug']+'/p/'+slug
        link=public_origin+path+'?source=qr';image=qrcode.make(link);buff=io.BytesIO();image.save(buff,format='PNG')
        return Response(buff.getvalue(),media_type='image/png')

    @app.get('/media/{name}')
    def media(name:str):
        if not re.fullmatch(r'[a-f0-9]{64}\.(png|jpg|webp|mp4)|[a-z-]+-demo\.svg',name):fail('MEDIA_NOT_FOUND',404)
        p=media_dir/name
        if not p.exists():p=ROOT/'web/media'/name
        if not p.is_file():fail('MEDIA_NOT_FOUND',404)
        return FileResponse(p,headers={'Cache-Control':'public, max-age=86400'})

    @app.get('/templates/{name}')
    def template(name:str):
        if not re.fullmatch(r'[A-Za-z0-9_.-]+\.(xlsx|csv)',name):fail('TEMPLATE_NOT_FOUND',404)
        p=ROOT/'templates'/name
        if not p.is_file():fail('TEMPLATE_NOT_FOUND',404)
        return FileResponse(p,filename=name)

    @app.get('/sw.js')
    def sw():return FileResponse(ROOT/'web/sw.js',media_type='application/javascript',headers={'Cache-Control':'no-cache','Service-Worker-Allowed':'/'})
    app.mount('/assets',StaticFiles(directory=ROOT/'web'),name='assets')
    @app.get('/{path:path}')
    def spa(path:str):
        if path.startswith(('api/','media/','templates/')):fail('NOT_FOUND',404)
        return FileResponse(ROOT/'web/index.html',headers={'Cache-Control':'no-cache'})
    return app
