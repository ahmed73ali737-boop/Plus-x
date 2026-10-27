"""R15 measurement: bounded child projection queries, without changing lock safety."""
from sqlalchemy import event, select, update
from app.db import sites
from app.server import create_app
from app.infrastructure.seed import seed_demo_data
from harness_support import app_client


def test_70_children_use_bounded_queries_and_published_content(tmp_path,monkeypatch):
    # Measure the HTTP projection alone; elected background jobs use their own
    # connections and have separate lifecycle/lease/load acceptance tests.
    from app.application.self_certificate_runtime import CertificateWorkers
    monkeypatch.setattr(CertificateWorkers,'start',lambda self:None)
    app=create_app('sqlite:///'+str(tmp_path/'seventy.sqlite'),origin='http://testserver',seed_demo=False)
    with app_client(app) as client:
        seed_demo_data(app.state.engine,count=70)
        with app.state.engine.begin() as c:
            site=dict(c.execute(select(sites).where(sites.c.id=='agency-01')).mappings().one())
            draft={**site['draft'],'title':'SECRET UNPUBLISHED TITLE'}
            c.execute(update(sites).where(sites.c.id==site['id']).values(draft=draft))
        statements=[]
        def observed(conn,cursor,statement,parameters,context,executemany):
            if statement.lstrip().upper().startswith('SELECT'):statements.append(statement)
        event.listen(app.state.engine,'before_cursor_execute',observed)
        try:response=client.get('/api/public/site/demo')
        finally:event.remove(app.state.engine,'before_cursor_execute',observed)
        assert response.status_code==200
        assert len(response.json()['agencies'])==70
        assert 'SECRET UNPUBLISHED TITLE' not in response.text
        print('70-child public projection SELECT count:',len(statements))
        assert len(statements)<=12, f'Unbounded child SELECTs: {len(statements)}'
