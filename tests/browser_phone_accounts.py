"""Real HTTP Chromium coverage of phone signup/login; never requests OTP."""
import json
import os
from pathlib import Path
import tempfile
import traceback

from playwright.sync_api import sync_playwright
from test_admission_http_ack import running_server

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / 'qa/phone-accounts'
PHONE = '+967777991236'
PASSWORD = 'Browser-Phone-Password-2026!'


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    report = {'status': 'failed', 'backend': 'SQLite', 'checks': [],
              'limitations': ['No production deployment', 'No native PostgreSQL from this script', 'No physical Android device']}
    def mark(name):
        report['checks'].append(name)
    try:
        with tempfile.TemporaryDirectory(prefix='px-phone-browser-') as folder:
            temp = Path(folder)
            with running_server(temp) as (base, staff), sync_playwright() as pw:
                launch = {'args': ['--no-sandbox', '--disable-dev-shm-usage']}
                if os.environ.get('PX_CHROMIUM_EXECUTABLE'):
                    launch['executable_path'] = os.environ['PX_CHROMIUM_EXECUTABLE']
                browser = pw.chromium.launch(**launch)
                try:
                    report['browser_version'] = browser.version
                    context = browser.new_context(viewport={'width': 390, 'height': 844}, locale='ar-YE')
                    page = context.new_page()
                    errors, requested = [], []
                    page.on('pageerror', lambda error: errors.append(str(error)))
                    page.on('request', lambda request: requested.append(request.url))
                    page.goto(base + '/account/signup')
                    page.get_by_label('الاسم', exact=True).fill('Synthetic Phone Owner')
                    page.get_by_label('رقم الهاتف', exact=True).fill(PHONE)
                    page.get_by_label('كلمة المرور الجديدة — 12 إلى 256 حرفًا', exact=True).fill(PASSWORD)
                    page.get_by_label('تأكيد كلمة المرور الجديدة', exact=True).fill('Mismatch-Password-2026!')
                    page.get_by_role('button', name='إرسال طلب حسابي', exact=True).click()
                    page.get_by_role('status').filter(has_text='غير مطابق').wait_for()
                    page.get_by_label('تأكيد كلمة المرور الجديدة', exact=True).fill(PASSWORD)
                    page.get_by_role('button', name='إرسال طلب حسابي', exact=True).click()
                    page.wait_for_url(base+'/account/request#*')
                    page.get_by_role('status').filter(has_text='بانتظار الموافقة').wait_for()
                    assert context.request.post(base+'/api/auth/login',data={'phone':PHONE,'password':PASSWORD}).status==401
                    accounts=json.loads((temp/'accounts.json').read_text())
                    admin=next(a for a in accounts if a['role']=='platform')
                    auth=staff.post('/api/auth/login',json=admin);auth.raise_for_status()
                    staff.headers.update({'X-CSRF':auth.json()['csrf'],'Origin':base})
                    reviewer=browser.new_context(viewport={'width':1440,'height':1000})
                    assert reviewer.request.post(base+'/api/auth/login',data=admin).ok
                    review_page=reviewer.new_page();review_page.goto(base+'/admin')
                    review_page.locator('#admin-nav').get_by_role('button',name='طلبات الحسابات',exact=True).click()
                    card=review_page.locator('.record-list article').filter(has_text='Synthetic Phone Owner')
                    card.get_by_role('button',name='موافقة',exact=True).click()
                    review_page.get_by_role('dialog').get_by_role('button',name='تأكيد القرار',exact=True).click()
                    page.get_by_role('button',name='تحديث الحالة',exact=True).click()
                    page.get_by_role('link',name='تسجيل الدخول',exact=True).click()
                    page.get_by_label('رقم الهاتف',exact=True).fill(PHONE)
                    page.get_by_label('كلمة المرور',exact=True).fill(PASSWORD)
                    page.get_by_role('button',name='تسجيل الدخول',exact=True).click()
                    page.wait_for_url(base+'/account')
                    page.get_by_role('heading',name='Synthetic Phone Owner',exact=True).wait_for()
                    reviewer.close()
                    assert context.request.get(base + '/api/admin/sites').status == 403
                    assert page.evaluate('document.documentElement.scrollWidth<=innerWidth+1')
                    page.screenshot(path=str(OUT / 'mobile-account.png'), full_page=True)
                    mark('phone_request_has_no_login_until_independent_admin_ui_approval_without_otp')
                    page.get_by_role('button', name='تسجيل الخروج', exact=True).click()
                    page.get_by_label('رقم الهاتف', exact=True).fill('٧٧٧٩٩١٢٣٦')
                    page.get_by_label('كلمة المرور', exact=True).fill('0000')
                    page.get_by_role('button', name='تسجيل الدخول', exact=True).click()
                    page.get_by_role('status').filter(has_text='بيانات الدخول غير صحيحة').wait_for()
                    page.get_by_label('كلمة المرور', exact=True).fill(PASSWORD)
                    page.get_by_role('button', name='تسجيل الدخول', exact=True).click()
                    page.wait_for_url(base + '/account')
                    mark('arabic_phone_login_rejects_wrong_password_and_accepts_correct_password')
                    page.get_by_role('button', name='نسيت كلمة المرور', exact=True).click()
                    page.get_by_role('dialog').get_by_role('heading', name='نسيت كلمة المرور', exact=True).wait_for()
                    assert page.get_by_role('dialog').locator('input').count() == 0
                    page.keyboard.press('Escape')
                    mark('forgot_password_explains_assisted_recovery_without_code_or_identity_prompt')
                    accounts = json.loads((temp / 'accounts.json').read_text())
                    admin = next(account for account in accounts if account['email'] == 'admin@pulsex.test')
                    auth = staff.post('/api/auth/login', json=admin)
                    auth.raise_for_status()
                    staff.headers.update({'X-CSRF': auth.json()['csrf'], 'Origin': base})
                    target = staff.get('/api/admin/users', params={'phone': PHONE}).json()['users'][0]['id']
                    reset = staff.post('/api/admin/users/' + target + '/password/reset', json={})
                    reset.raise_for_status()
                    page.goto(base + '/admin')
                    page.get_by_label('رقم الهاتف', exact=True).fill(PHONE)
                    page.get_by_label('كلمة المرور', exact=True).fill(reset.json()['temporary_password'])
                    page.get_by_role('button', name='تسجيل الدخول', exact=True).click()
                    page.get_by_role('heading', name='غيّر كلمة المرور المؤقتة', exact=True).wait_for()
                    page.get_by_label('كلمة المرور المؤقتة الحالية', exact=True).fill(reset.json()['temporary_password'])
                    page.get_by_label('كلمة المرور الجديدة — 12 إلى 256 حرفًا', exact=True).fill('Recovered-Phone-Password-2026!')
                    page.get_by_label('تأكيد كلمة المرور الجديدة', exact=True).fill('Recovered-Phone-Password-2026!')
                    page.get_by_role('button', name='تغيير كلمة المرور والمتابعة', exact=True).click()
                    page.get_by_role('heading', name='تسجيل الدخول', exact=True).wait_for()
                    page.get_by_label('رقم الهاتف', exact=True).fill(PHONE)
                    page.get_by_label('كلمة المرور', exact=True).fill('Recovered-Phone-Password-2026!')
                    page.get_by_role('button', name='تسجيل الدخول', exact=True).click()
                    page.wait_for_url(base + '/account')
                    mark('administrator_reset_forces_password_change_and_relogin_without_otp')
                    suspended = staff.patch('/api/admin/users/' + target, json={'active': False})
                    suspended.raise_for_status()
                    assert context.request.get(base + '/api/auth/me').status == 401
                    mark('platform_suspension_revokes_public_account_session')
                    page.goto(base + '/admin')
                    page.get_by_role('heading', name='تسجيل الدخول', exact=True).wait_for()
                    page.set_viewport_size({'width': 1440, 'height': 1000})
                    assert page.evaluate('document.documentElement.scrollWidth<=innerWidth+1')
                    page.screenshot(path=str(OUT / 'desktop-phone-login.png'), full_page=True)
                    assert not any('/api/auth/otp/' in url for url in requested)
                    assert not errors, errors
                    mark('no_otp_requests_no_javascript_errors_mobile_and_desktop_layout')
                    report['status'] = 'passed'
                finally:
                    browser.close()
    except Exception as error:
        report.update(error_type=type(error).__name__, traceback=traceback.format_exc())
    finally:
        (OUT / 'browser.json').write_text(json.dumps(report, ensure_ascii=False, indent=2) + '\n')
    return 0 if report['status'] == 'passed' else 1


if __name__ == '__main__':
    raise SystemExit(main())
