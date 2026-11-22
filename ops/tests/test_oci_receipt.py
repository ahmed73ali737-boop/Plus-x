"""Synthetic OCI bytes only; never real build/attestation or release evidence."""
import copy
import io
import json
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import patch

from test_release_receipt import g, fixture, S, H


def bound_fixture():
    r, mb, ar, c, im, rb = fixture()
    oci = json.dumps({'schemaVersion': 2,
        'mediaType': 'application/vnd.oci.image.manifest.v1+json',
        'config': {'mediaType': 'application/vnd.oci.image.config.v1+json',
                   'digest': r['image']['config_digest'], 'size': 123},
        'layers': [{'mediaType': 'application/vnd.oci.image.layer.v1.tar+gzip',
                    'digest': 'sha256:' + H, 'size': 456}]}).encode()
    r['schema'] = 'plusx-release-receipt/v2'
    r['image']['reference'] = 'example/plusx@sha256:' + g.digest(oci)
    im['digests'] = [r['image']['reference']]
    runtime = {k: v for k, v in c.items() if k not in ('id', 'image', 'running', 'started')}
    canonical = lambda v: json.dumps(v, sort_keys=True, separators=(',', ':')).encode()
    r['runtime_config_sha256'] = g.digest(canonical(runtime))
    statement = {'_type': 'https://in-toto.io/Statement/v1',
        'subject': [{'name': 'plusx', 'digest': {'sha256': g.digest(oci)}}],
        'predicateType': 'https://plusx.invalid/provenance/v2',
        'predicate': {'source_sha': S, 'context_sha256': r['context_sha256'],
            'manifest_sha256': r['manifest_sha256'],
            'dependency_install_receipt_sha256': H,
            'builder_binary_sha256': H, 'runtime_config_sha256': r['runtime_config_sha256'],
            'reproduced_manifest_sha256': g.digest(oci),
            'rollback_receipt_sha256': H}}
    attestation = canonical(statement)
    r['attestation_sha256'] = g.digest(attestation)
    return r, mb, ar, c, im, rb, oci, attestation


