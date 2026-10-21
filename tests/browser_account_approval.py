"""Native browser acceptance: platform invitation, organization owner and crew roles."""
import json
import os
from pathlib import Path
import tempfile
import traceback

from playwright.sync_api import sync_playwright, expect
from test_admission_http_ack import running_server

ROOT=Path(__file__).resolve().parents[1]
OUT=ROOT/'qa/account-approval'
PASSWORD='Browser-Approved-Password-2026!'


def main():
    OUT.mkdir(parents=True,exist_ok=True)
    report={'status':'failed','backend':'SQLite','checks':[],'limitations':['Synthetic identities only','No external delivery or physical device certification']}
    try:
        with tempfile.TemporaryDirectory(prefix='eventna-approval-browser-') as folder:
            temp=Path(folder)
            with running_server(temp) as (base,staff),sync_playwright() as pw:
                launch={'args':['--no-sandbox','--disable-dev-shm-usage']}
                if os.environ.get('PX_CHROMIUM_EXECUTABLE'):launch['executable_path']=os.environ['PX_CHROMIUM_EXECUTABLE']
                browser=pw.chromium.launch(**launch)
                try:
                    accounts=json.loads((temp/'accounts.json').read_text())
                    admin=next(a for a in accounts if a['role']=='platform')
                    organizer=next(a for a in accounts if a['role']=='organizer')
                    owner=next(a for a in accounts if a['email']=='agency01@pulsex.test')
                    admin_ctx=browser.new_context(viewport={'width':1440,'height':1000})
                    auth=admin_ctx.request.post(base+'/api/auth/login',data=admin).json()
                    errors=[]
                    page=admin_ctx.new_page();page.on('pageerror',lambda e:errors.append(str(e)))
                    page.goto(base+'/admin')
                    page.locator('#admin-nav').get_by_role('button',name='الحسابات',exact=True).click()
                    page.get_by_label('اسم المستخدم',exact=True).fill('Invited platform candidate')
                    page.get_by_label('رقم الهاتف',exact=True).fill('+967777889900')
                    with page.expect_response(lambda r:r.url.endswith('/api/admin/platform-account-invites')) as issued:
                        page.get_by_role('button',name='إرسال طلب حساب',exact=True).click()
                    invitation=issued.value.json();assert not invitation['grants_access']
                    candidate=browser.new_context(viewport={'width':390,'height':844})
                    cp=candidate.new_page();cp.on('pageerror',lambda e:errors.append(str(e)))
                    cp.goto(base+'/account/invite#'+invitation['invitation_token'])
                    cp.get_by_label('كلمة المرور الجديدة — 12 إلى 256 حرفًا',exact=True).fill(PASSWORD)
                    cp.get_by_label('تأكيد كلمة المرور الجديدة',exact=True).fill(PASSWORD)
                    cp.get_by_role('button',name='تقديم طلبي للمشرف',exact=True).click()
                    expect(cp.get_by_role('status').first).to_have_text('بانتظار الموافقة')
                    assert candidate.request.post(base+'/api/auth/login',data={'phone':'+967777889900','password':PASSWORD}).status==401
                    page.locator('#admin-nav').get_by_role('button',name='طلبات الحسابات',exact=True).click()
                    card=page.locator('.record-list article').filter(has_text='Invited platform candidate')
                    card.get_by_role('button',name='موافقة',exact=True).click()
                    page.get_by_role('dialog').get_by_role('button',name='تأكيد القرار',exact=True).click()
                    cp.get_by_role('button',name='تحديث الحالة',exact=True).click()
                    cp.get_by_role('link',name='تسجيل الدخول',exact=True).click()
                    cp.get_by_label('رقم الهاتف',exact=True).fill('+967777889900')
                    cp.get_by_label('كلمة المرور',exact=True).fill(PASSWORD)
                    cp.get_by_role('button',name='تسجيل الدخول',exact=True).click()
                    cp.locator('#admin-nav').wait_for()
                    assert candidate.request.get(base+'/api/auth/me').json()['user']['role']=='platform'
                    assert cp.evaluate('document.documentElement.scrollWidth<=innerWidth+1')
                    report['checks'].append('single_initial_admin_invites_candidate_who_applies_and_is_explicitly_approved_before_login')
                    # An owner reviews an editor request through the actual UI.
                    owner_ctx=browser.new_context(viewport={'width':1440,'height':1000})
                    assert owner_ctx.request.post(base+'/api/auth/login',data=owner).ok
                    org_auth=staff.post('/api/auth/login',json=organizer);org_auth.raise_for_status()
                    staff.headers.update({'X-CSRF':org_auth.json()['csrf'],'Origin':base})
                    requested=staff.post('/api/admin/organizations/org-01/users',json={'name':'Owner reviewed editor','email':'browser-editor@example.test','role':'editor'});requested.raise_for_status()
                    request=requested.json()
                    op=owner_ctx.new_page();op.on('pageerror',lambda e:errors.append(str(e)));op.goto(base+'/admin')
                    op.locator('#admin-nav').get_by_role('button',name='طلبات الحسابات',exact=True).click()
                    card=op.locator('.record-list article').filter(has_text='Owner reviewed editor')
                    card.get_by_role('button',name='موافقة',exact=True).click()
                    op.get_by_role('dialog').get_by_role('button',name='تأكيد القرار',exact=True).click()
                    applicant=browser.new_context(viewport={'width':390,'height':844})
                    ap=applicant.new_page();ap.on('pageerror',lambda e:errors.append(str(e)))
                    ap.goto(base+'/account/request#'+request['tracking_token'])
                    ap.get_by_label('كلمة المرور الجديدة — 12 إلى 256 حرفًا',exact=True).fill(PASSWORD)
                    ap.get_by_label('تأكيد كلمة المرور الجديدة',exact=True).fill(PASSWORD)
                    ap.get_by_role('button',name='تعيين كلمة المرور',exact=True).click()
                    ap.get_by_role('link',name='تسجيل الدخول',exact=True).click()
                    ap.get_by_label('رقم الهاتف',exact=True).fill('browser-editor@example.test')
                    ap.get_by_label('كلمة المرور',exact=True).fill(PASSWORD)
                    ap.get_by_role('button',name='تسجيل الدخول',exact=True).click()
                    ap.locator('#admin-nav').wait_for()
                    report['checks'].append('organization_owner_ui_review_and_applicant_self_password_setup')
                    # Exercise every committee UI role after independent review.
                    for i,role in enumerate(('scanner','reception','committee_supervisor','analyst','auditor','event_manager')):
                        result=staff.post('/api/admin/events/event-demo/committee',json={'name':'Browser '+role,'email':role+'-approval@example.test','role':role,'create_account':True})
                        result.raise_for_status();pending=result.json()
                        # The new platform user can be the designated reviewer; use
                        # the actual designation rather than assuming who it is.
                        current=candidate if pending['supervisor_id']==candidate.request.get(base+'/api/auth/me').json()['user']['id'] else admin_ctx
                        csrf=current.request.get(base+'/api/auth/me').json()['csrf']
                        approved=current.request.patch(base+'/api/admin/account-requests/'+pending['id'],data={'status':'approved'},headers={'X-CSRF':csrf})
                        assert approved.ok,approved.text()
                        ctx=browser.new_context(viewport={'width':1440,'height':1000})
                        setup=ctx.request.post(base+'/api/account-requests/password',data={'tracking_token':pending['tracking_token'],'password':PASSWORD,'confirmation':PASSWORD});assert setup.ok,setup.text()
                        assert ctx.request.post(base+'/api/auth/login',data={'email':role+'-approval@example.test','password':PASSWORD}).ok
                        rp=ctx.new_page();rp.on('pageerror',lambda e:errors.append(str(e)));rp.goto(base+'/admin')
                        rp.locator('#admin-nav').wait_for()
                        expect(rp.locator('#admin-nav .active')).not_to_be_empty()
                        if role!='event_manager':assert rp.get_by_role('button',name='نشر التغييرات',exact=True).count()==0
                        if role=='committee_supervisor':
                            rp.locator('#admin-nav').get_by_role('button',name='الدعوات وتأكيد الحضور',exact=True).click()
                            expect(rp.get_by_role('heading',level=1)).to_have_text('الدعوات وتأكيد الحضور')
                        if role in ('scanner','reception','committee_supervisor','analyst','auditor'):
                            forbidden=ctx.request.post(base+'/api/admin/events/event-demo/committee',data={'name':'Forbidden','email':'forbidden@example.test','role':'event_manager'},headers={'X-CSRF':ctx.request.get(base+'/api/auth/me').json()['csrf']})
                            assert forbidden.status==403
                        report['checks'].append(role+'_native_admin_surface_and_bounded_authority')
                        ctx.close()
                    org_result=admin_ctx.request.post(base+'/api/admin/organizations',data={'name':'Standalone owner organization','slug':'standalone-approval-org'},headers={'X-CSRF':admin_ctx.request.get(base+'/api/auth/me').json()['csrf']})
                    assert org_result.ok,org_result.text()
                    org=org_result.json()
                    submitted=admin_ctx.request.post(base+'/api/admin/organizations/'+org['id']+'/users',data={'name':'Standalone owner','email':'standalone-owner@example.test','role':'owner'},headers={'X-CSRF':admin_ctx.request.get(base+'/api/auth/me').json()['csrf']})
                    assert submitted.ok,submitted.text()
                    pending=submitted.json()
                    reviewed=candidate.request.patch(base+'/api/admin/account-requests/'+pending['id'],data={'status':'approved'},headers={'X-CSRF':candidate.request.get(base+'/api/auth/me').json()['csrf']})
                    assert reviewed.ok,reviewed.text()
                    solo=browser.new_context(viewport={'width':1440,'height':1000})
                    assert solo.request.post(base+'/api/account-requests/password',data={'tracking_token':pending['tracking_token'],'password':PASSWORD,'confirmation':PASSWORD}).ok
                    assert solo.request.post(base+'/api/auth/login',data={'email':'standalone-owner@example.test','password':PASSWORD}).ok
                    sp=solo.new_page();sp.on('pageerror',lambda e:errors.append(str(e)));sp.goto(base+'/admin')
                    expect(sp.locator('#admin-nav .active')).to_have_text('المؤسسات والمشاركات')
                    expect(sp.get_by_role('heading',name='Standalone owner organization',exact=True)).to_be_visible()
                    assert sp.get_by_role('button',name='نشر التغييرات',exact=True).count()==0
                    report['checks'].append('standalone_organization_owner_has_real_workspace_without_event_or_page')
                    solo.close()
                    # A rejected applicant sees a suitable reason; no login exists.
                    rejected=candidate.request.post(base+'/api/auth/register',data={'name':'Rejected applicant','phone':'+967777889901','password':PASSWORD,'confirmation':PASSWORD}).json()
                    current=candidate if rejected['supervisor_id']==candidate.request.get(base+'/api/auth/me').json()['user']['id'] else admin_ctx
                    rp=current.new_page();rp.goto(base+'/admin');rp.locator('#admin-nav').get_by_role('button',name='طلبات الحسابات',exact=True).click()
                    row=rp.locator('.record-list article').filter(has_text='Rejected applicant')
                    row.get_by_role('button',name='رفض مع السبب',exact=True).click()
                    dialog=rp.get_by_role('dialog');dialog.get_by_role('button',name='تأكيد القرار',exact=True).click();expect(dialog).to_be_visible()
                    dialog.get_by_label('سبب الرفض الموجّه لصاحب الطلب',exact=True).fill('يرجى مراجعة الجهة المنظمة.')
                    dialog.get_by_role('button',name='تأكيد القرار',exact=True).click();expect(dialog).to_have_count(0)
                    ap.goto(base+'/account/request#'+rejected['tracking_token'])
                    expect(ap.get_by_role('status').first).to_have_text('رُفض الطلب')
                    expect(ap.locator('main')).to_contain_text('يرجى مراجعة الجهة المنظمة.')
                    assert applicant.request.post(base+'/api/auth/login',data={'phone':'+967777889901','password':PASSWORD}).status==401
                    ap.screenshot(path=str(OUT/'mobile-request-decision.png'),full_page=True)
                    report['checks'].append('rejection_requires_reason_and_applicant_sees_decision_without_access')
                    assert not errors,errors
                    report.update(status='passed',browser_version=browser.version,page_errors=errors)
                finally:browser.close()
    except Exception as e:report.update(error_type=type(e).__name__,traceback=traceback.format_exc())
    (OUT/'browser.json').write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    print(json.dumps(report,ensure_ascii=False,indent=2))
    return 0 if report['status']=='passed' else 1


if __name__=='__main__':raise SystemExit(main())
