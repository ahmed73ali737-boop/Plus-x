"""Synthetic offline evidence only: no fixture is real build attestation."""
import copy
import importlib.util
import io
import json
from pathlib import Path
import subprocess
import tarfile
import tempfile
import unittest
from unittest.mock import patch

spec = importlib.util.spec_from_file_location('guard', Path(__file__).parents[1] / 'release_receipt.py')
g = importlib.util.module_from_spec(spec)
spec.loader.exec_module(g)
S = 'a' * 40
H = 'b' * 64
BASE = 'python:3.12-slim@sha256:' + H


def fixture():
    files = {'ops/Dockerfile.development': ('FROM ' + BASE + '\n').encode(),
             'requirements/locks/test.txt': b'fixture locked dependencies'}
    out = io.BytesIO()
    with tarfile.open(fileobj=out, mode='w') as tar:
        for n, data in files.items():
            info = tarfile.TarInfo(n); info.size = len(data); info.mode = 0o644
            tar.addfile(info, io.BytesIO(data))
    archive = out.getvalue()
    m = {'source_sha': S, 'profile': 'development', 'dockerfile': 'ops/Dockerfile.development',
         'build_args': {'PULSEX_SOURCE_SHA': S}, 'base_images': [BASE],
         'context_tar_sha256': g.digest(archive),
         'files': {n: {'sha256': g.digest(data), 'mode': '100644'} for n, data in files.items()},
         'dependency_locks': {'requirements/locks/test.txt': g.digest(files['requirements/locks/test.txt'])}}
    mb = json.dumps(m).encode()
    r = {'schema': 'plusx-release-receipt/v1', 'source_sha': S, 'manifest_sha256': g.digest(mb),
         'context_sha256': g.digest(archive), 'build_argv': g.recipe(S), 'build_environment': {},
         'secret_mounts': [], 'ssh_mounts': [], 'network': 'none', 'dependency_install': 'offline-hash-verified',
         'builder_binary_sha256': H, 'dependency_install_receipt_sha256': H, 'build_log_sha256': H,
         'dockerfile_sha256': g.digest(files[m['dockerfile']]),
         'base_materials': [{'reference': BASE, 'platform': 'linux/amd64', 'authenticated_origin_receipt_sha256': H}],
         'image': {'reference': 'example/plusx@sha256:' + H, 'config_digest': 'sha256:' + H},
         'rollback_image': {'reference': 'example/plusx@sha256:' + 'c'*64, 'config_digest': 'sha256:' + 'd'*64},
         'rollback_receipt_sha256': H, 'path_prefix': '/plusx', 'health_route': '/api/health/ready',
         'mounts': [{'Type': 'volume', 'Name': 'plusx-development_plusx_development_data', 'Destination': '/app/data', 'RW': True}]}
    c = {'id': 'e'*64, 'image': r['image']['config_digest'], 'running': True, 'started': 'fixture',
         'mounts': copy.deepcopy(r['mounts']), 'readonly': True, 'privileged': False,
         'cap_add': None, 'network': 'plusx-development_default', 'user': 'pulsex',
         'command_ok': True, 'entrypoint_ok': True, 'health_ok': True,
         'public_env': ['PUBLIC_PATH_PREFIX=/plusx', 'PUBLIC_ORIGIN=https://5.189.157.131', None]}
    image = {'id': r['image']['config_digest'], 'digests': [r['image']['reference']], 'revision': S}
    rollback = {'id': r['rollback_image']['config_digest'], 'digests': [r['rollback_image']['reference']], 'revision': 'f'*40}
    return r, mb, archive, c, image, rollback


