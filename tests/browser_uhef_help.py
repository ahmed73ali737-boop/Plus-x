"""Real HTTP Chromium: UHEF help on the Eventna screens (header button + F1, roadmap, journey
«أنت هنا», bot answer and refusal to support, copy-only report), every Studio tab, desktop 1440
and phone 390, no page errors."""
from pathlib import Path
import json, os, tempfile, traceback
from playwright.sync_api import sync_playwright
from test_admission_http_ack import running_server
ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / 'qa/uhef-help'
KNOWLEDGE = json.loads((ROOT / 'web/uhef-knowledge.json').read_text(encoding='utf-8'))

# Public screens: path, expected screen, header that must hold the button (None = floating).
PUBLIC = [('/', 'public.platform', 'header.site-topbar'), ('/e/demo', 'public.event', 'header.site-topbar'),
          ('/e/demo/p/agency-01', 'public.agency', 'header.site-topbar'), ('/e/demo/guest', 'guest.register', 'header.site-topbar'),
          ('/live/demo', 'live.wall', '.livewall-actions'), ('/start', 'access.start', 'header.access-header'),
          ('/account/signup', 'account.signup', 'header.access-header'), ('/admin', 'admin.login', None),
          ('/certificates/verify/not-a-token', 'selfcert.verify', None)]


def dismiss_welcome(page):
    """The optional visitor welcome dialog of public pages; help never depends on it."""
    page.wait_for_load_state('networkidle'); page.wait_for_timeout(300)
    for _ in range(3):
        if not page.locator('dialog.modal[open]').count(): return
        for name in ('الدخول دون بيانات', 'تخطي هذه الخطوة'):
            b = page.get_by_role('button', name=name, exact=True)
            if b.count() and b.first.is_visible(): b.first.click(); break
        page.wait_for_timeout(200)


def open_help(page, expected):
    page.keyboard.press('F1')
    dialog = page.locator('dialog#uhef-dialog[open]')
    dialog.wait_for()
    got = dialog.get_attribute('data-screen')
    assert got == expected, (got, expected)
    return dialog


