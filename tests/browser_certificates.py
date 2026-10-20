"""Native HTTP/Chromium certificate journey; executed in the guest CI job."""
import json
from pathlib import Path
import tempfile
from playwright.sync_api import sync_playwright
from test_admission_http_ack import running_server


def main():
    output=Path('qa/certificates-browser');output.mkdir(parents=True,exist_ok=True)
    report={'status':'failed','checks':[],'backend':'SQLite','limitations':['No production deployment','No external delivery provider','No physical Android device']}
    try:
        with tempfile.TemporaryDirectory(prefix='certificate-browser-') as folder:
            temp=Path(folder)
            with running_server(temp) as (base,staff), sync_playwright() as pw:
                browser=pw.chromium.launch(args=['--no-sandbox','--disable-dev-shm-usage'])
                context=browser.new_context(viewport={'width':1440,'height':1000},locale='ar-YE',timezone_id='Asia/Aden',accept_downloads=True)
                page=context.new_page();errors=[];page.on('pageerror',lambda error:errors.append(str(error)))
                admin=next(x for x in json.loads((temp/'accounts.json').read_text()) if x['email']=='admin@pulsex.test')
                auth=context.request.post(base+'/api/auth/login',data={'email':admin['email'],'password':admin['password']})
                assert auth.status==200
                page.goto(base+'/admin')
                page.get_by_label('مساحة العمل',exact=True).select_option('event-demo')
                page.get_by_role('button',name='الشهادات',exact=True).click()
                page.get_by_label('اسم نسخة القالب',exact=True).fill('قالب الاختبار')
                page.get_by_role('button',name='تحديث المعاينة',exact=True).click()
                page.locator('.certificate-stage img').wait_for()
                page.get_by_role('button',name='حفظ نسخة القالب',exact=True).click()
                page.get_by_label('المنطقة الزمنية للشهادة',exact=True).fill('Asia/Aden')
                page.get_by_label('اسم المشارك',exact=True).fill('أحمد علي')
                page.get_by_label('الدورة أو المنجز',exact=True).fill('إدارة الفعاليات')
                page.get_by_label('الجهة المصدرة',exact=True).fill('مركز الاختبار')
                page.get_by_label('معرّف المشارك الثابت',exact=True).fill('browser-person')
                page.get_by_label('رمز المنجز الثابت',exact=True).fill('browser-course')
                page.get_by_role('button',name='معاينة بيانات المشارك',exact=True).click()
                page.get_by_role('dialog').get_by_role('img').wait_for()
                page.keyboard.press('Escape')
                page.get_by_role('button',name='اعتماد وإصدار شهادة ثابتة',exact=True).click()
                access=page.get_by_role('link',name='رابط استلام المشارك',exact=True);access.wait_for()
                access_url=access.get_attribute('href')
                report['checks'].append('admin_template_preview_and_individual_issue')
                recipient=context.new_page();recipient.goto(access_url)
                recipient.get_by_role('heading',name='أحمد علي',exact=True).wait_for()
                recipient.get_by_text('Asia/Aden',exact=False).wait_for()
                for name,extension in [('تحميل PDF للطباعة','.pdf'),('تحميل صورة PNG','.png')]:
                    with recipient.expect_download() as result:recipient.get_by_role('link',name=name,exact=True).click()
                    assert result.value.suggested_filename.endswith(extension)
                    result.value.save_as(output/('download'+extension))
                recipient.set_viewport_size({'width':390,'height':844})
                assert recipient.evaluate('document.documentElement.scrollWidth<=innerWidth+1')
                assert recipient.locator('.certificate-page>.card').evaluate('(el)=>parseFloat(getComputedStyle(el).paddingRight)>=20')
                recipient.screenshot(path=str(output/'mobile-certificate.png'),full_page=True)
                verify=recipient.get_by_role('link',name='التحقق العام',exact=True).get_attribute('href')
                report['checks'].append('recipient_pdf_png_downloads_and_mobile_layout')
                page.get_by_role('button',name='تحديث السجل',exact=True).click()
                page.get_by_role('button',name='إلغاء الشهادة',exact=True).click()
                page.get_by_label('سبب الإلغاء',exact=True).fill('اختبار الإلغاء')
                page.get_by_role('button',name='تأكيد الإلغاء',exact=True).click()
                page.get_by_role('dialog').wait_for(state='detached')
                recipient.goto(verify);recipient.get_by_role('status').filter(has_text='ملغاة').wait_for()
                report['checks'].append('revocation_reflected_on_public_verification')
                assert not errors,errors
                report.update(status='passed',browser_version=browser.version,page_errors=errors)
                browser.close()
    except Exception as exc:
        report['error']=str(exc)
        raise
    finally:(output/'result.json').write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n')

if __name__=='__main__':main()
