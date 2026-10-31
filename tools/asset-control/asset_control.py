#!/usr/bin/env python3
"""Offline, system-owned source snapshots. Standard library only; never fetches code."""
import argparse
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import re
import shutil
import subprocess
import tempfile

SCHEMA = 'system.assets/1'
EXCLUDED = {'.git', 'node_modules', '.venv', '__pycache__', 'bin', 'obj', '.env'}


def relative(value):
    if (not isinstance(value, str) or not value or '\\' in value or ':' in value
            or '\0' in value or any(p in ('', '.', '..') for p in value.split('/'))):
        raise ValueError('Canonical relative path required')
    return PurePosixPath(value)


def within(root, value):
    relative(value)
    path = root / value
    if not path.resolve().is_relative_to(root.resolve()):
        raise ValueError('Path leaves repository: ' + value)
    for part in [path, *path.parents]:
        if part == root:
            break
        if part.is_symlink():
            raise ValueError('Symlink source is not supported: ' + value)
    return path


def inventory(root):
    result = {}
    for directory, folders, files in os.walk(root, followlinks=False):
        for name in folders + files:
            path = Path(directory) / name
            if path.is_symlink():
                raise ValueError('Symlink in source: ' + str(path.relative_to(root)))
        folders[:] = sorted(x for x in folders if x not in EXCLUDED)
        for name in sorted(files):
            if name in EXCLUDED or name.startswith('.env.') and not name.endswith('.example'):
                raise ValueError('Private configuration in source export')
            path = Path(directory) / name
            if path.stat().st_size > 20 * 1024 * 1024:
                raise ValueError('Source file exceeds 20 MiB')
            result[path.relative_to(root).as_posix()] = {
                'sha256': hashlib.sha256(path.read_bytes()).hexdigest(),
                'gitBlob': hashlib.sha1(b'blob ' + str(path.stat().st_size).encode() + b'\0' + path.read_bytes()).hexdigest(),
                'executable': bool(path.stat().st_mode & 0o111)}
            if len(result) > 20000:
                raise ValueError('Source file count exceeds limit')
    return result


def read_lock(path):
    lock = json.loads(path.read_text(encoding='utf-8'))
    if lock.get('schema') != SCHEMA or not isinstance(lock.get('assets'), list):
        raise ValueError('Invalid asset lock')
    seen, destinations = set(), []
    for asset in lock['assets']:
        if (not isinstance(asset, dict) or not re.fullmatch(r'[a-z][a-z0-9.-]{0,99}', asset.get('id', ''))
                or asset['id'] in seen or not re.fullmatch(r'[0-9a-f]{40}', asset.get('upstreamRevision', ''))
                or not isinstance(asset.get('files'), dict) or not asset['files']
                or not re.fullmatch(r'\d+\.\d+\.\d+(?:[-+][A-Za-z0-9.-]+)?', asset.get('localVersion', ''))):
            raise ValueError('Invalid or duplicate asset')
        seen.add(asset['id'])
        destination = relative(asset['path'])
        if any(destination == d or destination in d.parents or d in destination.parents for d in destinations):
            raise ValueError('Overlapping asset destinations')
        destinations.append(destination)
        for name, meta in asset['files'].items():
            relative(name)
            if (not isinstance(meta, dict) or not (re.fullmatch(r'[0-9a-f]{64}', meta.get('sha256', ''))
                    or re.fullmatch(r'[0-9a-f]{40}', meta.get('gitBlob', '')))
                    or type(meta.get('executable')) is not bool):
                raise ValueError('Invalid file digest')
    return lock


