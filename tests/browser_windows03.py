"""Chromium DOM + real backend HTTP through an explicit Python bridge.
Native browser network, native browser cookies, service workers and IndexedDB are NOT tested.
The environment blocks native browser navigation. Storage below is a test double.
"""
from pathlib import Path
import base64, json, re, sys, traceback, os, shutil
import httpx
from playwright.sync_api import sync_playwright
ROOT=Path(__file__).resolve().parents[1]
URL=os.environ.get('PX_QA_URL','')
if not URL.startswith('http://127.0.0.1:') or not os.environ.get('PX_QA_ACCOUNTS'):
    raise SystemExit('Use python tests/run_ui_bridge.py. This harness must use an isolated local QA database.')
ACCOUNTS=json.loads(Path(os.environ['PX_QA_ACCOUNTS']).read_text(encoding='utf-8'))
checks=[];errors=[]

def module(name):
    s=(ROOT/'web'/name).read_text(encoding='utf-8')
    s=re.sub(r'^import\s*\{[^}]*\}\s*from\s*[\'"][^\'"]+[\'"];?','',s,flags=re.M)
    return s.replace('export ','')

ui=module('ui.mjs')
ui=ui.replace("else e.setAttribute(k,v===true?'':String(v));", "else e.setAttribute(k,k==='src'&&window._media[String(v)]?window._media[String(v)]:v===true?'':String(v));")
common='const UI=(()=>{'+ui+';return {h,root,api,field,selectField,check,button,modal,toast,brand,media,msg,labels,types,setCSRF,download};})();'
icons='const Icons=(()=>{'+module('icons.mjs')+';return{icon};})();'
catalog='const Catalog=(()=>{'+module('catalog.mjs')+';return{sectionsMeta,snippet,route,sectionLink,itemLink};})();'
questions='const Questions=(()=>{const{h,field,selectField}=UI;'+module('questions.mjs')+';return{question,visible};})();'
exhibition='const Exhibition=(()=>{'+module('exhibition.mjs')+';return{exhibitionExperience};})();'
public=module('public.mjs').replace('new URLSearchParams(location.search)', "new URLSearchParams(window._query||'')")
public='const Public=(()=>{const{h,root,api,field,selectField,check,button,modal,toast,brand,media,msg,labels}=UI;const{icon}=Icons;const{sectionsMeta,snippet,route,sectionLink,itemLink}=Catalog;const{question,visible}=Questions;const{exhibitionExperience}=Exhibition;const bundle=async slug=>await api("/api/public/site/"+slug);const enqueue=async item=>(await api("/api/collect",{items:[item]})).receipts[0];const prepare=async()=>{throw Error("Native offline test unavailable in harness")};const backup=prepare;const sync=async()=>{};const activate=()=>{};const status=async()=>({pending:0,rejected:0,items:[]});'+public+';return{publicPage,welcome,renderRoute};})();window.PXPublic=Public;'
admin='const Admin=(()=>{const{h,root,api,field,selectField,check,button,modal,toast,brand,labels,types,setCSRF,msg}=UI;const{icon}=Icons;const backup=async()=>{throw Error("Not a native storage test")};'+module('admin.mjs')+';return{adminPage};})();window.PXAdmin=Admin;'
media={}
for file in (ROOT/'web/media').glob('*'):
    media['/media/'+file.name]='data:image/svg+xml;base64,'+base64.b64encode(file.read_bytes()).decode()

def mark(name):
    checks.append(name);print('PASS',name,flush=True)

