import importlib.util
import json
from pathlib import Path
import subprocess
import tempfile
import unittest

spec = importlib.util.spec_from_file_location('asset_control', Path(__file__).with_name('asset_control.py'))
control = importlib.util.module_from_spec(spec)
spec.loader.exec_module(control)


class SnapshotTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name) / 'system'
        self.root.mkdir()
        subprocess.run(['git', 'init', '-q', str(self.root)], check=True)
        self.lock = self.root / 'assets.lock.json'
        self.lock.write_text(json.dumps({'schema': control.SCHEMA, 'assets': []}))
        self.source = Path(self.temp.name) / 'export'
        self.source.mkdir()
        (self.source / 'module.py').write_text('VALUE = 42\n')

    def adopt(self, destination='vendor/owned', **changes):
        args = dict(root=self.root, lock_path=self.lock, source=self.source, destination=destination,
                    asset_id='sample.module', origin='owner/source', revision='a' * 40, version='1.0.0')
        args.update(changes)
        return control.adopt(**args)

    def test_independent_after_upstream_deleted(self):
        self.adopt()
        import shutil
        shutil.rmtree(self.source)
        result = control.verify(self.root, self.lock)
        self.assertEqual(result['status'], 'source-verified')
        self.assertFalse(result['runtimeVerified'])
        self.assertEqual((self.root / 'vendor/owned/module.py').read_text(), 'VALUE = 42\n')

    def test_modified_file_detected(self):
        self.adopt()
        (self.root / 'vendor/owned/module.py').write_text('VALUE = 0\n')
        self.assertEqual(control.verify(self.root, self.lock)['findings'][0]['code'], 'LOCAL_ASSET_DRIFT')

    def test_removed_file_detected(self):
        self.adopt()
        (self.root / 'vendor/owned/module.py').unlink()
        self.assertEqual(control.verify(self.root, self.lock)['status'], 'failed')

    def test_added_file_detected(self):
        self.adopt()
        (self.root / 'vendor/owned/new.py').write_text('pass')
        self.assertEqual(control.verify(self.root, self.lock)['status'], 'failed')

    def test_upgrade_never_overwrites_existing_copy(self):
        self.adopt()
        with self.assertRaises(ValueError):
            self.adopt()

    def test_parent_escape_rejected(self):
        with self.assertRaises(ValueError):
            self.adopt('../escape')

    def test_absolute_path_rejected(self):
        with self.assertRaises(ValueError):
            self.adopt('/escape')

    def test_symlink_source_rejected(self):
        (self.source / 'link').symlink_to(self.lock)
        with self.assertRaises(ValueError):
            self.adopt()

    def test_symlink_destination_parent_rejected(self):
        (self.root / 'vendor').symlink_to(self.source)
        with self.assertRaises(ValueError):
            self.adopt()

    def test_secret_file_rejected(self):
        (self.source / '.env').write_text('EXAMPLE=private')
        with self.assertRaises(ValueError):
            self.adopt()

    def test_bad_revision_rejected_before_copy(self):
        with self.assertRaises(ValueError):
            self.adopt(revision='main')
        self.assertFalse((self.root / 'vendor/owned').exists())

    def test_overlap_rejected(self):
        self.adopt()
        with self.assertRaises(ValueError):
            self.adopt(destination='vendor/owned/child', asset_id='sample.child')

    def test_gitlink_fails(self):
        subprocess.run(['git', '-C', str(self.root), 'update-index', '--add', '--cacheinfo',
                        '160000,' + 'b' * 40 + ',external'], check=True)
        self.assertEqual(control.verify(self.root, self.lock)['findings'][0]['code'], 'EXTERNAL_GITLINK')

    def test_git_blob_inventory_supported(self):
        self.adopt()
        data = json.loads(self.lock.read_text())
        for meta in data['assets'][0]['files'].values():
            del meta['sha256']
        self.lock.write_text(json.dumps(data))
        self.assertEqual(control.verify(self.root, self.lock)['status'], 'source-verified')

    def test_empty_registration_is_not_a_pass(self):
        self.assertEqual(control.verify(self.root, self.lock)['status'], 'registration-required')


if __name__ == '__main__':
    unittest.main()
