"""Quiz answer keys must not be disclosed in anonymous site or parent bundles."""
from fastapi.testclient import TestClient
from app.server import create_app


def test_quiz_correct_answers_never_leave_public_bundle_including_parent_event(tmp_path):
    app=create_app('sqlite:///'+str(tmp_path/'quiz.sqlite'),origin='http://testserver',seed_demo=True)
    with TestClient(app) as client:
        credentials=app.state.seed_credentials[0]
        signed=client.post('/api/auth/login',json={'email':credentials['email'],'password':credentials['password']})
        assert signed.status_code==200
        client.headers['X-CSRF']=signed.json()['csrf']
        for site in ('event-demo','agency-01'):
            state=client.get('/api/admin/sites/'+site).json()
            code='quiz-private-'+site.replace('_','-')
            quiz={'kind':'question','code':code,'title':'Question with private answer',
                  'qtype':'quiz','correct':'o1','score':10,'form_id':'main','enabled':True,
                  'order':500,'options':[{'key':'o1','label':'Option one'},
                                         {'key':'o2','label':'Option two'}]}
            config=state['draft']
            config['records'].append(quiz)
            saved=client.put('/api/admin/sites/'+site,json={'config':config,'draft_rev':state['draft_rev']})
            assert saved.status_code==200,saved.text
            published=client.post('/api/admin/sites/'+site+'/publish',json={'draft_rev':saved.json()['draft_rev']})
            assert published.status_code==200,published.text
            admin=client.get('/api/admin/sites/'+site).json()
            editable=next(x for x in admin['draft']['records'] if x['code']==code)
            assert editable['correct']=='o1'
        public=client.get('/api/public/site/agency-01').json()
        assert public['event'] is not None
        for config in (public['config'],public['event']['config']):
            item=next(x for x in config['records'] if x.get('qtype')=='quiz')
            assert 'correct' not in item
        draft=client.get('/api/admin/sites/agency-01/preview').json()
        answer=next(x for x in draft['config']['records'] if x.get('qtype')=='quiz')
        assert answer['correct']=='o1'
