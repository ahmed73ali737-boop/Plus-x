"""Source-bound acceptance gates, including real failure-path execution.

Step fields are read from the workflow's indentation-delimited blocks; commands
are parsed by the production provenance CLI. No optional YAML dependency or
network service is needed to exercise the coordinator and report verdicts.
"""
from __future__ import annotations

import ast
from copy import deepcopy
import json
from pathlib import Path
import re
import shlex
import subprocess
import textwrap

import pytest

from tools import build_provenance as provenance

ROOT = Path(__file__).resolve().parents[1]
HEAD = '${{ github.event.pull_request.head.sha || github.sha }}'
CASES = {
    'harness-reliability.yml': ('focused', 'qa', [
        'qa/reliability/run-1.xml', 'qa/reliability/run-2.xml',
        'qa/reliability/guest-1.json', 'qa/reliability/guest-2.json']),
    'runtime-recovery.yml': ('recovery', 'qa', ['qa/runtime-recovery/results.json']),
    'upgrade-rehearsal.yml': ('rehearsal', 'qa-postgres', [
        'qa/upgrade-rehearsal.json', 'qa/postgres-invitations-acceptance.json']),
}


def workflow(name):
    return (ROOT / '.github/workflows' / name).read_text(encoding='utf-8')


def steps(source):
    return [textwrap.dedent('        ' + block) for block in
            re.split(r'(?m)^      - ', source)[1:]]


def field(step, key):
    match = re.search(r'(?m)^' + re.escape(key) + r':\s*([^\n]*)$', step)
    if not match:
        return None
    value = match.group(1)
    if value in ('|', '|-', '>', '>-'):
        following = step[match.end():].splitlines()[1:]
        lines = []
        for line in following:
            if line and not line.startswith(' '):
                break
            lines.append(line)
        return textwrap.dedent('\n'.join(lines)).rstrip()
    if value.startswith(("'", '"')):
        return ast.literal_eval(value)
    return value


def nested(step, key):
    match = re.search(r'(?m)^  ' + re.escape(key) + r':\s*([^\n]+)$', step)
    if not match:
        return None
    value = match.group(1)
    return ast.literal_eval(value) if value.startswith(("'", '"')) else value


def cli_args(command, monkeypatch):
    argv = shlex.split(command)
    assert argv[:3] == ['python', 'tools/build_provenance.py', 'snapshot']
    # Actions expands expressions before invoking the CLI; retain the binding
    # assertion while supplying a real supported status to its argument parser.
    if '--job-status' in argv:
        index = argv.index('--job-status') + 1
        assert argv[index] == '${{ job.status }}'
        argv[index] = 'success'
    with monkeypatch.context() as patch:
        patch.setattr(provenance, 'snapshot', lambda args: args)
        return provenance.main(argv[2:])


