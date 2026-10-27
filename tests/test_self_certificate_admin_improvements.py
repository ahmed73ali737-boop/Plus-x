"""Owner-scoped admin contracts: lost acknowledgements, filters and joined history."""
from sqlalchemy import select,func,event,update
from tests.test_self_certificate_http import system,A,new_model,new_link,prepare,submit
from app.self_certificates_db import models,revisions,exports,export_snapshot_rows
from app.application import self_certificate_exports as exporter
from datetime import timedelta


def test_link_summary_revision_is_checked_and_lost_response_recovers_original(system):
    app,clients=system;staff=clients();model=new_model(staff)
    import secrets
    body=dict(event_id='self-event',model_id=model['id'],share_text='نص مصطنع',
        idempotency_key=secrets.token_hex(24),expected_revision_id=model['current_revision_id'])
    first=staff.post(A+'/links',json=body)
    assert first.status_code==200,first.text
    payload={k:model['revision'][k] for k in ('background_asset_id','stamp_asset_id','config')}
    assert staff.put(A+'/models/'+model['id'],json={**payload,'name':'نسخة أحدث','row_version':1}).status_code==200
    assert staff.post(A+'/links',json=body).json()==first.json()
    changed=staff.post(A+'/links',json={**body,'idempotency_key':secrets.token_hex(24)})
    assert changed.status_code==409 and changed.json()['detail']=='MODEL_REVISION_CHANGED'
    assert staff.get(A+'/links').json()['total']==1


def test_model_create_idempotency_preserves_one_model_and_rejects_changed_input(system):
    app,clients=system
    staff=clients()
    source=new_model(staff)
    payload={k:source['revision'][k] for k in ('background_asset_id','stamp_asset_id','config')}
    payload.update(name='حفظ فقد تأكيده',idempotency_key='model-create-operation-001')
    first=staff.post(A+'/models',json=payload)
    assert first.status_code==200,first.text
    replay=staff.post(A+'/models',json=payload)
    assert replay.status_code==200 and replay.json()==first.json()
    conflict=staff.post(A+'/models',json={**payload,'name':'تعديل مختلف'})
    assert conflict.status_code==409
    with app.state.engine.connect() as conn:
        assert conn.execute(select(func.count()).select_from(models)).scalar_one()==2
    assert clients('self-b').get(A+'/models?q=حفظ').json()['total']==0
    assert staff.get(A+'/models?q=فقد').json()['total']==1


def test_history_filters_keep_owner_scope_and_export_still_captures_all(system):
    app,clients=system
    staff=clients()
    link,_=new_link(staff)
    for name in ('مشارك أول','مشارك ثان','مشارك ثالث'):
        browser,token,prepared=prepare(app,link)
        assert submit(browser,token,prepared,name=name).status_code==202
    assert app.state.self_certificate_runtime.generate()
    assert staff.get(A+'/requests?status=issued').json()['total']==1
    assert staff.get(A+'/requests?status=registered').json()['total']==2
    assert staff.get(A+'/requests?q=ثالث').json()['total']==1
    assert staff.get(A+'/requests?q=%25').json()['total']==0
    assert clients('self-b').get(A+'/requests?q=مشارك').json()['total']==0
    assert staff.get(A+'/requests?status=foreign').status_code==422
    job=staff.post(A+'/exports',json={'format':'csv'}).json()
    assert job['expected_rows']==3
    statements=[]
    def track(conn,cursor,statement,params,context,many):
        if statement.lstrip().upper().startswith('SELECT') and 'px_self_certificates' in statement:
            statements.append(statement)
    event.listen(app.state.engine,'before_cursor_execute',track)
    try:assert staff.get(A+'/requests?limit=100').json()['total']==3
    finally:event.remove(app.state.engine,'before_cursor_execute',track)
    assert len(statements)==1,'History must not query one certificate for each row'


def test_failed_snapshot_cleanup_uses_owner_approved_seven_day_policy(system,monkeypatch):
    app,clients=system
    staff=clients();link,_=new_link(staff)
    browser,token,prepared=prepare(app,link)
    assert submit(browser,token,prepared).status_code==202
    job=staff.post(A+'/exports',json={'format':'csv'}).json()
    with app.state.engine.begin() as conn:
        conn.execute(update(exports).where(exports.c.id==job['id']).values(status='failed',error_code='EXPORT_FAILED'))
    real=exporter.datetime
    class Future(real):
        @classmethod
        def now(cls,tz=None):return real.now(tz)+timedelta(days=8)
    monkeypatch.setattr(exporter,'datetime',Future)
    result=app.state.self_certificate_runtime.expire_exports()
    assert result['expired_failed_snapshots']==1
    with app.state.engine.connect() as conn:
        assert conn.execute(select(func.count()).select_from(export_snapshot_rows)).scalar_one()==0
    assert staff.get(A+'/exports/'+job['id']+'/download').status_code==410
