"""Host-level pg_dump/pg_restore plus the versioned resource bundle, between
two dedicated QA databases named by the test itself via ready.json; only ever
touches names matching the same cert_p0_<hex> pattern
certificate_test_database.py already restricts itself to, and only inside the
evidence area the caller points it at. A real backup/restore rehearsal
restores the resources a certificate was rendered with, not just its rows."""
import argparse, json, os, re, shutil, subprocess, time
from pathlib import Path
from sqlalchemy.engine import make_url

REPO_ROOT = Path(__file__).resolve().parents[1]
_NAME = re.compile(r'cert_p0_[0-9a-f]{12}')


def restore_private_data(area: Path) -> None:
    """Carry the private per-instance keyring/certificate store across too --
    a real restore brings back what signed a capability token, not only the
    rows a token points at."""
    source = area / 'source-data/private-certificates'
    if not source.is_dir():
        return
    destination = area / 'restored-data/private-certificates'
    destination.parent.mkdir(parents=True, exist_ok=True)
    shutil.copytree(source, destination, dirs_exist_ok=True)


def restore_resources(resource_root: Path) -> None:
    """Copy the exact versioned fonts/branding this build renders with, plus
    the legacy certificate font, into the restore target -- this is the part
    of a real host-level restore that a plain pg_restore never touches."""
    resource_root.mkdir(parents=True, exist_ok=True)
    shutil.copytree(REPO_ROOT / 'app/resources/fonts', resource_root / 'fonts', dirs_exist_ok=True)
    shutil.copytree(REPO_ROOT / 'app/resources/branding', resource_root / 'branding', dirs_exist_ok=True)
    legacy_dir = resource_root / 'legacy'
    legacy_dir.mkdir(exist_ok=True)
    shutil.copy2(REPO_ROOT / 'web/fonts/CertificateSans.ttf', legacy_dir / 'CertificateSans.ttf')


def _admin_url():
    raw = os.environ.get('PX_CERTIFICATE_TEST_ADMIN_URL', '')
    url = make_url(raw)
    if url.drivername != 'postgresql+psycopg' or url.database != 'postgres':
        raise RuntimeError('DEDICATED_POSTGRES_ADMIN_URL_REQUIRED')
    return url


def _wait_for_ready(area: Path, timeout: float) -> dict:
    deadline = time.monotonic() + timeout
    ready = area / 'ready.json'
    while time.monotonic() < deadline:
        if ready.exists():
            return json.loads(ready.read_text(encoding='utf-8'))
        time.sleep(0.2)
    raise TimeoutError('NATIVE_RESTORE_COORDINATOR_READY_TIMEOUT')


def restore(admin_url, source_name: str, restore_name: str) -> dict:
    if not _NAME.fullmatch(source_name) or not _NAME.fullmatch(restore_name):
        raise RuntimeError('UNSAFE_COORDINATOR_DATABASE_NAME')
    env = dict(os.environ)
    if admin_url.password:
        env['PGPASSWORD'] = admin_url.password
    common = ['--host', admin_url.host or 'localhost', '--port', str(admin_url.port or 5432),
              '--username', admin_url.username or 'postgres', '--no-password']
    started = time.monotonic()
    dump_proc = subprocess.run(['pg_dump', '--format=custom', '--dbname', source_name, *common],
                                env=env, capture_output=True, timeout=120)
    if dump_proc.returncode != 0:
        raise RuntimeError('pg_dump_FAILED:' + dump_proc.stderr.decode(errors='replace')[-2000:])
    dump_seconds = time.monotonic() - started
    restored_started = time.monotonic()
    restore_proc = subprocess.run(['pg_restore', '--format=custom', '--dbname', restore_name,
                                    '--no-owner', '--no-privileges', '--clean', '--if-exists', '--exit-on-error', *common],
                                   input=dump_proc.stdout, capture_output=True, timeout=120, env=env)
    # --if-exists already handles absent objects. A nonzero status means the
    # restore was not completed and must never produce a restored.json receipt.
    stderr_text = restore_proc.stderr.decode(errors='replace')
    if restore_proc.returncode != 0:
        raise RuntimeError('pg_restore_FAILED:' + stderr_text[-2000:])
    restore_seconds = time.monotonic() - restored_started
    return {'backup': {'bytes': len(dump_proc.stdout), 'seconds': round(dump_seconds, 3)},
            'restore': {'seconds': round(restore_seconds, 3)}}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--area', required=True, help='Directory the test writes ready.json/reads restored.json in')
    parser.add_argument('--ready-timeout', type=float, default=180.0)
    args = parser.parse_args()
    area = Path(args.area)
    area.mkdir(parents=True, exist_ok=True)
    admin_url = _admin_url()
    ready = _wait_for_ready(area, args.ready_timeout)
    outcome = restore(admin_url, ready['source_database'], ready['restore_database'])
    restore_resources(area / 'restored-data/restore-resources')
    restore_private_data(area)
    (area / 'restored.json').write_text(
        json.dumps({'status': 'restored', **outcome}, ensure_ascii=False, indent=2), encoding='utf-8')


if __name__ == '__main__':
    main()
