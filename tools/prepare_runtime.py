"""Prepare/check an isolated, hash-locked environment; never starts the application."""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import platform
import re
import subprocess
import sys
import venv
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
VENV = ROOT / '.venv'
LOCKS = ROOT / 'requirements' / 'locks'
PROFILES = ('runtime', 'local', 'postgres', 'qa', 'qa-postgres', 'observability', 'postgres-observability')


def canonical_profile(profile: str) -> str:
    if profile not in PROFILES:
        raise ValueError('UNKNOWN_RUNTIME_PROFILE')
    return 'runtime' if profile == 'local' else profile


def executable(directory: Path | None = None) -> Path:
    return (directory or VENV) / ('Scripts/python.exe' if os.name == 'nt' else 'bin/python')


def _run(args: list[str]) -> subprocess.CompletedProcess:
    return subprocess.run(args, cwd=ROOT, capture_output=True, text=True, encoding='utf-8')


def lock_identity(profile: str) -> dict:
    selected = canonical_profile(profile)
    files = [LOCKS / 'bootstrap.txt', LOCKS / f'{selected}.txt']
    return {str(path.relative_to(ROOT)): hashlib.sha256(path.read_bytes()).hexdigest() for path in files}


def environment_probe(profile: str) -> dict:
    """Run inside the target interpreter; evaluate universal-lock markers locally."""
    from importlib.metadata import distributions
    from pip._vendor.packaging.requirements import Requirement
    from pip._vendor.packaging.utils import canonicalize_name
    from importlib import import_module

    selected = canonical_profile(profile)
    expected = {}
    for path in (LOCKS / 'bootstrap.txt', LOCKS / f'{selected}.txt'):
        for raw in path.read_text(encoding='utf-8').replace('\\\n', ' ').splitlines():
            line = raw.strip()
            if not line or line.startswith('#'):
                continue
            if '--hash=sha256:' not in line:
                raise RuntimeError('UNHASHED_LOCK_REQUIREMENT')
            requirement = Requirement(re.sub(r'\s+--hash=sha256:[a-f0-9]{64}', '', line).strip())
            if requirement.marker and not requirement.marker.evaluate():
                continue
            specifiers = list(requirement.specifier)
            if len(specifiers) != 1 or specifiers[0].operator != '==':
                raise RuntimeError('UNPINNED_LOCK_REQUIREMENT')
            name = canonicalize_name(requirement.name)
            version = specifiers[0].version
            if name in expected and expected[name] != version:
                raise RuntimeError('CONFLICTING_PROFILE_LOCKS')
            expected[name] = version
    installed = {canonicalize_name(dist.metadata['Name']): dist.version for dist in distributions()}
    mismatches = {name: {'expected': version, 'actual': installed.get(name)}
                  for name, version in expected.items() if installed.get(name) != version}
    # Python 3.11 ensurepip can include setuptools/wheel. They are bootstrap
    # tooling; application and optional profile packages still match exactly.
    unexpected = sorted(set(installed) - set(expected) - {'setuptools', 'wheel'})
    modules = ['fastapi', 'sqlalchemy', 'uvicorn', 'qrcode', 'PIL', 'fontTools', 'pypdfium2']
    if selected in ('postgres', 'qa-postgres', 'postgres-observability'):
        modules.append('psycopg')
    if selected in ('qa', 'qa-postgres'):
        modules.extend(['pytest', 'httpx', 'playwright', 'psutil', 'coverage'])
    if selected in ('observability', 'postgres-observability'):
        modules.extend(['opentelemetry.sdk', 'opentelemetry.exporter.otlp.proto.http.trace_exporter'])
    for module in modules:
        import_module(module)
    from datetime import datetime
    from zoneinfo import ZoneInfo, reset_tzpath
    reset_tzpath([])
    ZoneInfo.clear_cache()
    zone_seconds = int(datetime(2026, 10, 19, tzinfo=ZoneInfo('Asia/Aden')).utcoffset().total_seconds())
    return {'prefix': sys.prefix, 'version': list(sys.version_info[:2]), 'system': platform.system(),
            'exe': sys.executable, 'inventory': dict(sorted(installed.items())),
            'expected': dict(sorted(expected.items())), 'mismatches': mismatches,
            'unexpected': unexpected, 'imports_checked': modules,
            'tzdata_without_system_zoneinfo': zone_seconds == 10800,
            'lock_sha256': lock_identity(profile)}


