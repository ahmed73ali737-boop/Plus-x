"""Contract tests use fixtures; these files are NEVER production acceptance evidence."""
import hashlib,json
from pathlib import Path
import pytest
from tools.acceptance_gate import REQUIRED,validate_manifest
SHA='1'*40


def make_manifest(tmp_path):
    artifact=tmp_path/'run.json';artifact.write_text(json.dumps({'status':'passed','source_sha':SHA,'fixture':False}))
    gates={name:{'status':'accepted','source_sha':SHA,'environment':{'os':'fixture','architecture':'fixture','database':'fixture','test_layer':'fixture'},'reviewed_by':'unit-test-only','reviewed_at':'2026-10-20T00:00:00Z','slo_definition':'contract fixture','devices':['fixture'],
      'artifacts':[{'path':'run.json','kind':'result_json','sha256':hashlib.sha256(artifact.read_bytes()).hexdigest(),'source_sha':SHA}]} for name in REQUIRED}
    # Tests below deliberately vary this schema fixture. It must not be shipped as signoff.
    return {'status':'accepted','purpose':'production_acceptance','source_sha':SHA,'gates':gates}


def check(tmp_path,data):
    (tmp_path/'manifest.json').write_text(json.dumps(data))
    return validate_manifest('manifest.json',SHA,tmp_path)


def test_matching_artifact_binding_contract(tmp_path):
    assert check(tmp_path,make_manifest(tmp_path))['verified_gates']==list(REQUIRED)


@pytest.mark.parametrize('defect',['old-source','missing-file','wrong-hash','fixture','blocked','missing-environment','old-artifact','no-slo','no-hardware','unsafe-path','fixture-result'])
def test_release_rejects_invalid_or_incomplete_evidence(tmp_path,defect):
    data=make_manifest(tmp_path)
    gate=data['gates']['performance']
    if defect=='old-source':data['source_sha']='2'*40
    if defect=='missing-file':(tmp_path/'run.json').unlink()
    if defect=='wrong-hash':(tmp_path/'run.json').write_text('changed')
    if defect=='fixture':data['purpose']='test_fixture'
    if defect=='blocked':gate['status']='blocked'
    if defect=='missing-environment':gate['environment']={}
    if defect=='old-artifact':gate['artifacts'][0]['source_sha']='2'*40
    if defect=='no-slo':gate.pop('slo_definition')
    if defect=='no-hardware':data['gates']['field_offline']['devices']=[]
    if defect=='unsafe-path':gate['artifacts'][0]['path']='../outside.json'
    if defect=='fixture-result':
        (tmp_path/'run.json').write_text(json.dumps({'status':'passed','source_sha':SHA,'fixture':True}))
        digest=hashlib.sha256((tmp_path/'run.json').read_bytes()).hexdigest()
        for item in data['gates'].values():item['artifacts'][0]['sha256']=digest
    with pytest.raises((ValueError,OSError)):check(tmp_path,data)


def test_acceptance_manifest_cannot_escape_bundle(tmp_path):
    with pytest.raises(ValueError,match='OUTSIDE_ROOT'):validate_manifest('../manifest.json',SHA,tmp_path)
