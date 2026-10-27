"""End-to-end HTTP contracts; test identities and files are synthetic."""
from io import BytesIO
import base64,json,secrets,zipfile
from datetime import datetime,timedelta,timezone
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import insert,select,update,delete,func
from app.server import create_app
from app.db import sites,users
from app.core.security import hash_password
from app.self_certificates_db import requests,jobs,certificates,models,revisions,links,exports,assets,browser_sessions
from app.application.self_certificate_crypto import Keyring
from PIL import Image

A='/api/self-certificates';P='/api/public/self-certificates'
PASSWORD='Synthetic-QA-Only-8291!'

@pytest.fixture
def system(tmp_path,monkeypatch):
    from tests.certificate_test_support import require_isolated_runtime
    require_isolated_runtime()
    monkeypatch.setenv('PX_SELF_CERTIFICATES_ADMIN','true');monkeypatch.setenv('PX_SELF_CERTIFICATES_ACCEPT_NEW','true')
    monkeypatch.setenv('DATA_DIR',str(tmp_path/'data'))
    import os
    pg=os.environ.get('CERTIFICATE_TEST_POSTGRES')=='true'
    if pg:
        from tools.certificate_test_database import create_test_database
        from app.db import make_engine
        from tools.migrate_postgres import apply_migrations
        url=create_test_database();initial=make_engine(url);apply_migrations(initial);initial.dispose()
    else:url='sqlite:///'+str(tmp_path/'test.sqlite')
    app=create_app(url,origin='http://testserver',seed_demo=False)
    hashed=hash_password(PASSWORD)
    with app.state.engine.begin() as conn:
        conn.execute(insert(sites).values(id='self-event',kind='event',slug='self-event',draft={'title':'فعالية اختبار ثابتة'},draft_rev=1,published_version=0))
        for ident,role,scope in [('self-a','organizer','self-event'),('self-b','organizer',None),('self-editor','member',None)]:
            conn.execute(insert(users).values(id=ident,email=ident+'@example.test',name='Synthetic '+ident,role=role,scope_id=scope,password_hash=hashed,active=1,must_change_password=0))
    def client(ident='self-a'):
        value=TestClient(app)
        auth=value.post('/api/auth/login',json={'email':ident+'@example.test','password':PASSWORD});assert auth.status_code==200
        value.headers.update({'X-CSRF':auth.json()['csrf'],'Origin':'http://testserver'})
        return value
    yield app,client
    app.state.engine.dispose()
    if pg:
        from tools.certificate_test_database import drop_test_database
        drop_test_database(url)

def png():
    output=BytesIO();Image.new('RGB',(1200,800),'white').save(output,format='PNG');return output.getvalue()

def new_model(staff,name='نموذج ثابت'):
    bg=staff.post(A+'/assets?kind=background',content=png(),headers={'Content-Type':'application/octet-stream'})
    assert bg.status_code==200,bg.text
    options=staff.get(A+'/design-options',params={'background_id':bg.json()['id']}).json()
    result=staff.post(A+'/models',json=dict(name=name,background_asset_id=bg.json()['id'],stamp_asset_id=None,config=options['default_config']))
    assert result.status_code==200,result.text
    return result.json()

def new_link(staff,model=None):
    model=model or new_model(staff)
    payload=dict(event_id='self-event',model_id=model['id'],share_text='فخور بمشاركتي',idempotency_key=secrets.token_hex(24))
    result=staff.post(A+'/links',json=payload);assert result.status_code==200,result.text
    return result.json(),payload

def prepare(app,link,seed=None):
    browser=TestClient(app);browser.headers.update({'Origin':'http://testserver'})
    token=link['request_url'].split('/')[-1]
    response=browser.post(P+'/request/'+token+'/prepare',json={'browser_seed':seed or secrets.token_hex(32)})
    assert response.status_code==200,response.text
    return browser,token,response.json()

def submit(browser,token,prepared,name='محمد أحمد علي حسن العمري',phone='0770123456',consent=True):
    return browser.post(P+'/request/'+token,json=dict(name=name,phone=phone,consent=consent,request_nonce=prepared['request_nonce']))