def check(profile: str, directory: Path | None = None) -> dict:
    directory = (directory or VENV).resolve()
    exe = executable(directory)
    result = {'profile': canonical_profile(profile), 'system': platform.system(), 'architecture': platform.machine(),
              'host_python': platform.python_version(), 'venv_python': str(exe), 'exists': exe.is_file(),
              'platform_compatible': False, 'dependencies_ok': False, 'lock_sha256': lock_identity(profile)}
    if not exe.is_file():
        result['reason'] = 'VENV_NOT_PREPARED'
        return result
    try:
        identity = _run([str(exe), '-c', 'import json,sys,platform;print(json.dumps(dict(prefix=sys.prefix,version=list(sys.version_info[:2]),system=platform.system(),exe=sys.executable)))'])
        if identity.returncode:
            raise RuntimeError('VENV_INTERPRETER_FAILED')
        actual = json.loads(identity.stdout)
        result['platform_compatible'] = (
            actual['system'] == platform.system() and tuple(actual['version']) == sys.version_info[:2]
            and Path(actual['prefix']).resolve() == directory and Path(actual['exe']).resolve() == exe.resolve())
        if not result['platform_compatible']:
            result['reason'] = 'FOREIGN_OR_MISMATCHED_VENV'
            return result
        pip_check = _run([str(exe), '-m', 'pip', 'check'])
        if pip_check.returncode:
            result.update(reason='PIP_DEPENDENCIES_BROKEN', pip_check=pip_check.stdout + pip_check.stderr)
            return result
        probe = _run([str(exe), str(Path(__file__).resolve()), '--profile', profile, '--probe'])
        if probe.returncode:
            result.update(reason='LOCK_OR_TIMEZONE_PROBE_FAILED', probe_error=probe.stderr[-2000:])
            return result
        payload = json.loads(probe.stdout)
        result.update({key: payload[key] for key in ('inventory', 'expected', 'mismatches', 'unexpected', 'imports_checked', 'tzdata_without_system_zoneinfo')})
        result['dependencies_ok'] = not payload['mismatches'] and payload['tzdata_without_system_zoneinfo']
        result['profile_isolated'] = not payload['unexpected']
        if not result['dependencies_ok']:
            result['reason'] = 'DEPENDENCY_LOCK_MISMATCH'
    except (OSError, ValueError, RuntimeError) as exc:
        result['reason'] = str(exc)
    return result


def prepare(profile: str, directory: Path | None = None) -> dict:
    directory = (directory or VENV).resolve()
    exe = executable(directory)
    if not exe.is_file():
        if directory.exists():
            raise RuntimeError('INCOMPATIBLE_VENV_DO_NOT_OVERWRITE')
        venv.EnvBuilder(with_pip=True).create(directory)
    if not check(profile, directory)['platform_compatible']:
        raise RuntimeError('FOREIGN_OR_MISMATCHED_VENV_DO_NOT_OVERWRITE')
    for filename in ('bootstrap.txt', f'{canonical_profile(profile)}.txt'):
        subprocess.run([str(exe), '-m', 'pip', 'install', '--disable-pip-version-check', '--require-hashes',
                        '--only-binary=:all:', '-r', str(LOCKS / filename)], cwd=ROOT, check=True)
    return check(profile, directory)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description='PulseX hash-locked isolated environment setup')
    parser.add_argument('--profile', choices=PROFILES, default='local')
    parser.add_argument('--venv', type=Path, default=VENV, help='Explicit environment path; never overwrites a foreign environment')
    parser.add_argument('--check', action='store_true', help='Read-only validation; no install')
    parser.add_argument('--probe', action='store_true', help=argparse.SUPPRESS)
    parser.add_argument('--strict-profile', action='store_true', help='Fail if packages outside this profile are installed')
    args = parser.parse_args(argv)
    if not (3, 11) <= sys.version_info[:2] < (3, 14):
        raise RuntimeError('PYTHON_3_11_TO_3_13_REQUIRED')
    if args.probe:
        print(json.dumps(environment_probe(args.profile), ensure_ascii=False))
        return 0
    result = check(args.profile, args.venv) if args.check else prepare(args.profile, args.venv)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    passed = result['platform_compatible'] and result['dependencies_ok']
    if args.strict_profile:
        passed = passed and result.get('profile_isolated', False)
    return 0 if passed else 2


if __name__ == '__main__':
    raise SystemExit(main())
