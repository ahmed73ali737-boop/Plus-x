"""Chromium functional acceptance for V3 UI; physical devices remain a separate gate."""
from pathlib import Path
from io import BytesIO
import json,os,socket,subprocess,sys,time
import httpx,pytest
from PIL import Image
from playwright.sync_api import sync_playwright,expect
from app.db import users,sites
from app.server import create_app
from sqlalchemy import insert,select
from app.core.security import hash_password
from app.domain import default_config
from tests.test_self_certificate_http import PASSWORD,A,P

def browser_factory():
    if os.environ.get('PX_CERTIFICATE_BROWSER_QA')!='YES' or os.environ.get('PULSEX_ENV')!='test':
        raise RuntimeError('SYNTHETIC_BROWSER_QA_ONLY')
    app=create_app(seed_demo=False)
    with app.state.engine.begin() as conn:
        if not conn.execute(select(users.c.id).where(users.c.id=='self-a')).first():
            conn.execute(insert(sites).values(id='self-event',kind='event',slug='self-event',draft=default_config('فعالية الشهادات التجريبية','event'),draft_rev=1,published_version=0))
            conn.execute(insert(users).values(id='self-a',email='self-a@example.test',name='منظم مصطنع',role='organizer',scope_id='self-event',password_hash=hash_password(PASSWORD),active=1,must_change_password=0))
    return app

@pytest.fixture
def browser_server(tmp_path):
    if os.environ.get('PX_SELF_CERTIFICATE_BROWSER_ACCEPTANCE')!='YES':
        pytest.skip('Explicit browser acceptance with installed Chromium required')
    from tests.certificate_test_support import require_isolated_runtime
    require_isolated_runtime()
    with socket.socket() as value:
        value.bind(('127.0.0.1',0));port=value.getsockname()[1]
    base='http://127.0.0.1:'+str(port)
    env={**os.environ,'PX_CERTIFICATE_BROWSER_QA':'YES','PULSEX_ENV':'test','REQUIRE_POSTGRES':'false',
        'SEED_DEMO':'false','DATA_DIR':str(tmp_path/'data'),'MEDIA_DIR':str(tmp_path/'media'),
        'DATABASE_URL':'sqlite:///'+str(tmp_path/'qa.sqlite'),'PUBLIC_ORIGIN':base,
        'PX_SELF_CERTIFICATES_ADMIN':'true','PX_SELF_CERTIFICATES_ACCEPT_NEW':'true','PYTHONDONTWRITEBYTECODE':'1'}
    log=(tmp_path/'server.log').open('w')
    process=subprocess.Popen([sys.executable,'-m','uvicorn','tests.test_self_certificate_browser_improvements:browser_factory','--factory',
        '--host','127.0.0.1','--port',str(port),'--no-access-log'],env=env,stdout=log,stderr=log)
    try:
        for _ in range(150):
            try:
                if httpx.get(base+'/api/health/ready',timeout=2).status_code==200:break
            except httpx.HTTPError:pass
            if process.poll() is not None:raise RuntimeError('QA_SERVER_START_FAILED')
            time.sleep(.1)
        else:raise RuntimeError('QA_SERVER_READY_TIMEOUT')
        yield base
    finally:
        process.terminate()
        try:process.wait(timeout=40)
        except subprocess.TimeoutExpired:process.kill();process.wait()
        log.close()

def png():
    out=BytesIO();Image.new('RGB',(1200,800),'white').save(out,format='PNG');return out.getvalue()