def test_http_library_without_event_and_cross_account_isolation(system):
    app,client=system;staff=client('self-b')
    data=staff.get(A+'/access').json();assert data['can_manage'] and data['events']==[]
    row=new_model(staff)
    other=client()
    for path in ('/models/'+row['id'],'/assets/'+row['revision']['background_asset_id']):
        assert other.get(A+path).status_code==404
    assert staff.get(A+'/models').json()['total']==1
    changed=staff.put(A+'/models/'+row['id'],json=dict(name='نسخة ثانية',background_asset_id=row['revision']['background_asset_id'],
        stamp_asset_id=None,config=row['revision']['config'],row_version=1))
    assert changed.status_code==200,changed.text
    assert staff.put(A+'/models/'+row['id'],json=dict(name='تعارض',background_asset_id=row['revision']['background_asset_id'],stamp_asset_id=None,config=row['revision']['config'],row_version=1)).status_code==409
    assert staff.delete(A+'/models/'+row['id'],params={'row_version':2}).status_code==200
    assert staff.get(A+'/models').json()['total']==0
    assert client('self-editor').get(A+'/models').status_code==403

def test_http_acceptance_render_delivery_verify_export_and_immutable_original(system,monkeypatch):
    app,client=system;staff=client();model=new_model(staff);link,payload=new_link(staff,model)
    assert staff.post(A+'/links',json=payload).json()['request_url']==link['request_url']
    browser,token,prepared=prepare(app,link)
    assert submit(browser,token,prepared,consent=False).status_code==422
    with app.state.engine.connect() as conn:assert conn.execute(select(func.count()).select_from(requests)).scalar_one()==0
    first=submit(browser,token,prepared);assert first.status_code==202,first.text
    assert app.state.self_certificate_runtime.generate()
    mine=browser.get(P+'/request/'+token+'/mine');assert mine.status_code==200,mine.text
    assert mine.json()['status']=='issued',mine.text
    assert submit(browser,token,prepared,name='اسم مختلف').json()['receive_url']==mine.json()['receive_url']
    cap=mine.json()['receive_url'].split('/')[-1]
    receive=browser.get(P+'/receive/'+cap);assert receive.status_code==200,receive.text
    value=receive.json();assert value['status']=='valid' and value['name_printed']
    raw=browser.get(value['download_url']);assert raw.status_code==200,raw.text
    with Image.open(BytesIO(raw.content)) as im:assert im.size==(1200,800)
    assert browser.get(value['download_url']).content==raw.content
    public=browser.get(P+'/verify/'+value['serial']);assert public.status_code==200
    for forbidden in ('0770123456','phone_original','browser_session','delivery_token','owner_account_id','participant_name_original'):
        assert forbidden not in public.text
    assert browser.get(A+'/requests').status_code==401
    assert client('self-b').get(A+'/requests').json()['total']==0
    assert staff.delete(A+'/models/'+model['id'],params={'row_version':1}).status_code==200
    assert staff.post(A+'/links',json=payload).json()['request_url']==link['request_url']
    second,token2,prepared2=prepare(app,link)
    assert submit(second,token2,prepared2).status_code==202
    assert app.state.self_certificate_runtime.generate()
    assert browser.get(value['download_url']).content==raw.content
    history=staff.get(A+'/requests').json();assert history['total']==2 and history['items'][0]['participant_name_original']
    for fmt in ('xlsx','csv'):
        job=staff.post(A+'/exports',json={'format':fmt});assert job.status_code==200,job.text
        assert app.state.self_certificate_runtime.export()
        download=staff.get(A+'/exports/'+job.json()['id']+'/download');assert download.status_code==200,download.text
        assert client('self-b').get(A+'/exports/'+job.json()['id']+'/download').status_code==404
        if fmt=='xlsx':
            with zipfile.ZipFile(BytesIO(download.content)) as archive:
                xml=archive.read('xl/worksheets/sheet1.xml').decode()
                assert '0770123456' in xml and 'inlineStr' in xml and xml.count('<row ')==3
        else:assert '0770123456' in download.content.decode('utf-8-sig')
    with app.state.engine.connect() as conn:
        expired_job=conn.execute(select(exports.c.id,exports.c.asset_id).where(exports.c.format=='xlsx')).mappings().one()
    from app.application import self_certificate_exports as exporter
    real_datetime=exporter.datetime
    class EightDaysLater(real_datetime):
        @classmethod
        def now(cls,tz=None):return real_datetime.now(tz)+timedelta(days=8)
    monkeypatch.setattr(exporter,'datetime',EightDaysLater)
    expired_download=staff.get(A+'/exports/'+expired_job['id']+'/download')
    assert expired_download.status_code==410 and expired_download.json()['detail']=='EXPORT_EXPIRED'
    result=app.state.self_certificate_runtime.expire_exports()
    assert result['expired']==2 and result['removed_files']==2
    with app.state.engine.connect() as conn:
        assert conn.execute(select(func.count()).select_from(certificates)).scalar_one()==2
        assert conn.execute(select(func.count()).select_from(requests)).scalar_one()==2
        assert conn.execute(select(func.count()).select_from(jobs).where(jobs.c.status=='done')).scalar_one()==2
        expired=conn.execute(select(exports.c.status,exports.c.error_code,exports.c.asset_id).where(exports.c.id==expired_job['id'])).one()
        assert expired==( 'failed','EXPORT_EXPIRED',None)

