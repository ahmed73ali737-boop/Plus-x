"""Offline, fail-closed deployment context packaging and read-only identity probe.

A context fingerprint is NOT an image attestation. No label, supplied JSON or
historical PASS can make gate1 pass. No Docker build, exec, pull or mutation.
"""
from __future__ import annotations

import argparse
import hashlib
import io
import json
import os
from pathlib import Path, PurePosixPath
import re
import subprocess
import tarfile

SHA = r'[0-9a-f]{40}'
DIGEST = r'sha256:[0-9a-f]{64}'


def run(args, root=None):
    return subprocess.run(args, cwd=root, check=True, stdout=subprocess.PIPE,
                          stderr=subprocess.PIPE, timeout=30,
                          env={**os.environ, 'GIT_OPTIONAL_LOCKS': '0'}).stdout


def fingerprint(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(',', ':')).encode()).hexdigest()


def clean(root, sha):
    if not re.fullmatch(SHA, sha):
        raise ValueError('FULL_SOURCE_SHA_REQUIRED')
    if run(['git', 'rev-parse', 'HEAD'], root).decode().strip() != sha:
        raise ValueError('SOURCE_SHA_MISMATCH')
    if run(['git', 'status', '--porcelain', '--untracked-files=all'], root).strip():
        raise ValueError('SOURCE_NOT_CLEAN')


def tracked_bytes(root, sha):
    """Check bytes too: Git status alone trusts assume-unchanged/stat cache."""
    clean(root, sha)
    result = {}
    for row in run(['git', 'ls-tree', '-rz', sha], root).split(b'\0'):
        if not row:
            continue
        metadata, raw_name = row.split(b'\t', 1)
        mode, kind, oid = metadata.decode().split()
        name = raw_name.decode('utf-8')
        if mode not in ('100644', '100755') or kind != 'blob':
            raise ValueError('NON_REGULAR_SOURCE')
        path = root / name
        if any(p.is_symlink() for p in [path, *path.parents] if p != root.parent):
            raise ValueError('SYMLINK_SOURCE')
        data = path.read_bytes()
        actual = hashlib.sha1(b'blob ' + str(len(data)).encode() + b'\0' + data).hexdigest()
        if actual != oid and b'\r\n' in data:
            # Permit only Git's declared CRLF checkout conversion, and still
            # require the resulting bytes to equal the committed blob exactly.
            attribute = run(['git', 'check-attr', '-z', 'eol', '--', name], root).split(b'\0')
            if attribute[2] == b'crlf':
                canonical = data.replace(b'\r\n', b'\n')
                normalized = hashlib.sha1(b'blob ' + str(len(canonical)).encode() + b'\0' + canonical).hexdigest()
                if normalized == oid:
                    data, actual = canonical, normalized
        if actual != oid or bool(path.stat().st_mode & 0o111) != (mode == '100755'):
            raise ValueError('SOURCE_BYTES_OR_MODE_CHANGED')
        result[name] = (mode, data)
    clean(root, sha)
    return result


