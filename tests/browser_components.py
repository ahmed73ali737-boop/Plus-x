"""Read-only DOM component checks with in-memory fixtures; NO network or IndexedDB assurance.
Chromium policy blocks navigation to the local server in this environment. Do not treat
these checks as the blocked end-to-end test, offline test, or deployment validation.
"""
from pathlib import Path
import json,re,base64,sys
from fastapi.testclient import TestClient
from playwright.sync_api import sync_playwright
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from app.server import create_app
ROOT=Path(__file__).resolve().parents[1]
app=create_app('sqlite:///:memory:',origin='http://testserver',seed_demo=True);client=TestClient(app)
account=app.state.seed_credentials[2];auth=client.post('/api/auth/login',json={'email':account['email'],'password':account['password']}).json()
routes={'/api/auth/me':auth,'/api/admin/sites':client.get('/api/admin/sites').json(),'/api/admin/sites/agency-01':client.get('/api/admin/sites/agency-01').json(),'/api/admin/sites/agency-01/metrics':client.get('/api/admin/sites/agency-01/metrics').json(),'/api/admin/sites/agency-01/preview':client.get('/api/admin/sites/agency-01/preview').json()}
for slug in ('platform','demo','agency-01'):
    routes['/api/public/site/'+slug]=client.get('/api/public/site/'+slug).json()
    routes['/api/public/site/'+slug+'/results']=client.get('/api/public/site/'+slug+'/results').json()
def replace_media(x):
    if isinstance(x,str) and x.startswith('/media/'):
        p=ROOT/'web'/x.lstrip('/')
        if p.is_file():return 'data:image/svg+xml;base64,'+base64.b64encode(p.read_bytes()).decode()
    if isinstance(x,dict):return{k:replace_media(v) for k,v in x.items()}
    if isinstance(x,list):return[replace_media(v) for v in x]
    return x
routes=replace_media(routes)
qr=base64.b64encode(client.get('/api/admin/sites/agency-01/qr').content).decode()

def code(name):
    s=(ROOT/'web'/name).read_text();s=re.sub(r'^import\s*\{[^}]*\}\s*from\s*[\'\"][^\'\"]+[\'\"];?','',s,flags=re.M);return s.replace('export ','')
