"""Regression controls for locked setup, transitive drift and hash rejection."""
from __future__ import annotations
import hashlib
from importlib import metadata
import subprocess
import sys
import zipfile
from pathlib import Path

import pytest
from tools import launcher, prepare_runtime


def test_launcher_checks_full_locked_runtime(monkeypatch, tmp_path):
    seen = []
    monkeypatch.setattr(launcher, 'ENV', tmp_path / 'venv')
    monkeypatch.setattr(prepare_runtime, 'check', lambda profile, directory: (seen.append((profile, directory)) or {'platform_compatible': True, 'dependencies_ok': False}))
    assert launcher.env_check() is False
    assert seen == [('runtime', tmp_path / 'venv')]


def test_launcher_preparation_uses_locked_profile_without_independent_pip(monkeypatch, tmp_path):
    checks = iter((False, True))
    prepared = []
    monkeypatch.setattr(launcher, 'ENV', tmp_path/'venv')
    monkeypatch.setattr(launcher, 'env_check', lambda: next(checks))
    monkeypatch.setattr(prepare_runtime, 'prepare', lambda profile, directory: prepared.append((profile, directory)))
    launcher.prepare()
    assert prepared == [('runtime', tmp_path/'venv')]


def test_transitive_drift_is_reported_even_when_direct_pins_match(monkeypatch):
    original = metadata.distributions
    class ChangedDistribution:
        def __init__(self, actual):
            self.actual = actual
            self.metadata = actual.metadata
            self.version = '0.0.0' if actual.metadata['Name'].lower() == 'pydantic' else actual.version
        def __getattr__(self, name):
            return getattr(self.actual, name)
    monkeypatch.setattr(metadata, 'distributions', lambda: (ChangedDistribution(d) for d in original()))
    result = prepare_runtime.environment_probe('runtime')
    assert result['mismatches']['pydantic']['actual'] == '0.0.0'
    assert 'fastapi' not in result['mismatches']
    assert result['tzdata_without_system_zoneinfo'] is True


def test_prepare_refuses_foreign_environment_before_any_install(monkeypatch, tmp_path):
    directory = tmp_path/'foreign'
    exe = prepare_runtime.executable(directory)
    exe.parent.mkdir(parents=True)
    exe.write_text('foreign interpreter marker', encoding='utf-8')
    monkeypatch.setattr(prepare_runtime, 'check', lambda *_: {'platform_compatible': False})
    with pytest.raises(RuntimeError, match='FOREIGN_OR_MISMATCHED'):
        prepare_runtime.prepare('runtime', directory)
    assert exe.read_text() == 'foreign interpreter marker'


def test_strict_profile_rejects_qa_pollution_in_runtime(monkeypatch, tmp_path):
    monkeypatch.setattr(prepare_runtime, 'check', lambda *_: {'platform_compatible': True, 'dependencies_ok': True, 'profile_isolated': False, 'unexpected': ['playwright']})
    assert prepare_runtime.main(['--profile', 'runtime', '--venv', str(tmp_path/'env'), '--check', '--strict-profile']) == 2


def test_pip_rejects_a_modified_wheel_against_committed_hash(tmp_path):
    wheel = tmp_path/'px_hash_control-0.0.0-py3-none-any.whl'
    with zipfile.ZipFile(wheel, 'w') as archive:
        archive.writestr('px_hash_control-0.0.0.dist-info/METADATA', 'Metadata-Version: 2.1\nName: px-hash-control\nVersion: 0.0.0\n')
        archive.writestr('px_hash_control-0.0.0.dist-info/WHEEL', 'Wheel-Version: 1.0\nGenerator: test\nRoot-Is-Purelib: true\nTag: py3-none-any\n')
        archive.writestr('px_hash_control-0.0.0.dist-info/RECORD', '')
    trusted_hash = hashlib.sha256(wheel.read_bytes()).hexdigest()
    with zipfile.ZipFile(wheel, 'a') as archive:
        archive.writestr('changed.txt', 'changed after lock generation')
    locked = tmp_path/'control.txt'
    locked.write_text(f'px-hash-control==0.0.0 --hash=sha256:{trusted_hash}\n', encoding='utf-8')
    result = subprocess.run([sys.executable, '-m', 'pip', 'download', '--disable-pip-version-check', '--no-index',
                             '--no-deps', '--require-hashes', '--only-binary=:all:', '--find-links', str(tmp_path),
                             '-r', str(locked), '--dest', str(tmp_path/'downloads')], capture_output=True, text=True)
    assert result.returncode != 0
    assert 'HASHES' in (result.stdout+result.stderr).upper()
