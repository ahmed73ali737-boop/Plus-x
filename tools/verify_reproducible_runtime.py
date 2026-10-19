"""Build two fresh profile environments and compare inventories on the current OS.

CI must execute this independently on Python 3.12/Linux and 3.13/Windows; package
resolution is never represented as native execution of a different platform.
"""
from __future__ import annotations
import argparse
import hashlib
import json
import platform
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from tools.prepare_runtime import PROFILES, check, executable, lock_identity


def source_head():
    try:
        result = subprocess.run(['git', 'rev-parse', 'HEAD'], cwd=ROOT, capture_output=True, text=True)
        return result.stdout.strip() if result.returncode == 0 else None
    except OSError:
        return None


def test_source_hashes():
    # Hash actual checkout bytes: the repository LF policy must hold, and a
    # newline/content drift is visible rather than normalized out of evidence.
    return {path.relative_to(ROOT).as_posix(): hashlib.sha256(path.read_bytes()).hexdigest()
            for path in sorted((ROOT/'tests').rglob('*')) if path.is_file() and path.suffix in ('.py', '.mjs')}


def main(argv=None):
    parser = argparse.ArgumentParser()
    parser.add_argument('--profile', choices=PROFILES, default='qa')
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args(argv)
    output = args.output.resolve()
    output.parent.mkdir(parents=True, exist_ok=True)
    report = {'profile': args.profile, 'system': platform.system(), 'architecture': platform.machine(),
              'python': platform.python_version(), 'lock_sha256': lock_identity(args.profile), 'runs': [], 'passed': False}
    report['source_sha'] = report['source_sha_start'] = source_head()
    report['test_source_sha256_start'] = test_source_hashes()
    try:
        with tempfile.TemporaryDirectory(prefix='pulsex-repro-') as temporary:
            for number in (1, 2):
                directory = Path(temporary) / f'environment-{number}'
                command = [sys.executable, str(ROOT / 'tools/prepare_runtime.py'), '--profile', args.profile,
                           '--venv', str(directory), '--strict-profile']
                result = subprocess.run(command, cwd=ROOT, capture_output=True, text=True, encoding='utf-8')
                log = output.with_name(output.stem + f'-environment-{number}.log')
                log.write_text(result.stdout + result.stderr, encoding='utf-8')
                run = {'number': number, 'returncode': result.returncode, 'log': log.name}
                if result.returncode == 0:
                    run.update(check(args.profile, directory))
                    identity = subprocess.run([str(executable(directory)), '-c',
                        'import json;from app.core.build_info import runtime_identity;print(json.dumps(runtime_identity()))'],
                        cwd=ROOT, capture_output=True, text=True, encoding='utf-8')
                    if identity.returncode:
                        raise RuntimeError(f'APPLICATION_IDENTITY_{number}_FAILED')
                    run['application_identity'] = json.loads(identity.stdout)
                    run['test_source_sha256'] = test_source_hashes()
                report['runs'].append(run)
                if result.returncode:
                    raise RuntimeError(f'CLEAN_ENVIRONMENT_{number}_FAILED')
            first, second = report['runs']
            report['same_inventory'] = first['inventory'] == second['inventory']
            report['same_lock_files'] = first['lock_sha256'] == second['lock_sha256'] == report['lock_sha256']
            report['tzdata_fallback_passed'] = all(run['tzdata_without_system_zoneinfo'] for run in report['runs'])
            report['profiles_isolated'] = all(run['profile_isolated'] for run in report['runs'])
            report['same_application_identity'] = first['application_identity'] == second['application_identity']
            report['same_test_sources'] = first['test_source_sha256'] == second['test_source_sha256'] == report['test_source_sha256_start']
            report['source_sha_end'] = source_head()
            report['same_source_head'] = report['source_sha_start'] == report['source_sha_end']
            report['passed'] = all(report[key] for key in ('same_inventory', 'same_lock_files', 'tzdata_fallback_passed',
                'profiles_isolated', 'same_application_identity', 'same_test_sources', 'same_source_head'))
    except (OSError, RuntimeError) as exc:
        report['error'] = str(exc)
    finally:
        output.write_text(json.dumps(report, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    print(json.dumps({'passed': report['passed'], 'profile': args.profile, 'output': str(output)}, ensure_ascii=False))
    return 0 if report['passed'] else 1


if __name__ == '__main__':
    raise SystemExit(main())
