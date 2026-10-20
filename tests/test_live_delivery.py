import json
from pathlib import Path
import subprocess
import shutil
import httpx
import pytest
from tools.verify_live_delivery import DeliveryFailure, origin_value, verify_delivery
from test_admission_http_ack import running_server

ROOT = Path(__file__).resolve().parents[1]
SHA = 'a' * 40


@pytest.mark.parametrize('origin,local', [
    ('https://example.test/eventna', False), ('https://user:secret@example.test', False),
    ('https://example.test/?token=secret', False), ('http://example.test', False),
    ('http://example.test', True), ('http://127.0.0.1', False),
    ('https://example.test:bad', False), ('https://example.test/#part', False),
])
def test_unsafe_or_subpath_origins_rejected(origin, local):
    with pytest.raises(DeliveryFailure):
        origin_value(origin, local)


def test_actual_http_delivery_checks_local_mode_and_detects_old_build(tmp_path, monkeypatch):
    monkeypatch.setenv('PULSEX_BUILD_LABEL', 'git-'+SHA)
    with running_server(tmp_path) as (origin, _):
        result = verify_delivery(origin, SHA, allow_local_test=True)
        assert result['status'] == 'passed', result
        assert result['local_test'] and result['production_accepted'] is False
        assert len(result['checks']) == 4 and result['apk_bytes'] == 299736
        stale = verify_delivery(origin, 'b'*40, allow_local_test=True)
        assert stale['status'] == 'failed' and stale['reason'] == 'SOURCE_BUILD_MISMATCH'


def synthetic_site(path):
    if path in ('/api/health', '/api/health/ready'):
        return httpx.Response(200, json={'build':'git-'+SHA, 'status':'ready',
            'schema_tables_current':True, 'critical_columns_current':True,
            'database':'postgresql', 'schema_migrations_current':True})
    if path in ('/', '/start', '/admin'):
        return httpx.Response(200, text='<script src="/assets/app.mjs"></script>', headers={'content-type':'text/html'})
    if path == '/api/public/site/platform':
        return httpx.Response(200, json={'events':[]})
    if path == '/api/admin/sites':
        return httpx.Response(401, json={'detail':'AUTH_REQUIRED'})
    if path == '/api/downloads/android':
        evidence=json.loads((ROOT/'artifacts/android/BUILD_EVIDENCE.json').read_text())
        return httpx.Response(200, json={'download_url':'/downloads/pulsex-android-preview.apk',
            'channel':'preview', 'production_signed':False, 'bytes':evidence['apk_bytes'], 'sha256':evidence['apk_sha256']})
    if path == '/downloads/pulsex-android-preview.apk':
        return httpx.Response(200, content=(ROOT/'artifacts/android/PulseX-Android-Preview-1.0.2.apk').read_bytes(),
            headers={'content-type':'application/vnd.android.package-archive',
                     'content-disposition':'attachment; filename=preview.apk', 'x-content-type-options':'nosniff'})
    name=path.rsplit('/',1)[1]
    mime='application/manifest+json' if name.endswith('.webmanifest') else 'text/css' if name.endswith('.css') else 'text/javascript'
    return httpx.Response(200, content=(ROOT/'web'/name).read_bytes(), headers={'content-type':mime})


@pytest.mark.parametrize('fault,reason', [
    ('none', None), ('redirect','HTTP_302:/api/health'),
    ('stale_asset','ASSET_DOES_NOT_MATCH_CHECKOUT:/assets/app.mjs'),
    ('exposed_admin','HTTP_200:/api/admin/sites'),
    ('tampered_apk','APK_BYTES_DO_NOT_MATCH_CHECKOUT'),
    ('remote_apk','APK_METADATA_DOES_NOT_MATCH_CHECKOUT'),
    ('sqlite','POSTGRES_MIGRATIONS_REQUIRED'),
    ('oversize','BODY_LIMIT:/downloads/pulsex-android-preview.apk'),
    ('network','DELIVERY_PROBE_FAILED'),
])
def test_external_delivery_never_accepts_stale_unsafe_or_partial_response(fault, reason):
    methods=[]
    def handle(request):
        methods.append(request.method)
        path=request.url.path
        if fault=='network':raise httpx.ConnectError('sensitive network details', request=request)
        if fault=='redirect' and path=='/api/health':return httpx.Response(302, headers={'location':'https://untrusted.test'})
        if fault=='stale_asset' and path=='/assets/app.mjs':return httpx.Response(200, text='old asset', headers={'content-type':'text/javascript'})
        if fault=='exposed_admin' and path=='/api/admin/sites':return httpx.Response(200,json={'users':[]})
        if fault in ('tampered_apk','oversize') and path.endswith('.apk'):
            return httpx.Response(200,content=b'x'*(299737 if fault=='oversize' else 299736),headers={'content-type':'application/vnd.android.package-archive'})
        response=synthetic_site(path)
        if fault=='remote_apk' and path=='/api/downloads/android':
            data=response.json();data['download_url']='https://untrusted.test/file.apk';return httpx.Response(200,json=data)
        if fault=='sqlite' and path=='/api/health/ready':
            data=response.json();data['database']='sqlite';return httpx.Response(200,json=data)
        return response
    with httpx.Client(transport=httpx.MockTransport(handle)) as client:
        result=verify_delivery('https://events.example.test',SHA,client=client)
    assert set(methods)=={'GET'}
    assert result['production_accepted'] is False
    if reason:
        assert result['status']=='failed' and result['reason']==reason, result
    else:
        assert result['status']=='passed'
    assert 'sensitive network details' not in json.dumps(result)


def test_shared_edge_effective_compose_configuration(monkeypatch):
    if not shutil.which('docker'):
        if __import__('os').environ.get('PX_REQUIRE_COMPOSE_CHECK')=='YES':
            pytest.fail('Docker is required for the explicit Compose validation gate')
        pytest.skip('Compose validation runs in the dedicated Docker CI gate')
    for key,value in {'POSTGRES_PASSWORD':'synthetic-ci-only', 'GUEST_ID_SECRET':'x'*40,
                      'BOOTSTRAP_ADMIN_EMAIL':'qa@pulsex.test','DOMAIN':'eventna.app'}.items():
        monkeypatch.setenv(key,value)
    output=subprocess.check_output(['docker','compose','-f','compose.yaml','-f','ops/compose.shared-edge.yaml','config','--format','json'],cwd=ROOT,text=True)
    services=json.loads(output)['services']
    # Compose omits services with inactive profiles from the effective config.
    # Their absence proves the existing edge will not compete with project Caddy.
    assert set(services)=={'app','postgres'}
    assert set(services['app']['depends_on'])=={'postgres'}
    port=services['app']['ports'][0]
    assert port['host_ip']=='127.0.0.1' and str(port['published'])=='14310' and port['target']==4310
    assert services['app']['environment']['PUBLIC_ORIGIN']=='https://eventna.app'
    assert services['app']['environment']['PULSEX_ENV']=='production'
    assert services['app']['environment']['PX_FIELD_OFFLINE_ACCEPTED']=='false'
    assert 'ports' not in services['postgres']