def package(root, sha, profile):
    root = Path(root).resolve()
    files = tracked_bytes(root, sha)
    if profile not in ('development', 'production'):
        raise ValueError('UNKNOWN_PROFILE')
    dockerfile = 'ops/Dockerfile' + ('.development' if profile == 'development' else '')
    required = [dockerfile, '.dockerignore', 'ops/container-image-lock.json',
                'ops/build-toolchain.json', 'ops/consolidated-source-lock.json']
    if any(name not in files for name in required):
        raise ValueError('BUILD_CONFIGURATION_MISSING')
    text = files[dockerfile][1].decode().replace('\\\n', ' ')
    locked_images = {item['digest'] for item in json.loads(files['ops/container-image-lock.json'][1])['images']}
    selected = set(required)
    bases, locks = [], set()
    for line in text.splitlines():
        words = line.strip().split()
        if not words or words[0].startswith('#'):
            continue
        instruction = words[0].upper()
        if instruction == 'FROM':
            if len(words) != 2 or not re.fullmatch(r'[^\s@]+@' + DIGEST, words[1]):
                raise ValueError('IMMUTABLE_BASE_REQUIRED')
            if words[1].split('@')[1] not in locked_images:
                raise ValueError('BASE_NOT_IN_IMAGE_LOCK')
            bases.append(words[1])
        if instruction == 'ADD':
            raise ValueError('ADD_NOT_SUPPORTED')
        if instruction == 'COPY':
            if len(words) < 3:
                raise ValueError('UNSUPPORTED_COPY')
            for source in words[1:-1]:
                p = PurePosixPath(source)
                if (source.startswith(('/', '-', '.')) or '..' in p.parts
                        or any(c in source for c in '*?[$\\')):
                    raise ValueError('UNSUPPORTED_COPY')
                matches = {n for n in files if n == source or n.startswith(source.rstrip('/') + '/')}
                if not matches:
                    raise ValueError('COPY_INPUT_MISSING')
                selected.update(matches)
        if instruction == 'RUN':
            # Supported deployment recipes use hash-locked pip only; changes to
            # installer syntax require review instead of silently losing closure.
            for part in re.split(r'&&|;', line):
                if re.search(r'\bpip\s+install\b', part):
                    match = re.fullmatch(r'\s*(?:RUN\s+)?python -m pip install (?:--no-cache-dir )?--require-hashes --only-binary=:all: -r (requirements/locks/[\w-]+\.txt)\s*', part)
                    if not match:
                        raise ValueError('UNSUPPORTED_DEPENDENCY_INSTALL')
                    locks.add(match[1])
                elif re.search(r'\b(pip3?|uv|npm|yarn|pnpm|apt-get|apt|curl|wget)\b', part) and 'python -m pip check' not in part:
                    raise ValueError('UNLOCKED_BUILD_INPUT')
    if not bases or not locks:
        raise ValueError('BASE_OR_DEPENDENCY_COVERAGE_MISSING')
    marker_atom = r"(?:sys_platform|platform_machine|implementation_name)\s*(?:==|!=)\s*'[A-Za-z0-9_.-]+'"
    marker = r'(?:\s*;\s*' + marker_atom + r'(?:\s+(?:or|and)\s+' + marker_atom + r')*)?'
    for name in locks:
        if name not in selected:
            raise ValueError('DEPENDENCY_LOCK_NOT_COPIED')
        entries = files[name][1].decode().replace('\\\n', ' ').splitlines()
        count = 0
        for entry in entries:
            entry = entry.strip()
            if not entry or entry.startswith('#'):
                continue
            if not re.fullmatch(r'[A-Za-z0-9_.-]+==[A-Za-z0-9_.+!-]+' + marker + r'(?:\s+--hash=sha256:[0-9a-f]{64})+\s*', entry):
                raise ValueError('DEPENDENCY_LOCK_NOT_HASH_PINNED')
            count += 1
        if not count:
            raise ValueError('EMPTY_DEPENDENCY_LOCK')
    # Cover existing dependency declarations/locks, toolchain, adapter and all
    # committed compose configuration without reading resolved secret values.
    config = {n for n in files if n.startswith(('ops/', 'requirements/'))
              or n.startswith('requirements') or n in ('.dockerignore', 'pyproject.toml')
              or (n.startswith('compose') and n.endswith(('.yaml', '.yml')))}
    selected.update(config)
    inventory = {n: {'mode': files[n][0], 'sha256': hashlib.sha256(files[n][1]).hexdigest()}
                 for n in sorted(selected)}
    buffer = io.BytesIO()
    with tarfile.open(fileobj=buffer, mode='w', format=tarfile.USTAR_FORMAT) as archive:
        for name in sorted(selected):
            mode, data = files[name]
            info = tarfile.TarInfo(name)
            info.size, info.mode, info.mtime = len(data), int(mode, 8) & 0o777, 0
            info.uid = info.gid = 0
            archive.addfile(info, io.BytesIO(data))
    archive = buffer.getvalue()
    clean(root, sha)
    return {'schema': 1, 'source_sha': sha, 'profile': profile, 'dockerfile': dockerfile,
            'build_args': {'PULSEX_SOURCE_SHA': sha}, 'base_images': bases,
            'dependency_locks': {n: inventory[n]['sha256'] for n in sorted(locks)},
            'config_sha256': fingerprint({n: inventory[n] for n in sorted(config)}),
            'inputs_sha256': fingerprint(inventory), 'files': inventory,
            'context_tar_sha256': hashlib.sha256(archive).hexdigest(),
            'scope': 'INPUTS_ONLY_NOT_BUILD_OR_RUNTIME_ACCEPTANCE'}, archive


