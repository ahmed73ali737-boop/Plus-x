"""Opt-in offline receipt validation and read-only runtime comparison; never deploys."""
import argparse
import hashlib
import io
import json
from pathlib import Path
import re
import subprocess
import tarfile
import tempfile

HEX = r'[0-9a-f]{64}'
SHA = r'[0-9a-f]{40}'
REF = r'[a-z0-9][a-z0-9./_-]*@sha256:' + HEX
REV = 'org.opencontainers.image.revision'


def require(ok, code):
    if not ok:
        raise ValueError(code)


def digest(data):
    return hashlib.sha256(data).hexdigest()


def run(argv):
    return subprocess.run(argv, check=True, capture_output=True, timeout=30).stdout


def strict_json(data):
    def pairs(items):
        result = {}
        for k, v in items:
            require(k not in result, 'DUPLICATE_JSON_KEY')
            result[k] = v
        return result
    return json.loads(data, object_pairs_hook=pairs)


def authenticate(receipt, signature, public_key, trusted_key_sha256):
    # Fingerprint must come from a separately approved builder trust anchor.
    require(re.fullmatch(HEX, trusted_key_sha256), 'TRUST_ANCHOR_REQUIRED')
    payload, sig, key = receipt.read_bytes(), signature.read_bytes(), public_key.read_bytes()
    require(digest(key) == trusted_key_sha256, 'UNTRUSTED_SIGNER')
    # Verify the exact bytes parsed, avoiding replacement between verify/read.
    with tempfile.TemporaryDirectory(prefix='plusx-receipt-') as directory:
        root = Path(directory)
        for name, data in [('receipt', payload), ('signature', sig), ('key', key)]:
            (root / name).write_bytes(data)
            (root / name).chmod(0o600)
        run(['openssl', 'dgst', '-sha256', '-verify', str(root / 'key'),
             '-signature', str(root / 'signature'), str(root / 'receipt')])
    return strict_json(payload)


def recipe(source):
    require(re.fullmatch(SHA, source), 'FULL_SOURCE_REQUIRED')
    return ['docker', 'build', '--platform=linux/amd64', '--network=none',
            '--pull=false', '--no-cache', '--build-arg', 'PULSEX_SOURCE_SHA=' + source,
            '-f', 'ops/Dockerfile.development', '-']


