"""Native Chromium commands for invitation administration, imports and committee roles.

Runs a disposable SQLite server. Screens are operated, then HTTP/database state
is checked separately. No production accounts or old audit databases are used.
"""
from pathlib import Path
from contextlib import contextmanager
import os,sys,json,subprocess,tempfile,socket,time,traceback,uuid
import httpx
from playwright.sync_api import sync_playwright,expect

ROOT=Path(__file__).resolve().parents[1]
QA=ROOT/'qa/functional-workflows'
BASE='/api/admin/events/event-demo'


def main():
    QA.mkdir(parents=True,exist_ok=True);cases=[];errors=[]
    def mark(name,detail=None):
        cases.append({'name':name,'status':'passed','detail':detail});print('PASS',name,flush=True)
    @contextmanager
    def scenario(name, fatal=True):
        try:
            yield
            mark(name)
        except Exception as exc:
            cases.append({'name':name,'status':'failed','reason':str(exc),'traceback':traceback.format_exc()})
            if fatal:raise
    with tempfile.TemporaryDirectory(prefix='pulsex-functional-workflows-') as td:
        tmp=Path(td)
        with socket.socket() as sock:sock.bind(('127.0.0.1',0));port=sock.getsockname()[1]
        origin=f'http://127.0.0.1:{port}'
        env={**os.environ,'HOST':'127.0.0.1','PORT':str(port),'PUBLIC_ORIGIN':origin,'DATABASE_URL':'sqlite:///'+str(tmp/'db.sqlite'),'CREDENTIALS_PATH':str(tmp/'accounts.json'),'MEDIA_DIR':str(tmp/'media'),'SEED_DEMO':'true','REQUIRE_POSTGRES':'false','PULSEX_ENV':'test'}
        with (QA/'server.log').open('w',encoding='utf-8') as log:
            proc=subprocess.Popen([sys.executable,'run.py'],cwd=ROOT,env=env,stdout=log,stderr=log)
            try:
                with httpx.Client(base_url=origin,timeout=20,trust_env=False) as staff:
                    for _ in range(150):
                        try:
                            if staff.get('/api/health').status_code==200:break
                        except httpx.HTTPError:pass
                        time.sleep(.1)
                    else:raise RuntimeError('Functional server startup failed')
                    account=next(x for x in json.loads((tmp/'accounts.json').read_text()) if x['role']=='organizer')
                    auth=staff.post('/api/auth/login',json={'email':account['email'],'password':account['password']}).json()
                    staff.headers.update({'X-CSRF':auth['csrf'],'Origin':origin})
                    def api(path,body=None,method='GET',code=200):
                        r=staff.request(method,path,json=body);assert r.status_code==code,(path,r.status_code,r.text[:400]);return r.json()
                    def rows():return api(BASE+'/invitations')['invitations']
                    with sync_playwright() as pw:
                        browser=pw.chromium.launch(args=['--no-sandbox','--disable-dev-shm-usage'])
                        ctx=browser.new_context(viewport={'width':1440,'height':1050},locale='ar-YE')
                        page=ctx.new_page();page.on('pageerror',lambda e:errors.append(str(e)))
                        page.goto(origin+'/admin');page.get_by_label('البريد الإلكتروني',exact=True).fill(account['email']);page.get_by_label('كلمة المرور',exact=True).fill(account['password']);page.get_by_role('button',name='تسجيل الدخول',exact=True).click()
                        page.get_by_role('heading',name='نظرة عامة',exact=True).wait_for()
                        def nav(label):page.locator('#admin-nav').get_by_role('button',name=label,exact=True).click();page.get_by_role('heading',name=label,exact=True,level=1).wait_for()
                        def tab(label):page.get_by_role('tab',name=label,exact=True).click()
                        def close_dialog():page.locator('dialog[open]').last.get_by_role('button',name='×',exact=True).click()
                        with scenario('sections_screen_save_persists_visibility_order_layout_and_preview_count'):
                            nav('أقسام الصفحة');row=page.locator('.section-edit').first
                            title=row.get_by_label('اسم القسم',exact=True);old_title=title.input_value();new_title='QA '+uuid.uuid4().hex[:6]
                            title.fill(new_title);row.get_by_label('الترتيب',exact=True).fill('7');row.get_by_label('نموذج العرض',exact=True).select_option('list');row.get_by_label('عدد العناصر في الرئيسية',exact=True).fill('4')
                            with page.expect_response(lambda r:r.url.endswith('/api/admin/sites/event-demo') and r.request.method=='PUT') as saved:page.get_by_role('button',name='حفظ إعدادات الأقسام',exact=True).click()
                            assert saved.value.status==200
                            section=next(x for x in api('/api/admin/sites/event-demo')['draft']['sections'] if x['title']==new_title)
                            assert section['order']==7 and section['layout']=='list' and section['preview_count']==4
                        with scenario('organizations_screen_adds_and_rereads_person_without_creating_account'):
                            nav('المؤسسات والمشاركات');org=page.locator('article.card').first
                            org_name=org.locator('h3').inner_text();org_id=next(x['id'] for x in api('/api/admin/organizations')['organizations'] if x['name']==org_name)
                            org.get_by_role('button',name='الفريق / أعضاء بدون حساب',exact=True).click()
                            dialog=page.locator('dialog[open]').last;person_name='QA Person '+uuid.uuid4().hex[:6];person_email='qa-'+uuid.uuid4().hex[:8]+'@example.test'
                            dialog.get_by_label('اسم العضو / الممثل',exact=True).fill(person_name);dialog.get_by_label('المسمى الوظيفي',exact=True).fill('Functional Tester');dialog.get_by_label('البريد — اختياري',exact=True).fill(person_email)
                            dialog.get_by_role('button',name='إضافة العضو',exact=True).click()
                            refreshed=page.locator('dialog[open]').last;expect(refreshed.get_by_text(person_name,exact=True)).to_be_visible()
                            people=api('/api/admin/organizations/'+org_id+'/people')['people'];created=next(x for x in people if x['email']==person_email)
                            assert created['name']==person_name and created['job_title']=='Functional Tester' and created['user_id'] is None
                            refreshed.get_by_role('button',name='×',exact=True).click()
                        with scenario('organization_create_without_account_and_edit_its_event_participation'):
                            nav('المؤسسات والمشاركات');new_org='QA Org '+uuid.uuid4().hex[:6];new_slug='qa-'+uuid.uuid4().hex[:10]
                            page.get_by_label('اسم المؤسسة',exact=True).fill(new_org);page.get_by_label('رمز المؤسسة بالإنجليزية',exact=True).fill(new_slug)
                            with page.expect_response(lambda r:r.url.endswith('/api/admin/organizations') and r.request.method=='POST') as created_org:page.get_by_role('button',name='إنشاء المؤسسة وربطها بالفعالية الحالية',exact=True).click()
                            assert created_org.value.status==200
                            organization_id=created_org.value.json()['id']
                            org_card=page.locator('article.card').filter(has=page.get_by_role('heading',name=new_org,exact=True));org_card.get_by_role('button',name='إدارة',exact=True).click()
                            d=page.locator('dialog[open]').last;d.get_by_label('نوع المشاركة',exact=True).select_option('sponsor');d.get_by_label('الجناح',exact=True).fill('QA-42');d.get_by_label('الحالة',exact=True).select_option('suspended')
                            with page.expect_response(lambda r:'/api/admin/participations/' in r.url and r.request.method=='PATCH') as changed:d.get_by_role('button',name='حفظ التغييرات',exact=True).click()
                            assert changed.value.status==200
                            event_part=next(x for x in api(BASE+'/participations')['participations'] if x['organization_id']==organization_id)
                            assert event_part['status']=='suspended' and event_part['participation_type']=='sponsor' and event_part['booth']=='QA-42'
                        with scenario('organization_user_creation_and_membership_role_status_changes_from_ui'):
                            nav('المؤسسات والمشاركات');org_card=page.locator('article.card').filter(has=page.get_by_role('heading',name=new_org,exact=True));org_card.get_by_role('button',name='إضافة مستخدم',exact=True).click()
                            d=page.locator('dialog[open]').last;member_email='qa-member-'+uuid.uuid4().hex[:8]+'@pulsex.test'
                            d.get_by_label('اسم المستخدم',exact=True).fill('QA Member');d.get_by_label('البريد',exact=True).fill(member_email);d.get_by_label('دوره داخل المؤسسة',exact=True).select_option('editor')
                            with page.expect_response(lambda r:r.url.endswith('/users') and r.request.method=='POST') as linked:d.get_by_role('button',name='إنشاء / ربط العضوية',exact=True).click()
                            assert linked.value.status==200;close_dialog()
                            org_card.get_by_role('button',name='عضويات الحسابات',exact=True).click();d=page.locator('dialog[open]').last
                            d.get_by_label('الدور',exact=True).select_option('analyst');d.get_by_label('حالة العضوية',exact=True).select_option('suspended')
                            with page.expect_response(lambda r:'/members/' in r.url and r.request.method=='PATCH') as changed:d.get_by_role('button',name='حفظ العضوية',exact=True).click()
                            assert changed.value.status==200
                            member=next(x for x in api('/api/admin/organizations/'+organization_id+'/members')['members'] if x['email']==member_email)
                            assert member['role']=='analyst' and member['status']=='suspended';close_dialog()
                        with scenario('storyboard_keyboard_button_reorders_draft_and_persists_on_reload'):
                            nav('ترتيب التجربة');first=page.locator('.storyboard-card').first;first_code=first.get_attribute('data-code')
                            with page.expect_response(lambda r:r.url.endswith('/api/admin/sites/event-demo') and r.request.method=='PUT') as moved:first.get_by_role('button',name='↓ تأخير',exact=True).click()
                            assert moved.value.status==200
                            records=sorted(api('/api/admin/sites/event-demo')['draft']['records'],key=lambda r:r['order'])
                            assert records[1]['code']==first_code
                            nav('نظرة عامة');nav('ترتيب التجربة');assert page.locator('.storyboard-card').nth(1).get_attribute('data-code')==first_code
                        with scenario('metrics_export_and_print_controls_execute_from_actual_screen'):
                            nav('النتائج والتقارير')
                            with page.expect_download() as downloaded:page.get_by_role('link',name='تصدير CSV — بيانات هذه المساحة فقط',exact=True).click()
                            path=downloaded.value.path();assert path and Path(path).stat().st_size>0
                            page.evaluate('()=>{window.__qaPrinted=0;window.print=()=>window.__qaPrinted++;}')
                            page.get_by_role('button',name='طباعة التقرير / حفظ PDF من المتصفح',exact=True).click();assert page.evaluate('window.__qaPrinted')==1
                        with scenario('identity_saved_as_draft_then_publish_changes_public_projection'):
                            before=api('/api/public/site/demo')['config']['title']
                            nav('الهوية والقالب');page.get_by_label('اسم المنصة / الفعالية / الجهة',exact=True).fill('Functional Screen Event')
                            with page.expect_response(lambda r:r.url.endswith('/api/admin/sites/event-demo') and r.request.method=='PUT') as result:page.get_by_role('button',name='حفظ الهوية والتصميم كمسودة',exact=True).click()
                            assert result.value.status==200
                            assert api('/api/admin/sites/event-demo')['draft']['title']=='Functional Screen Event'
                            assert api('/api/public/site/demo')['config']['title']==before
                            with page.expect_response(lambda r:r.url.endswith('/publish')) as published:page.get_by_role('button',name='نشر التغييرات',exact=True).click()
                            assert published.value.status==200 and api('/api/public/site/demo')['config']['title']=='Functional Screen Event'
                        # Operate each generic content editor, including edit/delete and published snapshots.
                        materials=[('participant','المشاركون','الفعالية والخدمات'),('sponsor','الرعاة','الفعالية والخدمات'),('session','البرنامج والأحداث','الفعالية والخدمات'),('place','الأماكن والمخططات','الفعالية والخدمات'),('service','الخدمات','الفعالية والخدمات'),('media','مكتبة العرض','الفعالية والخدمات'),('contact','التواصل','الفعالية والخدمات'),('news','المستجدات','الفعالية والخدمات'),('ad','الإعلانات','الإعلانات والعروض'),('offer','العروض','الإعلانات والعروض'),('fact','الحقائق والإحصائيات','الحقائق والأرقام')]
                        for kind,label,screen in materials:
                            with scenario('native_create_edit_delete_publish_'+kind):
                                nav(screen);page.get_by_role('button',name='+ '+label,exact=True).click()
                                dialog=page.locator('dialog[open]');code='fn-'+kind;title='Synthetic '+kind
                                dialog.get_by_label('رمز ثابت — أحرف وأرقام إنجليزية',exact=True).fill(code)
                                title_label='نص السؤال' if kind=='poll' else 'العنوان'
                                dialog.get_by_label(title_label,exact=True).fill(title)
                                if kind=='poll':dialog.get_by_label('الخيارات: كل سطر «المفتاح | العنوان | رابط الصورة الاختياري»',exact=True).fill('o1 | One\no2 | Two')
                                if kind=='fact':dialog.get_by_label('القيمة',exact=True).fill('42')
                                dialog.get_by_role('button',name='فحص وحفظ المادة',exact=True).click();expect(page.locator('dialog[open]')).to_have_count(0)
                                assert any(r['code']==code for r in api('/api/admin/sites/event-demo')['draft']['records'])
                                with page.expect_response(lambda r:r.url.endswith('/publish')):page.get_by_role('button',name='نشر التغييرات',exact=True).click()
                                assert next(r for r in api('/api/public/site/demo')['config']['records'] if r['code']==code)['title']==title
                                row=page.locator('.record-line').filter(has_text=code);row.get_by_role('button',name='تعديل',exact=True).click()
                                page.locator('dialog[open]').get_by_label(title_label,exact=True).fill(title+' revised');page.locator('dialog[open]').get_by_role('button',name='فحص وحفظ المادة',exact=True).click();expect(page.locator('dialog[open]')).to_have_count(0)
                                assert next(r for r in api('/api/admin/sites/event-demo')['draft']['records'] if r['code']==code)['title']==title+' revised'
                                assert next(r for r in api('/api/public/site/demo')['config']['records'] if r['code']==code)['title']==title
                                page.once('dialog',lambda d:d.accept());page.locator('.record-line').filter(has_text=code).get_by_role('button',name='حذف من المسودة',exact=True).click()
                                expect(page.locator('.record-line').filter(has_text=code)).to_have_count(0)
                                assert not any(r['code']==code for r in api('/api/admin/sites/event-demo')['draft']['records'])
                                assert any(r['code']==code for r in api('/api/public/site/demo')['config']['records'])
                                with page.expect_response(lambda r:r.url.endswith('/publish')):page.get_by_role('button',name='نشر التغييرات',exact=True).click()
                                assert not any(r['code']==code for r in api('/api/public/site/demo')['config']['records'])

                        with scenario('native_poll_create_edit_close_open_and_publish'):
                            nav('التصويت');page.get_by_role('button',name='+ تصويت جديد',exact=True).click()
                            d=page.locator('dialog[open]');d.get_by_label('رمز التصويت',exact=True).fill('fn-poll');d.get_by_label('سؤال التصويت',exact=True).fill('Synthetic native poll');d.get_by_label('الخيارات — كل خيار في سطر: المفتاح | العنوان',exact=True).fill('o1 | One\no2 | Two');d.get_by_role('button',name='حفظ التصويت في المسودة',exact=True).click();expect(page.locator('dialog[open]')).to_have_count(0)
                            assert next(r for r in api('/api/admin/sites/event-demo')['draft']['records'] if r['code']=='fn-poll')['status']=='open'
                            card=page.locator('article').filter(has=page.get_by_role('heading',name='Synthetic native poll',exact=True));card.get_by_role('button',name='إغلاق',exact=True).click();expect(card.get_by_role('button',name='فتح',exact=True)).to_be_visible()
                            with page.expect_response(lambda r:r.url.endswith('/publish')):page.get_by_role('button',name='نشر التغييرات',exact=True).click()
                            assert next(r for r in api('/api/public/site/demo')['config']['records'] if r['code']=='fn-poll')['status']=='closed'
                            card=page.locator('article').filter(has=page.get_by_role('heading',name='Synthetic native poll',exact=True));card.get_by_role('button',name='تعديل',exact=True).click();page.locator('dialog[open]').get_by_label('سؤال التصويت',exact=True).fill('Synthetic native poll revised');page.locator('dialog[open]').get_by_role('button',name='حفظ التصويت في المسودة',exact=True).click();expect(page.locator('dialog[open]')).to_have_count(0)
                            card=page.locator('article').filter(has=page.get_by_role('heading',name='Synthetic native poll revised',exact=True));card.get_by_role('button',name='فتح',exact=True).click();expect(card.get_by_role('button',name='إغلاق',exact=True)).to_be_visible()
                            with page.expect_response(lambda r:r.url.endswith('/publish')):page.get_by_role('button',name='نشر التغييرات',exact=True).click()
                            poll=next(r for r in api('/api/public/site/demo')['config']['records'] if r['code']=='fn-poll');assert poll['status']=='open' and poll['title']=='Synthetic native poll revised'

                        with scenario('post_save_publish_navigation_must_retain_event_admission_capabilities',fatal=False):
                            # reload() must re-fetch capabilities, not silently lose event-only tabs.
                            assert page.locator('#admin-nav').get_by_role('button',name='الدعوات وتأكيد الحضور',exact=True).count()==1, 'Invitation tab disappeared after saving/publishing the same authorized event'
                            assert page.locator('#admin-nav').get_by_role('button',name='اللجان والصلاحيات',exact=True).count()==1, 'Committee tab disappeared after saving/publishing'
                        # Explicit test continuation after recording the defect; not an acceptance workaround.
                        page.goto(origin+'/admin');page.locator('#admin-nav').wait_for()
                        with scenario('organizer_configures_manual_private_policy_through_real_screen'):
                            nav('الدعوات وتأكيد الحضور');tab('إعدادات الحضور')
                            page.get_by_label('فتح استقبال تأكيدات الحضور',exact=True).check()
                            page.get_by_label('ظهور الفعالية',exact=True).select_option('private')
                            page.get_by_label('اعتماد طلب الحضور',exact=True).select_option('manual')
                            page.get_by_label('الحد الأقصى للمرافقين لكل دعوة',exact=True).fill('2')
                            with page.expect_response(lambda r:r.url.endswith('/admission-policy') and r.request.method=='PUT') as pending:page.get_by_role('button',name='حفظ إعدادات الحضور',exact=True).click()
                            assert pending.value.status==200
                            assert api(BASE+'/admission-policy')['policy']['visibility']=='private'
                        with scenario('create_guest_list_and_invitation_from_admin_forms'):
                            tab('المدعوون');page.get_by_role('button',name='قائمة جديدة',exact=True).click();page.get_by_label('اسم القائمة',exact=True).fill('Synthetic VIP')
                            page.get_by_role('button',name='إنشاء القائمة',exact=True).click();expect(page.locator('dialog[open]')).to_have_count(0)
                            page.get_by_role('button',name='إضافة مدعو',exact=True).click();page.get_by_label('اسم المدعو',exact=True).fill('Functional Native Guest');page.get_by_label('رقم الهاتف',exact=True).fill('777887001');page.get_by_label('المرافقون المسموحون',exact=True).fill('1')
                            listing=api(BASE+'/guest-lists')['lists'];page.get_by_label('قائمة المدعوين',exact=True).select_option(listing[0]['id']);page.get_by_role('button',name='إنشاء الدعوة',exact=True).click()
                            link=page.get_by_label('الرابط الشخصي',exact=True);link.wait_for();token=link.input_value().rsplit('/',1)[-1];close_dialog()
                            invited=next(r for r in rows() if r['name']=='Functional Native Guest');assert invited['list_id']==listing[0]['id'] and invited['max_companions']==1
                        with scenario('search_status_and_list_filters_change_actual_invitation_results'):
                            page.get_by_label('البحث في المدعوين',exact=True).fill('NO-MATCH');expect(page.get_by_role('heading',name='لا توجد نتائج مطابقة',exact=True)).to_be_visible()
                            page.get_by_label('البحث في المدعوين',exact=True).fill('Functional Native');expect(page.locator('tbody tr')).to_have_count(1)
                            page.get_by_label('حالة الدعوة',exact=True).select_option('approved');expect(page.locator('tbody tr')).to_have_count(0)
                            page.get_by_label('حالة الدعوة',exact=True).select_option('');page.get_by_label('القائمة',exact=True).select_option(listing[0]['id']);expect(page.locator('tbody tr')).to_have_count(1)
                        with scenario('rsvp_pending_then_admin_approval_from_screen_issues_pass'):
                            with httpx.Client(base_url=origin,trust_env=False) as public:
                                r=public.post('/api/public/invitations/'+token+'/rsvp',json={'response':'accepted','consent':True,'companions':1});assert r.status_code==200 and 'guest_number' not in r.json()
                            page.get_by_role('button',name='تحديث الردود',exact=True).click();page.get_by_role('button',name='اعتماد',exact=True).click();page.get_by_role('link',name='بطاقة الدخول',exact=True).wait_for()
                            assert next(r for r in rows() if r['id']==invited['id'])['status']=='approved'
                        with scenario('rotation_and_revocation_commands_invalidate_old_links'):
                            page.get_by_role('button',name='رابط جديد',exact=True).click();page.get_by_role('button',name='إصدار الرابط',exact=True).click()
                            new_link=page.get_by_label('الرابط الشخصي',exact=True);new_link.wait_for();new_token=new_link.input_value().rsplit('/',1)[-1]
                            assert new_token!=token;close_dialog()
                            with httpx.Client(base_url=origin,trust_env=False) as public:assert public.get('/api/public/invitations/'+token).status_code==404
                            page.get_by_role('button',name='إلغاء الدعوة',exact=True).click();page.get_by_role('button',name='تأكيد الإلغاء',exact=True).click()
                            expect(page.locator('dialog[open]')).to_have_count(0)
                            assert next(r for r in rows() if r['id']==invited['id'])['status']=='revoked'
                        with scenario('invitation_csv_preview_errors_block_commit_in_real_browser'):
                            tab('استيراد المدعوين');page.get_by_label('ملف المدعوين',exact=True).set_input_files({'name':'bad.csv','mimeType':'text/csv','buffer':b'name,phone\nBad,not-a-phone\n'})
                            page.get_by_role('button',name='معاينة وفحص الملف',exact=True).click();page.get_by_text('صحح الأخطاء ثم أعد معاينة الملف.',exact=True).wait_for()
                            assert page.get_by_role('button',name='اعتماد استيراد 1 مدعوًا',exact=True).count()==0
                        with scenario('valid_csv_preview_commit_persists_invitations_and_downloadable_links'):
                            before=len(rows());page.get_by_label('ملف المدعوين',exact=True).set_input_files({'name':'good.csv','mimeType':'text/csv','buffer':b'name,phone\nNative Import,777887002\n'})
                            page.get_by_role('button',name='معاينة وفحص الملف',exact=True).click();page.get_by_role('button',name='اعتماد استيراد 1 مدعوًا',exact=True).click()
                            page.get_by_role('heading',name='روابط الدعوات المستوردة',exact=True).wait_for();assert len(rows())==before+1
                            with page.expect_download() as download:page.get_by_role('button',name='تنزيل الروابط',exact=True).click()
                            assert download.value.suggested_filename=='invitation-links.json';close_dialog()
                        with scenario('committee_create_and_revoke_from_screen_changes_real_permissions'):
                            nav('اللجان والصلاحيات');page.get_by_role('button',name='إضافة عضو إلى اللجنة',exact=True).click();page.get_by_label('بريد حساب العضو',exact=True).fill('native-crew@example.test');page.get_by_label('إنشاء حساب محدود جديد إذا لم يوجد حساب بهذا البريد',exact=True).check();page.get_by_label('اسم العضو الجديد',exact=True).fill('Native crew');page.get_by_label('دور العضو',exact=True).select_option('scanner');page.get_by_role('button',name='حفظ التكليف',exact=True).click()
                            page.get_by_label('كلمة المرور المؤقتة',exact=True).wait_for();password_dialog=page.locator('dialog').filter(has=page.get_by_label('كلمة المرور المؤقتة',exact=True));password_dialog.get_by_role('button',name='×',exact=True).click();expect(password_dialog).to_have_count(0);expect(page.locator('.committee-admin tbody').get_by_text('native-crew@example.test',exact=True)).to_be_visible()
                            page.locator('.committee-admin tbody tr').filter(has_text='native-crew@example.test').get_by_role('button',name='تعديل التكليف',exact=True).click();page.get_by_label('حالة التكليف',exact=True).select_option('revoked');page.get_by_role('button',name='حفظ التكليف',exact=True).click();expect(page.locator('dialog[open]')).to_have_count(0)
                            assert next(r for r in api(BASE+'/committee')['assignments'] if r['email']=='native-crew@example.test')['status']=='revoked'
                        # Actual role-specific pages use real HTTP sessions after required password change.
                        for role in ['reception','committee_supervisor','analyst','auditor','event_manager']:
                            with scenario('native_screen_permissions_'+role,fatal=False):
                                email='functional-'+role+'@example.test'
                                result=api(BASE+'/committee',{'email':email,'name':'Synthetic '+role,'role':role,'create_account':True},'POST')
                                with httpx.Client(base_url=origin,trust_env=False) as member:
                                    login=member.post('/api/auth/login',json={'email':email,'password':result['temporary_password']});assert login.status_code==200
                                    member.headers.update({'X-CSRF':login.json()['csrf'],'Origin':origin})
                                    changed=member.post('/api/auth/password',json={'current':result['temporary_password'],'password':'FunctionalOnlyNewPass42!'});assert changed.status_code==200
                                    login=member.post('/api/auth/login',json={'email':email,'password':'FunctionalOnlyNewPass42!'});assert login.status_code==200
                                    role_ctx=browser.new_context(viewport={'width':1280,'height':950},locale='ar-YE')
                                    role_ctx.add_cookies([{'name':c.name,'value':c.value,'url':origin} for c in member.cookies.jar])
                                    rp=role_ctx.new_page();rp.on('pageerror',lambda e:errors.append(str(e)));rp.goto(origin+'/admin');rp.locator('#admin-nav').wait_for()
                                    if role!='event_manager':assert rp.get_by_role('button',name='نشر التغييرات',exact=True).count()==0
                                    if role in ['analyst','auditor','reception']:
                                        assert rp.locator('#admin-nav').get_by_role('button',name='الدعوات وتأكيد الحضور',exact=True).count()==0
                                    if role=='committee_supervisor':
                                        rp.locator('#admin-nav').get_by_role('button',name='الدعوات وتأكيد الحضور',exact=True).click();rp.get_by_label('البحث في المدعوين',exact=True).wait_for();assert rp.get_by_role('tab',name='إعدادات الحضور',exact=True).count()==0
                                    elif role=='event_manager':
                                        rp.locator('#admin-nav').get_by_role('button',name='اللجان والصلاحيات',exact=True).click();rp.get_by_role('button',name='إضافة عضو إلى اللجنة',exact=True).wait_for()
                                    else:
                                        rp.locator('#admin-nav').get_by_role('button',name='الزوار و QR',exact=True).click();rp.get_by_label('بحث بالاسم أو رقم التذكرة',exact=True).wait_for()
                                        if role in ['analyst','auditor']:assert rp.get_by_role('button',name='تسجيل الدخول',exact=True).count()==0
                                        if role=='reception':
                                            rp.get_by_label('اسم الزائر',exact=True).fill('Native reception');rp.get_by_label('رقم هاتف الزائر',exact=True).fill('777887003');rp.get_by_label('حصلت على موافقة الزائر على تسجيل بياناته للحضور.',exact=True).check()
                                            rp.get_by_role('button',name='تسجيل الزائر وإصدار الدعوة',exact=True).click();rp.get_by_text('طلب الحضور بانتظار الاعتماد من المنظم.',exact=True).wait_for()
                                            assert next(r for r in rows() if r['name']=='Native reception')['status']=='pending_approval'
                                    rp.screenshot(path=str(QA/(role+'.png')),full_page=True);role_ctx.close()
                        with scenario('native_lost_ack_retries_same_scan_without_second_database_consumption'):
                            result=api(BASE+'/committee',{'email':'native-lost-ack@example.test','name':'Lost ACK scanner','role':'scanner','create_account':True},'POST')
                            invitation=api(BASE+'/invitations',{'name':'Lost ACK visitor','phone':'777887004','max_companions':1},'POST')
                            with httpx.Client(base_url=origin,trust_env=False) as visitor:
                                r=visitor.post('/api/public/invitations/'+invitation['token']+'/rsvp',json={'response':'accepted','consent':True,'companions':1});assert r.status_code==200
                                api(BASE+'/invitations/'+invitation['invitation']['id']+'/review',{'decision':'approve','revision':r.json()['invitation']['revision']},'POST')
                                number=visitor.get('/api/public/invitations/'+invitation['token']).json()['guest_number']
                            with httpx.Client(base_url=origin,trust_env=False) as member:
                                login=member.post('/api/auth/login',json={'email':'native-lost-ack@example.test','password':result['temporary_password']}).json();member.headers.update({'X-CSRF':login['csrf'],'Origin':origin})
                                assert member.post('/api/auth/password',json={'current':result['temporary_password'],'password':'NativeLostAckNewPass42!'}).status_code==200
                                assert member.post('/api/auth/login',json={'email':'native-lost-ack@example.test','password':'NativeLostAckNewPass42!'}).status_code==200
                                c=browser.new_context();c.add_cookies([{'name':cookie.name,'value':cookie.value,'url':origin} for cookie in member.cookies.jar]);rp=c.new_page();rp.goto(origin+'/admin');rp.get_by_label('بحث بالاسم أو رقم التذكرة',exact=True).fill(number)
                                fault={'first':True,'scan_ids':[]}
                                def lose_first_response(route):
                                    if route.request.method!='POST':return route.continue_()
                                    fault['scan_ids'].append(route.request.post_data_json['scan_id'])
                                    if fault['first']:
                                        fault['first']=False;reply=route.fetch();assert reply.status==200;route.abort('connectionfailed')
                                    else:route.continue_()
                                rp.route('**/api/admin/events/event-demo/guest-checkins',lose_first_response)
                                count_before=api(BASE+'/guest-checkins')['total_checkins']
                                button=rp.get_by_role('button',name='تسجيل الدخول',exact=True);button.click();expect(button).to_be_enabled(timeout=20000)
                                assert api(BASE+'/guest-checkins')['total_checkins']==count_before+1
                                assert rp.evaluate("Object.keys(sessionStorage).filter(k=>k.startsWith('px-desk-pending:')).length")==1
                                button.click();expect(rp.get_by_role('status').filter(has_text='سبق تسجيل العملية')).to_be_visible()
                                assert len(fault['scan_ids'])==2 and fault['scan_ids'][0]==fault['scan_ids'][1]
                                assert api(BASE+'/guest-checkins')['total_checkins']==count_before+1
                                assert rp.evaluate("Object.keys(sessionStorage).filter(k=>k.startsWith('px-desk-pending:')).length")==0
                                c.close()

                        with scenario('device_screen_creates_pairs_disables_and_invalidates_browser_authority'):
                            nav('الأجهزة والطرفيات');device_name='QA Kiosk '+uuid.uuid4().hex[:6]
                            page.get_by_label('اسم الجهاز',exact=True).fill(device_name);page.get_by_label('نوع الطرفية',exact=True).select_option('kiosk')
                            with page.expect_response(lambda r:r.url.endswith('/devices') and r.request.method=='POST') as registered:page.get_by_role('button',name='إنشاء وربط الطرفية',exact=True).click()
                            assert registered.value.status==200
                            page.get_by_role('button',name='ربط هذا المتصفح بهذه الطرفية',exact=True).click();expect(page.get_by_role('button',name='تم ربط الطرفية',exact=True)).to_be_visible()
                            heartbeat=page.evaluate("async()=>{const o=await import('/assets/offline.mjs');return o.deviceHeartbeat();}")
                            assert heartbeat.get('paired') is True and not heartbeat.get('offline'),heartbeat
                            page.get_by_role('button',name='تم الحفظ — حدّث القائمة',exact=True).click()
                            card=page.locator('.card.mini').filter(has=page.get_by_text(device_name,exact=True));card.get_by_label('الحالة',exact=True).select_option('disabled')
                            with page.expect_response(lambda r:'/devices/' in r.url and r.request.method=='PATCH') as disabled:card.get_by_role('button',name='حفظ الحالة',exact=True).click()
                            assert disabled.value.status==200
                            revoked=page.evaluate("async()=>{const o=await import('/assets/offline.mjs');const h=await o.deviceHeartbeat();return {h,hasAuth:!!await o.get('bundles','device-auth')};}")
                            assert revoked['h'].get('authorization_failed') is True and revoked['hasAuth'] is False,revoked
                        with scenario('approved_mobile_pass_renders_real_qr_and_printable_pdf'):
                            invitation=api(BASE+'/invitations',{'name':'QA Print Guest','phone':'777889456'},'POST')
                            with httpx.Client(base_url=origin,trust_env=False) as visitor:
                                response=visitor.post('/api/public/invitations/'+invitation['token']+'/rsvp',json={'response':'accepted','consent':True});assert response.status_code==200
                                api(BASE+'/invitations/'+invitation['invitation']['id']+'/review',{'decision':'approve','revision':response.json()['invitation']['revision']},'POST')
                                number=visitor.get('/api/public/invitations/'+invitation['token']).json()['guest_number']
                            mobile=browser.new_page(viewport={'width':390,'height':844},locale='ar-YE');mobile.goto(origin+'/e/demo/guest/'+number)
                            qr=mobile.locator('img.guest-qr').first
                            expect(qr).to_be_visible();expect(qr).to_have_js_property('complete',True);assert qr.evaluate('image=>image.naturalWidth>20')
                            assert mobile.evaluate('document.documentElement.scrollWidth<=innerWidth+1')
                            pdf=mobile.pdf(path=str(QA/'approved-pass-print.pdf'),format='A4',print_background=True)
                            assert pdf.startswith(b'%PDF') and len(pdf)>1000;mobile.close()
                        with scenario('account_security_exports_local_queue_backup_from_ui'):
                            nav('الإعدادات والإشعارات')
                            with page.expect_download() as saved:page.get_by_role('button',name='نسخة احتياطية من الطابور المحلي — للمشغل',exact=True).click()
                            backup=json.loads(Path(saved.value.path()).read_text());assert backup['format']=='pulsex-offline-v04-redacted'
                            assert all(key in backup for key in ['items','guest_registrations','checkins'])
                        with scenario('accounts_screen_creates_disables_and_reenables_event_user_and_revokes_session'):
                            platform_credential=next(x for x in json.loads((tmp/'accounts.json').read_text()) if x['role']=='platform')
                            platform_ctx=browser.new_context(viewport={'width':1280,'height':950},locale='ar-YE')
                            pp=platform_ctx.new_page();pp.goto(origin+'/admin')
                            pp.get_by_label('البريد الإلكتروني',exact=True).fill(platform_credential['email']);pp.get_by_label('كلمة المرور',exact=True).fill(platform_credential['password']);pp.get_by_role('button',name='تسجيل الدخول',exact=True).click()
                            pp.get_by_role('heading',name='نظرة عامة',exact=True).wait_for();pp.get_by_label('مساحة العمل',exact=True).select_option('event-demo')
                            pp.locator('#admin-nav').get_by_role('button',name='الحسابات',exact=True).click();pp.get_by_role('heading',name='الحسابات',exact=True,level=1).wait_for()
                            email='qa-user-'+uuid.uuid4().hex[:8]+'@pulsex.test';pp.get_by_label('اسم المستخدم',exact=True).fill('QA Account');pp.get_by_label('البريد',exact=True).fill(email)
                            with pp.expect_response(lambda r:r.url.endswith('/api/admin/sites/event-demo/users') and r.request.method=='POST') as created_response:pp.get_by_role('button',name='إنشاء الحساب',exact=True).click()
                            assert created_response.value.status==200
                            notice=pp.locator('.notice').filter(has_text=email);codes=notice.locator('code').all_text_contents();assert len(codes)>=2 and codes[0]==email
                            temporary_password=codes[1]
                            with httpx.Client(base_url=origin,trust_env=False) as member:
                                login=member.post('/api/auth/login',json={'email':email,'password':temporary_password});assert login.status_code==200
                                member.headers.update({'X-CSRF':login.json()['csrf'],'Origin':origin})
                                changed=member.post('/api/auth/password',json={'current':temporary_password,'password':'FunctionalAccountNewPass42!'});assert changed.status_code==200
                                relogin=member.post('/api/auth/login',json={'email':email,'password':'FunctionalAccountNewPass42!'});assert relogin.status_code==200
                                user_row=next(x for x in staff.get('/api/admin/sites/event-demo/users').json()['users'] if x['email']==email);user_id=user_row['id']
                                if pp.locator('.record-line').filter(has_text=email).count()==0:
                                    cases.append({'name':'accounts_screen_immediately_refreshes_created_account_list','status':'failed','reason':'Create succeeded but the accounts list remains stale until the screen is reopened'})
                                    print('FAIL accounts_screen_immediately_refreshes_created_account_list',flush=True)
                                    pp.goto(origin+'/admin');pp.locator('#admin-nav').wait_for();pp.locator('#admin-nav').get_by_role('button',name='الحسابات',exact=True).click();pp.get_by_role('heading',name='الحسابات',exact=True,level=1).wait_for()
                                account_row=pp.locator('.record-line').filter(has_text=email);account_row.get_by_role('button',name='إيقاف',exact=True).click()
                                assert member.get('/api/auth/me').status_code==401
                                assert next(x for x in staff.get('/api/admin/sites/event-demo/users').json()['users'] if x['id']==user_id)['active']==0
                                account_row=pp.locator('.record-line').filter(has_text=email);account_row.get_by_role('button',name='تفعيل',exact=True).click()
                                assert next(x for x in staff.get('/api/admin/sites/event-demo/users').json()['users'] if x['id']==user_id)['active']==1
                            platform_ctx.close()

                        with scenario('audit_screen_renders_recent_actions_created_by_user_workflows'):
                            nav('السجل والتدقيق')
                            expect(page.get_by_text('invitation_created',exact=True).first).to_be_visible()
                            expect(page.get_by_text('invitation_reviewed',exact=True).first).to_be_visible()
                            expect(page.get_by_text('user_created',exact=True).first).to_be_visible()
                            expect(page.get_by_text('publish',exact=True).first).to_be_visible()
                        with scenario('account_security_screen_shows_sessions_and_revokes_them_from_ui'):
                            nav('الإعدادات والإشعارات');revoke=page.get_by_role('button',name='إنهاء جميع جلساتي على كل الأجهزة',exact=True);expect(revoke).to_be_visible()
                            page.once('dialog',lambda d:d.accept());revoke.click()
                            page.get_by_label('البريد الإلكتروني',exact=True).wait_for(timeout=15000)
                            assert staff.get('/api/admin/sites/event-demo').status_code==401

                        with scenario('account_security_password_change_from_ui_rejects_old_password_and_all_old_sessions'):
                            page.get_by_label('البريد الإلكتروني',exact=True).fill(account['email']);page.get_by_label('كلمة المرور',exact=True).fill(account['password']);page.get_by_role('button',name='تسجيل الدخول',exact=True).click();page.locator('#admin-nav').wait_for()
                            nav('الإعدادات والإشعارات');new_password='FunctionalScreenChangedPass42!'
                            page.get_by_label('كلمة المرور الحالية',exact=True).fill(account['password']);page.get_by_label('كلمة المرور الجديدة — 12 حرفًا على الأقل',exact=True).fill(new_password)
                            page.get_by_role('button',name='تغيير كلمة المرور وإنهاء الجلسات',exact=True).click();page.get_by_label('البريد الإلكتروني',exact=True).wait_for()
                            with httpx.Client(base_url=origin,trust_env=False) as relogin:
                                assert relogin.post('/api/auth/login',json={'email':account['email'],'password':account['password']}).status_code==401
                                assert relogin.post('/api/auth/login',json={'email':account['email'],'password':new_password}).status_code==200

                        assert not errors,errors;mark('no_uncaught_functional_browser_errors')
                        ctx.close();browser.close()
            except Exception as exc:
                if not cases or cases[-1]['status']!='failed':cases.append({'name':'harness_or_fixture','status':'failed','reason':str(exc),'traceback':traceback.format_exc()})
            finally:
                proc.terminate()
                try:proc.wait(timeout=10)
                except subprocess.TimeoutExpired:proc.kill();proc.wait(timeout=5)
                report={'scope':'Native Chromium and HTTP, disposable SQLite; not physical hardware','status':'failed' if any(c['status']=='failed' for c in cases) else 'passed','cases':cases,'page_errors':errors}
                (QA/'results.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8');print(json.dumps(report,ensure_ascii=False,indent=2),flush=True)
    return 1 if any(c['status']=='failed' for c in cases) else 0


if __name__=='__main__':raise SystemExit(main())
