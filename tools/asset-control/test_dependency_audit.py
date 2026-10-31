import importlib.util
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

spec = importlib.util.spec_from_file_location('dependency_audit', Path(__file__).with_name('dependency_audit.py'))
audit = importlib.util.module_from_spec(spec)
spec.loader.exec_module(audit)


class DependencyAuditTests(unittest.TestCase):
    def snapshot(self, files, extra=(), **changes):
        return {'schema': 'system.dependencies/1', 'repository': 'owner/system',
                'revision': 'a' * 40, 'coverage': 'full-tree',
                'nodes': {**{p: {'mode': '100644', 'sha': audit.git_blob(c)} for p, c in files.items()},
                          **{p: {'mode': '100644'} for p in extra}},
                'metadata': files, **changes}

    def codes(self, data):
        return {x['code'] for x in audit.audit(data)['findings']}

    def test_local_project_reference(self):
        data = self.snapshot({'app/App.csproj': '<Project><ItemGroup><ProjectReference Include="../lib/Lib.csproj"/></ItemGroup></Project>',
                              'lib/Lib.csproj': '<Project/>'})
        result = audit.audit(data)
        self.assertEqual(result['status'], 'source-boundaries-checked')
        self.assertEqual(result['referenceCount'], 1)
        self.assertFalse(result['runtimeVerified'])

    def test_outside_project_reference(self):
        data = self.snapshot({'App.csproj': '<Project><ProjectReference Include="../other/Other.csproj"/></Project>'})
        self.assertIn('CROSS_REPOSITORY_SOURCE_REFERENCE', self.codes(data))

    def test_missing_local_project(self):
        data = self.snapshot({'App.csproj': '<Project><ProjectReference Include="missing.csproj"/></Project>'})
        self.assertEqual(audit.audit(data)['status'], 'failed')

    def test_partial_tree_cannot_claim_missing_target(self):
        data = self.snapshot({'src/App.csproj': '<Project><ProjectReference Include="../components/A.csproj"/></Project>'},
                             coverage='selected-subtrees', scannedRoots=['src'])
        self.assertEqual(audit.audit(data)['status'], 'review-required')
        self.assertIn('TARGET_OUTSIDE_OBSERVED_SCOPE', self.codes(data))

    def test_conditional_group_is_not_ignored(self):
        data = self.snapshot({'App.csproj': '<Project><ItemGroup Condition="optional"><ProjectReference Include="missing.csproj"/></ItemGroup></Project>'})
        self.assertEqual(audit.audit(data)['status'], 'review-required')

    def test_msbuild_property_requires_native_resolution(self):
        data = self.snapshot({'App.csproj': '<Project><ProjectReference Include="$(OwnerSource)/A.csproj"/></Project>'})
        self.assertIn('DYNAMIC_REFERENCE_REQUIRES_BUILD', self.codes(data))

    def test_xml_namespace_supported(self):
        data = self.snapshot({'App.csproj': '<Project xmlns="urn:msbuild"><ProjectReference Include="../A.csproj"/></Project>'})
        self.assertIn('CROSS_REPOSITORY_SOURCE_REFERENCE', self.codes(data))

    def test_node_local_file_dependencies_only(self):
        data = self.snapshot({'package.json': json.dumps({'scripts': {'test': 'DATABASE_URL=file:./test.db run'}, 'dependencies': {'local': 'file:lib'}})}, extra=['lib/index.js'])
        self.assertFalse(self.codes(data))

    def test_node_external_file_dependency(self):
        data = self.snapshot({'package.json': json.dumps({'dependencies': {'x': 'file:../x'}})})
        self.assertIn('CROSS_REPOSITORY_SOURCE_REFERENCE', self.codes(data))

    def test_first_party_git_dependency_requires_copy(self):
        data = self.snapshot({'package.json': json.dumps({'dependencies': {'x': 'github:owner/x#' + 'a'*40}})})
        self.assertIn('FIRST_PARTY_GIT_PACKAGE_REQUIRES_LOCAL_COPY', self.codes(data))

    def test_pinned_third_party_git_not_first_party(self):
        data = self.snapshot({'package.json': json.dumps({'dependencies': {'x': 'github:external/x#' + 'a'*40}})})
        self.assertFalse(self.codes(data))

    def test_flutter_sibling_package_is_internal(self):
        data = self.snapshot({'mobile/app/pubspec.yaml': 'dependencies:\n  local:\n    path: ../core\n'}, extra=['mobile/core/lib/main.dart'])
        self.assertFalse(self.codes(data))

    def test_flutter_escape(self):
        data = self.snapshot({'pubspec.yaml': 'dependencies:\n  local:\n    path: ../other\n'})
        self.assertIn('CROSS_REPOSITORY_SOURCE_REFERENCE', self.codes(data))

    def test_flutter_path_package_version_is_not_local_path(self):
        data = self.snapshot({'pubspec.yaml': 'dependencies:\n  path: ^1.9.0\n'})
        self.assertFalse(self.codes(data))

    def test_flutter_git_subdirectory_is_not_local_path(self):
        data = self.snapshot({'pubspec.yaml': 'dependencies:\n  local:\n    git:\n      url: https://example.invalid/repo\n      path: package\n'})
        self.assertEqual(self.codes(data), {'PUB_GIT_DEPENDENCY_REQUIRES_REVIEW'})

    def test_missing_supported_metadata_requires_review(self):
        self.assertIn('NO_SUPPORTED_METADATA', self.codes(self.snapshot({})))

    def test_inline_pub_path_never_silently_passes(self):
        data = self.snapshot({'pubspec.yaml': 'dependencies:\n  local: {path: ../outside}\n'})
        self.assertIn('PUB_NONLITERAL_SOURCE_REQUIRES_REVIEW', self.codes(data))

    def test_python_poetry_local_path(self):
        data = self.snapshot({'pyproject.toml': '[tool.poetry.dependencies]\nx = {path="../other"}\n'})
        self.assertIn('CROSS_REPOSITORY_SOURCE_REFERENCE', self.codes(data))

    def test_digest_mismatch(self):
        data = self.snapshot({'App.csproj': '<Project/>'})
        data['metadata']['App.csproj'] = '<Other/>'
        self.assertIn('METADATA_DIGEST_MISMATCH', self.codes(data))

    def test_unread_metadata_is_not_complete(self):
        data = self.snapshot({}, extra=['App.csproj'])
        result = audit.audit(data)
        self.assertFalse(result['metadataCompleteWithinTree'])
        self.assertEqual(result['status'], 'review-required')

    def test_gitlink_fails(self):
        data = self.snapshot({})
        data['nodes']['external'] = {'mode': '160000', 'sha': 'b' * 40}
        self.assertIn('EXTERNAL_GITLINK', self.codes(data))

    def test_path_traversal_rejected(self):
        with self.assertRaises(ValueError):
            audit.audit(self.snapshot({'../App.csproj': '<Project/>'}))

    def test_dirty_state_is_preserved(self):
        result = audit.audit(self.snapshot({}, workspaceDirty=True))
        self.assertTrue(result['workspaceDirty'])
        self.assertFalse(result['productionReady'])

    def run_checkout(self, content, edit=None):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            (root / 'App.csproj').write_text(content)
            def git(*args):
                subprocess.run(['git', '-C', str(root), '-c', 'user.name=Test', '-c',
                                'user.email=test@local.invalid', *args], check=True, capture_output=True)
            git('init', '-q'); git('add', '.'); git('commit', '-qm', 'fixture')
            if edit is not None:
                (root / 'App.csproj').write_text(edit)
            result = subprocess.run([sys.executable, str(Path(audit.__file__).resolve()), '--root', str(root)],
                                    capture_output=True, text=True, timeout=15)
            return result.returncode, json.loads(result.stdout)

    def test_actual_checkout_cli_pass(self):
        code, result = self.run_checkout('<Project/>')
        self.assertEqual(code, 0)
        self.assertFalse(result['workspaceDirty'])

    def test_actual_checkout_dirty_metadata_is_not_attested(self):
        code, result = self.run_checkout('<Project/>', '<Other/>')
        self.assertEqual(code, 1)
        self.assertTrue(result['workspaceDirty'])
        self.assertIn('METADATA_DIGEST_MISMATCH', {x['code'] for x in result['findings']})

    def test_actual_checkout_cli_review_is_nonzero(self):
        code, result = self.run_checkout('<Project><ProjectReference Include="$(SOURCE)/Other.csproj"/></Project>')
        self.assertEqual(code, 2)
        self.assertFalse(result['runtimeVerified'])


if __name__ == '__main__':
    unittest.main()