def inspect_contract(name, source, monkeypatch):
    job, profile, reports = CASES[name]
    assert re.search(r'(?m)^  SOURCE_HEAD: (.+)$', source).group(1) == HEAD
    assert re.search(r'(?m)^  push:\n    branches: \[main\]$', source)
    assert not re.search(r'(?m)^\s*continue-on-error:', source)
    records = steps(source)
    assert len(re.findall(r'(?m)^  [\w-]+:\n    (?:strategy|runs-on):', source)) == 1
    checkout = [step for step in records if field(step, 'uses') == 'actions/checkout@v4']
    assert len(checkout) == 1 and nested(checkout[0], 'ref') == HEAD
    assert nested(checkout[0], 'fetch-depth') == '1'
    python = [step for step in records if field(step, 'uses') == 'actions/setup-python@v5']
    assert len(python) == 1
    toolchain = json.loads((ROOT / 'ops/build-toolchain.json').read_text())
    if job == 'focused':
        assert nested(python[0], 'python-version') == '${{ matrix.python }}'
        matrix = re.findall(r'(?m)^          - os: ([^\n]+)\n            python: \'([^\']+)\'', source)
        assert dict(matrix) == {'ubuntu-latest': toolchain['python_linux'],
                                'windows-latest': toolchain['python_windows']}
        assert '    runs-on: ${{ matrix.os }}' in source
        node = [step for step in records if field(step, 'uses') == 'actions/setup-node@v4']
        assert len(node) == 1 and nested(node[0], 'node-version') == toolchain['node']
    else:
        assert nested(python[0], 'python-version') == toolchain['python_linux']
    commands = [(index, field(step, 'run')) for index, step in enumerate(records) if field(step, 'run')]
    snapshots = [(index, cli_args(command, monkeypatch)) for index, command in commands
                 if command.startswith('python tools/build_provenance.py snapshot ')]
    assert len(snapshots) == 2
    (first_index, initial), (last_index, final) = snapshots
    assert initial.baseline is None and initial.output == f'qa/ci/{job}/baseline.json'
    assert final.baseline == initial.output and final.output == f'qa/ci/{job}/bundle/provenance.json'
    for args in (initial, final):
        assert args.verify_ci and args.job_id == job and args.profile == profile
    assert final.job_status == 'success'
    assert field(records[last_index], 'if') == 'always()'
    required = {f'qa/ci/{job}/source-locks.json', *reports}
    assert set(final.require_pass) == required
    assert required <= set(final.evidence)
    assert final.probe_postgres == (job == 'rehearsal')
    installs = [(index, shlex.split(command)) for index, command in commands
                if shlex.split(command)[:4] == ['python', '-m', 'pip', 'install']]
    assert len(installs) == 2
    for (_, argv), lock in zip(installs, ['bootstrap', profile]):
        assert '--require-hashes' in argv and '--only-binary=:all:' in argv
        assert argv[argv.index('-r') + 1] == f'requirements/locks/{lock}.txt'
    guards = ['python tools/verify_shared_observability.py',
              'python tools/verify_consolidation_assets.py']
    guard_indices = [next(index for index, command in commands if command == guard) for guard in guards]
    assert len(set(guard_indices)) == 2
    diagnostics = [(index, shlex.split(command)) for index, command in commands
                   if command.startswith('python tools/source_lock_diagnostics.py ')]
    assert len(diagnostics) == 1
    diag_index, diag = diagnostics[0]
    assert {'--controls', '--checkouts'} <= set(diag)
    assert diag[diag.index('--output') + 1] == f'qa/ci/{job}/source-locks.json'
    assert first_index < min(guard_indices) <= max(guard_indices) < diag_index < installs[0][0]
    assert installs[0][0] < installs[1][0] < last_index
    cleanup = [(index, shlex.split(command)) for index, command in commands
               if command.startswith('python -c ') and 'targets=' in command]
    assert len(cleanup) == 1 and first_index < cleanup[0][0] < min(guard_indices)
    assignments = ast.parse(cleanup[0][1][2]).body
    targets = ast.literal_eval(next(node.value for node in assignments
                                   if isinstance(node, ast.Assign) and node.targets[0].id == 'targets'))
    assert all(path.startswith('qa/') and '..' not in Path(path).parts for path in targets)
    assert 'qa' not in targets and 'qa/' not in targets and initial.output not in targets
    for report in required:
        assert any(Path(report) == Path(target) or Path(target) in Path(report).parents for target in targets)
    uploads = [step for step in records if field(step, 'uses') == 'actions/upload-artifact@v4']
    assert len(uploads) >= 2
    assert any(nested(step, 'path') == f'qa/ci/{job}/bundle/' for step in uploads)
    for step in uploads:
        assert field(step, 'if') == 'always()' and nested(step, 'if-no-files-found') == 'error'
        artifact_name = nested(step, 'name')
        assert all(part in artifact_name for part in ('${{ env.SOURCE_HEAD }}', '${{ github.run_id }}', '${{ github.run_attempt }}'))
        if job == 'focused':
            assert '${{ matrix.os }}' in artifact_name
    return initial, final


@pytest.mark.parametrize('name', CASES)
def test_acceptance_workflow_binds_checkout_environment_and_required_reports(name, monkeypatch):
    inspect_contract(name, workflow(name), monkeypatch)


@pytest.mark.parametrize('defect', ['merge-checkout', 'floating-python', 'missing-source-guard',
                                  'missing-negative-control', 'unlocked-bootstrap', 'failure-seal-skipped',
                                  'missing-required-report', 'shared-matrix-artifact', 'wrong-job-id'])
def test_contract_detects_workflow_regressions(defect, monkeypatch):
    source = workflow('harness-reliability.yml')
    changes = {
        'merge-checkout': ('ref: ' + HEAD, 'ref: ${{ github.sha }}'),
        'floating-python': ("python: '3.13.16'", "python: '3.13'"),
        'missing-source-guard': ('python tools/verify_consolidation_assets.py', 'python -V'),
        'missing-negative-control': ('--controls --checkouts', '--checkouts'),
        'unlocked-bootstrap': ('--require-hashes --only-binary=:all: -r requirements/locks/bootstrap.txt', '-r requirements/locks/bootstrap.txt'),
        'failure-seal-skipped': ('if: always()', 'if: success()'),
        'missing-required-report': (" --require-pass 'qa/reliability/guest-2.json'", ''),
        'shared-matrix-artifact': ('harness-reliability-${{ matrix.os }}-', 'harness-reliability-'),
        'wrong-job-id': ('--job-id focused', '--job-id focused-linux'),
    }
    before, after = changes[defect]
    assert before in source
    with pytest.raises((AssertionError, StopIteration)):
        inspect_contract('harness-reliability.yml', source.replace(before, after), monkeypatch)


