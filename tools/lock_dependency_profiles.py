"""Regenerate profile locks from committed constraints using the recorded resolver.

Run deliberately after reviewing direct input/constraint changes. Normal setup
installs committed locks and never invokes a resolver or updates these files.
"""
from __future__ import annotations
import hashlib
import json
import os
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
LOCKS = ROOT / 'requirements' / 'locks'
PROFILES = {
    'runtime': ['requirements.txt'],
    'postgres': ['requirements-postgres.txt'],
    'qa': ['requirements.txt', 'requirements-qa.txt'],
    'qa-postgres': ['requirements-postgres.txt', 'requirements-qa.txt'],
    'observability': ['requirements.txt', 'requirements-observability.txt'],
    'postgres-observability': ['requirements-postgres.txt', 'requirements-observability.txt'],
    'bootstrap': ['requirements/locks/bootstrap.in'],
}


def main():
    resolver = subprocess.check_output(['uv', '--version'], text=True).strip()
    if resolver.split()[:2] != ['uv', '0.12.23']:
        raise RuntimeError('REGENERATION_REQUIRES_RECORDED_UV_0_12_23')
    # Regeneration claims PyPI provenance, so do not silently inherit private
    # indexes, extra indexes or uv configuration. Proxy/TLS system settings stay
    # available; no index credentials are inspected, logged or committed.
    resolver_env = {key: value for key, value in os.environ.items()
                    if not key.startswith(('UV_', 'PIP_'))}
    for profile, inputs in PROFILES.items():
        subprocess.run(['uv', '--no-config', 'pip', 'compile', *inputs,
                        '--default-index', 'https://pypi.org/simple', '--constraints', 'requirements/locks/constraints.txt',
                        '--universal', '--python-version', '3.11', '--generate-hashes', '--only-binary=:all:',
                        '--no-annotate', '--no-header', '--output-file', f'requirements/locks/{profile}.txt'],
                       cwd=ROOT, env=resolver_env, check=True, stdout=subprocess.DEVNULL)
    paths = sorted({Path(name) for inputs in PROFILES.values() for name in inputs}
                   | {Path(f'requirements/locks/{profile}.txt') for profile in PROFILES}
                   | {Path('requirements/locks/constraints.txt')})
    manifest = {
        'schema_version': 1, 'resolver': resolver, 'index_url': 'https://pypi.org/simple',
        'index_selection': 'Explicit --default-index; --no-config; UV_/PIP_ overrides excluded from resolver environment.',
        'profiles': PROFILES,
        'native_ci_targets': [{'python': '3.12', 'os': 'linux', 'architectures': ['x86_64', 'aarch64']},
                              {'python': '3.13', 'os': 'windows', 'architectures': ['AMD64']}],
        'legacy_python_3_11': 'Universal resolution retained; native execution is a separate acceptance claim.',
        'policy': 'Preserve direct pins and observed baseline transitive versions. All allowed distribution hashes are committed. Install wheels only.',
        'sha256': {path.as_posix(): hashlib.sha256((ROOT/path).read_bytes()).hexdigest() for path in paths},
    }
    (LOCKS/'profiles.json').write_text(json.dumps(manifest, indent=2)+'\n', encoding='utf-8')


if __name__ == '__main__':
    main()
