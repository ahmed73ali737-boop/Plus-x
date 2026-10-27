"""Self-service certificate HTTP adapter; legacy certificate routes remain separate."""
from pathlib import Path
from types import SimpleNamespace
import io,logging,os,re
from datetime import datetime
from fastapi import Request
from fastapi.exceptions import RequestValidationError
from fastapi.exception_handlers import request_validation_exception_handler
from fastapi.responses import Response,JSONResponse,FileResponse
from sqlalchemy import select,func,update,and_,or_
from sqlalchemy.exc import IntegrityError
import qrcode
from app.domain import fail
from app.self_certificates_db import links,requests,jobs,certificates,exports,assets
from app.application import self_certificate_repository as repo,self_certificate_links as linksvc,self_certificate_participants as people
from app.application import self_certificate_rendering as rendering,self_certificate_fonts as fonts,self_certificate_branding as brand
from app.application import self_certificate_delivery as delivery,self_certificate_worker as worker,self_certificate_exports as exporter
from app.application.self_certificate_access import require_library,live_principal,can_manage_library,eligible_events,require_capability,owner_can_accept
from app.application.self_certificate_assets import ingest_asset
from app.application.self_certificate_crypto import Keyring,REMEMBER_SECONDS
from app.application.self_certificate_storage import CertificateStore,cleanup_unreferenced
from app.application.self_certificate_limits import consume
from app.core.certificate_features import certificate_features

ADMIN='/api/self-certificates'
PUBLIC='/api/public/self-certificates'

class RedactCertificateAccess(logging.Filter):
    def filter(self,record):
        if isinstance(record.args,tuple):
            record.args=tuple(re.sub(r'(/(?:api/public/self-certificates|certificates)/receive/)[^ /?]+',r'\1[redacted]',v) if isinstance(v,str) else v for v in record.args)
        return True