def coordinator():
    matches = [field(step, 'run') for step in steps(workflow('harness-reliability.yml'))
               if field(step, 'name') == 'Run ownership and fault contracts twice in fresh directories']
    assert len(matches) == 1
    command = matches[0]
    assert command.startswith("python - <<'PY'\n") and command.endswith('\nPY')
    return compile(command.split('\n', 1)[1].rsplit('\nPY', 1)[0], '<workflow-coordinator>', 'exec')


@pytest.mark.parametrize('failure', ['none', 'pytest-first', 'guest-first', 'missing-second-json', 'spawn-first'])
def test_both_attempts_preserve_actual_reports_and_nonzero_exit(tmp_path, monkeypatch, failure):
    monkeypatch.chdir(tmp_path)
    calls = []
    def run(command, *, stdout, stderr):
        calls.append(command)
        stdout.write('synthetic subprocess diagnostic\n')
        attempt = (len(calls) + 1) // 2
        is_pytest = command[1:3] == ['-m', 'pytest']
        if is_pytest:
            if failure == 'spawn-first' and attempt == 1:
                raise OSError('synthetic process spawn failure')
            report = next(arg.split('=', 1)[1] for arg in command if arg.startswith('--junitxml='))
            Path(report).write_text('<testsuite><testcase name="fixture"/></testsuite>')
            return subprocess.CompletedProcess(command, 17 if failure == 'pytest-first' and attempt == 1 else 0)
        target = Path('qa/guest-capacity-smoke.json')
        assert not target.exists(), 'previous attempt JSON was reused'
        failed = failure == 'guest-first' and attempt == 1
        if not (failure == 'missing-second-json' and attempt == 2):
            target.write_text(json.dumps({'status': 'failed' if failed else 'passed', 'attempt': attempt}))
        return subprocess.CompletedProcess(command, 19 if failed else 0)
    monkeypatch.setattr(subprocess, 'run', run)
    with pytest.raises(SystemExit) as exited:
        exec(coordinator(), {'__name__': '__main__'})
    assert exited.value.code == (0 if failure == 'none' else 1)
    assert len(calls) == 4
    first = json.loads(Path('qa/reliability/guest-1.json').read_text())
    assert first == {'status': 'failed' if failure == 'guest-first' else 'passed', 'attempt': 1}
    if failure == 'missing-second-json':
        assert not Path('qa/reliability/guest-2.json').exists()
    else:
        assert json.loads(Path('qa/reliability/guest-2.json').read_text()) == {'status': 'passed', 'attempt': 2}
    assert len(list(Path('qa/reliability').glob('*.log'))) == 4


@pytest.mark.parametrize('name', CASES)
@pytest.mark.parametrize('bad_result', ['blocked', 'failed', 'missing'])
def test_actual_workflow_seal_rejects_bad_or_missing_primary_report(name, bad_result, tmp_path, monkeypatch):
    initial, final = inspect_contract(name, workflow(name), monkeypatch)
    monkeypatch.chdir(tmp_path)
    (tmp_path / 'VERSION').write_text('test\n')
    source = {'sha': '1' * 40, 'tree': '2' * 40, 'files': {'VERSION': 'fixed'},
              'git_status': [], 'untracked_source_files': {}}
    context = {'expected_sha': source['sha'], 'job': final.job_id, 'run_id': '1', 'run_attempt': '1',
               'workflow': name, 'repository': 'fixture/repo'}
    monkeypatch.setattr(provenance, 'source_inventory', lambda root: deepcopy(source))
    monkeypatch.setattr(provenance, 'ci_context', lambda: context.copy())
    monkeypatch.setattr(provenance, 'installed_packages', lambda: [])
    monkeypatch.setattr(provenance, 'versions', lambda *_: {'system': 'Linux'})
    assert provenance.snapshot(initial, tmp_path) == 0
    for report in final.require_pass:
        path = tmp_path / report
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text('<testsuite><testcase name="fixture"/></testsuite>' if path.suffix == '.xml' else '{"status":"passed"}')
    # Logs are attachments, not independently asserted acceptance reports.
    for pattern in final.evidence:
        path = tmp_path / pattern
        if path.suffix == '.log':
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text('synthetic diagnostic\n')
        elif pattern == 'qa/upgrade-logs':
            path.mkdir(parents=True, exist_ok=True)
            (path / 'runner.log').write_text('synthetic diagnostic\n')
    final.job_status = 'success'
    assert provenance.snapshot(final, tmp_path) == 0
    target = tmp_path / CASES[name][2][-1]
    if bad_result == 'missing':
        target.unlink()
    else:
        target.write_text(json.dumps({'status': bad_result}))
    assert provenance.snapshot(final, tmp_path) == 1
    result = json.loads((tmp_path / final.output).read_text())
    assert not result['verified']
    assert any(CASES[name][2][-1] in error for error in result['failures'])
