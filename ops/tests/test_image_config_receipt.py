"""Synthetic config bytes and Docker responses; no daemon or production artifacts."""
import copy
import io
from pathlib import Path
from contextlib import ExitStack
import json
import unittest
from unittest.mock import patch
from test_release_receipt import g


def fixture():
    layers = ['sha256:' + 'a' * 64, 'sha256:' + 'b' * 64]
    config = {'os': 'linux', 'architecture': 'amd64',
              'rootfs': {'type': 'layers', 'diff_ids': layers}}
    raw = g.canonical(config)
    receipt = {'image': {'config_digest': 'sha256:' + g.digest(raw)}}
    observed = {'id': receipt['image']['config_digest'], 'os': 'linux',
                'architecture': 'amd64', 'rootfs_type': 'layers', 'layers': layers}
    return receipt, raw, config, observed


class ImageConfigTests(unittest.TestCase):
    def test_config_verifier_exists(self):
        self.assertTrue(callable(getattr(g, 'validate_image_config', None)),
                        'actual OCI config byte verification is missing')

    def test_positive_offline_and_fake_docker(self):
        r, raw, _, observed = fixture()
        g.validate_image_config(r, raw)
        with patch.object(g, 'run', return_value=json.dumps(observed).encode()):
            actual = g.inspect('image', r['image']['config_digest'], g.IMAGE_CONTENT_FORMAT)
        g.validate_image_config(r, raw, actual)

    def test_tampered_bytes(self):
        r, raw, _, _ = fixture()
        with self.assertRaisesRegex(g.ReceiptError, 'OCI_CONFIG_BYTES_MISMATCH'):
            g.validate_image_config(r, raw + b' ')

    def test_invalid_signed_config(self):
        for field, value in [('os', 'windows'), ('architecture', 'arm64'),
                             ('rootfs', {}), ('rootfs', {'type': 'layers', 'diff_ids': []}),
                             ('rootfs', {'type': 'layers', 'diff_ids': ['not-a-digest']}),
                             ('rootfs', {'type': 'other', 'diff_ids': ['sha256:' + 'a'*64]})]:
            with self.subTest(field=field, value=value):
                r, _, config, _ = fixture()
                config[field] = value
                raw = g.canonical(config)
                r['image']['config_digest'] = 'sha256:' + g.digest(raw)
                with self.assertRaises(g.ReceiptError):
                    g.validate_image_config(r, raw)

    def test_fake_docker_mismatches_and_missing_fields(self):
        for field, value in [('id', 'sha256:'+'0'*64), ('os', 'windows'),
                             ('architecture', 'arm64'), ('rootfs_type', 'other'),
                             ('layers', []), ('layers', None),
                             ('layers', ['sha256:'+'b'*64, 'sha256:'+'a'*64])]:
            with self.subTest(field=field, value=value):
                r, raw, _, observed = fixture()
                observed[field] = value
                with patch.object(g, 'run', return_value=json.dumps(observed).encode()):
                    actual = g.inspect('image', r['image']['config_digest'], g.IMAGE_CONTENT_FORMAT)
                with self.assertRaisesRegex(g.ReceiptError, 'LOCAL_IMAGE_CONTENT_MISMATCH'):
                    g.validate_image_config(r, raw, actual)
        r, raw, _, observed = fixture()
        for malformed in (None, [], {}, "synthetic-secret"):
            with self.assertRaisesRegex(g.ReceiptError, "LOCAL_IMAGE_CONTENT_MISMATCH"):
                g.validate_image_config(r, raw, malformed)
        for field in observed:
            incomplete = copy.deepcopy(observed)
            del incomplete[field]
            with self.assertRaisesRegex(g.ReceiptError, 'LOCAL_IMAGE_CONTENT_MISMATCH'):
                g.validate_image_config(r, raw, incomplete)

    def test_duplicate_config_keys(self):
        r, _, _, _ = fixture()
        raw = b'{"os":"linux","os":"windows"}'
        r['image']['config_digest'] = 'sha256:' + g.digest(raw)
        with self.assertRaisesRegex(g.ReceiptError, 'DUPLICATE_JSON_KEY'):
            g.validate_image_config(r, raw)

    def test_cli_checks_config_and_actual_docker_metadata(self):
        from test_release_receipt import fixture as release_fixture
        for mismatch in (False, True):
            with self.subTest(mismatch=mismatch), ExitStack() as stack:
                r, mb, ar, c, image, rollback = release_fixture()
                bound, raw, _, observed = fixture()
                r['image']['config_digest'] = bound['image']['config_digest']
                c['image'] = image['id'] = r['image']['config_digest']
                if mismatch:
                    observed['layers'] = []
                argv = ['guard', '--source-sha', r['source_sha'],
                        '--trusted-key-sha256', 'b'*64, '--container-id', c['id']]
                for name in ('receipt', 'signature', 'public-key', 'manifest',
                             'archive', 'source-root', 'oci-manifest', 'attestation', 'oci-config'):
                    argv.extend(['--' + name, '/fixture'])
                stack.enter_context(patch('sys.argv', argv))
                stack.enter_context(patch.object(Path, 'exists', return_value=True))
                stack.enter_context(patch.object(Path, 'read_bytes',
                    side_effect=[mb, ar, b'oci', b'attestation', raw]))
                for name in ('source_check', 'validate', 'local_inputs', 'validate_oci'):
                    stack.enter_context(patch.object(g, name))
                stack.enter_context(patch.object(g, 'authenticate', return_value=r))
                # The Docker transport is fake; parsing, new comparison, runtime
                # reconciliation and CLI error handling are real.
                stack.enter_context(patch.object(g, 'run', side_effect=[
                    json.dumps(v).encode() for v in (c, image, rollback, observed, c)]))
                out = stack.enter_context(patch('sys.stdout', new_callable=io.StringIO))
                self.assertEqual(g.main(), 2)
                report = json.loads(out.getvalue())
                self.assertFalse(report['release_allowed'])
                self.assertEqual(report['gate1'], 'UNVERIFIED')
                self.assertEqual(report['blockers'], ['LOCAL_IMAGE_CONTENT_MISMATCH']
                                 if mismatch else ['FULL_RELEASE_EVIDENCE_REQUIRED'])
                self.assertEqual(report['receipt_and_runtime_subset'],
                                 'BLOCKED' if mismatch else 'SUBSET_VERIFIED')

    def test_projection_contains_no_image_environment(self):
        self.assertNotIn('Config', g.IMAGE_CONTENT_FORMAT)
        self.assertNotIn('Env', g.IMAGE_CONTENT_FORMAT)


if __name__ == '__main__':
    unittest.main()