def install_self_certificate_routes(app,engine,settings,identify,log):
    store=CertificateStore(settings.data_dir/'private-certificates')
    keypath=Path(os.environ.get('PX_SELF_CERTIFICATE_KEYRING_PATH') or store.root/'keyring.json')
    origin=settings.public_origin
    def keys(create=False):
        allow_create=False
        if not keypath.exists() and create:
            with engine.connect() as conn:
                existing=conn.execute(select(links.c.id).limit(1)).first() or conn.execute(select(certificates.c.id).limit(1)).first()
            allow_create=not existing and certificate_features().admin_enabled
        return Keyring(keypath,allow_create=allow_create)
    app.state.self_certificate_runtime=SimpleNamespace(store=store,keys=keys,
        generate=lambda:worker.process_one(engine,store,keys),export=lambda:exporter.process_export(engine,store),
        expire_exports=lambda:exporter.expire_exports(engine,store),
        cleanup_assets=lambda:cleanup_unreferenced(engine,store))
    runtime=app.state.self_certificate_runtime
    runtime.keypath=keypath
    from app.application.self_certificate_health import CertificateReadiness
    from app.application import self_certificate_metrics as metrics
    runtime.readiness=CertificateReadiness(engine,store,keys,runtime)
    telemetry=getattr(app.state,'g_observability',None)
    if telemetry is not None:metrics.configure(telemetry.metrics)
    logging.getLogger('uvicorn.access').addFilter(RedactCertificateAccess())

    @app.exception_handler(RequestValidationError)
    async def sanitized_validation(request,error):
        if request.scope.get('path','').startswith((ADMIN,PUBLIC)):
            return JSONResponse({'detail':'CERTIFICATE_INPUT_INVALID'},status_code=422)
        return await request_validation_exception_handler(request,error)

    def account(conn,request,write=False,library=False):
        user,_=identify(request,conn,write)
        if library:
            features=certificate_features()
            if not features.admin_enabled:fail('CERTIFICATE_ADMIN_PAUSED',409)
            if not features.account_allowed(user['id']):fail('CERTIFICATE_PILOT_UNAVAILABLE',409)
            return require_library(conn,user)
        return live_principal(conn,user)

    def rate(request,scope,value,limit=60):
        consume(engine,scope,value,limit)
        ip=request.client.host if request.client else 'unknown'
        consume(engine,'certificate-ip',ip,120000)

    def model_payload(body):
        if not isinstance(body,dict) or set(body)-{'name','background_asset_id','stamp_asset_id','config','row_version','idempotency_key'} or not isinstance(body.get('name'),str) or not isinstance(body.get('background_asset_id'),str):
            fail('MODEL_INPUT_INVALID')
        return dict(name=body['name'],background_asset_id=body['background_asset_id'],stamp_asset_id=body.get('stamp_asset_id'),config=body.get('config'),idempotency_key=body.get('idempotency_key'))

    @app.get(ADMIN+'/access')
    def access(request:Request):
        with engine.connect() as conn:
            user=account(conn,request)
            features=certificate_features()
            enabled=features.admin_enabled and features.account_allowed(user['id'])
            has_history=bool(conn.execute(select(requests.c.id).where(requests.c.owner_account_id==user["id"]).limit(1)).first() or conn.execute(select(links.c.id).where(links.c.owner_account_id==user["id"]).limit(1)).first())
            return dict(has_history=has_history,enabled=enabled,can_manage=enabled and can_manage_library(conn,user),can_read_history=True,
                events=[dict(id=e['id'],name=(e.get('draft') or {}).get('title') or e.get('slug')) for e in eligible_events(conn,user) if features.link_allowed(user['id'],e['id'])] if enabled else [])

    @app.get(ADMIN+'/models')
    def models(request:Request,offset:int=0,limit:int=30,q:str=''):
        with engine.connect() as conn:return repo.list_models(conn,account(conn,request,library=True),offset,limit,q=q)

    @app.get(ADMIN+'/models/{ident}')
    def model(ident:str,request:Request):
        with engine.connect() as conn:
            user=account(conn,request,library=True);row=repo.get_model(conn,user,ident)
            return {**row,'revision':repo.get_revision(conn,user,row['current_revision_id'])}

    @app.post(ADMIN+'/models')
    def add_model(body:dict,request:Request):
        with engine.begin() as conn:
            user=account(conn,request,True,True);payload=model_payload(body)
            result=repo.save_model(conn,user,**payload);log(conn,user,None,'self_certificate_model_created',{'model_id':result['id']})
            return result

    @app.put(ADMIN+'/models/{ident}')
    def edit_model(ident:str,body:dict,request:Request):
        with engine.begin() as conn:
            user=account(conn,request,True,True);payload=model_payload(body)
            result=repo.save_model(conn,user,model_id=ident,row_version=body.get('row_version'),**payload)
            log(conn,user,None,'self_certificate_model_updated',{'model_id':ident});return result

    @app.delete(ADMIN+'/models/{ident}')
    def delete_model(ident:str,request:Request,row_version:int):
        with engine.begin() as conn:
            user=account(conn,request,True,True);repo.delete_model(conn,user,ident,row_version)
            log(conn,user,None,'self_certificate_model_deleted',{'model_id':ident});return {'ok':True}

    @app.post(ADMIN+'/assets')
    async def upload(request:Request,kind:str='background'):
        with engine.connect() as conn:user=account(conn,request,True,True)
        rate(request,'certificate-upload',user['id'],20)
        data=await request.body()
        from starlette.concurrency import run_in_threadpool
        def perform():
            with engine.begin() as conn:
                current=account(conn,request,True,True)
                row=ingest_asset(conn,current,store,data,kind)
                return {k:row[k] for k in ('id','kind','width','height','mime','size_bytes','source_kind','source_metadata')}
        return await run_in_threadpool(perform)

    @app.get(ADMIN+'/assets/{ident}')
    def get_asset(ident:str,request:Request):
        with engine.connect() as conn:
            user=account(conn,request,library=True);asset=repo.owned_asset(conn,user,ident)
            if asset['kind'] not in ('background','stamp'):fail('NOT_FOUND',404)
        return FileResponse(store.verified_path(asset),media_type=asset['mime'])

    @app.get(ADMIN+'/design-options')
    def options(request:Request,background_id:str,has_stamp:bool=False):
        with engine.connect() as conn:
            user=account(conn,request,library=True);asset=repo.owned_asset(conn,user,background_id,'background')
        width,height=asset['width'],asset['height']
        return dict(width=width,height=height,fonts=fonts.choices(),default_config=rendering.default_config(width,height,has_stamp),
            branding_manifest=brand.system_profile(width,height),background_url=ADMIN+'/assets/'+background_id)

    @app.post(ADMIN+'/preview')
    def preview(body:dict,request:Request):
        if set(body)!={'background_asset_id','stamp_asset_id','config','sample_name'}:fail('PREVIEW_INPUT_INVALID')
        with engine.connect() as conn:
            user=account(conn,request,True,True)
            background=repo.owned_asset(conn,user,body['background_asset_id'],'background')
            stamp=repo.owned_asset(conn,user,body['stamp_asset_id'],'stamp') if body['stamp_asset_id'] else None
        rate(request,'certificate-preview',user['id'],60)
        branding=brand.system_profile(background['width'],background['height'])
        config,font_manifest=rendering.validate_config(body['config'],background['width'],background['height'],stamp is not None,branding)
        revision=dict(schema_version=2,renderer_version=rendering.VERSION,config=config,font_manifest=font_manifest,branding_manifest=branding)
        layout=rendering.fit_name(body['sample_name'],config,font_manifest,branding)
        image=worker.render_isolated(store,revision,background,stamp,layout)
        return Response(image,media_type='image/png')

    @app.get(ADMIN+'/branding/rts.png')
    def branding_asset():
        return Response(brand.verified_bytes(brand.LOGO_PATH,brand.LOGO_SHA256,'BRANDING_ASSET_UNAVAILABLE'),media_type='image/png')

    @app.post(ADMIN+'/links')
    def add_link(body:dict,request:Request):
        with engine.connect() as conn:account(conn,request,True,True)
        keyring=keys(create=True)
        try:
            with engine.begin() as conn:
                user=account(conn,request,True,True)
                result=linksvc.create(conn,user,keyring,origin,body);log(conn,user,result['event_id'],'self_certificate_link_created',{'link_id':result['id']});return result
        except IntegrityError:
            with engine.begin() as conn:return linksvc.create(conn,account(conn,request,True,True),keyring,origin,body)

    @app.get(ADMIN+'/links')
    def list_links(request:Request,offset:int=0,limit:int=30):
        with engine.connect() as conn:
            user=account(conn,request);repo.page(offset,limit)
            if not conn.execute(select(links.c.id).where(links.c.owner_account_id==user["id"]).limit(1)).first():return dict(items=[],total=0)
            return linksvc.list_links(conn,user,keys(),origin,offset,limit)

    @app.post(ADMIN+'/links/{ident}/state')
    def link_state(ident:str,body:dict,request:Request):
        keyring=keys()
        with engine.begin() as conn:
            user=account(conn,request,True)
            if body.get('status')=='active' and not certificate_features().admin_enabled:fail('CERTIFICATE_ADMIN_PAUSED',409)
            if body.get('status')=='active':
                owned=linksvc.get_owned(conn,user,ident)
                if not certificate_features().link_allowed(user['id'],owned['event_id']):fail('CERTIFICATE_PILOT_UNAVAILABLE',409)
            result=linksvc.set_state(conn,user,ident,body,keyring,origin)
            log(conn,user,result['event_id'],'self_certificate_link_state',{'link_id':ident,'status':result['status']});return result

    @app.get(ADMIN+'/links/{ident}/qr')
    def qr(ident:str,request:Request):
        keyring=keys()
        with engine.connect() as conn:
            row=linksvc.get_owned(conn,account(conn,request),ident)
            url=linksvc.projection(row,keyring,origin)['request_url']
        qr=qrcode.QRCode(error_correction=qrcode.constants.ERROR_CORRECT_Q,box_size=12,border=4);qr.add_data(url);qr.make(fit=True)
        out=io.BytesIO();qr.make_image(fill_color='black',back_color='white').save(out,format='PNG')
        return Response(out.getvalue(),media_type='image/png',headers={'Content-Disposition':'attachment; filename="certificate-request-qr.png"'})

    @app.post(PUBLIC+'/request/{token}/prepare')
    def prepare(token:str,body:dict,request:Request):
        if set(body)!={'browser_seed'}:fail('BROWSER_INPUT_INVALID')
        keyring=keys();ip=request.client.host if request.client else 'unknown'
        consume(engine,'certificate-prepare',ip,3000)
        with engine.begin() as conn:
            link=linksvc.get_public(conn,keyring,token)
            browser,cookie=people.prepare_browser(conn,keyring,body['browser_seed'],request.cookies.get('px_certificate_browser'))
            mine=people.find_request(conn,link['id'],browser['id'])
            data=dict(event_name=link['event_name_snapshot'],can_request=certificate_features().accept_new_requests and certificate_features().link_allowed(link['owner_account_id'],link['event_id']) and link['status']=='active' and owner_can_accept(conn,link['owner_account_id'],link['event_id']),
                consent_text=people.CONSENT_TEXT,request_nonce=keyring.nonce(browser['id'],link['id']),mine=people.state(conn,mine,keyring,origin),remember_days=365)
            result=JSONResponse(data)
            result.set_cookie('px_certificate_browser',cookie,max_age=people.browser_expiry(browser),httponly=True,
                secure=settings.public_origin.startswith('https://'),samesite='lax',path='/')
            return result

    @app.get(PUBLIC+'/request/{token}/mine')
    def mine(token:str,request:Request):
        keyring=keys()
        with engine.connect() as conn:
            link=linksvc.get_public(conn,keyring,token);browser=people.current_browser(conn,keyring,request.cookies.get('px_certificate_browser'))
            result=people.state(conn,people.find_request(conn,link['id'],browser['id']),keyring,origin)
        rate(request,'certificate-poll',browser['id'],120);return result

    @app.post(PUBLIC+'/request/{token}')
    def submit(token:str,body:dict,request:Request):
        keyring=keys()
        with engine.connect() as conn:
            browser=people.current_browser(conn,keyring,request.cookies.get('px_certificate_browser'))
            public_link=linksvc.get_public(conn,keyring,token)
            existing=people.find_request(conn,public_link['id'],browser['id'])
        if existing is None and certificate_features().accept_new_requests:
            capability=app.state.self_certificate_runtime.readiness()['capabilities']['accept_new']
            if not capability['ready']:fail('CERTIFICATE_SERVICE_UNAVAILABLE',503)
        rate(request,'certificate-submit',browser['id'],60)
        try:
            with engine.begin() as conn:
                link=linksvc.get_public(conn,keyring,token,lock=True)
                browser=people.current_browser(conn,keyring,request.cookies.get('px_certificate_browser'))
                result,created=people.accept(conn,link,browser,keyring,body,origin,certificate_features().accept_new_requests)
            if created:metrics.record('accepted')
            return JSONResponse(result,status_code=202 if created else 200)
        except IntegrityError:
            with engine.connect() as conn:
                link=linksvc.get_public(conn,keyring,token)
                existing=people.find_request(conn,link['id'],browser['id'])
                if not existing:fail('REQUEST_CONFLICT',409)
                return people.state(conn,existing,keyring,origin)

    @app.get(PUBLIC+'/receive/{token}')
    def receive(token:str,request:Request):
        keyring=keys();rate(request,'certificate-receive',token[:100],120)
        with engine.connect() as conn:return delivery.public_certificate(conn,delivery.by_token(conn,keyring,token),store,keyring,origin,True)

    def final_file(token,request,thumbnail=False):
        keyring=keys();rate(request,'certificate-file',token[:100],120)
        with engine.connect() as conn:
            row=delivery.by_token(conn,keyring,token)
            final,thumb=delivery.issued_assets(conn,row)
            if row['integrity_hash']!=delivery.certificate_integrity(row,final,thumb):fail('FINAL_FILE_UNAVAILABLE',503)
        asset=thumb if thumbnail else final
        return FileResponse(store.verified_path(asset),media_type='image/png',
            filename=None if thumbnail else 'certificate-'+row['serial']+'.png')

    @app.get(PUBLIC+'/receive/{token}/image')
    def image(token:str,request:Request):return final_file(token,request,True)
    @app.get(PUBLIC+'/receive/{token}/download')
    def download(token:str,request:Request):return final_file(token,request)

    @app.get(PUBLIC+'/verify/{serial}')
    def verify(serial:str,request:Request):
        if not re.fullmatch('SC[A-F0-9]{32}',serial):fail('NOT_FOUND',404)
        rate(request,'certificate-verify',serial,120)
        with engine.connect() as conn:
            row=conn.execute(select(certificates).where(certificates.c.serial==serial)).mappings().first()
            if not row:fail('NOT_FOUND',404)
            return delivery.public_certificate(conn,dict(row),store,keys(),origin)

    @app.get(ADMIN+'/requests')
    def history(request:Request,offset:int=0,limit:int=30,q:str='',status:str='',event_id:str=''):
        repo.page(offset,limit)
        if len(q)>160 or len(event_id)>64 or status not in ('','registered','processing','failed','issued'):
            fail('FILTER_INVALID',422)
        with engine.connect() as conn:
            user=account(conn,request)
            scope=[requests.c.owner_account_id==user['id'],links.c.owner_account_id==user['id']]
            if q.strip():
                scope.append(or_(requests.c.participant_name_original.icontains(q.strip(),autoescape=True),
                    requests.c.phone_original.icontains(q.strip(),autoescape=True),
                    links.c.model_name_snapshot.icontains(q.strip(),autoescape=True),
                    links.c.event_name_snapshot.icontains(q.strip(),autoescape=True)))
            if status:scope.append(requests.c.status==status)
            if event_id:scope.append(links.c.event_id==event_id)
            joined=requests.join(links,and_(links.c.id==requests.c.link_id,links.c.owner_account_id==requests.c.owner_account_id))
            issued=and_(certificates.c.request_id==requests.c.id,certificates.c.owner_account_id==requests.c.owner_account_id,
                certificates.c.link_id==requests.c.link_id)
            query=select(requests.c.id,requests.c.participant_name_original,requests.c.phone_original,requests.c.status,
                requests.c.submitted_at_utc,requests.c.layout,requests.c.error_code,links.c.model_name_snapshot,
                links.c.event_name_snapshot,certificates.c.id.label('certificate_id'),
                certificates.c.key_version.label('certificate_key_version')).select_from(joined.outerjoin(certificates,issued)).where(*scope)
            rows=[dict(r) for r in conn.execute(query.order_by(requests.c.submitted_at_utc.desc(),requests.c.id).offset(offset).limit(limit)).mappings()]
            keyring=keys() if any(r['certificate_id'] for r in rows) else None
            for row in rows:
                row['name_printed']=(row.pop('layout') or {}).get('name_printed',row['participant_name_original'])
                cert_id=row.pop('certificate_id');version=row.pop('certificate_key_version')
                row['receive_url']=origin+'/certificates/receive/'+keyring.token('receive',cert_id,version) if cert_id else None
            return dict(items=rows,total=conn.execute(select(func.count()).select_from(joined).where(*scope)).scalar_one())

    @app.post(ADMIN+'/requests/{ident}/retry')
    def retry(ident:str,request:Request):
        with engine.begin() as conn:
            user=account(conn,request,True)
            row=conn.execute(select(requests).where(requests.c.id==ident,requests.c.owner_account_id==user['id']).with_for_update()).mappings().first()
            if not row:fail('NOT_FOUND',404)
            if row['status']!='failed':fail('REQUEST_NOT_FAILED',409)
            job=conn.execute(select(jobs).where(jobs.c.request_id==ident).with_for_update()).mappings().one()
            if job['status']!='failed':fail('REQUEST_NOT_FAILED',409)
            conn.execute(update(jobs).where(jobs.c.id==job['id']).values(status='pending',attempts=0,available_at=people.utc_now(),last_error_code=None))
            conn.execute(update(requests).where(requests.c.id==ident).values(status='registered',error_code=None))
            log(conn,user,None,'self_certificate_retry',{'request_id':ident})
        return {'ok':True}

    @app.post(ADMIN+'/exports')
    def new_export(body:dict,request:Request):
        with engine.begin() as conn:return exporter.request_export(conn,account(conn,request,True),body)

    @app.get(ADMIN+'/exports')
    def export_list(request:Request,offset:int=0,limit:int=30):
        repo.page(offset,limit)
        with engine.connect() as conn:
            user=account(conn,request)
            rows=conn.execute(select(exports.c.id,exports.c.status,exports.c.format,exports.c.row_count,exports.c.cutoff,
                exports.c.error_code,exports.c.snapshot_version,exports.c.snapshot_taken_at,exports.c.expected_rows,
                assets.c.created_at.label('file_created_at'))
                .select_from(exports.outerjoin(assets,exports.c.asset_id==assets.c.id))
                .where(exports.c.owner_account_id==user['id']).order_by(exports.c.created_at.desc(),exports.c.id).offset(offset).limit(limit)).mappings()
            result=[]
            for row in rows:
                value=dict(row)
                value['expires_at']=(datetime.fromisoformat(value['file_created_at'])+exporter.EXPORT_RETENTION).isoformat() if value['file_created_at'] else None
                result.append(value)
            return {'items':result}

    @app.get(ADMIN+'/exports/{ident}/download')
    def export_file(ident:str,request:Request):
        with engine.connect() as conn:
            user=account(conn,request)
            row=conn.execute(select(exports).where(exports.c.id==ident,exports.c.owner_account_id==user['id'])).mappings().first()
            if not row:fail('NOT_FOUND',404)
            if row['error_code']=='EXPORT_EXPIRED':fail('EXPORT_EXPIRED',410)
            if row['status']!='done':fail('EXPORT_NOT_READY',409)
            asset=repo.owned_asset(conn,user,row['asset_id'],'export')
            if exporter.is_expired(asset['created_at']):fail('EXPORT_EXPIRED',410)
        return FileResponse(store.verified_path(asset),media_type=asset['mime'],filename='certificate-requests-'+ident+'.'+row['format'])