class ReceiptTests(unittest.TestCase):
    def test_valid_offline_fixture(self):
        r, mb, ar, c, im, rb = fixture()
        self.assertEqual(g.validate(r, mb, ar, S), r)
        g.reconcile(r, c, im, rb)

    def test_duplicate_json_rejected(self):
        with self.assertRaises(ValueError): g.strict_json(b'{"x":1,"x":2}')

    def test_archive_tamper(self):
        r, mb, ar, *_ = fixture()
        with self.assertRaises(ValueError): g.validate(r, mb, ar + b'changed', S)

    def test_full_source_required(self):
        with self.assertRaises(ValueError): g.recipe('main')

    def test_source_checkout_drift(self):
        with patch.object(g, 'run', return_value=b'wrong'):
            with self.assertRaises(ValueError): g.source_check(Path('/fixture'), S)

    def test_dirty_checkout(self):
        with patch.object(g, 'run', side_effect=[S.encode(), b' M file']):
            with self.assertRaises(ValueError): g.source_check(Path('/fixture'), S)

    def test_clean_checkout(self):
        with patch.object(g, 'run', side_effect=[S.encode(), b'']):
            g.source_check(Path('/fixture'), S)

    def test_manifest_lock_drift(self):
        r, mb, ar, *_ = fixture()
        m = json.loads(mb); m['dependency_locks']['requirements/locks/test.txt'] = '0'*64
        mb = json.dumps(m).encode(); r['manifest_sha256'] = g.digest(mb)
        with self.assertRaisesRegex(ValueError, 'LOCK_DRIFT'): g.validate(r, mb, ar, S)

    def test_archive_symlink(self):
        r, mb, ar, *_ = fixture()
        out = io.BytesIO()
        with tarfile.open(fileobj=out, mode='w') as tar:
            member = tarfile.TarInfo('ops/Dockerfile.development')
            member.type = tarfile.SYMTYPE; member.linkname = '/etc/passwd'; tar.addfile(member)
        ar = out.getvalue(); m = json.loads(mb); m['context_tar_sha256'] = g.digest(ar)
        mb = json.dumps(m).encode(); r.update(context_sha256=g.digest(ar), manifest_sha256=g.digest(mb))
        with self.assertRaisesRegex(ValueError, 'UNSAFE_ARCHIVE'): g.validate(r, mb, ar, S)

    def test_missing_receipt_never_inspects(self):
        argv = ['guard', '--source-root', '/fixture', '--source-sha', S,
                '--manifest', '/missing', '--archive', '/missing', '--receipt', '/missing',
                '--signature', '/missing', '--public-key', '/missing',
                '--trusted-key-sha256', H, '--container-id', 'e'*64]
        with patch('sys.argv', argv), patch.object(g, 'source_check'), patch.object(g, 'inspect') as inspect, patch('sys.stdout', new_callable=io.StringIO):
            self.assertEqual(g.main(), 2)
            inspect.assert_not_called()

    def test_runtime_race_blocks(self):
        r, mb, ar, c, im, rb = fixture()
        argv = ['guard', '--source-root', '/fixture', '--source-sha', S,
                '--manifest', '/fixture', '--archive', '/fixture', '--receipt', '/fixture',
                '--signature', '/fixture', '--public-key', '/fixture',
                '--trusted-key-sha256', H, '--container-id', 'e'*64]
        changed = dict(c, started='restarted')
        with patch('sys.argv', argv), patch.object(g, 'source_check'), patch.object(g, 'authenticate', return_value=r), patch.object(Path, 'read_bytes', side_effect=[mb, ar]), patch.object(g, 'inspect', side_effect=[c, im, rb, changed]), patch('sys.stdout', new_callable=io.StringIO):
            self.assertEqual(g.main(), 2)

    def test_signed_bytes_and_tamper(self):
        # Ephemeral test-only key; never used as a deployment trust anchor.
        with tempfile.TemporaryDirectory() as d:
            p = Path(d)
            def openssl(*args):
                subprocess.run(['openssl', *args], check=True, capture_output=True)
            openssl('genpkey', '-algorithm', 'EC', '-pkeyopt', 'ec_paramgen_curve:P-256', '-out', str(p/'test.key'))
            openssl('pkey', '-in', str(p/'test.key'), '-pubout', '-out', str(p/'test.pub'))
            (p/'receipt').write_text('{"fixture":true}')
            openssl('dgst', '-sha256', '-sign', str(p/'test.key'), '-out', str(p/'sig'), str(p/'receipt'))
            pin = g.digest((p/'test.pub').read_bytes())
            self.assertEqual(g.authenticate(p/'receipt', p/'sig', p/'test.pub', pin), {'fixture': True})
            with self.assertRaises(ValueError): g.authenticate(p/'receipt', p/'sig', p/'test.pub', '0'*64)
            (p/'receipt').write_text('{"fixture":false}')
            with self.assertRaises(subprocess.CalledProcessError): g.authenticate(p/'receipt', p/'sig', p/'test.pub', pin)

    def test_inspection_never_fetches_secrets(self):
        with patch.object(g, 'run', return_value=b'{}') as run:
            g.inspect('container', 'e'*64, g.CONTAINER_FORMAT)
        args = run.call_args.args[0]
        self.assertEqual(args[:4], ['docker', 'container', 'inspect', '--format'])
        self.assertNotIn('{{json .Config.Env}}', args[4])
        self.assertNotIn('{{json .Config.Cmd}}', args[4])