def runtime_summary(container, image, sha):
    cid, image_id = container.get('Id', ''), container.get('Image', '')
    if not re.fullmatch(r'[0-9a-f]{64}', cid) or not re.fullmatch(DIGEST, image_id):
        raise ValueError('IMMUTABLE_RUNTIME_ID_REQUIRED')
    if image.get('Id') != image_id:
        raise ValueError('IMAGE_ID_MISMATCH')
    revision = (image.get('Config', {}).get('Labels') or {}).get('org.opencontainers.image.revision', '')
    revision = revision if re.fullmatch(SHA, revision) else None
    # Ignore free-form labels, environment, commands, mount paths and health logs.
    return {'container_id': cid, 'image_id': image_id,
            'repo_digests': [x for x in image.get('RepoDigests', []) if re.fullmatch(r'[\w./:-]+@' + DIGEST, x)],
            'running': container.get('State', {}).get('Running') is True,
            'revision_label': revision, 'source_mismatch': revision != sha,
            'mount_count': len(container.get('Mounts', [])),
            'gate1': 'UNVERIFIED', 'artifact_reconciled': False,
            'blockers': ['NO_TRUSTED_CONTEXT_TO_IMAGE_ATTESTATION',
                         'RUNTIME_FILES_AND_EFFECTIVE_CONFIGURATION_NOT_RECONCILED']}


def inspect_runtime(container_id, sha):
    if not re.fullmatch(r'[0-9a-f]{64}', container_id):
        raise ValueError('FULL_CONTAINER_ID_REQUIRED')
    container = json.loads(run(['docker', 'container', 'inspect', container_id]))[0]
    image = json.loads(run(['docker', 'image', 'inspect', container['Image']]))[0]
    result = runtime_summary(container, image, sha)
    again = json.loads(run(['docker', 'container', 'inspect', container_id]))[0]
    if again['Image'] != container['Image'] or again['State']['Running'] != container['State']['Running']:
        raise ValueError('RUNTIME_CHANGED_DURING_INSPECTION')
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--root', type=Path, required=True)
    parser.add_argument('--source-sha', required=True)
    parser.add_argument('--profile', choices=['development', 'production'], default='development')
    parser.add_argument('--context-tar', type=Path, help='Create new archive; never overwrite')
    parser.add_argument('--container-id', help='Read-only Docker identity probe; exits 2 for unverified gate1')
    args = parser.parse_args()
    try:
        report, archive = package(args.root, args.source_sha, args.profile)
        if args.container_id:
            report['runtime'] = inspect_runtime(args.container_id, args.source_sha)
        if args.context_tar:
            fd = os.open(args.context_tar, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
            with os.fdopen(fd, 'wb') as output:
                output.write(archive)
        print(json.dumps(report, sort_keys=True, indent=2))
        return 2 if args.container_id else 0
    except Exception as exc:
        # Git/Docker/file errors can contain secrets. Never echo exception text.
        print(json.dumps({'gate1': 'UNVERIFIED', 'error_type': type(exc).__name__}))
        return 2


if __name__ == '__main__':
    raise SystemExit(main())
