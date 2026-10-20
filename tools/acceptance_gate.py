"""Fail-closed acceptance evidence validation, independent of configuration flags.

Hashes bind artifacts to a declared source and environment; authenticity of human
field signoff remains an operator responsibility. Never treats fixtures as proof.
"""
from __future__ import annotations
import argparse
from datetime import datetime
import hashlib
import json
from pathlib import Path
import re

REQUIRED=('runtime_recovery','native_postgres','upgrade_restore','performance','security','field_offline')


def validate_manifest(path,source_sha,root):
    root=Path(root).resolve()
    path=Path(path)
    if path.is_absolute():raise ValueError('ACCEPTANCE_PATH_MUST_BE_RELATIVE')
    target=(root/path).resolve()
    if not target.is_relative_to(root):raise ValueError('ACCEPTANCE_PATH_OUTSIDE_ROOT')
    report=json.loads(target.read_text(encoding='utf-8'))
    if not re.fullmatch('[0-9a-f]{40}',source_sha):raise ValueError('SOURCE_SHA_INVALID')
    if report.get('source_sha')!=source_sha:raise ValueError('ACCEPTANCE_SOURCE_MISMATCH')
    if report.get('purpose')!='production_acceptance':raise ValueError('FIXTURE_OR_NONPRODUCTION_EVIDENCE')
    if report.get('status')!='accepted':raise ValueError('ACCEPTANCE_NOT_ACCEPTED')
    gates=report.get('gates',{})
    for name in REQUIRED:
        gate=gates.get(name,{})
        if gate.get('status')!='accepted':raise ValueError('GATE_NOT_ACCEPTED:'+name)
        if gate.get('source_sha')!=source_sha:raise ValueError('GATE_SOURCE_MISMATCH:'+name)
        environment=gate.get('environment',{})
        if any(not environment.get(k) for k in ('os','architecture','database','test_layer')):raise ValueError('ENVIRONMENT_MISSING:'+name)
        signed=gate.get('reviewed_by')
        if not isinstance(signed,str) or not signed.strip():raise ValueError('REVIEWER_MISSING:'+name)
        try:
            when=datetime.fromisoformat(gate['reviewed_at'].replace('Z','+00:00'))
            if when.tzinfo is None:raise ValueError()
        except (KeyError,TypeError,ValueError):raise ValueError('REVIEW_TIME_INVALID:'+name)
        artifacts=gate.get('artifacts',[])
        if not artifacts:raise ValueError('ARTIFACTS_MISSING:'+name)
        has_result=False
        for artifact in artifacts:
            value=artifact.get('path','')
            if not value or '://' in value:raise ValueError('ARTIFACT_FILE_REQUIRED:'+name)
            relative=Path(value)
            file=(root/relative).resolve()
            if relative.is_absolute() or not file.is_relative_to(root):raise ValueError('ARTIFACT_PATH_UNSAFE:'+name)
            if not file.is_file():raise ValueError('ARTIFACT_NOT_FOUND:'+name)
            if hashlib.sha256(file.read_bytes()).hexdigest()!=artifact.get('sha256'):raise ValueError('ARTIFACT_HASH_MISMATCH:'+name)
            if artifact.get('source_sha')!=source_sha:raise ValueError('ARTIFACT_SOURCE_MISMATCH:'+name)
            if artifact.get('kind')=='result_json':
                result=json.loads(file.read_text(encoding='utf-8'))
                if result.get('fixture') is True or result.get('purpose')=='test_fixture':raise ValueError('FIXTURE_RESULT_NOT_ACCEPTED:'+name)
                if result.get('status')!='passed' or result.get('source_sha')!=source_sha:raise ValueError('RESULT_NOT_PASSED_OR_STALE:'+name)
                has_result=True
        if not has_result:raise ValueError('BOUND_RESULT_REQUIRED:'+name)
        if name=='performance' and not gate.get('slo_definition'):raise ValueError('SLO_NOT_DEFINED')
        if name=='field_offline' and not gate.get('devices'):raise ValueError('FIELD_DEVICES_NOT_IDENTIFIED')
    return {'status':'accepted','source_sha':source_sha,'verified_gates':list(REQUIRED)}


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--manifest',required=True);parser.add_argument('--source-sha',required=True);parser.add_argument('--root',default='.')
    args=parser.parse_args()
    try:result=validate_manifest(args.manifest,args.source_sha,args.root)
    except (OSError,ValueError,TypeError,AttributeError) as error:
        # Error type or bounded validation label only, never read or print secrets.
        print(json.dumps({'status':'blocked','reason':str(error) if isinstance(error,ValueError) else type(error).__name__}));return 2
    print(json.dumps(result));return 0


if __name__=='__main__':raise SystemExit(main())