def validate(r, manifest_bytes, archive_bytes, source):
    require(re.fullmatch(SHA, source), 'FULL_SOURCE_REQUIRED')
    require(r['schema'] == 'plusx-release-receipt/v1', 'SCHEMA')
    m = strict_json(manifest_bytes)
    require(r['source_sha'] == m['source_sha'] == source, 'SOURCE_DRIFT')
    require(r['manifest_sha256'] == digest(manifest_bytes), 'MANIFEST_DRIFT')
    require(r['context_sha256'] == m['context_tar_sha256'] == digest(archive_bytes), 'CONTEXT_DRIFT')
    require(m['profile'] == 'development' and m['dockerfile'] == 'ops/Dockerfile.development', 'PROFILE')
    require(m['build_args'] == {'PULSEX_SOURCE_SHA': source}, 'UNSAFE_BUILD_ARGS')
    require(r['build_argv'] == recipe(source), 'UNSAFE_BUILD_RECIPE')
    require(r['build_environment'] == {} and r['secret_mounts'] == [] and r['ssh_mounts'] == [], 'BUILD_SECRETS')
    require(r['network'] == 'none' and r['dependency_install'] == 'offline-hash-verified', 'DEPENDENCY_PROVENANCE')
    require(re.fullmatch(HEX, r['builder_binary_sha256']), 'BUILDER_REQUIRED')
    require(re.fullmatch(HEX, r['dependency_install_receipt_sha256']), 'INSTALL_RECEIPT_REQUIRED')
    require(re.fullmatch(HEX, r['build_log_sha256']), 'BUILD_LOG_REQUIRED')
    files = {}
    with tarfile.open(fileobj=io.BytesIO(archive_bytes), mode='r:') as tar:
        for member in tar:
            name = member.name
            require(member.isfile() and name not in files and not name.startswith('/')
                    and '..' not in name.split('/'), 'UNSAFE_ARCHIVE')
            files[name] = tar.extractfile(member).read()
            require(name in m['files'], 'UNLISTED_ARCHIVE_MEMBER')
            require(digest(files[name]) == m['files'][name]['sha256'], 'MEMBER_DRIFT')
            require(member.mode == int(m['files'][name]['mode'], 8) & 0o777, 'MEMBER_MODE')
    require(set(files) == set(m['files']), 'ARCHIVE_INCOMPLETE')
    require(m['dependency_locks'] and all(n in files and digest(files[n]) == h
            for n, h in m['dependency_locks'].items()), 'LOCK_DRIFT')
    require(r['dockerfile_sha256'] == digest(files[m['dockerfile']]), 'DOCKERFILE_DRIFT')
    bases = re.findall(r'^FROM (\S+)\s*$', files[m['dockerfile']].decode(), re.M)
    require(bases == m['base_images'] and bases, 'BASE_DRIFT')
    require(len(r['base_materials']) == len(bases), 'BASE_PROVENANCE')
    for base, material in zip(bases, r['base_materials']):
        # A digest pin is allowed with a descriptive tag, but a bare tag is not.
        require(re.fullmatch(r'[\w./:-]+@sha256:' + HEX, base), 'MUTABLE_BASE')
        require(material['reference'] == base and material['platform'] == 'linux/amd64'
                and re.fullmatch(HEX, material['authenticated_origin_receipt_sha256']), 'BASE_PROVENANCE')
    for key in ('image', 'rollback_image'):
        require(re.fullmatch(REF, r[key]['reference']), 'IMMUTABLE_IMAGE_REQUIRED')
        require(re.fullmatch('sha256:' + HEX, r[key]['config_digest']), 'IMAGE_CONFIG_REQUIRED')
    require(r['image']['reference'] != r['rollback_image']['reference'], 'DISTINCT_ROLLBACK_REQUIRED')
    require(re.fullmatch(HEX, r['rollback_receipt_sha256']), 'ROLLBACK_PROVENANCE')
    require(r['path_prefix'] == '/plusx' and r['health_route'] == '/api/health/ready', 'INVALID_ROUTE')
    require(r['mounts'] == [{'Type': 'volume', 'Name': 'plusx-development_plusx_development_data',
                            'Destination': '/app/data', 'RW': True}], 'UNEXPECTED_MOUNTS')
    return r


# Docker formats return only selected non-secret fields. Never fetch Config.Env,
# health logs or complete inspect documents. Equality checks hide command text.
CONTAINER_FORMAT = '''{"id":{{json .Id}},"image":{{json .Image}},"running":{{json .State.Running}},"started":{{json .State.StartedAt}},"readonly":{{json .HostConfig.ReadonlyRootfs}},"privileged":{{json .HostConfig.Privileged}},"network":{{json .HostConfig.NetworkMode}},"cap_add":{{json .HostConfig.CapAdd}},"user":{{json .Config.User}},"mounts":[{{range $i,$m := .Mounts}}{{if $i}},{{end}}{"Type":{{json $m.Type}},"Name":{{json $m.Name}},"Destination":{{json $m.Destination}},"RW":{{json $m.RW}}}{{end}}],"command_ok":{{eq (json .Config.Cmd) "[\\"python\\",\\"run.py\\"]"}},"entrypoint_ok":{{or (eq (json .Config.Entrypoint) "null") (eq (json .Config.Entrypoint) "[]")}},"health_ok":{{eq (json .Config.Healthcheck.Test) "[\\"CMD\\",\\"python\\",\\"-m\\",\\"tools.app_healthcheck\\"]"}},"public_env":[{{range .Config.Env}}{{if or (eq . "PUBLIC_PATH_PREFIX=/plusx") (eq . "PUBLIC_ORIGIN=https://5.189.157.131")}}{{json .}},{{end}}{{end}}null]}'''
IMAGE_FORMAT = '{"id":{{json .Id}},"digests":{{json .RepoDigests}},"revision":{{json (index .Config.Labels "org.opencontainers.image.revision")}}}'


