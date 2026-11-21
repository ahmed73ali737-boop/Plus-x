"""Isolated Git fixtures; no Docker daemon, network or application imports."""
import importlib.util
import io
import json
from pathlib import Path
import subprocess
import tarfile
import tempfile
import unittest

SCRIPT = Path(__file__).resolve().parents[1] / 'deployment_provenance.py'


class ProvenanceTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name) / 'repo'
        self.root.mkdir()
        self.git('init', '-q')
        self.git('config', 'user.email', 'test@example.invalid')
        self.git('config', 'user.name', 'Test')
        self.put('.gitignore', 'ignored/\n')
        self.put('app/main.py', 'print(42)\n')
        self.put('requirements/locks/runtime.txt', 'example==1.0 --hash=sha256:' + 'a'*64 + '\n')
        self.put('ops/container-image-lock.json', json.dumps({'images': [{'digest': 'sha256:' + 'b'*64}]}))
        self.put('ops/build-toolchain.json', '{}')
        self.put('ops/consolidated-source-lock.json', '{}')
        self.put('compose.development.yaml', 'services: {}\n')
        self.put('.dockerignore', '.git\n')
        self.put('ops/Dockerfile.development', 'FROM python@sha256:' + 'b'*64 + '\nCOPY app ./app\nCOPY requirements/locks/runtime.txt ./requirements/locks/\nRUN python -m pip install --require-hashes --only-binary=:all: -r requirements/locks/runtime.txt\n')
        self.commit()

    def put(self, name, data):
        p = self.root / name
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(data)

    def git(self, *args):
        return subprocess.check_output(['git', *args], cwd=self.root, stderr=subprocess.DEVNULL).decode().strip()

    def commit(self):
        self.git('add', '.')
        self.git('commit', '-qm', 'fixture')
        self.sha = self.git('rev-parse', 'HEAD')

    def module(self):
        self.assertTrue(SCRIPT.exists(), 'deployment packaging must verify source before producing context')
        spec = importlib.util.spec_from_file_location('deployment_provenance', SCRIPT)
        m = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(m)
        return m

    def snapshot(self, sha=None):
        return self.module().package(self.root, sha or self.sha, 'development')

    def test_deterministic_context_excludes_ignored_injection(self):
        first, archive = self.snapshot()
        self.put('ignored/secret', 'DO_NOT_PACKAGE')
        second, again = self.snapshot()
        self.assertEqual(archive, again)
        self.assertEqual(first, second)
        with tarfile.open(fileobj=io.BytesIO(archive)) as tar:
            self.assertEqual(tar.extractfile('app/main.py').read(), b'print(42)\n')
            self.assertNotIn('ignored/secret', tar.getnames())
        self.assertEqual(first['source_sha'], self.sha)
        self.assertIn('requirements/locks/runtime.txt', first['dependency_locks'])

    def test_wrong_or_symbolic_source_rejected(self):
        for sha in ('HEAD', self.sha[:8], '0'*40):
            with self.subTest(sha=sha), self.assertRaises(ValueError):
                self.snapshot(sha)

    def test_dirty_tracked_source_rejected(self):
        self.put('app/main.py', 'changed')
        with self.assertRaises(ValueError): self.snapshot()

    def test_untracked_source_rejected(self):
        self.put('app/injected.py', 'changed')
        with self.assertRaises(ValueError): self.snapshot()

    def test_assume_unchanged_cannot_hide_mutation(self):
        self.git('update-index', '--assume-unchanged', 'app/main.py')
        self.put('app/main.py', 'changed')
        with self.assertRaises(ValueError): self.snapshot()

    def test_symlink_source_rejected(self):
        (self.root / 'app/main.py').unlink()
        (self.root / 'app/main.py').symlink_to('/etc/passwd')
        self.commit()
        with self.assertRaises(ValueError): self.snapshot()

    def test_mutable_base_rejected(self):
        p = self.root / 'ops/Dockerfile.development'
        p.write_text(p.read_text().replace('python@sha256:' + 'b'*64, 'python:latest'))
        self.commit()
        with self.assertRaises(ValueError): self.snapshot()

    def test_unhashed_dependency_rejected(self):
        self.put('requirements/locks/runtime.txt', 'example>=1\n')
        self.commit()
        with self.assertRaises(ValueError): self.snapshot()

    def test_missing_copy_input_rejected(self):
        p = self.root / 'ops/Dockerfile.development'
        p.write_text(p.read_text() + 'COPY missing /missing\n')
        self.commit()
        with self.assertRaises(ValueError): self.snapshot()

    def test_config_changes_fingerprint(self):
        before, _ = self.snapshot()
        self.put('compose.development.yaml', 'services: {app: {}}\n')
        self.commit()
        after, _ = self.snapshot()
        self.assertNotEqual(before['config_sha256'], after['config_sha256'])

    def test_labels_alone_never_pass_and_sensitive_fields_omitted(self):
        m = self.module()
        container = {'Id': 'c'*64, 'Image': 'sha256:'+'d'*64,
                     'State': {'Running': True}, 'Config': {'Env': ['PASSWORD=SECRET']}, 'Mounts': []}
        image = {'Id': container['Image'], 'RepoDigests': [],
                 'Config': {'Labels': {'org.opencontainers.image.revision': self.sha, 'secret': 'SECRET'}}}
        result = m.runtime_summary(container, image, self.sha)
        self.assertEqual(result['gate1'], 'UNVERIFIED')
        self.assertFalse(result['artifact_reconciled'])
        self.assertEqual(result['image_id'], container['Image'])
        self.assertNotIn('SECRET', json.dumps(result))

    def test_runtime_revision_mismatch(self):
        result = self.module().runtime_summary(
            {'Id': 'c'*64, 'Image': 'sha256:'+'d'*64, 'State': {'Running': True}},
            {'Id': 'sha256:'+'d'*64, 'Config': {'Labels': {'org.opencontainers.image.revision': '0'*40}}}, self.sha)
        self.assertTrue(result['source_mismatch'])

    def test_ignored_file_inside_copy_directory_is_not_packaged(self):
        self.put('.gitignore', 'app/cache/\n')
        self.commit()
        self.put('app/cache/injected.py', 'SECRET')
        _, archive = self.snapshot()
        with tarfile.open(fileobj=io.BytesIO(archive)) as tar:
            self.assertNotIn('app/cache/injected.py', tar.getnames())

    def test_unlocked_extra_install_rejected(self):
        p = self.root / 'ops/Dockerfile.development'
        p.write_text(p.read_text() + 'RUN pip install unlocked\n')
        self.commit()
        with self.assertRaises(ValueError): self.snapshot()

    def test_unknown_base_digest_rejected(self):
        p = self.root / 'ops/Dockerfile.development'
        p.write_text(p.read_text().replace('b'*64, 'e'*64))
        self.commit()
        with self.assertRaises(ValueError): self.snapshot()

    def test_archive_cli_does_not_overwrite_and_redacts_errors(self):
        archive = Path(self.tmp.name) / 'context.tar'
        command = ['python3', str(SCRIPT), '--root', str(self.root),
                   '--source-sha', self.sha, '--context-tar', str(archive)]
        result = subprocess.run(command, capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stdout)
        self.assertEqual(archive.stat().st_mode & 0o777, 0o600)
        before = archive.read_bytes()
        result = subprocess.run(command, capture_output=True, text=True)
        self.assertEqual(result.returncode, 2)
        self.assertEqual(archive.read_bytes(), before)
        self.assertNotIn(str(archive), result.stdout)
        self.assertEqual(result.stderr, '')

    def test_image_identity_disagreement_rejected(self):
        with self.assertRaises(ValueError):
            self.module().runtime_summary(
                {'Id': 'c'*64, 'Image': 'sha256:'+'d'*64}, {'Id': 'sha256:'+'e'*64}, self.sha)

    def test_declared_crlf_checkout_uses_canonical_committed_bytes(self):
        self.put('.gitattributes', '*.cmd text eol=crlf\n')
        self.put('app/start.cmd', 'echo hello\n')
        self.commit()
        (self.root / 'app/start.cmd').unlink()
        self.git('checkout', '--', 'app/start.cmd')
        self.assertEqual((self.root / 'app/start.cmd').read_bytes(), b'echo hello\r\n')
        _, archive = self.snapshot()
        with tarfile.open(fileobj=io.BytesIO(archive)) as tar:
            self.assertEqual(tar.extractfile('app/start.cmd').read(), b'echo hello\n')

    def test_hash_locked_environment_marker_is_covered(self):
        self.put('requirements/locks/runtime.txt', "example==1.0 ; sys_platform == 'win32' --hash=sha256:" + 'a'*64 + '\n')
        self.commit()
        report, _ = self.snapshot()
        self.assertIn('requirements/locks/runtime.txt', report['dependency_locks'])

    def test_untrusted_revision_label_is_redacted(self):
        result = self.module().runtime_summary(
            {'Id': 'c'*64, 'Image': 'sha256:'+'d'*64},
            {'Id': 'sha256:'+'d'*64, 'Config': {'Labels': {'org.opencontainers.image.revision': 'SECRET'}}}, self.sha)
        self.assertIsNone(result['revision_label'])
        self.assertNotIn('SECRET', json.dumps(result))
        self.assertEqual(result['gate1'], 'UNVERIFIED')


if __name__ == '__main__':
    unittest.main()