def close_help(page):
    page.keyboard.press('Escape')
    page.locator('dialog#uhef-dialog[open]').wait_for(state='hidden')


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    report = {'status': 'failed', 'backend': 'SQLite', 'scope': 'Chromium HTTP; UHEF help only', 'checks': [], 'screens': []}
    def mark(name): report['checks'].append(name)
    try:
        with tempfile.TemporaryDirectory(prefix='px-uhef-') as folder:
            temp = Path(folder)
            with running_server(temp) as (base, staff), sync_playwright() as pw:
                admin = next(a for a in json.loads((temp / 'accounts.json').read_text()) if a['email'] == 'admin@pulsex.test')
                launch = {'args': ['--no-sandbox', '--disable-dev-shm-usage']}
                if os.environ.get('PX_CHROMIUM_EXECUTABLE'): launch['executable_path'] = os.environ['PX_CHROMIUM_EXECUTABLE']
                browser = pw.chromium.launch(**launch)
                try:
                    report['browser_version'] = browser.version
                    context = browser.new_context(viewport={'width': 1440, 'height': 1000}, locale='ar-YE', service_workers='block')
                    page = context.new_page()
                    errors = []; page.on('pageerror', lambda e: errors.append(str(e)))

                    for path, key, header in PUBLIC:
                        page.goto(base + path)
                        button = page.locator('#uhef-help')
                        button.wait_for(); dismiss_welcome(page)
                        if header:
                            page.locator(header + ' #uhef-help.uhef-inline').wait_for()
                        else:
                            assert button.get_attribute('class') == 'uhef-fab'
                        open_help(page, key); close_help(page)
                        report['screens'].append(key)
                    mark('header_button_and_f1_on_public_screens')

                    page.goto(base + '/e/demo')
                    dismiss_welcome(page)
                    page.locator('header.site-topbar #uhef-help').click()
                    dialog = page.locator('dialog#uhef-dialog[open]'); dialog.wait_for()
                    assert dialog.get_attribute('data-screen') == 'public.event'
                    assert dialog.get_by_role('heading', name='المساعدة: موقع الفعالية').count() == 1
                    tabs = [b.inner_text() for b in dialog.locator('.uhef-tabs button').all()]
                    assert tabs == ['الشاشة', 'الخريطة', 'الخطوات', 'الحقول', 'الترابط والرحلة', 'أسئلة', 'المساعد', 'الدعم'], tabs
                    dialog.get_by_role('tab', name='الخريطة').click()
                    assert dialog.locator('.uhef-part').count() == len(KNOWLEDGE['screens']['public.event']['parts'])
                    dialog.locator('.uhef-part').first.locator('.uhef-links button').first.wait_for()
                    mark('roadmap_parts_with_links')
                    dialog.get_by_role('tab', name='الترابط والرحلة').click()
                    here = dialog.locator('.uhef-journey li.uhef-here').first
                    assert 'أنت هنا' in here.inner_text()
                    mark('journey_you_are_here')

                    dialog.get_by_role('tab', name='المساعد').click()
                    page.evaluate("() => { window.__keys = 0; document.addEventListener('keydown', () => window.__keys++); return true; }")
                    ask = dialog.get_by_label('سؤالك للمساعد', exact=True)
                    ask.fill('ما هو وضع التاب؟'); ask.press('Enter')
                    answer = dialog.locator('.uhef-answer').first
                    answer.wait_for()
                    assert 'وضع كشك' in answer.inner_text() and 'المصدر: موقع الفعالية' in answer.inner_text()
                    assert page.evaluate('window.__keys') == 0, 'keys inside the panel reach the page'
                    mark('bot_answers_with_source_and_panel_keys_do_not_reach_the_app')
                    ask.fill('كم سعر تذكرة الطيران إلى القمر'); ask.press('Enter')
                    dialog.get_by_text('لم أجد إجابة موثقة لهذا السؤال، ولن أخمّن.', exact=False).first.wait_for()
                    dialog.get_by_role('button', name='أرسل السؤال للدعم').click()
                    desc = dialog.get_by_label('وصف البلاغ', exact=True)
                    assert desc.input_value() == 'كم سعر تذكرة الطيران إلى القمر'
                    desc.fill('رقمي 777123456 والمشكلة أن الصفحة لا تفتح')
                    dialog.get_by_role('button', name='نسخ البلاغ').click()
                    page.wait_for_function("() => document.getElementById('uhef-dialog').dataset.report")
                    copied = dialog.get_attribute('data-report')
                    assert 'screen=public.event page=/e/:event at=' in copied and '777123456' not in copied and '/e/demo' not in copied
                    mark('bot_refusal_hands_over_to_support_report_without_values')
                    page.screenshot(path=str(OUT / 'desktop-help.png'))
                    close_help(page)

                    assert context.request.post(base + '/api/auth/login', data=admin).ok
                    page.goto(base + '/admin')
                    page.locator('.admin-layout').wait_for()
                    by_label = {s['adminTab']: k for k, s in KNOWLEDGE['screens'].items() if s.get('adminTab')}
                    seen = set()
                    for workspace in ('platform', 'event-demo'):
                        if workspace != 'platform':
                            page.get_by_label('مساحة العمل', exact=True).select_option(workspace)
                            page.locator('#admin-nav').get_by_role('button', name='الزوار و QR', exact=True).wait_for()
                        labels = [x.inner_text().strip() for x in page.locator('#admin-nav .nav-item').all()]
                        for label in labels:
                            if label in seen: continue
                            page.locator('#admin-nav').get_by_role('button', name=label, exact=True).click()
                            if label == 'الشهادات':
                                # renderCertificates replaces the tab heading; the button then floats.
                                page.locator('.admin-main > h2', has_text=label).wait_for()
                                page.locator('body > #uhef-help.uhef-fab').wait_for()
                            else:
                                page.locator('.admin-heading h1', has_text=label).wait_for()
                                page.locator('.admin-heading #uhef-help.uhef-inline').wait_for()
                            open_help(page, by_label[label]); close_help(page)
                            seen.add(label); report['screens'].append(by_label[label])
                    assert seen == set(by_label), sorted(set(by_label) - seen)
                    mark('every_visible_studio_tab_has_its_own_help_and_button_reattaches')
                    page.locator('#admin-nav').get_by_role('button', name='الأجهزة والطرفيات', exact=True).click()
                    page.locator('.admin-heading h1', has_text='الأجهزة والطرفيات').wait_for()
                    dialog = open_help(page, 'admin.devices')
                    dialog.get_by_role('tab', name='الحقول').click()
                    assert dialog.locator('details.uhef-field[data-field="device_type"]').count() == 1
                    close_help(page)
                    mark('studio_fields_tab')

                    phone = browser.new_context(viewport={'width': 390, 'height': 844}, locale='ar-YE', service_workers='block', is_mobile=True, has_touch=True)
                    mpage = phone.new_page(); mpage.on('pageerror', lambda e: errors.append(str(e)))
                    for path in ('/e/demo', '/start', '/admin'):
                        mpage.goto(base + path)
                        mpage.locator('#uhef-help').wait_for(); dismiss_welcome(mpage)
                        assert mpage.locator('#uhef-help').is_visible()
                        assert mpage.evaluate('document.documentElement.scrollWidth<=innerWidth+1'), path
                    mpage.locator('#uhef-help').click()
                    mdialog = mpage.locator('dialog#uhef-dialog[open]'); mdialog.wait_for()
                    box = mdialog.bounding_box()
                    assert box['width'] <= 391 and box['x'] >= -1
                    mdialog.get_by_role('tab', name='الترابط والرحلة').click()
                    assert 'أنت هنا' in mdialog.locator('.uhef-here').first.inner_text()
                    mpage.screenshot(path=str(OUT / 'mobile-help.png'))
                    mark('phone_390_button_visible_no_overflow_panel_fits')
                    phone.close()
                    assert not errors, errors
                    mark('no_page_errors')
                    report['status'] = 'passed'
                finally:
                    browser.close()
    except Exception as error:
        report.update(error_type=type(error).__name__, traceback=traceback.format_exc())
    finally:
        report['screens_checked'] = len(set(report['screens']))
        (OUT / 'browser.json').write_text(json.dumps(report, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    print(json.dumps({k: report[k] for k in ('status', 'checks', 'screens_checked')}, ensure_ascii=False))
    return 0 if report['status'] == 'passed' else 1


if __name__ == '__main__': raise SystemExit(main())
