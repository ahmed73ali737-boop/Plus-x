"""Certificate policy is narrower than general organization/page editing."""
import pytest
from sqlalchemy import insert, update
from fastapi import HTTPException
from app.db import make_engine, metadata, users, sites, organizations, memberships, event_participations, assignments
from app.application.self_certificate_access import eligible_events, require_event, require_owner, require_capability, owner_can_accept

@pytest.fixture
def policy():
    engine=make_engine('sqlite:///:memory:')
    metadata.create_all(engine)
    with engine.begin() as conn:
        for ident,kind,event in [('ev-a','event',None),('ev-b','event',None),('agency-a','agency','ev-a')]:
            conn.execute(insert(sites).values(id=ident,kind=kind,event_id=event,slug=ident,draft={},draft_rev=1,published_version=0))
        for ident,role,scope in [('platform','platform',None),('organizer','organizer','ev-a'),('manager','agency','agency-a'),('other','attendee',None)]:
            conn.execute(insert(users).values(id=ident,email=ident+'@example.test',name=ident,role=role,scope_id=scope,password_hash='unused-synthetic-fixture',active=1,must_change_password=0))
        conn.execute(insert(organizations).values(id='org',slug='org',name='Synthetic',profile={},status='active',created_at='2026-01-01'))
        conn.execute(insert(memberships).values(user_id='manager',organization_id='org',role='owner',status='active',created_at='2026-01-01'))
        conn.execute(insert(event_participations).values(id='part',event_id='ev-a',organization_id='org',agency_site_id='agency-a',status='active',services=[],valid_until='2020-01-01',created_at='2026-01-01'))
        yield conn
    engine.dispose()

def ids(conn, user):
    return {e['id'] for e in eligible_events(conn, {'id':user})}

def test_event_scope_and_organization_owners_are_separate_from_event_management(policy):
    assert ids(policy,'platform')=={'ev-a','ev-b'}
    assert ids(policy,'organizer')=={'ev-a'}
    assert ids(policy,'manager')=={'ev-a'}  # Ended event remains eligible.
    assert ids(policy,'other')==set()
    with pytest.raises(HTTPException) as exc: require_event(policy,{'id':'manager'},'ev-b')
    assert exc.value.status_code==403
    from app.application.access import event_permissions
    manager=dict(policy.execute(users.select().where(users.c.id=='manager')).mappings().one())
    assert 'certificates.issue' not in event_permissions(policy,manager,'ev-a')

@pytest.mark.parametrize('role,allowed',[('owner',True),('admin',True),('editor',False),('member',False),('analyst',False)])
def test_only_approved_membership_roles(policy,role,allowed):
    policy.execute(update(memberships).values(role=role))
    assert bool(ids(policy,'manager')) is allowed

@pytest.mark.parametrize('role,allowed',[('event_manager',True),('scanner',False),('reception',False),('committee_supervisor',False),('analyst',False),('auditor',False),('site_manager',False)])
def test_event_assignment_does_not_escalate_other_roles(policy,role,allowed):
    policy.execute(insert(assignments).values(id='test',user_id='other',site_id='ev-a',role=role,status='active',created_at='2026-01-01'))
    assert bool(ids(policy,'other')) is allowed
    policy.execute(update(assignments).values(valid_until='2020-01-01T00:00:00+00:00'))
    assert ids(policy,'other')==set()

@pytest.mark.parametrize('table', [memberships,event_participations,organizations])
def test_withdrawal_blocks_new_requests_but_owner_history_remains(policy,table):
    policy.execute(update(table).values(status='suspended'))
    assert not owner_can_accept(policy,'manager','ev-a')
    assert require_owner(policy,{'id':'manager'},'manager')['id']=='manager'
    assert require_capability(policy,{'id':'manager'},'requests.export')['id']=='manager'
    if table is event_participations:
        assert require_capability(policy,{'id':'manager'},'models.manage')['id']=='manager'
        with pytest.raises(HTTPException):require_event(policy,{'id':'manager'},'ev-a')
    else:
        with pytest.raises(HTTPException): require_capability(policy,{'id':'manager'},'links.manage')

def test_suspension_and_password_change_are_rechecked_in_database(policy):
    assert owner_can_accept(policy,'manager','ev-a')
    policy.execute(update(users).where(users.c.id=='manager').values(active=0))
    assert not owner_can_accept(policy,'manager','ev-a')
    with pytest.raises(HTTPException): require_owner(policy,{'id':'manager','active':1},'manager')
    policy.execute(update(users).where(users.c.id=='manager').values(active=1,must_change_password=1))
    assert not owner_can_accept(policy,'manager','ev-a')

