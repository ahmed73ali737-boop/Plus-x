#!/usr/bin/env python3
"""Offline first-party source boundary audit. No build, network, or business acceptance."""
import argparse
import hashlib
import json
from pathlib import Path, PurePosixPath
import posixpath
import re
import subprocess
import xml.etree.ElementTree as ET

SKIP = {'archive', 'archives', 'imports', 'asset-vault', 'candidate-kits', 'snapshots',
        'node_modules', 'bin', 'obj', '.git', '.agents', '.specify', 'repairs'}
NAMES = {'package.json', 'pubspec.yaml', 'pyproject.toml', '.gitmodules'}
SUFFIXES = {'.csproj', '.props', '.targets'}


def canonical(path):
    return (isinstance(path, str) and bool(path) and '\\' not in path and ':' not in path
            and '\0' not in path and all(x not in ('', '.', '..') for x in path.split('/')))


def metadata_path(path):
    p = PurePosixPath(path)
    return not bool(set(p.parts) & SKIP) and (p.name in NAMES or p.suffix in SUFFIXES)


def git_blob(body):
    raw = body.encode('utf-8')
    return hashlib.sha1(b'blob ' + str(len(raw)).encode() + b'\0' + raw).hexdigest()


def audit(snapshot):
    if (not isinstance(snapshot, dict) or snapshot.get('schema') != 'system.dependencies/1' or
            snapshot.get('coverage') not in ('full-tree', 'selected-subtrees') or
            not re.fullmatch('[a-f0-9]{40}', snapshot.get('revision', ''))):
        raise ValueError('Explicit coverage and immutable source revision required')
    nodes = snapshot.get('nodes')
    contents = snapshot.get('metadata')
    if not isinstance(nodes, dict) or len(nodes) > 200000 or not isinstance(contents, dict):
        raise ValueError('Bounded source inventory required')
    if any(not canonical(p) for p in nodes) or any(p not in nodes for p in contents):
        raise ValueError('Metadata must belong to canonical inventoried paths')
    findings, edges = [], []
    def add(code, path, severity='review', target=None):
        item = {'code': code, 'path': path, 'severity': severity}
        if target is not None:
            item['target'] = target
        if item not in findings:
            findings.append(item)
    def reference(path, value, kind, conditional=False):
        if not isinstance(value, str) or not value.strip():
            add('EMPTY_REFERENCE', path, 'error'); return
        value = value.strip().replace('\\', '/')
        if '$(' in value or '*' in value or '${' in value:
            add('DYNAMIC_REFERENCE_REQUIRES_BUILD', path); return
        if value.startswith('/') or re.match(r'^[A-Za-z]:', value):
            add('ABSOLUTE_SOURCE_REFERENCE', path, 'error'); return
        target = posixpath.normpath(posixpath.join(posixpath.dirname(path), value))
        if target == '..' or target.startswith('../'):
            add('CROSS_REPOSITORY_SOURCE_REFERENCE', path, 'error'); return
        edges.append({'from': path, 'to': target, 'kind': kind, 'conditional': conditional})
        if target == '.' or target in nodes or any(p.startswith(target.rstrip('/') + '/') for p in nodes):
            return
        # A partial tree cannot prove the absence of a target outside its scanned roots.
        roots = snapshot.get('scannedRoots', [])
        known = snapshot['coverage'] == 'full-tree' or any(target == r or target.startswith(r + '/') for r in roots)
        if not known:
            add('TARGET_OUTSIDE_OBSERVED_SCOPE', path, target=target)
        elif '_shared-source' in PurePosixPath(target).parts:
            add('PREPARED_SOURCE_NOT_PRESENT', path, target=target)
        else:
            reference_copy = bool({'reconciliation', 'our-copy', 'reference', 'fixtures'} & set(PurePosixPath(path).parts))
            add('SOURCE_TARGET_MISSING', path, 'review' if conditional or reference_copy else 'error', target)
    for path, node in sorted(nodes.items()):
        if not isinstance(node, dict) or node.get('mode') not in ('040000', '100644', '100755', '120000', '160000'):
            raise ValueError('Invalid source node')
        if node['mode'] == '160000' and not set(PurePosixPath(path).parts) & SKIP:
            add('EXTERNAL_GITLINK', path, 'error')
        if not metadata_path(path) or node['mode'] == '040000':
            continue
        if node['mode'] == '120000':
            add('SYMLINK_METADATA', path, 'error'); continue
        body = contents.get(path)
        if not isinstance(body, str):
            add('METADATA_NOT_READ', path); continue
        if len(body.encode()) > 1024 * 1024:
            raise ValueError('Metadata exceeds 1 MiB')
        if node.get('sha') and git_blob(body) != node['sha']:
            add('METADATA_DIGEST_MISMATCH', path, 'error'); continue
        p = PurePosixPath(path)
        try:
            if p.suffix in SUFFIXES:
                root = ET.fromstring(body.lstrip('\ufeff'))
                def walk(element, inherited=False):
                    conditional = inherited or bool(element.get('Condition'))
                    if element.tag.split('}')[-1] == 'ProjectReference':
                        reference(path, element.get('Include'), 'dotnet', conditional)
                    for child in element:
                        walk(child, conditional)
                walk(root)
            elif p.name == 'package.json':
                data = json.loads(body)
                for section in ('dependencies', 'devDependencies', 'optionalDependencies', 'peerDependencies'):
                    for name, version in data.get(section, {}).items():
                        if not isinstance(version, str):
                            add('PACKAGE_REFERENCE_INVALID', path, 'error'); continue
                        if version.startswith(('file:', 'link:')):
                            reference(path, version.split(':', 1)[1], 'node')
                        elif version.startswith(('git+', 'github:', 'git://', 'https://github.com/')):
                            owner = snapshot.get('repository', '').split('/')[0]
                            if owner and re.search(r'(?:[/:])' + re.escape(owner) + r'/', version):
                                add('FIRST_PARTY_GIT_PACKAGE_REQUIRES_LOCAL_COPY', path, 'error', name)
                            elif not re.search(r'#[a-f0-9]{40}$', version):
                                add('UNPINNED_GIT_PACKAGE', path, target=name)
            elif p.name == 'pubspec.yaml':
                # Bounded syntax recognition; anchors/templates still require native pub resolution.
                section, dependency_indent, dependency_block = None, None, False
                for line in body.splitlines():
                    top = re.match(r'^([A-Za-z_][A-Za-z0-9_]*):', line)
                    if top:
                        section = top[1]
                        dependency_indent, dependency_block = None, False
                    if section not in {'dependencies', 'dev_dependencies', 'dependency_overrides'}:
                        continue
                    entry = re.match(r'^( +)([A-Za-z_][A-Za-z0-9_]*):\s*(.*)$', line)
                    if not entry:
                        continue
                    indent = len(entry[1])
                    if dependency_indent is None or indent <= dependency_indent:
                        dependency_indent, dependency_block = indent, not entry[3].strip()
                        continue
                    match = re.match(r'^ +path:\s*[\x22\x27]?([^#\x22\x27]+)', line)
                    if match and dependency_block and indent == dependency_indent + 2:
                        reference(path, match[1].strip(), 'flutter')
                if re.search(r'^\s+git:', body, re.M):
                    add('PUB_GIT_DEPENDENCY_REQUIRES_REVIEW', path)
                if re.search(r'[{,]\s*path\s*:', body) or ('path:' in body and re.search(r'<<:|\$\{|&[A-Za-z]', body)):
                    add('PUB_NONLITERAL_SOURCE_REQUIRES_REVIEW', path)
            elif p.name == 'pyproject.toml':
                import tomllib
                data = tomllib.loads(body)
                poetry = data.get('tool', {}).get('poetry', {})
                groups = [poetry.get('dependencies', {}), poetry.get('dev-dependencies', {})]
                groups += [v.get('dependencies', {}) for v in poetry.get('group', {}).values()]
                for group in groups:
                    for spec in group.values():
                        if isinstance(spec, dict) and 'path' in spec:
                            reference(path, spec['path'], 'python')
                for entry in data.get('project', {}).get('dependencies', []):
                    match = re.search(r'@\s*file:([^;]+)', entry)
                    if match:
                        reference(path, match[1].strip(), 'python')
            elif p.name == '.gitmodules' and body.strip():
                add('SUBMODULE_CONFIGURATION_REQUIRES_REVIEW', path)
        except (ValueError, TypeError, AttributeError, ET.ParseError) as error:
            add('METADATA_PARSE_FAILED', path, 'error')
    if not contents:
        add('NO_SUPPORTED_METADATA', '<repository>')
    findings.sort(key=lambda x: (x['severity'], x['code'], x['path'], x.get('target', '')))
    complete = snapshot['coverage'] == 'full-tree' and not any(f['code'] == 'METADATA_NOT_READ' for f in findings)
    return {'schema': 'system.dependencies-result/1', 'repository': snapshot.get('repository'),
            'revision': snapshot['revision'], 'scope': 'source-metadata-only', 'coverage': snapshot['coverage'],
            'metadataCompleteWithinTree': complete, 'inspectedMetadata': len(contents),
            'workspaceDirty': snapshot.get('workspaceDirty'),
            'referenceCount': len(edges), 'references': edges, 'findings': findings,
            'status': 'failed' if any(x['severity'] == 'error' for x in findings) else
                      'review-required' if findings or not complete else 'source-boundaries-checked',
            'inputSha256': hashlib.sha256(json.dumps(snapshot, sort_keys=True, separators=(',', ':')).encode()).hexdigest(),
            'runtimeVerified': False, 'productionReady': False}