def inspect(kind, identity, template):
    return strict_json(run(['docker', kind, 'inspect', '--format', template, identity]))


def reconcile(r, c, image, rollback):
    require(c['running'] is True, 'NOT_RUNNING')
    require(c['image'] == image['id'] == r['image']['config_digest'], 'RUNNING_IMAGE_DRIFT')
    require(r['image']['reference'] in (image['digests'] or []), 'IMAGE_DIGEST_DRIFT')
    require(image['revision'] == r['source_sha'], 'OCI_REVISION_DRIFT')
    require(rollback['id'] == r['rollback_image']['config_digest'] and
            r['rollback_image']['reference'] in (rollback['digests'] or []), 'ROLLBACK_UNAVAILABLE')
    require(c['mounts'] == r['mounts'], 'RUNTIME_MOUNT_DRIFT')
    require(c['readonly'] is True and c['privileged'] is False and not c['cap_add']
            and c['network'] == 'plusx-development_default' and c['user'] == 'pulsex', 'UNSAFE_RUNTIME')
    require(c['command_ok'] and c['entrypoint_ok'] and c['health_ok'], 'RUNTIME_COMMAND_DRIFT')
    require(sorted(x for x in c['public_env'] if x is not None) ==
            ['PUBLIC_ORIGIN=https://5.189.157.131', 'PUBLIC_PATH_PREFIX=/plusx'], 'RUNTIME_ROUTE_DRIFT')


def source_check(root, source):
    require(re.fullmatch(SHA, source), 'FULL_SOURCE_REQUIRED')
    require(run(['git', '-C', str(root), 'rev-parse', 'HEAD']).decode().strip() == source, 'CHECKOUT_DRIFT')
    require(not run(['git', '-C', str(root), 'status', '--porcelain', '--untracked-files=all']).strip(), 'DIRTY_SOURCE')


def main():
    p = argparse.ArgumentParser(description=__doc__)
    for name in ['receipt', 'signature', 'public-key', 'manifest', 'archive', 'source-root']:
        p.add_argument('--' + name, type=Path, required=True)
    for name in ['trusted-key-sha256', 'source-sha', 'container-id']:
        p.add_argument('--' + name, required=True)
    a = p.parse_args()
    try:
        require(re.fullmatch(HEX, a.container_id), 'FULL_CONTAINER_ID_REQUIRED')
        source_check(a.source_root, a.source_sha)
        r = authenticate(a.receipt, a.signature, a.public_key, a.trusted_key_sha256)
        validate(r, a.manifest.read_bytes(), a.archive.read_bytes(), a.source_sha)
        c = inspect('container', a.container_id, CONTAINER_FORMAT)
        image = inspect('image', r['image']['config_digest'], IMAGE_FORMAT)
        rollback = inspect('image', r['rollback_image']['config_digest'], IMAGE_FORMAT)
        reconcile(r, c, image, rollback)
        require(c == inspect('container', a.container_id, CONTAINER_FORMAT), 'RUNTIME_CHANGED')
        source_check(a.source_root, a.source_sha)
        print(json.dumps({'receipt_and_runtime_subset': 'PASS', 'promotion': 'NOT_AUTHORIZED',
                          'gate1': 'UNVERIFIED', 'scope': 'No full environment, database, writable-volume or application acceptance'}))
        return 0
    except Exception:
        # Never emit values or third-party errors; these may contain credentials.
        print(json.dumps({'receipt_and_runtime_subset': 'BLOCKED', 'promotion': 'NOT_AUTHORIZED', 'gate1': 'UNVERIFIED'}))
        return 2


if __name__ == '__main__':
    raise SystemExit(main())