class BindingTests(unittest.TestCase):
    def verify(self, f):
        r, mb, ar, c, im, rb, oci, att = f
        g.validate(r, mb, ar, S)
        g.validate_oci(r, oci, att)
        g.reconcile(r, c, im, rb)

    def test_positive_synthetic_binding(self):
        self.verify(bound_fixture())

    def test_missing_attestation(self):
        f = list(bound_fixture()); f[-1] = b''
        with self.assertRaisesRegex(ValueError, 'ATTESTATION_MISMATCH'):
            self.verify(f)

    def test_oci_digest_tamper(self):
        f = list(bound_fixture()); f[-2] += b' '
        with self.assertRaisesRegex(ValueError, 'OCI_MANIFEST_MISMATCH'):
            self.verify(f)

    def test_oci_config_mismatch(self):
        f = list(bound_fixture()); f[0]['image']['config_digest'] = 'sha256:' + '0'*64
        with self.assertRaisesRegex(ValueError, 'OCI_CONFIG_MISMATCH'):
            self.verify(f)

    def test_attested_context_mismatch(self):
        f = list(bound_fixture()); a = json.loads(f[-1]); a['predicate']['context_sha256'] = '0'*64
        f[-1] = json.dumps(a).encode(); f[0]['attestation_sha256'] = g.digest(f[-1])
        with self.assertRaisesRegex(ValueError, 'ATTESTATION_BINDING_MISMATCH'):
            self.verify(f)

    def test_not_reproducible(self):
        f = list(bound_fixture()); a = json.loads(f[-1]); a['predicate']['reproduced_manifest_sha256'] = '0'*64
        f[-1] = json.dumps(a).encode(); f[0]['attestation_sha256'] = g.digest(f[-1])
        with self.assertRaisesRegex(ValueError, 'ATTESTATION_BINDING_MISMATCH'):
            self.verify(f)

    def test_secret_fields_rejected(self):
        for target in ('top', 'image', 'rollback_image', 'base_materials'):
            with self.subTest(target=target):
                f = list(bound_fixture()); r = f[0]
                obj = r if target == 'top' else r[target][0] if target == 'base_materials' else r[target]
                obj['TOKEN'] = 'synthetic-do-not-print'
                with self.assertRaisesRegex(ValueError, 'RECEIPT_FIELDS_NOT_ALLOWED'):
                    self.verify(f)

    def test_runtime_configuration_binding(self):
        f = list(bound_fixture()); f[0]['runtime_config_sha256'] = '0'*64
        # Change signed attestation too: still must compare observed runtime.
        a = json.loads(f[-1]); a['predicate']['runtime_config_sha256'] = '0'*64
        f[-1] = json.dumps(a).encode(); f[0]['attestation_sha256'] = g.digest(f[-1])
        with self.assertRaisesRegex(ValueError, 'RUNTIME_CONFIG_MISMATCH'):
            self.verify(f)

    def test_missing_evidence_cli_no_docker(self):
        with patch('sys.argv', ['guard', '--offline']), patch.object(g, 'inspect') as inspect, patch('sys.stdout', new_callable=io.StringIO) as out:
            self.assertEqual(g.main(), 2)
            report = json.loads(out.getvalue())
            self.assertIn('MISSING_SIGNATURE', report['blockers'])
            self.assertIn('MISSING_ATTESTATION', report['blockers'])
            self.assertFalse(report['release_allowed'])
            inspect.assert_not_called()

    def test_changed_container_id(self):
        self.assertTrue(hasattr(g, 'stable_runtime'), 'explicit runtime identity reconciliation missing')
        _, _, _, c, *_ = bound_fixture()
        with self.assertRaisesRegex(ValueError, 'RUNTIME_ID_MISMATCH'):
            g.stable_runtime(c, c, '0'*64)
        changed = dict(c, id='0'*64)
        with self.assertRaisesRegex(ValueError, 'RUNTIME_CHANGED'):
            g.stable_runtime(c, changed, c['id'])

    def test_end_to_end_offline_never_authorizes_release(self):
        # Real temporary Git, packaging, crypto and CLI. No Docker mocks needed:
        # --offline must succeed through verification without invoking Docker.
        from test_deployment_provenance import ProvenanceTests
        setup = ProvenanceTests()
        setup.setUp()
        self.addCleanup(setup.doCleanups)
        m, ar = setup.snapshot()
        mb = json.dumps(m).encode()
        r, _, _, _, _, _, oci, _ = bound_fixture()
        r.update(source_sha=setup.sha, manifest_sha256=g.digest(mb),
                 context_sha256=g.digest(ar), build_argv=g.recipe(setup.sha),
                 dockerfile_sha256=m['files']['ops/Dockerfile.development']['sha256'])
        r['base_materials'][0]['reference'] = m['base_images'][0]
        att = {'_type': 'https://in-toto.io/Statement/v1',
            'subject': [{'name': 'plusx', 'digest': {'sha256': g.digest(oci)}}],
            'predicateType': 'https://plusx.invalid/provenance/v2',
            'predicate': {k: r[k] for k in ('source_sha', 'context_sha256',
                'manifest_sha256', 'dependency_install_receipt_sha256',
                'builder_binary_sha256', 'runtime_config_sha256', 'rollback_receipt_sha256')}}
        att['predicate']['reproduced_manifest_sha256'] = g.digest(oci)
        ab = g.canonical(att); r['attestation_sha256'] = g.digest(ab)
        p = Path(setup.tmp.name)
        for name, data in [('manifest', mb), ('archive', ar), ('oci-manifest', oci),
                           ('attestation', ab), ('receipt', g.canonical(r))]:
            (p/name).write_bytes(data)
        def openssl(*args):
            subprocess.run(['openssl', *args], check=True, capture_output=True)
        openssl('genpkey', '-algorithm', 'EC', '-pkeyopt', 'ec_paramgen_curve:P-256', '-out', str(p/'test.key'))
        openssl('pkey', '-in', str(p/'test.key'), '-pubout', '-out', str(p/'public-key'))
        openssl('dgst', '-sha256', '-sign', str(p/'test.key'), '-out', str(p/'signature'), str(p/'receipt'))
        command = ['python3', str(Path(g.__file__)), '--offline', '--source-root', str(setup.root),
                   '--source-sha', setup.sha, '--trusted-key-sha256', g.digest((p/'public-key').read_bytes())]
        for name in ('manifest', 'archive', 'oci-manifest', 'attestation', 'receipt', 'signature', 'public-key'):
            command.extend(['--' + name, str(p/name)])
        result = subprocess.run(command, capture_output=True, text=True)
        self.assertEqual(result.returncode, 2, result.stderr)
        report = json.loads(result.stdout)
        self.assertEqual(report['receipt_and_runtime_subset'], 'OFFLINE_BINDINGS_VERIFIED', report)
        self.assertFalse(report['release_allowed'])
        self.assertEqual(report['gate1'], 'UNVERIFIED')
        self.assertIn('LIVE_RUNTIME_AND_ROLLBACK_NOT_OBSERVED', report['blockers'])
        # Even signed metadata cannot replace checkout/context reconciliation.
        setup.put('app/main.py', 'changed')
        result = subprocess.run(command, capture_output=True, text=True)
        self.assertEqual(json.loads(result.stdout)['blockers'], ['DIRTY_SOURCE'])
        (p/'signature').write_bytes(b'synthetic-bad-signature')
        setup.git('checkout', '--', 'app/main.py')
        result = subprocess.run(command, capture_output=True, text=True)
        self.assertEqual(json.loads(result.stdout)['blockers'], ['SIGNATURE_OR_INSPECTION_FAILED'])
        self.assertNotIn('synthetic-bad-signature', result.stdout + result.stderr)

    def test_real_signature_full_fixture_and_missing_signature(self):
        f = bound_fixture()
        with tempfile.TemporaryDirectory() as directory:
            p = Path(directory)
            def openssl(*args):
                subprocess.run(['openssl', *args], check=True, capture_output=True)
            openssl('genpkey', '-algorithm', 'EC', '-pkeyopt', 'ec_paramgen_curve:P-256', '-out', str(p/'key'))
            openssl('pkey', '-in', str(p/'key'), '-pubout', '-out', str(p/'pub'))
            (p/'receipt').write_text(json.dumps(f[0]))
            openssl('dgst', '-sha256', '-sign', str(p/'key'), '-out', str(p/'sig'), str(p/'receipt'))
            r = g.authenticate(p/'receipt', p/'sig', p/'pub', g.digest((p/'pub').read_bytes()))
            self.verify((r, *f[1:]))
            (p/'sig').unlink()
            with self.assertRaises(FileNotFoundError):
                g.authenticate(p/'receipt', p/'sig', p/'pub', g.digest((p/'pub').read_bytes()))


if __name__ == '__main__':
    unittest.main()