def test_editor_admin_participant_and_prepared_share(browser_server,tmp_path):
    base=browser_server
    from tests.certificate_test_support import evidence_root
    evidence=Path(os.environ.get('CERTIFICATE_BROWSER_EVIDENCE') or evidence_root(tmp_path)/'browser')
    evidence.mkdir(parents=True,exist_ok=True)
    checks=[];errors=[]
    def check(label,condition=True):
        if not condition:
            page.screenshot(path=str(evidence/'failure.png'),full_page=True)
            (evidence/'failure.json').write_text(json.dumps({'label':label,'checks':checks,'errors':errors},ensure_ascii=False,indent=2),encoding='utf-8')
        assert condition,label
        checks.append(label)
    def wait_state(expression):
        deadline=time.monotonic()+15
        while time.monotonic()<deadline:
            if page.evaluate(expression):return
            time.sleep(.05)
        raise AssertionError('Synthetic browser race did not reach expected state')
    with sync_playwright() as pw:
        browser=pw.chromium.launch(args=['--no-sandbox','--disable-dev-shm-usage'])
        context=browser.new_context(viewport={'width':1366,'height':768},locale='ar-YE',timezone_id='Asia/Aden',accept_downloads=True)
        auth=context.request.post(base+'/api/auth/login',data={'email':'self-a@example.test','password':PASSWORD})
        assert auth.status==200
        csrf=auth.json()['csrf'];headers={'X-CSRF':csrf,'Origin':base}
        page=context.new_page()
        page.on('pageerror',lambda error:errors.append(str(error)))
        page.on('dialog',lambda dialog:dialog.accept())
        page.goto(base+'/certificates')
        page.get_by_role('button',name='إضافة نموذج شهادة',exact=True).click()
        dialog=page.get_by_role('dialog')
        dialog.get_by_label('خلفية PNG أو JPEG أو PDF',exact=True).set_input_files({'name':'background.png','mimeType':'image/png','buffer':png()})
        dialog.get_by_label('الخط',exact=True).wait_for()
        dialog.get_by_label('اسم النموذج',exact=True).fill('نموذج تحسين مصطنع')
        dialog.get_by_label('اسم النموذج',exact=True).press('Tab')
        save=dialog.get_by_role('button',name='حفظ النموذج',exact=True)
        expect(save).to_be_enabled(timeout=30000)
        value=dialog.get_by_label('الحجم المفضل',exact=True)
        value.focus()
        value.evaluate("(el)=>{window.__sizeField=el;el.value='57';el.dispatchEvent(new Event('change',{bubbles:true}));}")
        check('Property input identity and focus survive config change',value.evaluate('(el)=>el===window.__sizeField&&el===document.activeElement'))
        expect(value).to_have_value('57')
        expect(save).to_be_enabled(timeout=30000)
        page.evaluate("""() => {
          window.__originalFetch=window.fetch;window.__raceStarted=false;window.__raceSettled=false;
          window.fetch=(url,init={})=>{
            if(String(url).includes('/api/self-certificates/preview')&&!window.__raceStarted){
              window.__raceStarted=true;
              return window.__originalFetch(url,{...init,signal:undefined}).then(()=>new Promise((resolve,reject)=>{
                setTimeout(()=>{window.__raceSettled=true;reject(new Error('Synthetic stale failure'));},1800);
              }));
            }
            return window.__originalFetch(url,init);
          };
        }""")
        value.fill('58');value.press('Tab')
        wait_state('window.__raceStarted')
        value.fill('59');value.press('Tab')
        expect(save).to_be_enabled(timeout=30000)
        wait_state('window.__raceSettled')
        expect(save).to_be_enabled()
        check('Late failed preview cannot replace the latest valid proof')
        page.evaluate('window.fetch=window.__originalFetch')
        name_box=dialog.locator('.selfcert-name-box')
        before_box=name_box.get_attribute('style')
        name_box.focus();name_box.press('ArrowRight')
        moved_box=name_box.get_attribute('style')
        check('Keyboard arrow moves only selected name area',moved_box!=before_box)
        dialog.get_by_role('button',name='تراجع عن تعديل',exact=True).click()
        expect(name_box).to_have_attribute('style',before_box)
        check('Undo restores name geometry')
        dialog.get_by_role('button',name='إعادة تعديل',exact=True).click()
        expect(name_box).to_have_attribute('style',moved_box)
        check('Redo restores the same geometry')
        resize=dialog.get_by_role('button',name='تحجيم مساحة الاسم بالأسهم',exact=True)
        resize.focus();resize.press('ArrowRight')
        check('Resize handle is keyboard accessible',name_box.get_attribute('style')!=moved_box)
        dialog.get_by_role('button',name='تراجع عن تعديل',exact=True).click()
        expect(name_box).to_have_attribute('style',moved_box)
        dialog.get_by_role('button',name='عينة إنجليزية',exact=True).click()
        expect(save).to_be_enabled(timeout=30000)
        check('English sample is proof only',value.input_value()=='59')
        dialog.get_by_role('button',name='عينة عربية',exact=True).click()
        expect(save).to_be_enabled(timeout=30000)
        for width,height in [(1366,768),(1920,1080),(1093,614),(910,512),(683,384)]:
            page.set_viewport_size({'width':width,'height':height})
            save.scroll_into_view_if_needed()
            check('Save reachable and unobscured '+str(width),save.evaluate("(el)=>{const r=el.getBoundingClientRect();return r.y>=0&&r.bottom<=innerHeight&&el.contains(document.elementFromPoint(r.x+r.width/2,r.y+r.height/2));}"))
        page.set_viewport_size({'width':1366,'height':768})
        page.screenshot(path=str(evidence/'editor.png'))
        calls=[]
        def lose_first(route):
            if route.request.method!='POST':route.continue_();return
            response=route.fetch()
            calls.append(response.json()['id'])
            route.abort('failed')
        page.route('**/api/self-certificates/models',lose_first,times=1)
        save.click()
        expect(dialog.locator('.selfcert-editor-status')).to_contain_text('قد يكون الحفظ اكتمل',timeout=20000)
        expect(save).to_be_enabled()
        save.click()
        dialog.wait_for(state='detached')
        data=context.request.get(base+A+'/models').json()
        check('Lost create acknowledgement recovers one model',data['total']==1 and len(calls)==1 and data['items'][0]['id']==calls[0])
        page.get_by_role('button',name='فتح وتعديل',exact=True).click()
        dialog=page.get_by_role('dialog')
        expect(dialog.get_by_role('button',name='حفظ النموذج',exact=True)).to_be_enabled(timeout=30000)
        ident=data['items'][0]['id']
        saved=context.request.get(base+A+'/models/'+ident).json()
        payload={k:saved['revision'][k] for k in ('background_asset_id','stamp_asset_id','config')}
        changed=context.request.put(base+A+'/models/'+ident,headers=headers,data={**payload,'name':'جلسة أخرى','row_version':saved['row_version']})
        assert changed.status==200
        dialog.get_by_label('اسم النموذج',exact=True).fill('تعديلي محفوظ هنا')
        dialog.get_by_label('اسم النموذج',exact=True).press('Tab')
        dialog.get_by_role('button',name='حفظ النموذج',exact=True).click()
        expect(dialog.locator('.selfcert-conflict')).to_be_visible()
        expect(dialog.get_by_label('اسم النموذج',exact=True)).to_have_value('تعديلي محفوظ هنا')
        check('409 keeps dirty edits and offers explicit copy')
        dialog.get_by_role('button',name='حفظ تعديلي كنموذج جديد',exact=True).click()
        dialog.wait_for(state='detached')
        check('Explicit save-as-copy creates one separate model',context.request.get(base+A+'/models').json()['total']==2)
        page.get_by_role('button',name='الإصدار والروابط',exact=True).click()
        page.get_by_role('button',name='إنشاء رابط وQR لطلب الشهادات',exact=True).click()
        dialog=page.get_by_role('dialog')
        dialog.get_by_label('النموذج',exact=True).locator('option').first.wait_for(state='attached')
        expect(dialog.locator('.notice').last).to_contain_text('ستثبت نسخة')
        link_ids=[]
        def lose_link(route):
            response=route.fetch();link_ids.append(response.json()['id']);route.abort('failed')
        page.route('**/api/self-certificates/links',lose_link,times=1)
        dialog.get_by_role('button',name='تأكيد إنشاء الرابط',exact=True).click()
        expect(dialog.get_by_role('button',name='تأكيد إنشاء الرابط',exact=True)).to_be_enabled()
        expect(dialog.get_by_label('الفعالية',exact=True)).to_be_disabled()
        dialog.get_by_role('button',name='تأكيد إنشاء الرابط',exact=True).click()
        check('Lost link acknowledgement restores one frozen link',context.request.get(base+A+'/links').json()['total']==1 and len(link_ids)==1)
        page.get_by_label('رابط الطلب',exact=True).wait_for()
        request_url=page.get_by_label('رابط الطلب',exact=True).input_value()
        page.get_by_role('dialog').get_by_role('button',name='×',exact=True).click()
        participant=browser.new_context(viewport={'width':390,'height':844},is_mobile=True,has_touch=True,locale='ar-YE')
        p=participant.new_page();p.on('pageerror',lambda error:errors.append(str(error)))
        p.add_init_script("""window.__shared=[];Object.defineProperty(navigator,'canShare',{configurable:true,value:()=>true});Object.defineProperty(navigator,'share',{configurable:true,value:payload=>{window.__shared.push({text:payload.text,files:payload.files.map(f=>({name:f.name,size:f.size,type:f.type})),activation:navigator.userActivation.isActive});return Promise.resolve();}});""")
        p.goto(request_url)
        p.get_by_label('الاسم الكامل',exact=True).fill('أ ب ج د ه و')
        p.get_by_label('رقم الهاتف',exact=True).fill('0770123456')
        p.get_by_role('checkbox').check()
        p.get_by_role('button',name='طلب الشهادة',exact=True).click()
        expect(p.locator('#selfcert-name-error')).to_contain_text('خمس كلمات')
        check('Name error remains beside preserved input')
        p.get_by_label('الاسم الكامل',exact=True).fill('محمد أحمد علي حسن العمري')
        p.get_by_role('button',name='طلب الشهادة',exact=True).click()
        p.get_by_role('link',name='عرض الشهادة وتنزيلها',exact=True).wait_for(timeout=45000)
        p.get_by_role('link',name='عرض الشهادة وتنزيلها',exact=True).click()
        p.get_by_role('link',name='تنزيل الصورة الأصلية',exact=True).wait_for()
        original_url=p.get_by_role('link',name='تنزيل الصورة الأصلية',exact=True).get_attribute('href')
        original_png=participant.request.get(base+original_url).body()
        check('Participant has no share text field or copy button',p.locator('textarea').count()==0 and p.get_by_role('button',name='نسخ نص المشاركة',exact=True).count()==0)
        expect(p.get_by_role('heading',name='رمز التحقق الخاص بالشهادة',exact=True)).to_be_visible()
        check('Verification code is labeled in the real issued certificate',bool(p.locator('.selfcert-serial').inner_text()))
        p.get_by_role('button',name='مشاركة الصورة عبر الجهاز',exact=True).click()
        expect(p.get_by_role('button',name='مشاركة الصورة الجاهزة عبر الجهاز',exact=True)).to_be_visible(timeout=20000)
        check('First share prepares file without claiming a share',p.evaluate('window.__shared.length')==0)
        p.get_by_role('button',name='مشاركة الصورة الجاهزة عبر الجهاز',exact=True).click()
        shares=p.evaluate('window.__shared')
        check('Fresh click carries File and public verify only',len(shares)==1 and shares[0]['activation'] and shares[0]['files'][0]['type']=='image/png' and '/certificates/verify/' in shares[0]['text'] and '/receive/' not in shares[0]['text'] and '0770123456' not in shares[0]['text'])
        check('Sharing keeps the issued PNG byte-identical',participant.request.get(base+original_url).body()==original_png)
        with p.expect_download() as issued_download:p.get_by_role('link',name='تنزيل الصورة الأصلية',exact=True).click()
        check('Actual original download keeps issued PNG bytes',Path(issued_download.value.path()).read_bytes()==original_png)
        p.screenshot(path=str(evidence/'participant-result.png'),full_page=True)
        page.get_by_role('button',name='سجل الطلبات والشهادات',exact=True).click()
        page.get_by_role('button',name='تصدير كامل السجل XLSX',exact=True).click()
        expect(page.locator('.selfcert-export-context')).to_contain_text('لقطة تأكيد الطلب')
        download=page.locator('.selfcert-export-row a')
        expect(download).to_be_visible(timeout=30000)
        check('Export displays frozen count, time, expiry and ready download','انتهاء الملف' in page.locator('.selfcert-export-context').inner_text())
        page.screenshot(path=str(evidence/'history-and-export.png'),full_page=True)
        check('No JavaScript page errors',not errors)
        report={'checks':checks,'status':'passed','browser':'Chromium','limitations':['Web Share mocked; physical Android/iOS target transfer not established','Viewport sizes do not establish full screen-reader/WCAG or physical mobile acceptance','No native Excel opening in this browser test']}
        (evidence/'result.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
        participant.close();context.close();browser.close()
