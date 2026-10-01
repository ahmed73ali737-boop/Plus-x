from __future__ import annotations
from pathlib import Path
import json, os, socket, subprocess, sys, tempfile, time, urllib.request

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'sdk/python'))
from pulsex_sdk import PulseXClient

with tempfile.TemporaryDirectory(prefix='px-sdk-') as td:
    temp=Path(td)
    with socket.socket() as s:s.bind(('127.0.0.1',0));port=s.getsockname()[1]
    base=f'http://127.0.0.1:{port}'
    env={**os.environ,'HOST':'127.0.0.1','PORT':str(port),'PUBLIC_ORIGIN':base,'DATABASE_URL':'sqlite:///'+str(temp/'db.sqlite'),'CREDENTIALS_PATH':str(temp/'accounts.json'),'MEDIA_DIR':str(temp/'media'),'SEED_DEMO':'true'}
    log=open(temp/'server.log','w',encoding='utf-8')
    proc=subprocess.Popen([sys.executable,str(ROOT/'run.py')],cwd=ROOT,env=env,stdout=log,stderr=log)
    try:
        for _ in range(100):
            try: urllib.request.urlopen(base+'/api/health',timeout=.3);break
            except Exception: time.sleep(.1)
        accounts=json.loads((temp/'accounts.json').read_text())
        sdk=PulseXClient(base)
        assert sdk.health()['build']=='windows-08'
        assert sdk.public_site('agency-01')['slug']=='agency-01'
        user=sdk.login(accounts[2]['email'],accounts[2]['password']); assert user['scope_id']=='agency-01'
        assert sdk.admin_site('agency-01')['id']=='agency-01'
        assert 'counts' in sdk.metrics('agency-01')
        dev=sdk.create_device('agency-01','SDK Tablet','tablet','0.9.0'); assert dev['token_shown_once']
        assert any(x['id']==dev['id'] for x in sdk.devices('agency-01')['devices'])
        sdk.logout()
        report={'status':'passed','checks':8,'transport':'real localhost HTTP','sdk':'python'}
    finally:
        proc.terminate();proc.wait(timeout=10);log.close()
(ROOT/'qa/hardening/sdk-python-smoke.json').write_text(json.dumps(report,indent=2),encoding='utf-8')
print(json.dumps(report))