with sync_playwright() as p:
    browser=p.chromium.launch(executable_path=os.environ.get('PX_QA_CHROMIUM') or shutil.which('chromium'),args=['--no-sandbox','--disable-dev-shm-usage'])
    page=browser.new_page(viewport={'width':1440,'height':1000});page.on('pageerror',lambda e:errors.append(str(e)))
    client=httpx.Client(base_url=URL,timeout=20,trust_env=False)
    def bridge(req):
        headers={k:v for k,v in req.get('headers',{}).items() if k.lower() not in ('host','content-length')}
        res=client.request(req.get('method','GET'),req['url'],headers=headers,content=req.get('body'))
        try:body=res.json()
        except Exception:body={'detail':'BRIDGE_NON_JSON'}
        return {'ok':res.is_success,'status':res.status_code,'body':body}
    page.expose_function('pxBridge',bridge)
    def setup(mode,query=''):
        page.goto('about:blank')
        page.set_content('<html lang="ar" dir="rtl"><body><div id="app"></div><div id="toasts" aria-live="polite"></div></body></html>')
        page.add_style_tag(content=(ROOT/'web/style.css').read_text(encoding='utf-8'))
        page.add_style_tag(content=(ROOT/'web/design.css').read_text(encoding='utf-8'))
        page.evaluate('''arg=>{window._media=arg.media;window._query=arg.query;window.crypto.randomUUID=()=>"xxxxxxxx-xxxx-4xxx-yxxx-xxxxxxxxxxxx".replace(/[xy]/g,c=>{const r=crypto.getRandomValues(new Uint8Array(1))[0]%16;return(c==='x'?r:(r&3|8)).toString(16)});for(const name of ['localStorage','sessionStorage']){const values={};Object.defineProperty(window,name,{configurable:true,value:{getItem:k=>values[k]||null,setItem:(k,v)=>{values[k]=v},removeItem:k=>delete values[k]}});}window.fetch=async(url,options={})=>{const r=await window.pxBridge({url:String(url),method:options.method||'GET',headers:options.headers||{},body:options.body});return{ok:r.ok,status:r.status,json:async()=>r.body};};}''',{'media':media,'query':query})
        page.add_script_tag(content='(()=>{'+common+icons+catalog+questions+exhibition+(public if mode=='public' else admin)+'})()')
    try:
        setup('public');page.evaluate("PXPublic.publicPage('platform')")
        page.get_by_role('heading',name='الفعاليات الجارية والقادمة').wait_for();page.get_by_role('button',name='طلب اشتراك / حساب',exact=True).wait_for()
        assert page.locator('[data-section]').count()==4
        mark('platform_open_sections_real_backend_reads')
        page.screenshot(path=str(ROOT/'qa/platform-desktop.png'),full_page=True)
        setup('public');page.evaluate("PXPublic.publicPage('agency-01')")
        page.get_by_role('button',name='الدخول دون بيانات',exact=True).click()
        assert page.locator('[data-section]').count()==10
        assert page.locator('fieldset.question').count()==0 # summaries, not ten forms stacked on home
        mark('agency_ten_open_sections_with_previews')
        page.screenshot(path=str(ROOT/'qa/agency-desktop.png'),full_page=True)
        # HTML anchors mutate about:blank's hash only, no external network navigation.
        page.locator('#services .browse-card a').first.click()
        page.get_by_role('heading',level=1,name='خدمات رقمية أقرب إليك').wait_for()
        assert page.locator('.detail-copy').count()==1
        mark('service_card_opens_full_detail')
        page.screenshot(path=str(ROOT/'qa/service-detail.png'),full_page=True)
        page.get_by_role('link',name='العودة إلى القسم',exact=True).click()
        page.get_by_role('heading',level=1,name='الخدمات',exact=True).wait_for()
        mark('detail_returns_to_parent_section')
        page.get_by_role('link',name='كل الأقسام',exact=True).click()
        page.locator('#questions').get_by_role('link',name='ابدأ الاستبيان',exact=True).click()
        page.locator('fieldset[data-code="q-interest"] input').first.check()
        page.locator('fieldset[data-code="q-rate"] button').last.click()
        survey_form=page.locator('form[data-form="main"]')
        survey_form.get_by_role('button',name='إرسال الاستبيان',exact=True).click()
        success=survey_form.locator('.success')
        success.wait_for()
        assert 'استلام' in success.inner_text()
        mark('survey_ui_to_real_http_and_database_bridge')
        page.screenshot(path=str(ROOT/'qa/survey-desktop.png'),full_page=True)
        page.get_by_role('link',name='الرئيسية',exact=True).first.click()
        page.locator('#polls a.btn').first.click()
        page.locator('fieldset input').first.check()
        page.get_by_role('button',name='إرسال التصويت',exact=True).click()
        page.get_by_text(re.compile('1 أصوات مستلمة')).wait_for()
        mark('vote_and_results_via_real_http_bridge')
        page.get_by_role('link',name='الرئيسية',exact=True).first.click()
        page.locator('#ratings a.btn').click()
        page.get_by_role('button',name='قيّم الزيارة',exact=True).click()
        page.get_by_role('button',name='5 من 5',exact=True).first.click()
        page.get_by_label('ملاحظة — اختيارية',exact=True).fill('ملاحظة اختبار للنسخة الجديدة')
        page.get_by_role('button',name='إرسال التقييم والملاحظة',exact=True).click()
        page.wait_for_function("document.querySelectorAll('dialog').length===0")
        mark('general_rating_submission_bridge')
        page.get_by_role('link',name='كل الأقسام',exact=True).click()
        for width in [360,390,768,1440]:
            page.set_viewport_size({'width':width,'height':900})
            assert page.evaluate('document.documentElement.scrollWidth<=innerWidth+1'),f'overflow {width}'
            mark(f'responsive_home_width_{width}')
            if width==390:
                page.evaluate('scrollTo(0,0)');page.wait_for_timeout(7500)
                page.screenshot(path=str(ROOT/'qa/agency-mobile.png'),full_page=False)
                page.screenshot(path=str(ROOT/'qa/agency-mobile-full.png'),full_page=True)
        page.set_viewport_size({'width':1440,'height':1000})
        setup('admin');page.evaluate('PXAdmin.adminPage()')
        account=ACCOUNTS[2]
        page.get_by_label('البريد الإلكتروني',exact=True).fill(account['email'])
        page.get_by_label('كلمة المرور',exact=True).fill(account['password'])
        page.get_by_role('button',name='تسجيل الدخول',exact=True).click()
        page.get_by_role('heading',level=1,name='نظرة عامة').wait_for()
        assert page.locator('.admin-main .grid .card').count()==10
        mark('admin_login_and_ten_functional_shortcuts_bridge')
        qr=base64.b64encode(client.get('/api/admin/sites/agency-01/qr').content).decode();page.evaluate('data=>{const i=document.querySelector("img.qr");if(i)i.src="data:image/png;base64,"+data}',qr);page.screenshot(path=str(ROOT/'qa/admin-overview.png'),full_page=True)
        page.get_by_role('button',name='إدخال الأسئلة',exact=True).click()
        page.get_by_role('button',name='+ سؤال واحد',exact=True).first.click()
        dialog=page.locator('dialog')
        dialog.get_by_label('رمز داخلي',exact=True).fill('W09-UI-Q')
        dialog.get_by_label('نص السؤال',exact=True).fill('سؤال Windows من اختبار الواجهة')
        dialog.get_by_label('نوع الإجابة',exact=True).select_option('short_text')
        page.screenshot(path=str(ROOT/'qa/question-editor.png'),full_page=True)
        dialog.get_by_role('button',name='حفظ السؤال',exact=True).click()
        page.get_by_text('سؤال Windows من اختبار الواجهة',exact=True).wait_for()
        mark('manual_question_saved_from_ui_to_real_backend')
        page.get_by_role('button',name='Excel / CSV',exact=True).click()
        page.get_by_label('نوع CSV فقط',exact=False).select_option('fact')
        page.get_by_label('أو الصق CSV',exact=False).fill('code,title,value,unit,source\nW04-UI-FACT,رقم من واجهة الاستيراد,73,%,اختبار واجهة')
        page.get_by_role('button',name='فحص ومعاينة الاستيراد',exact=True).click()
        page.get_by_role('button',name='اعتماد الاستيراد وحفظ المسودة',exact=True).wait_for()
        page.screenshot(path=str(ROOT/'qa/import-preview.png'),full_page=True)
        page.get_by_role('button',name='اعتماد الاستيراد وحفظ المسودة',exact=True).click()
        page.get_by_text('تم الحفظ في المسودة.',exact=True).wait_for()
        mark('csv_preview_and_commit_from_ui_bridge')
        page.get_by_role('button',name='النتائج والتقارير',exact=True).click()
        page.get_by_text('أشخاص فريدون موثّقون',exact=True).wait_for()
        mark('real_analytics_page_and_honest_people_counts')
        page.screenshot(path=str(ROOT/'qa/analytics.png'),full_page=True)
        for tab in ['الهوية والقالب','أقسام الصفحة','الفعالية والخدمات','التصويت','الإعلانات والعروض','الحقائق والأرقام','الأجهزة والطرفيات','السجل والتدقيق','أمان الحساب']:
            page.get_by_role('button',name=tab,exact=True).click()
            page.get_by_role('heading',level=1,name=tab,exact=True).wait_for()
            mark('admin_module_'+tab)
        # Organizer-specific Admin Panel coverage: organizations, accounts and access-request review.
        client.cookies.clear()
        client.post('/api/access-request',json={'site_id':'event-demo','name':'UI Request','email':'ui-request@example.test'})
        setup('admin');page.evaluate('PXAdmin.adminPage()')
        organizer=ACCOUNTS[1]
        page.get_by_label('البريد الإلكتروني',exact=True).fill(organizer['email'])
        page.get_by_label('كلمة المرور',exact=True).fill(organizer['password'])
        page.get_by_role('button',name='تسجيل الدخول',exact=True).click()
        page.get_by_role('heading',level=1,name='نظرة عامة').wait_for()
        page.get_by_role('button',name='المؤسسات والمشاركات',exact=True).click()
        page.get_by_role('heading',level=1,name='المؤسسات والمشاركات').wait_for();mark('organizer_organizations_admin_module')
        page.get_by_role('button',name='الحسابات',exact=True).click()
        page.get_by_role('heading',level=1,name='الحسابات').wait_for();page.get_by_text('ui-request@example.test',exact=False).first.wait_for();mark('organizer_accounts_and_access_requests_module')
        # Preview endpoint is verified through the authenticated real backend.
        # Browser-preview write suppression is covered by test_pilot.py because this bridge
        # cannot safely exercise a second public app context in this environment.
        preview_payload=client.get('/api/admin/sites/agency-01/preview').json()
        assert preview_payload.get('preview') is True and preview_payload.get('draft') is True
        mark('preview_endpoint_returns_actual_draft')
        if errors:raise AssertionError(errors)
        report={'status':'passed','passed':len(checks),'checks':checks,'errors':errors,
        'method':'Chromium DOM with Python HTTP bridge to Uvicorn/SQLite. Native browser networking blocked. Storage test double, NOT IndexedDB.',
        'native_windows_tested':False,'native_browser_network_tested':False,'service_worker_tested':False,'indexeddb_tested':False,'real_backend_used':True}
    except Exception as exc:
        report={'status':'failed','passed_before_failure':len(checks),'checks':checks,'error':str(exc),'trace':traceback.format_exc(),'page_errors':errors,'not_native_browser_e2e':True}
        page.screenshot(path=str(ROOT/'qa/browser-failure.png'),full_page=True)
    finally:
        (ROOT/'qa/browser-bridge-report.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
        print(json.dumps(report,ensure_ascii=False,indent=2));browser.close();client.close()
        if report['status']!='passed':raise SystemExit(1)
