"""Real HTTP Chromium: public entry, download bytes, mobile layout, pending signup."""
from pathlib import Path
import hashlib,json,os,sys,tempfile,traceback
from playwright.sync_api import sync_playwright
from test_admission_http_ack import running_server
ROOT=Path(__file__).resolve().parents[1]
OUT=ROOT/'qa/app-entry'


def main():
    OUT.mkdir(parents=True,exist_ok=True)
    report={'status':'failed','backend':'SQLite','scope':'Chromium HTTP, not physical Android','checks':[]}
    def mark(name):report['checks'].append(name)
    try:
        with tempfile.TemporaryDirectory(prefix='px-app-entry-') as folder:
            temp=Path(folder)
            with running_server(temp) as (base,staff),sync_playwright() as pw:
                launch={'args':['--no-sandbox','--disable-dev-shm-usage']}
                if os.environ.get('PX_CHROMIUM_EXECUTABLE'):launch['executable_path']=os.environ['PX_CHROMIUM_EXECUTABLE']
                browser=pw.chromium.launch(**launch)
                try:
                    report['browser_version']=browser.version
                    page=browser.new_page(viewport={'width':390,'height':844},locale='ar-YE')
                    errors=[];page.on('pageerror',lambda e:errors.append(str(e)))
                    page.goto(base+'/start')
                    page.get_by_role('link',name='تحميل Android',exact=False).wait_for()
                    assert page.evaluate('document.documentElement.scrollWidth<=innerWidth+1')
                    page.screenshot(path=str(OUT/'mobile-entry.png'),full_page=True)
                    mark('mobile_390_no_horizontal_overflow')
                    with page.expect_download() as pending:
                        page.get_by_role('link',name='تحميل Android',exact=False).click()
                    download=pending.value;target=temp/'preview.apk';download.save_as(target)
                    evidence=staff.get('/api/downloads/android').json()
                    assert hashlib.sha256(target.read_bytes()).hexdigest()==evidence['sha256']
                    mark('download_link_returns_pinned_apk_bytes')
                    page.get_by_label('اسم الجهة أو المؤسسة',exact=True).fill('Synthetic browser org')
                    page.get_by_label('اسم المسؤول',exact=True).fill('Synthetic browser owner')
                    page.get_by_label('البريد الإلكتروني',exact=True).fill('browser-entry@example.test')
                    page.get_by_role('button',name='إرسال طلب المراجعة',exact=True).click()
                    page.get_by_text('يلزم الموافقة على إرسال البيانات قبل تقديم الطلب.',exact=True).wait_for()
                    page.get_by_label('أوافق على إرسال هذه البيانات للمنظم لمراجعة طلب الحساب.',exact=True).check()
                    page.get_by_role('button',name='إرسال طلب المراجعة',exact=True).click()
                    page.get_by_role('heading',name='تم استلام طلبك للمراجعة',exact=True).wait_for()
                    assert staff.get('/api/admin/sites').status_code==401
                    mark('anonymous_request_stays_pending_without_admin_access')
                    page.get_by_role('link',name='تصفح كضيف أثناء الانتظار',exact=True).click()
                    assert page.url==base+'/'
                    page.goto(base+'/start')
                    page.get_by_role('link',name='تسجيل الدخول',exact=True).click()
                    page.get_by_label('البريد الإلكتروني',exact=True).wait_for()
                    assert page.get_by_role('link',name='إنشاء طلب حساب جهة',exact=True).count()==1
                    mark('guest_and_registered_routes_reach_canonical_surfaces')
                    page.goto(base+'/start');page.set_viewport_size({'width':1440,'height':1000})
                    page.screenshot(path=str(OUT/'desktop-entry.png'),full_page=True)
                    assert not errors,errors
                    report['status']='passed'
                finally:browser.close()
    except Exception as error:report.update(error_type=type(error).__name__,traceback=traceback.format_exc())
    finally:
        (OUT/'browser.json').write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    return 0 if report['status']=='passed' else 1


if __name__=='__main__':raise SystemExit(main())
