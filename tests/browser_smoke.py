from pathlib import Path
import os, subprocess, tempfile, json, time, urllib.request, sys
from playwright.sync_api import sync_playwright
ROOT=Path(__file__).resolve().parents[1]
TEMP=Path(tempfile.mkdtemp(prefix='pulsex-browser-'))
PORT=4431;URL=f'http://127.0.0.1:{PORT}'
env={**os.environ,'PORT':str(PORT),'PUBLIC_ORIGIN':URL,'DATABASE_URL':'sqlite:///'+str(TEMP/'pilot.sqlite'),'CREDENTIALS_PATH':str(TEMP/'accounts.json'),'MEDIA_DIR':str(TEMP/'media')}
log=open(ROOT/'qa/browser-server.log','w');proc=subprocess.Popen([sys.executable,'run.py'],cwd=ROOT,env=env,stdout=log,stderr=log)
try:
    for _ in range(80):
        try:
            urllib.request.urlopen(URL+'/api/health',timeout=1);break
        except Exception:time.sleep(.15)
    creds=json.loads((TEMP/'accounts.json').read_text())
    out=[];errors=[]
    with sync_playwright() as p:
        browser=p.chromium.launch(executable_path='/usr/bin/chromium',args=['--no-sandbox','--disable-dev-shm-usage'])
        context=browser.new_context(viewport={'width':1440,'height':1000},locale='ar-YE')
        page=context.new_page();page.on('pageerror',lambda e:errors.append(str(e)))
        page.goto(URL);page.get_by_role('heading',name='الفعاليات والتجارب').wait_for();page.screenshot(path=str(ROOT/'qa/platform-desktop.png'),full_page=True);out.append('platform_page')
        page.goto(URL+'/e/demo/p/agency-01');page.get_by_role('button',name='الدخول دون بيانات',exact=True).click();page.get_by_role('heading',name='الجهة التجريبية 01',exact=True,level=1).wait_for();page.screenshot(path=str(ROOT/'qa/agency-desktop.png'),full_page=True);out.append('agency_page_optional_welcome')
        page.locator('fieldset[data-code="q-interest"] input').first.check();page.locator('form[data-form="main"]').get_by_role('button',name='إرسال الإجابات').click();page.get_by_text('تم استلام الإجابات',exact=True).wait_for();out.append('real_http_survey_submission')
        context2=browser.new_context(viewport={'width':390,'height':844},is_mobile=True,locale='ar-YE');mobile=context2.new_page();mobile.on('pageerror',lambda e:errors.append(str(e)));mobile.goto(URL+'/e/demo/p/agency-01');mobile.get_by_role('button',name='الدخول دون بيانات',exact=True).click();mobile.screenshot(path=str(ROOT/'qa/agency-mobile.png'),full_page=False);assert mobile.evaluate('document.documentElement.scrollWidth <= innerWidth+1');out.append('mobile_layout_no_overflow')
        page.goto(URL+'/admin');page.get_by_label('البريد الإلكتروني',exact=True).fill(creds[2]['email']);page.get_by_label('كلمة المرور',exact=True).fill(creds[2]['password']);page.get_by_role('button',name='تسجيل الدخول',exact=True).click();page.get_by_role('heading',name='نظرة عامة',exact=True).wait_for();page.screenshot(path=str(ROOT/'qa/admin-overview.png'),full_page=True);out.append('agency_login_and_dashboard')
        page.get_by_role('button',name='إدخال الأسئلة',exact=True).click();page.get_by_role('button',name='+ الأسئلة والاستبيانات',exact=True).click();dialog=page.locator('dialog');dialog.get_by_label('رمز ثابت').fill('UI-Q01');dialog.get_by_label('نص السؤال',exact=True).fill('سؤال يدوي من الاختبار');dialog.get_by_label('نوع السؤال',exact=True).select_option('short_text');dialog.get_by_role('button',name='فحص وحفظ المادة',exact=True).click();page.get_by_text('سؤال يدوي من الاختبار',exact=True).wait_for();out.append('manual_question_ui_to_database')
        page.get_by_role('button',name='Excel / CSV',exact=True).click();page.locator('input[type=file]').set_input_files(str(ROOT/'templates/PulseX_Windows04_Import.xlsx'));page.get_by_role('button',name='فحص ومعاينة الاستيراد',exact=True).click();page.get_by_role('button',name='اعتماد الاستيراد وحفظ المسودة',exact=True).wait_for();page.screenshot(path=str(ROOT/'qa/import-preview.png'),full_page=True);page.get_by_role('button',name='اعتماد الاستيراد وحفظ المسودة',exact=True).click();page.get_by_text('تم الحفظ في المسودة.',exact=True).wait_for();out.append('xlsx_preview_commit_ui')
        page.get_by_role('button',name='معاينة الصفحة',exact=True).click();frame=page.frame_locator('iframe');frame.get_by_text('وضع المعاينة · نسخة المسودة · لا تُسجل أصوات أو إحصائيات').wait_for();page.screenshot(path=str(ROOT/'qa/preview-studio.png'),full_page=True);out.append('preview_uses_actual_draft')
        page.get_by_role('button',name='النتائج والتقارير',exact=True).click();page.get_by_text('أشخاص فريدون موثّقون',exact=True).wait_for();out.append('analytics_ui')
        browser.close()
    assert not errors,errors
    (ROOT/'qa/browser-smoke.json').write_text(json.dumps({'passed':len(out),'checks':out,'page_errors':errors,'backend':'SQLite','real_local_http':True,'not_native_postgresql':True},ensure_ascii=False,indent=2))
    print(json.dumps({'passed':len(out),'checks':out,'page_errors':errors},ensure_ascii=False))
except Exception as exc:
    report={'status':'blocked' if 'ERR_BLOCKED_BY_ADMINISTRATOR' in str(exc) else 'failed','reason':str(exc),'not_passed':True,'not_offline_test':True}
    (ROOT/'qa/browser-smoke.json').write_text(json.dumps(report,ensure_ascii=False,indent=2))
    print(json.dumps(report,ensure_ascii=False))
    raise
finally:
    proc.terminate();proc.wait(timeout=10);log.close()