ui=code('ui.mjs').replace("else e.setAttribute(k,v===true?'':String(v));","else e.setAttribute(k,k==='src'&&String(v).includes('/qr')?window._qr:v===true?'':String(v));")
icons='const Icons=(()=>{'+code('icons.mjs')+';return{icon};})();'
catalog='const Catalog=(()=>{'+code('catalog.mjs')+';return{sectionsMeta,snippet,route,sectionLink,itemLink};})();'
common="const UI=(()=>{"+ui+";return {h,root,api,field,selectField,check,button,modal,toast,brand,media,msg,labels,types,setCSRF,download};})();"
questions="const Questions=(()=>{const {h,field,selectField}=UI;"+code('questions.mjs')+";return{question,visible};})();"
public=code('public.mjs').replace("if(!preview&&page.kind!=='platform')", "if(false&&page.kind!=='platform')").replace('identity();',"visitor='fixture';session='fixture';")
public="const Public=(()=>{const{h,root,api,field,selectField,check,button,modal,toast,brand,media,msg,labels}=UI;const{icon}=Icons;const{sectionsMeta,snippet,route,sectionLink,itemLink}=Catalog;const{question,visible}=Questions;const bundle=async slug=>structuredClone(window._routes['/api/public/site/'+slug]);const enqueue=async()=>{throw Error('Read-only component harness forbids writes')};const prepare=enqueue,backup=enqueue,sync=async()=>{},activate=()=>{},status=async()=>({pending:0,rejected:0,items:[]});"+public+";return {publicPage,welcome};})();window.PXPublic=Public;"
admin="const Admin=(()=>{const{h,root,api,field,selectField,check,button,modal,toast,brand,labels,types,setCSRF,msg}=UI;const{icon}=Icons;const backup=async()=>{throw Error('Read-only')};"+code('admin.mjs')+";return{adminPage};})();window.PXAdmin=Admin;"
checks=[];errors=[]
with sync_playwright() as p:
    browser=p.chromium.launch(executable_path='/usr/bin/chromium',args=['--no-sandbox'])
    page=browser.new_page(viewport={'width':1440,'height':1000});page.on('pageerror',lambda e:errors.append(str(e)))
    def setup(modules):
        page.goto('about:blank')
        page.set_content('<html lang="ar" dir="rtl"><body><div id="app"></div><div id="toasts"></div></body></html>')
        page.add_style_tag(content=(ROOT/'web/style.css').read_text())
        page.add_style_tag(content=(ROOT/'web/design.css').read_text())
        page.evaluate('''arg=>{window._routes=arg.routes;window._qr=arg.qr;window.crypto.randomUUID=()=>"component-"+Math.random().toString(36).slice(2);for(const name of ['localStorage','sessionStorage']){const values={};Object.defineProperty(window,name,{configurable:true,value:{getItem:k=>values[k]||null,setItem:(k,v)=>{values[k]=v},removeItem:k=>delete values[k]}});}window.fetch=async(url,options)=>{if(options?.method&&options.method!=='GET')throw Error('Read-only component harness forbids writes');if(!(url in window._routes))throw Error('Missing read fixture: '+url);return{ok:true,json:async()=>structuredClone(window._routes[url])}};}''',{'routes':routes,'qr':'data:image/png;base64,'+qr})
        page.add_script_tag(content='(async()=>{'+common+icons+catalog+questions+modules+'})()')
    setup(public)
    page.evaluate("PXPublic.publicPage('platform')");page.get_by_role('heading',name='الفعاليات الجارية والقادمة').wait_for();checks.append('platform_directory_component');page.screenshot(path=str(ROOT/'qa/platform-desktop.png'),full_page=True)
    page.evaluate("PXPublic.publicPage('agency-01')");page.get_by_role('heading',name='الجهة التجريبية 01',exact=True,level=1).wait_for();assert page.locator('[data-section]').count()==10;checks.append('agency_ten_sections_component');page.screenshot(path=str(ROOT/'qa/agency-desktop.png'),full_page=True)
    page.locator('#questions').get_by_role('link',name='ابدأ الاستبيان',exact=True).click();page.locator('fieldset[data-code="q-interest"] input').first.check();assert page.locator('fieldset[data-code="q-interest"] input:checked').count()==1;checks.append('choice_control_interaction_component')
    page.evaluate('PXPublic.welcome()');page.get_by_role('button',name='تخطي هذه الخطوة',exact=True).click();assert page.get_by_label('الاسم',exact=True).count()==1;page.get_by_role('button',name='الدخول دون بيانات',exact=True).click();assert page.locator('dialog[open]').count()==0;checks.append('progressive_welcome_skip_component')
    page.set_viewport_size({'width':390,'height':844});setup(public);page.evaluate("PXPublic.publicPage('agency-01')");page.get_by_role('heading',name='الجهة التجريبية 01',exact=True,level=1).wait_for();assert page.evaluate('document.documentElement.scrollWidth<=innerWidth+1');page.evaluate("document.activeElement.blur();scrollTo({top:0,left:0,behavior:'instant'})");page.wait_for_timeout(200);page.screenshot(path=str(ROOT/'qa/agency-mobile.png'),full_page=False);checks.append('mobile_component_no_horizontal_overflow')
    page.set_viewport_size({'width':1440,'height':1000});setup(admin);page.evaluate('PXAdmin.adminPage()');page.get_by_role('heading',name='نظرة عامة',exact=True).wait_for();page.screenshot(path=str(ROOT/'qa/admin-overview.png'),full_page=True);checks.append('agency_admin_scoped_fixture_component')
    page.get_by_role('button',name='إدخال الأسئلة',exact=True).click();page.get_by_role('button',name='+ سؤال واحد',exact=True).first.click();page.locator('dialog').get_by_label('نوع الإجابة',exact=True).select_option('matrix');page.locator('dialog').get_by_label('بنود المصفوفة',exact=False).fill('الوضوح\nالسرعة');page.screenshot(path=str(ROOT/'qa/manual-question-editor.png'),full_page=True);checks.append('manual_question_editor_component');page.locator('dialog').get_by_role('button',name='×',exact=True).click()
    page.get_by_role('button',name='Excel / CSV',exact=True).click();page.get_by_role('button',name='فحص ومعاينة الاستيراد',exact=True).wait_for();page.screenshot(path=str(ROOT/'qa/import-component.png'),full_page=True);checks.append('import_controls_component')
    page.get_by_role('button',name='النتائج والتقارير',exact=True).click();page.get_by_text('أشخاص فريدون موثّقون',exact=True).wait_for();checks.append('metric_definitions_component')
    browser.close()
assert not errors,errors
report={'scope':'read-only browser DOM components; in-memory fixtures','network_used':False,'not_e2e':True,'not_offline_storage_test':True,'passed':len(checks),'checks':checks,'page_errors':errors}
(ROOT/'qa/browser-components.json').write_text(json.dumps(report,ensure_ascii=False,indent=2));print(json.dumps(report))
