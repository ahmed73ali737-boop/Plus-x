"""Read-only HTTP delivery evidence; never creates users or changes production data.

TLS verification is mandatory outside explicitly opted-in local HTTP tests.
Does not certify production acceptance, phone hardware, load, RPO or offline gates.
"""
from __future__ import annotations
import argparse
from contextlib import nullcontext
import hashlib
import ipaddress
import json
from pathlib import Path
import re
from urllib.parse import urlsplit
import httpx

ROOT = Path(__file__).resolve().parents[1]
MAX_BODY = 2 * 1024 * 1024


class DeliveryFailure(ValueError):
    pass


def origin_value(value, allow_local_test=False):
    parsed = urlsplit(value)
    if (not parsed.hostname or parsed.username is not None or parsed.password is not None
            or parsed.path not in ('', '/') or parsed.query or parsed.fragment):
        raise DeliveryFailure('ORIGIN_MUST_BE_DOMAIN_ROOT_WITHOUT_CREDENTIALS')
    try:
        port = parsed.port
    except ValueError:
        raise DeliveryFailure('INVALID_PORT') from None
    local = parsed.hostname.lower() == 'localhost'
    try:
        local = local or ipaddress.ip_address(parsed.hostname).is_loopback
    except ValueError:
        pass
    if parsed.scheme != 'https' and not (allow_local_test and local and parsed.scheme == 'http'):
        raise DeliveryFailure('HTTPS_REQUIRED')
    if allow_local_test and not local:
        raise DeliveryFailure('LOCAL_TEST_REQUIRES_LOOPBACK')
    return value.rstrip('/')


def verify_delivery(origin, expected_source, *, allow_local_test=False, client=None):
    report = {'status': 'failed', 'scope': 'read_only_delivery_smoke',
              'production_accepted': False, 'physical_device_tested': False,
              'checks': [], 'expected_source': expected_source}
    def require(condition, reason):
        if not condition:
            raise DeliveryFailure(reason)
    try:
        origin = origin_value(origin, allow_local_test)
        report.update(origin=origin, local_test=allow_local_test)
        require(bool(re.fullmatch(r'[a-f0-9]{40}', expected_source)), 'FULL_SOURCE_SHA_REQUIRED')
        context = nullcontext(client) if client is not None else httpx.Client(
            timeout=12, trust_env=False, follow_redirects=False, verify=True)
        with context as http:
            def get(path, status=200, mime=None, limit=MAX_BODY):
                with http.stream('GET', origin+path, follow_redirects=False) as response:
                    require(response.status_code == status, 'HTTP_'+str(response.status_code)+':'+path)
                    if mime:
                        require(response.headers.get('content-type', '').split(';')[0] in mime,
                                'WRONG_CONTENT_TYPE:'+path)
                    body = bytearray()
                    for chunk in response.iter_bytes():
                        body.extend(chunk)
                        require(len(body) <= limit, 'BODY_LIMIT:'+path)
                    return bytes(body), dict(response.headers)
            def data(path):
                raw, _ = get(path, mime={'application/json'})
                return json.loads(raw)
            health, ready = data('/api/health'), data('/api/health/ready')
            for result in (health, ready):
                require(result.get('build') == 'git-'+expected_source, 'SOURCE_BUILD_MISMATCH')
            require(ready.get('status') == 'ready' and ready.get('schema_tables_current') is True
                    and ready.get('critical_columns_current') is True, 'SCHEMA_NOT_READY')
            if not allow_local_test:
                require(ready.get('database') == 'postgresql'
                        and ready.get('schema_migrations_current') is True, 'POSTGRES_MIGRATIONS_REQUIRED')
            report['checks'].append('ready_schema_and_expected_source')
            for path in ('/', '/start', '/admin'):
                raw, _ = get(path, mime={'text/html'})
                require(b'/assets/app.mjs' in raw, 'WRONG_APPLICATION_SHELL:'+path)
            for path, mime in (
                    ('/assets/app.mjs', {'text/javascript', 'application/javascript'}),
                    ('/assets/access.mjs', {'text/javascript', 'application/javascript'}),
                    ('/assets/access.css', {'text/css'}),
                    ('/sw.js', {'text/javascript', 'application/javascript'})):
                raw, _ = get(path, mime=mime)
                require(bool(raw.strip()), 'EMPTY_ASSET:'+path)
                local = ROOT/'web'/('sw.js' if path == '/sw.js' else path.rsplit('/', 1)[1])
                require(hashlib.sha256(raw).digest() == hashlib.sha256(local.read_bytes()).digest(),
                        'ASSET_DOES_NOT_MATCH_CHECKOUT:'+path)
            raw, _ = get('/assets/manifest.webmanifest', mime={'application/manifest+json', 'application/json'})
            manifest = json.loads(raw)
            require(manifest.get('scope') == '/' and manifest.get('start_url') == '/', 'PWA_ROOT_SCOPE_MISMATCH')
            require(isinstance(data('/api/public/site/platform').get('events'), list), 'PUBLIC_CATALOG_MISSING')
            report['checks'].append('root_routes_assets_manifest_and_guest_catalog')
            raw, _ = get('/api/admin/sites', status=401, mime={'application/json'})
            require(isinstance(json.loads(raw).get('detail'), str), 'UNEXPECTED_AUTH_DENIAL')
            report['checks'].append('anonymous_administration_denied')
            meta = data('/api/downloads/android')
            require(meta.get('available') is False and meta.get('channel')=='withdrawn'
                    and meta.get('security_status')=='review_required' and meta.get('web_url')=='/'
                    and not meta.get('download_url'), 'ANDROID_QUARANTINE_METADATA_REQUIRED')
            for path in ('/downloads/eventna-android-preview.apk','/downloads/pulsex-android-preview.apk'):
                raw, headers = get(path,status=410,mime={'application/json'})
                require(json.loads(raw).get('detail')=='ANDROID_SECURITY_REVIEW_REQUIRED'
                        and headers.get('cache-control')=='no-store', 'ANDROID_QUARANTINE_REQUIRED')
            report['checks'].append('reported_android_apk_withdrawn_both_aliases')
            report.update(android_distribution='withdrawn_pending_review', status='passed')

    except Exception as error:
        report['error_type'] = type(error).__name__
        report['reason'] = str(error) if isinstance(error, DeliveryFailure) else 'DELIVERY_PROBE_FAILED'
    return report


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--origin', required=True)
    parser.add_argument('--expected-source', required=True)
    parser.add_argument('--output', type=Path, default=ROOT/'qa/live-delivery.json')
    parser.add_argument('--allow-local-test', action='store_true')
    args = parser.parse_args(argv)
    report = verify_delivery(args.origin, args.expected_source, allow_local_test=args.allow_local_test)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2)+'\n', encoding='utf-8')
    print(json.dumps(report, ensure_ascii=False))
    return 0 if report['status'] == 'passed' else 1


if __name__ == '__main__':
    raise SystemExit(main())