def verify(root, lock_path):
    lock = read_lock(lock_path)
    findings = []
    for asset in lock['assets']:
        try:
            path = within(root, asset['path'])
            if not path.is_dir():
                raise ValueError('Missing asset directory')
            actual = inventory(path)
            expected = asset['files']
            for name in sorted(set(actual) | set(expected)):
                recorded, observed = expected.get(name), actual.get(name)
                if (recorded is None or observed is None or any(observed.get(k) != v for k, v in recorded.items())):
                    findings.append({'code': 'LOCAL_ASSET_DRIFT', 'asset': asset['id'], 'path': name})
        except (ValueError, OSError) as error:
            findings.append({'code': 'ASSET_UNREADABLE', 'asset': asset['id'], 'detail': str(error)})
    git = subprocess.run(['git', '-C', str(root), 'ls-files', '--stage', '-z'], capture_output=True)
    if git.returncode:
        findings.append({'code': 'GIT_INVENTORY_UNAVAILABLE'})
    else:
        for item in git.stdout.split(b'\0'):
            if item.startswith(b'160000 '):
                findings.append({'code': 'EXTERNAL_GITLINK', 'path': item.split(b'\t', 1)[1].decode('utf-8')})
    # File-level validation is intentionally separate from build/runtime acceptance.
    return {'schema': 'system.assets-result/1', 'status': 'failed' if findings else 'source-verified' if lock['assets'] else 'registration-required',
            'assets': len(lock['assets']), 'findings': findings,
            'dependencyCoverage': 'registered-assets-and-gitlinks-only',
            'runtimeVerified': False, 'productionReady': False}


def adopt(root, lock_path, source, destination, asset_id, origin, revision, version):
    lock = read_lock(lock_path)
    if not re.fullmatch(r'[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+', origin):
        raise ValueError('Origin must be owner/repository')
    target = within(root, destination)
    if target.exists():
        raise ValueError('Destination exists; preserve and review local changes before upgrading')
    source = Path(source).resolve(strict=True)
    if not source.is_dir() or source == root or source in root.parents or root in source.parents:
        raise ValueError('Use a separate reviewed source export')
    files = inventory(source)
    record = {'id': asset_id, 'path': destination, 'upstreamRepository': origin,
              'upstreamRevision': revision, 'localVersion': version,
              'ownership': 'system-local', 'updatePolicy': 'explicit-reviewed-upgrade', 'files': files}
    candidate = {**lock, 'assets': [*lock['assets'], record]}
    # Validate complete candidate before changing the destination.
    with tempfile.TemporaryDirectory() as temporary:
        validation = Path(temporary) / 'lock.json'
        validation.write_text(json.dumps(candidate), encoding='utf-8')
        read_lock(validation)
        staged = Path(temporary) / 'source'
        staged.mkdir()
        for name, meta in files.items():
            dest = staged / name
            dest.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(source / name, dest)
            dest.chmod(0o755 if meta['executable'] else 0o644)
        if inventory(staged) != files:
            raise ValueError('Source changed during snapshot')
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copytree(staged, target)
        try:
            temporary_lock = lock_path.with_name(lock_path.name + '.pending')
            with temporary_lock.open('x', encoding='utf-8') as stream:
                stream.write(json.dumps(candidate, ensure_ascii=False, indent=2) + '\n')
            temporary_lock.replace(lock_path)
        except Exception:
            shutil.rmtree(target)
            raise
    return record


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action', choices=['verify', 'adopt'])
    parser.add_argument('--root', type=Path, default=Path(__file__).resolve().parents[2])
    parser.add_argument('--lock', default='tools/asset-control/assets.lock.json')
    parser.add_argument('--source', type=Path)
    parser.add_argument('--destination')
    parser.add_argument('--id')
    parser.add_argument('--origin')
    parser.add_argument('--revision')
    parser.add_argument('--version')
    args = parser.parse_args()
    try:
        root = args.root.resolve(strict=True)
        lock = within(root, args.lock)
        if args.action == 'verify':
            result = verify(root, lock)
            print(json.dumps(result, ensure_ascii=False, indent=2))
            return 1 if result['findings'] else 0 if result['assets'] else 2
        if any(getattr(args, k) is None for k in ('source', 'destination', 'id', 'origin', 'revision', 'version')):
            raise ValueError('adopt requires source, destination, id, origin, revision and version')
        result = adopt(root, lock, args.source, args.destination, args.id, args.origin, args.revision, args.version)
        print(json.dumps({'status': 'adopted', 'asset': result['id'], 'runtimeVerified': False}))
        return 0
    except (ValueError, OSError, KeyError, TypeError) as error:
        print(json.dumps({'status': 'invalid', 'error': str(error)}))
        return 2


if __name__ == '__main__':
    raise SystemExit(main())
