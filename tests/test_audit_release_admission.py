"""Exercise the actual workflow Python gate; no GitHub publication is performed."""
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import tempfile
import textwrap
import unittest

ROOT = Path(__file__).resolve().parents[1]
SHA = '1' * 40


class ReleaseAdmissionTests(unittest.TestCase):
    def gate(self, data, notes=None):
        workflow = (ROOT / '.github/workflows/release.yml').read_text()
        script = textwrap.dedent(re.search(r"python - <<'PY'\n(.*?)\n          PY", workflow, re.S).group(1))
        with tempfile.TemporaryDirectory() as folder:
            target = Path(folder)
            for name in ('VERSION', 'FINAL_RELEASE_AR.md', 'EXHIBITION_CI_EVIDENCE_20261006.md'):
                (target / name).write_text((ROOT / name).read_text())
            if notes is not None:
                (target / 'FINAL_RELEASE_AR.md').write_text(notes)
            (target / 'FINAL_RELEASE.json').write_text(json.dumps(data))
            return subprocess.run([sys.executable, '-c', script], cwd=target,
                env={**os.environ, 'GITHUB_SHA': SHA}, capture_output=True, text=True)

    def admitted_fixture(self):
        data = json.loads((ROOT / 'FINAL_RELEASE.json').read_text())
        data['audit_admission'] = {'status': 'verified', 'commit': SHA,
            'evidence': ['fixture://test-only-not-production-evidence'], 'open_defects': []}
        return data

    def test_current_unverified_manifest_blocks_publication(self):
        result = self.gate(json.loads((ROOT / 'FINAL_RELEASE.json').read_text()))
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('Audit defects remain open', result.stderr)

    def test_matching_contract_fixture_is_accepted(self):
        self.assertEqual(self.gate(self.admitted_fixture()).returncode, 0)

    def test_wrong_release_type_is_rejected(self):
        data = self.admitted_fixture(); data['release_type'] = 'invalid'
        self.assertNotEqual(self.gate(data).returncode, 0)

    def test_wrong_version_is_rejected(self):
        data = self.admitted_fixture(); data['release'] = 'v9.9.9'
        self.assertNotEqual(self.gate(data).returncode, 0)

    def test_previous_commit_evidence_is_rejected(self):
        data = self.admitted_fixture(); data['audit_admission']['commit'] = '2' * 40
        self.assertNotEqual(self.gate(data).returncode, 0)

    def test_missing_evidence_is_rejected(self):
        data = self.admitted_fixture(); data['audit_admission']['evidence'] = []
        self.assertNotEqual(self.gate(data).returncode, 0)

    def test_old_archive_names_are_rejected(self):
        notes = (ROOT / 'FINAL_RELEASE_AR.md').read_text().replace('v1.0.1', 'v1.1.0')
        self.assertNotEqual(self.gate(self.admitted_fixture(), notes).returncode, 0)


if __name__ == '__main__':
    unittest.main()