def checkout(root):
    root = root.resolve(strict=True)
    def git(*args):
        return subprocess.run(['git', '-C', str(root), *args], check=True, capture_output=True).stdout
    nodes, metadata = {}, {}
    for entry in git('ls-files', '--stage', '-z').split(b'\0'):
        if not entry:
            continue
        info, path = entry.split(b'\t', 1)
        mode, sha, stage = info.decode().split()
        path = path.decode()
        if stage != '0':
            raise ValueError('Unmerged index requires reconciliation first')
        if not canonical(path):
            raise ValueError('Noncanonical tracked path')
        nodes[path] = {'mode': mode, 'sha': sha}
        if metadata_path(path) and mode != '120000':
            local = root / path
            if not local.resolve().is_relative_to(root) or local.is_symlink():
                raise ValueError('Metadata leaves checkout')
            if local.is_file():
                if local.stat().st_size > 1024 * 1024:
                    raise ValueError('Metadata exceeds 1 MiB')
                metadata[path] = local.read_bytes().decode('utf-8')
    repository = root.name
    lock_path = root / 'tools/asset-control/assets.lock.json'
    if lock_path.is_file():
        repository = json.loads(lock_path.read_text()).get('repository', repository)
    return {'schema': 'system.dependencies/1', 'repository': repository,
            'revision': git('rev-parse', 'HEAD').decode().strip(), 'coverage': 'full-tree',
            'workspaceDirty': bool(git('status', '--porcelain', '--untracked-files=no').strip()),
            'nodes': nodes, 'metadata': metadata}


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--root', type=Path, default=Path(__file__).resolve().parents[2])
    p.add_argument('--snapshot', type=Path)
    p.add_argument('--output', type=Path)
    args = p.parse_args()
    try:
        if args.snapshot and args.snapshot.stat().st_size > 32 * 1024 * 1024:
            raise ValueError('Snapshot exceeds 32 MiB')
        result = audit(json.loads(args.snapshot.read_text()) if args.snapshot else checkout(args.root))
        body = json.dumps(result, ensure_ascii=False, indent=2) + '\n'
        if args.output:
            args.output.parent.mkdir(parents=True, exist_ok=True)
            args.output.write_text(body, encoding='utf-8')
        print(body)
        return 1 if result['status'] == 'failed' else 2 if result['status'] == 'review-required' else 0
    except (ValueError, OSError, subprocess.CalledProcessError) as error:
        print(json.dumps({'status': 'invalid', 'error': str(error), 'runtimeVerified': False}))
        return 2


if __name__ == '__main__':
    raise SystemExit(main())
