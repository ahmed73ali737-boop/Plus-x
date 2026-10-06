"""Isolated local acceptance runnable on Windows without pytest or a browser driver.
Never uses the operator's production database. Records the actual host OS in its report.
"""
from contextlib import closing
from pathlib import Path
import base64, http.cookiejar, json, os, platform, socket, sqlite3, subprocess, sys, tempfile, time, urllib.error, urllib.request, uuid
ROOT=Path(__file__).resolve().parents[1]
checks=[]

def main():
    (ROOT/'qa').mkdir(exist_ok=True)
    with tempfile.TemporaryDirectory(prefix='pulsex-acceptance-') as td:
        temp=Path(td)
        with socket.socket() as s:s.bind(('127.0.0.1',0));port=s.getsockname()[1]
        base=f'http://127.0.0.1:{port}'
        env={**os.environ,'HOST':'127.0.0.1','PORT':str(port),'PUBLIC_ORIGIN':base,'DATABASE_URL':'sqlite:///'+str(temp/'db.sqlite'),'CREDENTIALS_PATH':str(temp/'accounts.json'),'MEDIA_DIR':str(temp/'media'),'REQUIRE_POSTGRES':'false','SEED_DEMO':'true','PYTHONUTF8':'1'}
        log=open(temp/'server.log','w',encoding='utf-8')
        def start():
            proc=subprocess.Popen([sys.executable,str(ROOT/'run.py')],cwd=ROOT,env=env,stdout=log,stderr=log)
            for _ in range(100):
                try:
                    with urllib.request.build_opener(urllib.request.ProxyHandler({})).open(base+'/api/health',timeout=.5):return proc
                except Exception:
                    if proc.poll() is not None:raise RuntimeError('Application failed to start; '+(temp/'server.log').read_text(encoding='utf-8')[-1500:])
                    time.sleep(.1)
            proc.terminate();raise RuntimeError('Server startup timeout')
        proc=start();csrf='';jar=http.cookiejar.CookieJar();opener=urllib.request.build_opener(urllib.request.ProxyHandler({}),urllib.request.HTTPCookieProcessor(jar))
        def req(path,body=None,method=None,extra=None):
            headers={'Content-Type':'application/json',**({'X-CSRF':csrf} if csrf else {}),**(extra or {})}
            r=urllib.request.Request(base+path,data=json.dumps(body).encode() if body is not None else None,method=method or ('POST' if body is not None else 'GET'),headers=headers)
            try:
                with opener.open(r,timeout=20) as out:return out.status,out.read(),out.headers
            except urllib.error.HTTPError as out:return out.code,out.read(),out.headers
        def j(path,body=None,method=None,code=200,extra=None):
            status,data,_=req(path,body,method,extra);assert status==code,(path,status,data[:200]);return json.loads(data)
        def mark(name):checks.append(name);print('PASS',name,flush=True)
        try:
            assert j('/api/health')['build']=='windows-08';mark('application_health')
            for path in ['/','/e/demo','/e/demo/p/agency-01','/admin','/assets/design.css','/assets/catalog.mjs','/assets/public.mjs','/sw.js']:
                assert req(path)[0]==200;mark('route_'+path)
            assert len(j('/api/public/site/demo')['agencies'])==10;mark('organizer_and_ten_agencies')
            accounts=json.loads((temp/'accounts.json').read_text(encoding='utf-8'))
            assert len(accounts)==12;mark('unique_first_run_accounts')
            credentials=accounts[1];auth=j('/api/auth/login',{'email':credentials['email'],'password':credentials['password']});csrf=auth['csrf'];mark('organizer_http_cookie_login')
            dev=j('/api/admin/sites/agency-01/devices',{'name':'Native Tablet','device_type':'tablet','app_version':'0.9.0'});mark('device_registered')
            heartbeat=j('/api/device/heartbeat',{'pending_count':3,'app_version':'0.9.0','synced':True},extra={'X-PulseX-Device-Token':dev['device_token']});assert heartbeat['pending_count']==3;mark('device_heartbeat')
            j('/api/admin/sites/agency-02');mark('organizer_event_scope_allows_participant')
            j('/api/admin/sites/platform',code=403);mark('organizer_platform_scope_denial')
            d=j('/api/admin/sites/agency-01')
            j('/api/admin/sites/agency-01',{'draft_rev':d['draft_rev'],'config':d['draft']},'PUT',403,{'X-CSRF':''});mark('csrf_write_denial')
            d['draft']['records'].append({'kind':'question','code':'native-q','qtype':'short_text','title':'سؤال اختبار محلي','form_id':'native'})
            result=j('/api/admin/sites/agency-01',{'draft_rev':d['draft_rev'],'config':d['draft']},'PUT');mark('manual_question_persisted')
            before=j('/api/public/site/agency-01');assert not any(x['code']=='native-q' for x in before['config']['records']);mark('draft_not_leaked')
            j('/api/admin/sites/agency-01/publish',{'draft_rev':result['draft_rev']});mark('publish_revision')
            published=j('/api/public/site/agency-01');assert any(x['code']=='native-q' for x in published['config']['records']);mark('published_question_visible')
            b={'id':str(uuid.uuid4()),'site_id':'agency-01','version':published['version'],'kind':'survey','visitor_id':str(uuid.uuid4()),'session_id':str(uuid.uuid4()),'source':'web','target':'main','payload':{'answers':{'q-interest':'o1','q-rate':5}},'client_time':'2026-09-28T00:00:00Z'}
            assert j('/api/collect',{'items':[b]})['receipts'][0]['status']=='accepted';mark('anonymous_survey_collection')
            assert j('/api/collect',{'items':[b]})['receipts'][0]['status']=='duplicate';mark('duplicate_replay_is_idempotent')
            poll={**b,'id':str(uuid.uuid4()),'kind':'poll','target':'p-first','payload':{'answer':'o1'}}
            assert j('/api/collect',{'items':[poll]})['receipts'][0]['status']=='accepted';mark('poll_collection')
            assert j('/api/public/site/agency-01/results')['polls']['p-first']['ballots']==1;mark('poll_result_matches')
            xlsx=base64.b64encode((ROOT/'templates/PulseX_Windows04_Import.xlsx').read_bytes()).decode()
            imp=j('/api/admin/sites/agency-01/imports/preview',{'name':'template.xlsx','base64':xlsx})
            assert imp['valid'];mark('xlsx_validated')
            j('/api/admin/sites/agency-01/imports/'+imp['id']+'/commit',{});mark('xlsx_committed_to_draft')
            csv=j('/api/admin/sites/agency-01/imports/preview',{'kind':'fact','csv':'code,title,value,unit,source\r\nnative-fact,رقم تجريبي,42,جهة,اختبار فقط\r\n'})
            assert csv['valid'];mark('csv_utf8_validated')
            metric=j('/api/admin/sites/agency-01/metrics');assert metric['counts']['survey']==1 and metric['verified_people'] is None;mark('metrics_match_no_fake_people')
            status,png,_=req('/api/admin/sites/agency-01/qr');assert status==200 and png.startswith(b'\x89PNG');mark('qr_png_generated')
            assert req('/api/admin/sites/agency-01/export')[1].startswith(b'\xef\xbb\xbf');mark('csv_export_utf8_bom')
            proc.terminate();proc.wait(timeout=8);proc=start()
            with closing(sqlite3.connect(temp/'db.sqlite')) as con:
                assert con.execute('PRAGMA integrity_check').fetchone()[0]=='ok'
                assert con.execute("select count(*) from px_submissions where kind='survey'").fetchone()[0]==1
            mark('restart_persists_database')
            proc.terminate();proc.wait(timeout=8)
            if os.name == 'nt':
                db_path=temp/'db.sqlite';probe=temp/'db-release-probe.sqlite';released=False
                for _ in range(40):
                    try:
                        if db_path.exists():
                            os.replace(db_path,probe);os.replace(probe,db_path)
                        released=True;break
                    except PermissionError:
                        time.sleep(.1)
                assert released,'SQLite handle was not released after server shutdown'
                mark('sqlite_handle_released')
            report={'status':'passed','passed':len(checks),'checks':checks,'host_os':platform.platform(),'native_windows':os.name=='nt','python':platform.python_version(),'database':'SQLite','browser_ui_tested':False,'physical_kiosks_tested':False,'postgresql_tested':False}
        except Exception as exc:
            report={'status':'failed','passed_before_failure':len(checks),'checks':checks,'error':str(exc),'host_os':platform.platform(),'native_windows':os.name=='nt'}
        finally:
            if proc.poll() is None:proc.terminate();proc.wait(timeout=8)
            log.close()
    dest=ROOT/'qa'/('windows-native-acceptance.json' if os.name=='nt' else 'linux-local-acceptance.json')
    dest.write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
    print('Report:',dest);print(json.dumps(report,ensure_ascii=True,indent=2));return 0 if report['status']=='passed' else 1
if __name__=='__main__':raise SystemExit(main())
