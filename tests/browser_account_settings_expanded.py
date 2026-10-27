"""Native Chromium settings/inbox scenarios with real isolated HTTP storage.

Only named network-failure scenarios intercept transport; account APIs remain real.
"""
from pathlib import Path
import json, os, tempfile, traceback
from contextlib import contextmanager
from playwright.sync_api import sync_playwright, expect
from test_admission_http_ack import running_server

ROOT=Path(__file__).resolve().parents[1]
OUT=ROOT/'qa/account-settings-expanded'

def main():
    OUT.mkdir(parents=True,exist_ok=True);cases=[];errors=[]
    @contextmanager
    def scenario(name):
        try:
            yield
            cases.append({'name':name,'status':'passed'})
            print('PASS',name,flush=True)
        except Exception as exc:
            cases.append({'name':name,'status':'failed','reason':str(exc),'traceback':traceback.format_exc()})
            print('FAIL',name,type(exc).__name__,flush=True)
    try:
        with tempfile.TemporaryDirectory(prefix='eventna-expanded-browser-') as td:
            temp=Path(td)
            with running_server(temp) as (base,staff),sync_playwright() as pw:
                accounts=json.loads((temp/'accounts.json').read_text())
                admin=next(a for a in accounts if a['role']=='platform')
                recipient=next(a for a in accounts if a['role']=='organizer')
                browser=pw.chromium.launch(args=['--no-sandbox','--disable-dev-shm-usage'])
                try:
                    guest=browser.new_context(viewport={'width':390,'height':844},locale='ar-YE',color_scheme='light')
                    page=guest.new_page();page.on('pageerror',lambda e:errors.append(str(e)))
                    def open_guest():
                        page.locator('.preferences-launcher').click()
                        page.get_by_role('button',name='حفظ الإعدادات',exact=True).wait_for()
                    def close_guest():page.get_by_role('button',name='إغلاق الإعدادات',exact=True).click()
                    page.goto(base+'/start')
                    with scenario('guest_theme_text_motion_and_local_persistence'):
                        open_guest()
                        page.get_by_label('المظهر',exact=True).select_option('dark')
                        page.get_by_label('حجم النص',exact=True).select_option('large')
                        page.get_by_label('تقليل الحركة والمؤثرات',exact=True).check()
                        page.get_by_role('button',name='حفظ الإعدادات',exact=True).click()
                        expect(page.get_by_role('status').filter(has_text='حُفظت الإعدادات على هذا الجهاز.')).to_be_visible()
                        expect(page.locator('html')).to_have_attribute('data-appearance','dark')
                        expect(page.locator('html')).to_have_attribute('data-text-size','large')
                        expect(page.locator('html')).to_have_attribute('data-reduce-motion','true')
                        assert page.evaluate('document.documentElement.scrollWidth<=innerWidth+1')
                        page.screenshot(path=str(OUT/'guest-mobile-dark.png'))
                        close_guest();page.reload()
                        expect(page.locator('html')).to_have_attribute('data-appearance','dark')
                    with scenario('system_theme_tracks_device_color_scheme'):
                        open_guest();page.get_by_label('المظهر',exact=True).select_option('system')
                        page.get_by_role('button',name='حفظ الإعدادات',exact=True).click()
                        page.emulate_media(color_scheme='dark');expect(page.locator('html')).to_have_attribute('data-appearance','dark')
                        page.emulate_media(color_scheme='light');expect(page.locator('html')).to_have_attribute('data-appearance','light')
                        close_guest()
                    with scenario('corrupt_local_preferences_do_not_break_entry'):
                        page.evaluate("localStorage.setItem('eventna-preferences','{broken')")
                        page.reload();page.get_by_role('heading',name='تنزيل Android متوقف مؤقتًا',exact=True).wait_for()
                        expect(page.locator('html')).to_have_attribute('data-appearance','light')
                        open_guest();close_guest()
                    with scenario('guest_setting_save_remains_local_without_network'):
                        open_guest();guest.set_offline(True)
                        page.get_by_label('المظهر',exact=True).select_option('dark')
                        page.get_by_role('button',name='حفظ الإعدادات',exact=True).click()
                        expect(page.get_by_role('status').filter(has_text='حُفظت الإعدادات على هذا الجهاز.')).to_be_visible()
                        guest.set_offline(False);close_guest()

                    def login_context(credential):
                        ctx=browser.new_context(viewport={'width':1440,'height':1000},locale='ar-YE')
                        response=ctx.request.post(base+'/api/auth/login',data={'email':credential['email'],'password':credential['password']})
                        assert response.status==200
                        csrf=response.json()['csrf']
                        ctx.set_extra_http_headers({'X-CSRF':csrf,'Origin':base})
                        p=ctx.new_page();p.on('pageerror',lambda e:errors.append(str(e)))
                        p.goto(base+'/admin');p.locator('#admin-nav').wait_for()
                        return ctx,p,csrf
                    ac,ap,ac_csrf=login_context(admin);rc,rp,rc_csrf=login_context(recipient)
                    def panel(p):
                        p.locator('#admin-nav').get_by_role('button',name='الإعدادات والإشعارات',exact=True).click()
                        p.get_by_role('heading',name='صندوق الإشعارات',exact=True).wait_for()
                    panel(ap);panel(rp)
                    with scenario('account_settings_saved_server_side_and_survive_reload'):
                        ap.get_by_label('المظهر',exact=True).select_option('dark')
                        ap.get_by_label('حجم النص',exact=True).select_option('large')
                        ap.get_by_role('button',name='حفظ الإعدادات',exact=True).click()
                        expect(ap.get_by_role('status').filter(has_text='حُفظت إعدادات حسابك.')).to_be_visible()
                        assert ac.request.get(base+'/api/account/preferences').json()['theme']=='dark'
                        ap.reload();panel(ap)
                        expect(ap.get_by_label('المظهر',exact=True)).to_have_value('dark')
                    with scenario('non_platform_inbox_has_no_sender_form_and_defaults_are_isolated'):
                        assert rp.get_by_label('بريد المستلم',exact=True).count()==0
                        expect(rp.get_by_label('المظهر',exact=True)).to_have_value('system')
                        assert rc.request.post(base+'/api/admin/notifications',data={'email':admin['email'],'title':'x','body':'y'}).status==403
                    with scenario('platform_send_renders_recipient_content_as_text_only'):
                        ap.get_by_label('بريد المستلم',exact=True).fill(recipient['email'])
                        ap.get_by_label('العنوان',exact=True).fill('Synthetic <img src=x>')
                        ap.get_by_label('الرسالة',exact=True).fill('<script>window.__noticeXss=1</script>')
                        ap.get_by_role('button',name='إرسال إلى صندوق الحساب',exact=True).click()
                        expect(ap.get_by_role('status').filter(has_text='وصلت الرسالة إلى صندوق الحساب.')).to_be_visible()
                        rp.get_by_role('button',name='تحديث الرسائل',exact=True).click()
                        expect(rp.get_by_role('heading',name='Synthetic <img src=x>',exact=True)).to_be_visible()
                        assert rp.locator('.inbox-message script,.inbox-message img').count()==0
                        assert rp.evaluate('window.__noticeXss === undefined')
                        assert ac.request.get(base+'/api/account/notifications').json()['items']==[]
                    with scenario('unread_badge_updates_on_visibility_and_read_receipt_clears_it'):
                        rp.evaluate("document.dispatchEvent(new Event('visibilitychange'))")
                        expect(rp.locator('.preferences-launcher')).to_contain_text('الإشعارات (1)')
                        rp.get_by_role('button',name='تحديد كمقروء',exact=True).click()
                        expect(rp.get_by_role('button',name='تحديد كمقروء',exact=True)).to_have_count(0)
                        rp.evaluate("document.dispatchEvent(new Event('visibilitychange'))")
                        expect(rp.locator('.preferences-launcher')).to_have_text('المظهر والإشعارات')
                    with scenario('send_to_unknown_account_reports_failure_without_creating_message'):
                        ap.get_by_label('بريد المستلم',exact=True).fill('unknown@example.invalid')
                        ap.get_by_label('العنوان',exact=True).fill('Synthetic unknown')
                        ap.get_by_label('الرسالة',exact=True).fill('not delivered')
                        ap.get_by_role('button',name='إرسال إلى صندوق الحساب',exact=True).click()
                        expect(ap.get_by_role('status').filter(has_text='تعذر الإرسال. تحقق من بريد الحساب والاتصال.')).to_be_visible()
                        assert len(rc.request.get(base+'/api/account/notifications').json()['items'])==1
                    with scenario('disable_badge_keeps_durable_inbox_and_manual_refresh'):
                        rp.get_by_label('إظهار تنبيهات الرسائل الجديدة',exact=True).uncheck()
                        rp.get_by_role('button',name='حفظ الإعدادات',exact=True).click()
                        expect(rp.get_by_role('status').filter(has_text='حُفظت إعدادات حسابك.')).to_be_visible()
                        response=ac.request.post(base+'/api/admin/notifications',data={'email':recipient['email'],'title':'Second synthetic notice','body':'kept in inbox'})
                        assert response.status==200
                        rp.evaluate("document.dispatchEvent(new Event('visibilitychange'))")
                        expect(rp.locator('.preferences-launcher')).to_have_text('المظهر والإشعارات')
                        rp.get_by_role('button',name='تحديث الرسائل',exact=True).click()
                        expect(rp.get_by_role('heading',name='Second synthetic notice',exact=True)).to_be_visible()
                        assert len(rc.request.get(base+'/api/account/notifications').json()['items'])==2
                    with scenario('account_save_network_failure_preserves_confirmed_preferences'):
                        before=rc.request.get(base+'/api/account/preferences').json()
                        rp.route('**/api/account/preferences',lambda route:route.abort() if route.request.method=='PUT' else route.continue_())
                        rp.get_by_label('المظهر',exact=True).select_option('dark')
                        rp.get_by_role('button',name='حفظ الإعدادات',exact=True).click()
                        expect(rp.locator('.toast')).to_be_visible()
                        assert rc.request.get(base+'/api/account/preferences').json()==before
                        saved=rp.evaluate("JSON.parse(localStorage.getItem('eventna-preferences'))")
                        assert saved==before
                        rp.unroute('**/api/account/preferences');panel(rp)
                    with scenario('inbox_network_failure_has_retry_and_recovers'):
                        rp.route('**/api/account/notifications',lambda route:route.abort())
                        rp.locator('#admin-nav').get_by_role('button',name='الإعدادات والإشعارات',exact=True).click()
                        expect(rp.get_by_role('alert').filter(has_text='تعذر تحميل الرسائل. تحقق من الاتصال.')).to_be_visible()
                        rp.unroute('**/api/account/notifications')
                        rp.get_by_role('button',name='إعادة المحاولة',exact=True).click()
                        expect(rp.get_by_role('heading',name='Second synthetic notice',exact=True)).to_be_visible()
                    with scenario('settings_and_inbox_fit_390px_account_view'):
                        rp.set_viewport_size({'width':390,'height':844})
                        rp.locator('.preferences-launcher').click()
                        rp.get_by_role('button',name='إغلاق الإعدادات',exact=True).wait_for()
                        assert rp.evaluate('document.documentElement.scrollWidth<=innerWidth+1')
                        rp.screenshot(path=str(OUT/'recipient-mobile-inbox.png'),full_page=True)
                        rp.get_by_role('button',name='إغلاق الإعدادات',exact=True).click()
                    with scenario('no_uncaught_browser_page_errors'):
                        assert not errors,errors
                finally:browser.close()
    except Exception as exc:
        cases.append({'name':'harness_completion','status':'failed','reason':str(exc),'traceback':traceback.format_exc()})
    report={'source':'native HTTP + Chromium + disposable SQLite','cases':cases,'page_errors':errors,'status':'passed' if cases and all(x['status']=='passed' for x in cases) else 'failed'}
    (OUT/'results.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
    return int(report['status']!='passed')
if __name__=='__main__':raise SystemExit(main())
