"""Native HTTP/Chromium regression journeys for the two scoped admin P1 fixes.

Uses a disposable SQLite database. Does not claim the future account approval
lifecycle is implemented: the current account endpoint still creates users.
"""
import json
import os
from pathlib import Path
import tempfile
import traceback

from playwright.sync_api import expect, sync_playwright
from test_admission_http_ack import running_server

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / 'qa/admin-p1'


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    report = {'status': 'failed', 'backend': 'SQLite', 'checks': [],
              'scope': 'Invitation navigation and account list refresh only'}
    try:
        with tempfile.TemporaryDirectory(prefix='eventna-admin-p1-') as folder:
            temp = Path(folder)
            with running_server(temp) as (base, staff), sync_playwright() as pw:
                admin = next(a for a in json.loads((temp / 'accounts.json').read_text())
                             if a['email'] == 'admin@pulsex.test')
                auth = staff.post('/api/auth/login', json=admin)
                auth.raise_for_status()
                staff.headers.update({'X-CSRF': auth.json()['csrf'], 'Origin': base})
                request = staff.post('/api/access-request', json={
                    'site_id': 'event-demo', 'name': 'P1 Pending Applicant',
                    'email': 'p1-pending@example.test'})
                request.raise_for_status()
                launch = {'args': ['--no-sandbox', '--disable-dev-shm-usage']}
                if os.environ.get('PX_CHROMIUM_EXECUTABLE'):
                    launch['executable_path'] = os.environ['PX_CHROMIUM_EXECUTABLE']
                browser = pw.chromium.launch(**launch)
                try:
                    report['browser_version'] = browser.version
                    context = browser.new_context(viewport={'width': 1440, 'height': 1000}, locale='ar-YE')
                    assert context.request.post(base + '/api/auth/login', data=admin).ok
                    page = context.new_page()
                    errors, posts = [], []
                    page.on('pageerror', lambda error: errors.append(str(error)))
                    page.on('request', lambda req: posts.append(req.url)
                            if req.method == 'POST' and req.url.endswith('/sites/agency-01/users') else None)
                    page.goto(base + '/admin')
                    workspace = page.get_by_label('مساحة العمل', exact=True)
                    workspace.select_option('event-demo')
                    invitations = page.locator('#admin-nav').get_by_role('button', name='الدعوات وتأكيد الحضور', exact=True)
                    expect(invitations).to_be_visible()

                    # Record saving exercises both save() and reload(), unlike a pure draft PUT.
                    page.locator('#admin-nav').get_by_role('button', name='الفعالية والخدمات', exact=True).click()
                    page.get_by_role('button', name='+ الخدمات', exact=True).click()
                    dialog = page.get_by_role('dialog')
                    dialog.get_by_label('رمز ثابت — أحرف وأرقام إنجليزية', exact=True).fill('p1-service')
                    dialog.get_by_label('العنوان', exact=True).fill('P1 Saved Service')
                    dialog.locator('button[type=submit]').click()
                    expect(dialog).to_have_count(0)
                    expect(invitations).to_be_visible()
                    expect(page.locator('#admin-nav .active')).to_have_text('الفعالية والخدمات')
                    expect(workspace).to_have_value('event-demo')
                    report['checks'].append('save_reload_retains_workspace_tab_and_invitation_permission')

                    invitations.click()
                    with page.expect_response(lambda r: r.url.endswith('/events/event-demo/permissions')):
                        page.get_by_role('button', name='نشر التغييرات', exact=True).click()
                    expect(page.locator('#admin-nav .active')).to_have_text('الدعوات وتأكيد الحضور')
                    expect(page.get_by_role('heading', level=1)).to_have_text('الدعوات وتأكيد الحضور')
                    expect(workspace).to_have_value('event-demo')
                    report['checks'].append('publish_retains_current_invitation_tab_without_relogin')

                    permission_path = '**/api/admin/events/event-demo/permissions'
                    page.route(permission_path, lambda route: route.fulfill(
                        status=503, json={'detail': 'P1_PERMISSIONS_UNAVAILABLE'}))
                    page.get_by_role('button', name='نشر التغييرات', exact=True).click()
                    expect(page.locator('#toasts')).to_contain_text('P1_PERMISSIONS_UNAVAILABLE')
                    expect(invitations).to_be_visible()
                    expect(page.locator('#admin-nav .active')).to_have_text('الدعوات وتأكيد الحضور')
                    page.unroute(permission_path)
                    report['checks'].append('failed_permission_reload_preserves_last_complete_workspace')

                    # A genuine permission change must hide the privileged tab, not retain stale rights.
                    page.route(permission_path, lambda route: route.fulfill(json={'permissions': []}))
                    page.get_by_role('button', name='نشر التغييرات', exact=True).click()
                    expect(invitations).to_have_count(0)
                    expect(page.locator('#admin-nav .active')).to_have_text('نظرة عامة')
                    expect(page.locator('#toasts')).to_contain_text('لم يعد التبويب السابق متاحًا')
                    page.unroute(permission_path)
                    report['checks'].append('revoked_permissions_remove_tab_and_explain_fallback')

                    page.locator('#admin-nav').get_by_role('button',name='طلبات الحسابات',exact=True).click()
                    expect(page.locator('.record-list article').filter(has_text='P1 Pending Applicant')).to_be_visible()
                    report['checks'].append('pending_requests_have_separate_review_queue')
                    workspace.select_option('agency-01')
                    page.locator('#admin-nav').get_by_role('button',name='الحسابات',exact=True).click()
                    accounts=page.locator('main > .record-list').first
                    name=page.get_by_label('اسم المستخدم',exact=True)
                    phone=page.get_by_label('رقم الهاتف',exact=True)
                    create=page.get_by_role('button',name='إرسال طلب حساب',exact=True)
                    name.fill('P1 Immediate Account');phone.fill('+967777992301')
                    with page.expect_response(lambda r:r.request.method=='POST' and r.url.endswith('/sites/agency-01/users')) as sent:
                        create.evaluate('(button)=>{button.click();button.click();}')
                    pending=sent.value.json()
                    expect(page.locator('main')).to_contain_text(pending['id'])
                    expect(accounts).not_to_contain_text('P1 Immediate Account')
                    expect(create).to_be_enabled();assert len(posts)==1
                    report['checks'].append('submission_receipt_is_immediate_and_pending_account_is_not_active')
                    organizer=next(a for a in json.loads((temp/'accounts.json').read_text()) if a['role']=='organizer')
                    reviewer=browser.new_context()
                    auth=reviewer.request.post(base+'/api/auth/login',data=organizer).json()
                    approved=reviewer.request.patch(base+'/api/admin/account-requests/'+pending['id'],data={'status':'approved'},headers={'X-CSRF':auth['csrf']})
                    assert approved.ok,approved.text()
                    assert reviewer.request.post(base+'/api/account-requests/password',data={'tracking_token':pending['tracking_token'],'password':'P1-Setup-Password-2026!','confirmation':'P1-Setup-Password-2026!'}).ok
                    reviewer.close()
                    page.get_by_role('button',name='تحديث قائمة الحسابات',exact=True).click()
                    expect(accounts).to_contain_text('P1 Immediate Account')
                    expect(page.locator('main')).to_contain_text(pending['id'])
                    row=accounts.locator('.record-line').filter(has_text='P1 Immediate Account')
                    row.get_by_role('button',name='إيقاف',exact=True).click();expect(row.locator('.tag')).to_have_text('موقوف')
                    row.get_by_role('button',name='تفعيل',exact=True).click();expect(row.locator('.tag')).to_have_text('نشط')
                    report['checks'].append('approved_account_refresh_and_status_mutations_keep_request_receipt')
                    name.fill('P1 Invalid Attempt');phone.fill('invalid')
                    create.click()
                    expect(page.locator('#toasts')).to_contain_text('أدخل رقم هاتف صحيحًا')
                    expect(name).to_have_value('P1 Invalid Attempt');expect(phone).to_have_value('invalid')
                    report['checks'].append('failed_submission_keeps_entered_data')
                    endpoint='**/api/admin/sites/agency-01/users'
                    def fail_refresh(route):
                        if route.request.method=='GET':route.fulfill(status=503,json={'detail':'P1_REFRESH_UNAVAILABLE'})
                        else:route.continue_()
                    page.route(endpoint,fail_refresh)
                    name.fill('P1 Refresh Retry Account');phone.fill('+967777992302')
                    create.click()
                    retry=page.get_by_role('button',name='إعادة تحميل القائمة',exact=True)
                    expect(retry).to_be_visible()
                    expect(page.locator('main')).to_contain_text('بانتظار الموافقة')
                    count=len(posts);page.unroute(endpoint,fail_refresh);retry.click()
                    expect(retry).to_have_count(0);assert len(posts)==count
                    expect(accounts).not_to_contain_text('P1 Refresh Retry Account')
                    report['checks'].append('refresh_failure_retry_never_duplicates_or_activates_pending_request')
                    page.set_viewport_size({'width': 390, 'height': 844})
                    assert page.evaluate('document.documentElement.scrollWidth<=innerWidth+1')
                    page.screenshot(path=str(OUT / 'mobile-accounts.png'), full_page=True)
                    assert not errors, errors
                    report['checks'].append('mobile_layout_and_no_javascript_errors')
                    report['status'] = 'passed'
                finally:
                    browser.close()
    except Exception as error:
        report.update(error_type=type(error).__name__, traceback=traceback.format_exc())
    finally:
        (OUT / 'browser.json').write_text(json.dumps(report, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
        print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0 if report['status'] == 'passed' else 1


if __name__ == '__main__':
    raise SystemExit(main())
