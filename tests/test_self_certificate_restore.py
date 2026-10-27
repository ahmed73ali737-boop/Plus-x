"""Restore rehearsal for database, private files, signing keys and branded routes."""
import os,shutil
import pytest
from pathlib import Path
from fastapi.testclient import TestClient
from tests.test_self_certificate_http import A,P,PASSWORD,system,new_link,prepare,submit
from app.server import create_app

@pytest.mark.skipif(os.environ.get('CERTIFICATE_TEST_POSTGRES')=='true',
    reason='SQLite file-copy restore; PostgreSQL restore uses the opt-in native rehearsal')
def test_restore_database_assets_keyring_and_issued_identity(system,tmp_path):
    app,client=system
    staff=client();link,_=new_link(staff);browser,token,prepared=prepare(app,link)
    accepted=submit(browser,token,prepared);assert accepted.status_code==202
    assert app.state.self_certificate_runtime.generate()
    issued=browser.get(P+'/request/'+token+'/mine').json()
    assert issued['status']=='issued'
    cap=issued['receive_url'].split('/')[-1]
    receive=browser.get(P+'/receive/'+cap);assert receive.status_code==200
    original=browser.get(receive.json()['download_url']).content

    data_root=app.state.self_certificate_runtime.store.root.parent
    db_path=Path(app.state.engine.url.database)
    restore_root=tmp_path/'restored'
    restore_root.mkdir()
    app.state.engine.dispose()
    shutil.copy2(db_path,restore_root/'database.sqlite')
    shutil.copytree(data_root,restore_root/'data',dirs_exist_ok=True)

    restored=create_app('sqlite:///'+str(restore_root/'database.sqlite'),origin='http://testserver',seed_demo=False)
    try:
        restored_staff=TestClient(restored)
        login=restored_staff.post('/api/auth/login',json={'email':'self-a@example.test','password':PASSWORD})
        assert login.status_code==200
        restored_staff.headers.update({'X-CSRF':login.json()['csrf'],'Origin':'http://testserver'})
        links=restored_staff.get(A+'/links').json()['items']
        assert len(links)==1 and links[0]['request_url']==link['request_url']

        restored_browser=TestClient(restored)
        restored_browser.headers.update({'Origin':'http://testserver'})
        restored_browser.cookies.set('px_certificate_browser',browser.cookies.get('px_certificate_browser'))
        public=restored_browser.get(P+'/receive/'+cap)
        assert public.status_code==200 and public.json()['status']=='valid'
        recovered=restored_browser.get(public.json()['download_url'])
        assert recovered.status_code==200 and recovered.content==original
        verify=restored_browser.get(P+'/verify/'+public.json()['serial'])
        assert verify.status_code==200 and verify.json()['status']=='valid'
    finally:
        restored.state.engine.dispose()