def test_owner_isolation_also_applies_to_platform_and_unknown_capabilities(policy):
    for user in ('other','platform'):
        with pytest.raises(HTTPException) as exc: require_owner(policy,{'id':user},'manager')
        assert exc.value.status_code==404
    with pytest.raises(HTTPException): require_capability(policy,{'id':'platform'},'anything')

def test_v2_library_does_not_depend_on_events_or_participation(policy,monkeypatch):
    from sqlalchemy import delete
    from app.application import self_certificate_access as access
    from app.application import self_certificate_repository as repo
    from app.application.self_certificate_rendering import default_config
    from app.self_certificates_db import assets
    policy.execute(delete(event_participations))
    policy.execute(update(users).where(users.c.role=='organizer').values(scope_id=None))
    policy.execute(delete(sites).where(sites.c.kind=='event'))
    def forbidden_scan(*args,**kwargs):
        raise AssertionError('Library must not call eligible_events')
    monkeypatch.setattr(access,'eligible_events',forbidden_scan)
    for owner in ('manager','organizer','platform'):
        assert access.can_manage_library(policy,{'id':owner})
    policy.execute(insert(assets).values(id='v2-background',owner_account_id='manager',kind='background',
        storage_key='b'*2+'/'+'b'*64,sha256='0'*64,mime='image/png',size_bytes=10,width=1200,height=800,
        source_kind='png',original_size_bytes=10,source_metadata={},created_at='2026-10-22'))
    v1=repo.save_model(policy,{'id':'manager'},name='بدون فعالية',background_asset_id='v2-background',
        stamp_asset_id=None,config=default_config(1200,800))
    assert repo.list_models(policy,{'id':'manager'})['total']==1
    assert repo.get_model(policy,{'id':'manager'},v1['id'])['current_revision_id']==v1['revision']['id']
    assert repo.get_revision(policy,{'id':'manager'},v1['revision']['id'])['config']==default_config(1200,800)
    for other in ('platform','organizer'):
        assert repo.list_models(policy,{'id':other})['total']==0
        with pytest.raises(HTTPException):repo.get_model(policy,{'id':other},v1['id'])
        with pytest.raises(HTTPException):repo.owned_asset(policy,{'id':other},'v2-background')
        with pytest.raises(HTTPException):repo.get_revision(policy,{'id':other},v1['revision']['id'])
    v2=repo.save_model(policy,{'id':'manager'},name='تعديل',background_asset_id='v2-background',
        stamp_asset_id=None,config={**default_config(1200,800),'color':'#000000'},model_id=v1['id'],row_version=1)
    repo.delete_model(policy,{'id':'manager'},v2['id'],2)
    assert repo.list_models(policy,{'id':'manager'})['total']==0
    with pytest.raises(HTTPException):access.require_event(policy,{'id':'manager'},'ev-a')

def test_v2_direct_acceptance_does_not_scan_all_events(policy,monkeypatch):
    from app.application import self_certificate_access as access
    monkeypatch.setattr(access,'eligible_events',lambda *a:(_ for _ in ()).throw(AssertionError('Unexpected full scan')))
    assert access.owner_can_accept(policy,'manager','ev-a')
    policy.execute(update(event_participations).values(status='suspended'))
    assert access.can_manage_library(policy,{'id':'manager'})
    assert not access.owner_can_accept(policy,'manager','ev-a')
    assert access.require_owner(policy,{'id':'manager'},'manager')['id']=='manager'

@pytest.mark.parametrize('role',['editor','member','analyst'])
def test_v2_library_without_participation_still_rejects_non_manager_roles(policy,role):
    from sqlalchemy import delete
    from app.application.self_certificate_access import require_library
    policy.execute(delete(event_participations))
    policy.execute(update(memberships).values(role=role))
    with pytest.raises(HTTPException) as exc:require_library(policy,{'id':'manager'})
    assert exc.value.status_code==403

def test_v2_invalid_participant_input_rejected_before_any_request_or_job(policy):
    from sqlalchemy import select,func
    from app.self_certificates_db import requests,jobs
    from app.application.self_certificate_contracts import parse_participant_input
    payload=dict(name='محمد أحمد',phone='0770000000',consent=True,request_nonce='n'*32)
    for replacement in (False,None,'true',1):
        with pytest.raises(HTTPException) as exc:parse_participant_input({**payload,'consent':replacement})
        assert exc.value.detail=='CONSENT_REQUIRED'
    with pytest.raises(HTTPException) as exc:parse_participant_input({k:v for k,v in payload.items() if k!='consent'})
    assert exc.value.detail=='CONSENT_REQUIRED'
    for replacement in ({'name':'   '},{'phone':'  '},{'owner_account_id':'spoof'}):
        with pytest.raises(HTTPException):parse_participant_input({**payload,**replacement})
    assert policy.execute(select(func.count()).select_from(requests)).scalar_one()==0
    assert policy.execute(select(func.count()).select_from(jobs)).scalar_one()==0