def test_pause_revocation_flags_keep_old_receive_and_finish_registered_job(system,monkeypatch):
    app,client=system;staff=client();link,_=new_link(staff)
    old,token,data=prepare(app,link);assert submit(old,token,data).status_code==202
    paused=staff.post(A+'/links/'+link['id']+'/state',json={'status':'paused','row_version':1});assert paused.status_code==200,paused.text
    fresh,_,p=prepare(app,link);assert submit(fresh,token,p).status_code==409
    with app.state.engine.begin() as conn:conn.execute(update(users).where(users.c.id=='self-a').values(active=0))
    assert app.state.self_certificate_runtime.generate()
    mine=old.get(P+'/request/'+token+'/mine').json();assert mine['status']=='issued',mine
    cap=mine['receive_url'].split('/')[-1]
    monkeypatch.setenv('PX_SELF_CERTIFICATES_ADMIN','false');monkeypatch.setenv('PX_SELF_CERTIFICATES_ACCEPT_NEW','false')
    assert old.get(P+'/receive/'+cap).json()['status']=='valid'
    assert submit(old,token,data).json()['status']=='issued'
    assert fresh.get(P+'/request/'+token+'/mine').json()['status']=='unregistered'

def test_browser_identity_shared_seed_tabs_nonce_and_rotation(system):
    app,client=system;staff=client();link,_=new_link(staff);seed=secrets.token_hex(32)
    tab1,token,data1=prepare(app,link,seed);tab2,_,data2=prepare(app,link,seed)
    assert tab1.cookies.get('px_certificate_browser')==tab2.cookies.get('px_certificate_browser')
    bad=submit(tab1,token,{**data1,'request_nonce':'x'*32});assert bad.status_code==403
    assert submit(tab1,token,data1).status_code==202
    assert submit(tab2,token,data2).status_code==200
    keys=app.state.self_certificate_runtime.keys()
    raw=json.loads(keys.path.read_text());raw['keys']['v2']=base64.urlsafe_b64encode(secrets.token_bytes(32)).decode();raw['current']='v2';keys.path.write_text(json.dumps(raw))
    assert staff.get(A+'/links').json()['items'][0]['request_url']==link['request_url']
    assert app.state.self_certificate_runtime.generate()
    mine=tab1.get(P+'/request/'+token+'/mine').json();cap=mine['receive_url'].split('/')[-1]
    assert cap.startswith('v2.') and tab1.get(P+'/receive/'+cap).json()['status']=='valid'
    assert tab2.get(P+'/request/'+token+'/mine').json()['receive_url']==mine['receive_url']
