"""Bound local evidence to one immutable code commit; external gates stay blocked."""
from __future__ import annotations
import argparse,hashlib,json,platform,subprocess,sys,time
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
SCOPES=['app','web','tools','tests','ops','requirements','.github']
TESTS=[
 'test_upgrade_safety.py','test_acceptance_evidence.py','test_performance_measurement.py',
 'test_public_bundle_query_budget.py','test_public_quiz_privacy.py','test_pilot.py',
 'test_audit_release_admission.py','test_pwa_install_contract.py','test_guest_frontend_security.py',
 'test_device_admission_scope.py','test_invitations.py','test_invitations_ui_contract.py',
 'test_admission_gate_integration.py','test_admission_permissions.py','test_admission_http_ack.py',
 'test_guest_pass_isolation.py','test_harness_reliability.py','test_runtime_recovery.py',
 'test_linux_standalone_contract.py','test_release_dual_ci_gate.py']


def source_hashes():
    paths=subprocess.check_output(['git','ls-files','--',*SCOPES],cwd=ROOT,text=True).splitlines()
    return {p:hashlib.sha256((ROOT/p).read_bytes()).hexdigest() for p in paths}


def main():
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--output',required=True);args=parser.parse_args()
    out=Path(args.output).resolve();out.mkdir(parents=True,exist_ok=True)
    if subprocess.run(['git','diff','--quiet','HEAD','--',*SCOPES],cwd=ROOT).returncode:
        raise RuntimeError('COMMIT_CODE_CHANGES_BEFORE_CANDIDATE_RUN')
    sha=subprocess.check_output(['git','rev-parse','HEAD'],cwd=ROOT,text=True).strip()
    before=source_hashes()
    report={'status':'in_progress','source_sha':sha,'environment':{'os':platform.platform(),'architecture':platform.machine(),'python':platform.python_version(),'database':'SQLite','test_layer':'local unit/DOM/real HTTP; no native Chromium or PostgreSQL'},'source_hashes':before,'commands':[],'blocked':['Docker app/proxy recovery','native PostgreSQL upgrade/restore/concurrency','Windows and Ubuntu24 target acceptance','Chromium mobile/print journey','physical camera/reader/printer/venue network','production SLO undefined','runtime lock pip-audit network timeout']}
    commands=[
      [sys.executable,'-m','pytest','-q',*[str(Path('tests')/p) for p in TESTS],f'--basetemp={out / "temp"}',f'--junitxml={out / "junit.xml"}'],
      [sys.executable,'tests/security_hardening.py'],
      [sys.executable,'tests/guest_capacity_smoke.py'],
      [sys.executable,'tests/exhibition_scale_smoke.py'],
      [sys.executable,'tests/load_profiles.py','--profile','pilot','--output',str(out/'load-pilot.json')],
    ]
    try:
        for index,command in enumerate(commands,1):
            started=time.monotonic()
            log=out/f'command-{index}.log'
            item={'command':command,'status':'running','log':log.name};report['commands'].append(item)
            try:
                with log.open('w',encoding='utf-8') as handle:
                    run=subprocess.run(command,cwd=ROOT,stdout=handle,stderr=subprocess.STDOUT,timeout=240)
                item.update(status='passed' if run.returncode==0 else 'failed',returncode=run.returncode)
            except subprocess.TimeoutExpired:item.update(status='timeout',returncode=None)
            item['elapsed_seconds']=round(time.monotonic()-started,3)
        local_ok=all(c['status']=='passed' for c in report['commands'])
        stable=source_hashes()==before
        report.update(local_status='passed' if local_ok and stable else 'failed',source_unchanged=stable,status='blocked' if local_ok and stable else 'failed')
    finally:
        report['artifact_hashes']={p.name:hashlib.sha256(p.read_bytes()).hexdigest() for p in out.iterdir() if p.is_file() and p.name!='candidate.json'}
        (out/'candidate.json').write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    return 3 if report['status']=='blocked' else 1


if __name__=='__main__':raise SystemExit(main())
