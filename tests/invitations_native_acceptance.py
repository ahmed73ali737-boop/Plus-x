"""Real HTTP + Chromium invitation journeys against a disposable SQLite database.

This is native browser acceptance, not native PostgreSQL or camera hardware QA.
Optional PX_CHROMIUM_EXECUTABLE selects an installed browser for constrained hosts.
"""
from __future__ import annotations
from harness_support import sqlite_connection
import json
import os
import socket
import subprocess
import sys
import tempfile
import time
import traceback
import uuid
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo
import httpx
from playwright.sync_api import sync_playwright, expect

ROOT = Path(__file__).resolve().parents[1]
QA = ROOT / 'qa' / 'invitations'


def wait_for_qr(page, selector):
    # Locator assertions poll the image property without evaluating an expression
    # string, which strict CSP correctly rejects on some Chromium versions.
    image = page.locator(selector).first
    expect(image).not_to_have_js_property('naturalWidth', 0, timeout=30000)
    assert image.evaluate('(element) => element.naturalWidth') > 20


def main():
    QA.mkdir(parents=True, exist_ok=True)
    checks, page_errors = [], []
    report = {'status': 'failed', 'backend': 'SQLite', 'native_browser': True,
              'physical_camera_tested': False, 'native_postgresql_tested': False,
              'checks': checks, 'page_errors': page_errors}
    def mark(name):
        checks.append(name)
        print('PASS', name, flush=True)
    def ok(response):
        assert response.status_code == 200, (response.status_code, response.text)
        return response.json()
    with tempfile.TemporaryDirectory(prefix='pulsex-invitation-browser-') as td:
        temp = Path(td)
        with socket.socket() as sock:
            sock.bind(('127.0.0.1', 0))
            port = sock.getsockname()[1]
        base = f'http://127.0.0.1:{port}'
        env = {**os.environ, 'HOST': '127.0.0.1', 'PORT': str(port), 'PUBLIC_ORIGIN': base,
               'DATABASE_URL': 'sqlite:///' + str(temp / 'test.sqlite'),
               'CREDENTIALS_PATH': str(temp / 'accounts.json'), 'MEDIA_DIR': str(temp / 'media'),
               'REQUIRE_POSTGRES': 'false', 'SEED_DEMO': 'true'}
        with (QA / 'server.log').open('w', encoding='utf-8') as log:
            proc = subprocess.Popen([sys.executable, 'run.py'], cwd=ROOT, env=env, stdout=log, stderr=log)
            try:
                with httpx.Client(base_url=base, timeout=20, trust_env=False) as staff:
                    for _ in range(150):
                        try:
                            if staff.get('/api/health').status_code == 200:
                                break
                        except httpx.HTTPError:
                            pass
                        if proc.poll() is not None:
                            raise RuntimeError('Server failed: ' + (QA / 'server.log').read_text()[-4000:])
                        time.sleep(.1)
                    else:
                        raise RuntimeError('Server startup timeout')
                    accounts = json.loads((temp / 'accounts.json').read_text())
                    organizer = next(row for row in accounts if row['email'] == 'organizer@pulsex.test')
                    auth = ok(staff.post('/api/auth/login', json={'email': organizer['email'], 'password': organizer['password']}))
                    staff.headers.update({'X-CSRF': auth['csrf'], 'Origin': base})
                    path = '/api/admin/events/event-demo'
                    day = datetime.now(ZoneInfo('Asia/Aden')).date().isoformat()
                    policy = ok(staff.put(path + '/admission-policy', json={
                        'enabled': True, 'visibility': 'private', 'timezone': 'Asia/Aden',
                        'registration_mode': 'manual', 'entry_mode': 'daily', 'max_companions': 2,
                        'days': [{'date': day, 'capacity': 20}]}))['policy']
                    guest_list = ok(staff.post(path + '/guest-lists', json={'name': 'ضيوف تجربة المتصفح'}))
                    invite = ok(staff.post(path + '/invitations', json={
                        'name': 'ضيف الاختبار', 'phone': '+967777660001', 'list_id': guest_list['id'],
                        'max_companions': 2, 'days': [day]}))
                    token, invitation_id = invite['token'], invite['invitation']['id']
                    mark('real_http_policy_list_and_invitation_created')
                    with httpx.Client(base_url=base, trust_env=False) as public:
                        assert public.get('/api/public/site/demo').status_code in (403, 404)
                        assert public.get('/api/public/site/agency-01').status_code in (403, 404)
                        assert public.get('/api/public/events/demo/registration').status_code in (403, 404)
                        assert not any(row['id'] == 'event-demo' for row in ok(public.get('/api/public/site/platform'))['events'])
                        mark('private_event_hidden_from_catalog_and_public_bundles')
                    with sync_playwright() as pw:
                        launch = {'args': ['--no-sandbox', '--disable-dev-shm-usage', '--disable-gpu']}
                        if os.getenv('PX_CHROMIUM_EXECUTABLE'):
                            launch['executable_path'] = os.environ['PX_CHROMIUM_EXECUTABLE']
                        browser = pw.chromium.launch(**launch)
                        report['browser_version'] = browser.version
                        mobile_ctx = browser.new_context(viewport={'width': 390, 'height': 844}, is_mobile=True, locale='ar-YE')
                        mobile = mobile_ctx.new_page()
                        mobile.on('pageerror', lambda error: page_errors.append(str(error)))
                        mobile.on('console', lambda message: report.setdefault('console_errors', []).append(message.text) if message.type == 'error' else None)
                        mobile.goto(base + '/invite/' + token)
                        try:
                            mobile.get_by_role('heading', name='هل ستنضم إلينا؟', exact=True).wait_for(timeout=15000)
                        except Exception:
                            report['failure_body'] = mobile.locator('body').inner_text()
                            mobile.screenshot(path=str(QA / 'failure-mobile.png'), full_page=True)
                            raise
                        assert mobile.locator('img.inv-qr').count() == 0
                        assert mobile.evaluate('document.documentElement.scrollWidth <= innerWidth + 1')
                        mark('private_invitation_mobile_page_no_overflow_or_premature_qr')
                        mobile.get_by_label('عدد المرافقين', exact=True).fill('3')
                        assert not mobile.get_by_label('عدد المرافقين', exact=True).evaluate('el => el.checkValidity()')
                        mobile.get_by_label('عدد المرافقين', exact=True).fill('1')
                        mobile.get_by_role('button', name='تأكيد الحضور', exact=True).click()
                        mobile.get_by_text('يلزم الموافقة على استخدام البيانات لتنظيم الحضور.', exact=True).wait_for()
                        mark('rsvp_companion_bound_and_consent_validation')
                        mobile.get_by_label('أوافق على استخدام بياناتي لتنظيم الدعوة والحضور.', exact=True).check()
                        mobile.get_by_role('button', name='تأكيد الحضور', exact=True).click()
                        mobile.get_by_text('تم استلام ردك، وهو قيد مراجعة المنظم.', exact=True).wait_for()
                        assert mobile.locator('img.inv-qr').count() == 0
                        mark('mobile_rsvp_manual_pending_without_pass')
                        current = next(row for row in ok(staff.get(path + '/invitations'))['invitations'] if row['id'] == invitation_id)
                        ok(staff.post(path + '/invitations/' + invitation_id + '/review', json={'decision': 'approve', 'revision': current['revision']}))
                        mobile.get_by_role('button', name='تحديث حالة الطلب', exact=True).click()
                        mobile.get_by_role('heading', name='ننتظرك في الفعالية', exact=True).wait_for()
                        mobile.locator('img.inv-qr').wait_for()
                        wait_for_qr(mobile, 'img.inv-qr')
                        number = mobile.locator('.inv-pass-number').inner_text()
                        assert number.startswith('G-')
                        assert mobile.evaluate('document.documentElement.scrollWidth <= innerWidth + 1')
                        assert mobile.locator('.inv-pass-number').evaluate('el => el.scrollWidth <= el.clientWidth + 1')
                        mobile.screenshot(path=str(QA / 'private-approved-mobile.png'), full_page=True)
                        mark('approved_rsvp_shows_real_qr_and_companions_on_mobile')
                        mobile.get_by_role('link', name='عرض بطاقة الدخول', exact=True).click()
                        mobile.locator('img.guest-qr').wait_for()
                        wait_for_qr(mobile, 'img.guest-qr')
                        assert number in mobile.locator('body').inner_text()
                        mark('private_guest_pass_link_renders_without_public_event_disclosure')
                        desktop_ctx = browser.new_context(viewport={'width': 1440, 'height': 1000}, locale='ar-YE')
                        desktop = desktop_ctx.new_page()
                        desktop.on('pageerror', lambda error: page_errors.append(str(error)))
                        desktop.goto(base + '/admin')
                        desktop.get_by_label('البريد الإلكتروني', exact=True).fill(organizer['email'])
                        desktop.get_by_label('كلمة المرور', exact=True).fill(organizer['password'])
                        desktop.get_by_role('button', name='تسجيل الدخول', exact=True).click()
                        desktop.get_by_role('heading', name='نظرة عامة', exact=True).wait_for()
                        desktop.get_by_role('button', name='الأجهزة والطرفيات', exact=True).click()
                        desktop.get_by_label('اسم الجهاز', exact=True).fill('Invitation QA Gate')
                        desktop.get_by_label('نوع الطرفية', exact=True).select_option('operator')
                        desktop.get_by_role('button', name='إنشاء وربط الطرفية', exact=True).click()
                        desktop.get_by_role('button', name='ربط هذا المتصفح بهذه الطرفية', exact=True).click()
                        desktop.get_by_role('button', name='تم ربط بوابة المسح', exact=True).wait_for()
                        desktop.goto(base + '/e/demo/scan')
                        desktop.get_by_role('heading', name='بوابة الدخول والتحقق', exact=True).wait_for()
                        desktop.get_by_label('امسح QR أو ابحث بالاسم / الجهة / رقم الزائر', exact=True).fill(number)
                        desktop.get_by_role('button', name='بحث / فتح', exact=True).click()
                        desktop.get_by_text(number, exact=True).wait_for()
                        desktop.screenshot(path=str(QA / 'private-scanner-desktop.png'), full_page=True)
                        mark('paired_private_gate_resolves_approved_pass')
                        desktop_ctx.set_offline(True)
                        desktop.get_by_role('button', name='تسجيل دخول', exact=True).click()
                        desktop.get_by_text('هذه الدعوة تحتاج تأكيد الخادم. اتصل بشبكة الفعالية المحلية أو بالإنترنت؛ لا تسمح بالدخول قبل التأكيد.', exact=True).first.wait_for()
                        assert desktop.evaluate("async()=>{const m=await import('/assets/offline.mjs');return (await m.all('checkin_outbox')).length}") == 0
                        desktop_ctx.set_offline(False)
                        desktop.evaluate("window.dispatchEvent(new Event('online'))")
                        mark('managed_invitation_fails_closed_when_scanner_disconnected')
                        desktop.get_by_label('عدد الأشخاص الداخلين الآن', exact=True).fill('1')
                        desktop.get_by_role('button', name='تسجيل دخول', exact=True).click()
                        desktop.get_by_text('أكد الخادم تسجيل الدخول.', exact=True).first.wait_for()
                        desktop.get_by_text('يلزم تأكيد الخادم لكل دفعة. المتبقي: 1', exact=True).wait_for()
                        desktop.get_by_role('button', name='تسجيل دخول', exact=True).click()
                        desktop.get_by_text('اكتمل العدد المسموح بهذه الدعوة لهذا اليوم.', exact=True).wait_for()
                        summary = ok(staff.get(path + '/guest-checkins'))
                        assert summary['admitted_people'] == 2, summary
                        mark('scanner_companions_admitted_in_two_batches_then_blocked')
                        desktop.get_by_label('وضع المسح', exact=True).select_option('exit')
                        desktop.get_by_role('button', name='بحث / فتح', exact=True).click()
                        desktop.get_by_role('button', name='تسجيل خروج', exact=True).click()
                        desktop.get_by_text('أكد الخادم تسجيل الخروج.', exact=True).first.wait_for()
                        mark('fully_consumed_invitation_still_allows_exit')
                        # Revoke using the authorized organizer and verify a fresh public request.
                        ok(staff.post(path + '/invitations/' + invitation_id + '/revoke'))
                        mobile.goto(base + '/invite/' + token)
                        mobile.get_by_text('أُلغيت الدعوة', exact=True).first.wait_for()
                        assert mobile.locator('img.inv-qr').count() == 0
                        with httpx.Client(base_url=base, trust_env=False) as public:
                            revoked = public.get('/api/public/events/demo/guests/' + number + '/qr')
                            assert revoked.status_code == 410 and revoked.json()['detail'] == 'GUEST_PASS_INACTIVE', (revoked.status_code, revoked.text)
                        mark('revocation_removes_qr_and_invalidates_pass_endpoint')
                        mobile.goto(base + '/e/demo/guest/' + number)
                        mobile.get_by_role('heading', name='تعذر العثور على بطاقة الزائر', exact=True).wait_for()
                        assert mobile.locator('img.guest-qr').count() == 0
                        assert mobile.evaluate("async()=>{const m=await import('/assets/offline.mjs');return (await m.all('guests')).filter(g=>g.guest_number===" + json.dumps(number) + "&&g.qr_data_url).length}") == 0
                        mark('revoked_cached_pass_is_removed_on_online_refresh')
                        policy = ok(staff.get(path + '/admission-policy'))['policy']
                        policy.update(visibility='public', registration_mode='auto')
                        ok(staff.put(path + '/admission-policy', json=policy))
                        mobile.goto(base + '/e/demo/register')
                        mobile.get_by_label('الاسم', exact=True).fill('زائر التسجيل الذاتي')
                        mobile.get_by_label('رقم الهاتف', exact=True).fill('+967777660002')
                        mobile.locator('input[name="attendance_days"]').first.check()
                        mobile.get_by_label('أوافق على استخدام بياناتي لتنظيم الحضور.', exact=True).check()
                        mobile.get_by_role('button', name='تأكيد التسجيل', exact=True).click()
                        mobile.get_by_role('heading', name='ننتظرك في الفعالية', exact=True).wait_for()
                        wait_for_qr(mobile, 'img.inv-qr')
                        assert mobile.evaluate('document.documentElement.scrollWidth <= innerWidth + 1')
                        mobile.screenshot(path=str(QA / 'public-registration-mobile.png'), full_page=True)
                        mark('public_self_registration_ui_to_approved_pass')
                        with httpx.Client(base_url=base, trust_env=False) as public:
                            replay = ok(public.post('/api/public/events/demo/registration', json={'name': 'Other', 'phone': '+967777660002', 'days': [day], 'consent': True}))
                            assert replay.get('verification_required') and 'token' not in replay and 'guest_number' not in replay
                        mark('phone_only_registration_does_not_recover_existing_pass')
                        new_number = mobile.locator('.inv-pass-number').inner_text()
                        crew = ok(staff.post(path + '/committee', json={
                            'create_account': True, 'email': 'scanner-qa@example.test',
                            'name': 'موظف المسح', 'role': 'scanner'}))
                        assert crew.get('temporary_password')
                        crew_ctx = browser.new_context(viewport={'width': 1280, 'height': 900}, locale='ar-YE')
                        crew_page = crew_ctx.new_page()
                        crew_page.on('pageerror', lambda error: page_errors.append(str(error)))
                        crew_page.goto(base + '/admin')
                        crew_page.get_by_label('البريد الإلكتروني', exact=True).fill('scanner-qa@example.test')
                        crew_page.get_by_label('كلمة المرور', exact=True).fill(crew['temporary_password'])
                        crew_page.get_by_role('button', name='تسجيل الدخول', exact=True).click()
                        crew_page.get_by_role('heading', name='غيّر كلمة المرور المؤقتة', exact=True).wait_for()
                        crew_page.get_by_label('كلمة المرور المؤقتة الحالية', exact=True).fill(crew['temporary_password'])
                        crew_page.get_by_label('كلمة المرور الجديدة — 12 حرفًا على الأقل', exact=True).fill('PrivateScannerQA42!')
                        crew_page.get_by_role('button', name='تغيير كلمة المرور والمتابعة', exact=True).click()
                        crew_page.get_by_role('heading', name='دخول الإدارة والجهات', exact=True).wait_for()
                        crew_page.get_by_label('البريد الإلكتروني', exact=True).fill('scanner-qa@example.test')
                        crew_page.get_by_label('كلمة المرور', exact=True).fill('PrivateScannerQA42!')
                        crew_page.get_by_role('button', name='تسجيل الدخول', exact=True).click()
                        crew_page.get_by_label('بحث بالاسم أو رقم التذكرة', exact=True).wait_for()
                        assert crew_page.get_by_role('button', name='نشر التغييرات', exact=True).count() == 0
                        assert crew_page.get_by_role('button', name='إدخال الأسئلة', exact=True).count() == 0
                        assert crew_page.get_by_role('button', name='الدعوات والحضور', exact=True).count() == 0
                        crew_page.get_by_label('بحث بالاسم أو رقم التذكرة', exact=True).fill(new_number)
                        # Real HTTP fault injection: first 503 before commit, then
                        # server commit with the response deliberately lost, then
                        # reload and replay the exact same session-scoped scan ID.
                        attempts=[]
                        def admission_fault(route):
                            if route.request.method!='POST':
                                route.continue_();return
                            attempts.append(route.request.post_data_json)
                            if len(attempts)==1:
                                route.fulfill(status=503,json={'detail':'TEST_BEFORE_COMMIT'});return
                            response=route.fetch()
                            if len(attempts)==2:
                                assert response.json()['status']=='accepted'
                                route.abort('failed');return
                            assert response.json()['status']=='duplicate'
                            route.fulfill(response=response)
                        crew_page.route('**/api/admin/events/event-demo/guest-checkins',admission_fault)
                        crew_page.get_by_role('button', name='تسجيل الدخول', exact=True).click()
                        crew_page.locator('article[data-state="unknown-outcome"]').wait_for()
                        crew_page.get_by_role('button', name='تسجيل الدخول', exact=True).click()
                        crew_page.locator('article[data-state="unknown-outcome"]').wait_for()
                        assert len(attempts)==2
                        before_replay=ok(staff.get(path+'/guest-checkins'))
                        crew_page.reload()
                        crew_page.get_by_label('بحث بالاسم أو رقم التذكرة',exact=True).fill(new_number)
                        def fail_counters(route):
                            if route.request.method=='GET':route.fulfill(status=503,json={'detail':'TEST_COUNTER_FAILURE'})
                            else:admission_fault(route)
                        crew_page.unroute('**/api/admin/events/event-demo/guest-checkins',admission_fault)
                        crew_page.route('**/api/admin/events/event-demo/guest-checkins',fail_counters)
                        crew_page.get_by_role('button', name='تسجيل الدخول', exact=True).click()
                        crew_page.locator('article[data-state="confirmed"]').wait_for()
                        crew_page.get_by_text('سبق تسجيل العملية', exact=True).first.wait_for()
                        crew_page.locator('.admission-live[data-state="stale"]').wait_for()
                        assert len(attempts)==3
                        assert all(x['scan_id']==attempts[0]['scan_id'] and x['quantity']==attempts[0]['quantity'] for x in attempts)
                        after_replay=ok(staff.get(path+'/guest-checkins'))
                        for key in ('total_checkins','admitted_people','inside_count'):
                            assert before_replay[key]==after_replay[key]
                        import sqlite3
                        with sqlite_connection(temp/'test.sqlite') as db:
                            scan_id=attempts[0]['scan_id']
                            assert db.execute('SELECT count(*) FROM px_guest_checkins WHERE id=?',(scan_id,)).fetchone()[0]==1
                            assert db.execute('SELECT count(*) FROM px_admission_uses WHERE scan_id=?',(scan_id,)).fetchone()[0]==1
                        mark('desk_503_lost_ack_reload_replay_one_ledger_and_stale_counters')
                        crew_page.screenshot(path=str(QA / 'limited-scanner-role-desktop.png'), full_page=True)
                        mark('new_scanner_account_password_change_and_limited_checkin_ui')
                        assert crew_page.request.get(base + '/api/admin/sites/event-demo').status == 403
                        assert crew_page.request.get(base + path + '/guests/export').status == 403
                        mark('scanner_cannot_read_editor_or_export_guests')
                        crew_ctx.close()
                        assert not page_errors, page_errors
                        mark('no_uncaught_browser_javascript_errors')
                        browser.close()
                    report['status'] = 'passed'
            except Exception as error:
                report['error'] = str(error)
                report['traceback'] = traceback.format_exc()
                raise
            finally:
                proc.terminate()
                try:
                    proc.wait(timeout=10)
                except subprocess.TimeoutExpired:
                    proc.kill()
                    proc.wait(timeout=5)
                report['passed'] = len(checks)
                (QA / 'browser-acceptance.json').write_text(json.dumps(report, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
                print(json.dumps(report, ensure_ascii=False, indent=2), flush=True)


if __name__ == '__main__':
    main()