def receipt_case(name, key, value):
    def test(self):
        r, mb, ar, *_ = fixture(); r[key] = value
        with self.assertRaises((ValueError, KeyError, TypeError)): g.validate(r, mb, ar, S)
    setattr(ReceiptTests, 'test_reject_' + name, test)


for name, key, value in [
    ('source', 'source_sha', 'f'*40), ('manifest', 'manifest_sha256', '0'*64),
    ('context', 'context_sha256', '0'*64), ('host_context', 'build_argv', ['docker', 'build', '.']),
    ('secret_arg', 'build_argv', g.recipe(S) + ['--build-arg', 'TOKEN=fixture']),
    ('env', 'build_environment', {'TOKEN': 'fixture'}), ('secret_mount', 'secret_mounts', ['fixture']),
    ('ssh', 'ssh_mounts', ['default']), ('network', 'network', 'host'),
    ('missing_install', 'dependency_install_receipt_sha256', ''),
    ('missing_base', 'base_materials', []), ('missing_builder', 'builder_binary_sha256', ''),
    ('mutable_image', 'image', {'reference': 'example/plusx:latest', 'config_digest': 'sha256:'+H}),
    ('missing_rollback', 'rollback_image', {}), ('missing_rollback_receipt', 'rollback_receipt_sha256', ''),
    ('prefix', 'path_prefix', '/'), ('health_route', 'health_route', '/plusx/not-health'),
    ('host_mount', 'mounts', [{'Type': 'bind', 'Destination': '/app'}]),
    ('dockerfile', 'dockerfile_sha256', '0'*64), ('schema', 'schema', 'unknown')]:
    receipt_case(name, key, value)


def runtime_case(name, target, key, value):
    def test(self):
        r, _, _, c, im, rb = fixture()
        {'container': c, 'image': im, 'rollback': rb}[target][key] = value
        with self.assertRaises(ValueError): g.reconcile(r, c, im, rb)
    setattr(ReceiptTests, 'test_runtime_' + name, test)


for name, target, key, value in [
    ('stopped', 'container', 'running', False), ('writable', 'container', 'readonly', False),
    ('privileged', 'container', 'privileged', True), ('capabilities', 'container', 'cap_add', ['SYS_ADMIN']),
    ('host_network', 'container', 'network', 'host'), ('root', 'container', 'user', 'root'),
    ('command', 'container', 'command_ok', False), ('entrypoint', 'container', 'entrypoint_ok', False),
    ('health', 'container', 'health_ok', False), ('prefix', 'container', 'public_env', [None]),
    ('mount', 'container', 'mounts', []), ('unlabeled', 'image', 'revision', None),
    ('revision', 'image', 'revision', 'f'*40), ('digest', 'image', 'digests', []),
    ('image_id', 'container', 'image', 'sha256:'+'0'*64), ('rollback', 'rollback', 'digests', [])]:
    runtime_case(name, target, key, value)


if __name__ == '__main__': unittest.main()
