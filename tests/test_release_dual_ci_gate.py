"""Static release workflow checks: published release must wait on all three exact-source push CI workflows."""
from pathlib import Path
import re

ROOT=Path(__file__).resolve().parents[1]


def test_guest_qr_runs_on_same_main_push_as_release():
    source=(ROOT/'.github/workflows/guest-qr-ci.yml').read_text()
    assert re.search(r'(?m)^  pull_request:\n    branches: \[ main \]', source)
    assert re.search(r'(?m)^  push:\n    branches: \[ main \]', source)
    assert 'name: guest-qr-ci' in source


def test_release_blocks_without_three_exact_sha_push_run_ids():
    source=(ROOT/'.github/workflows/release.yml').read_text()
    ci=(ROOT/'.github/workflows/pulsex-ci.yml').read_text()
    assert 'name: PulseX CI' in ci
    assert re.search(r'(?m)^  push:\n    branches: \[ main \]', ci)
    blocks=re.findall(r'      - name: Require .+?\n.*?(?=      - name: |\Z)',source,re.S)
    assert len(blocks)==3
    for name in ('pulsex-ci.yml','guest-qr-ci','linux-standalone.yml'):
        matched=[block for block in blocks if f'--workflow "{name}"' in block]
        assert len(matched)==1
        block=matched[0]
        assert '--commit "$GITHUB_SHA"' in block
        assert 'select(.event=="push")' in block
        assert 'test -n "$RUN_ID"' in block
        assert 'gh run watch "$RUN_ID" --exit-status' in block
        assert 'gh run view "$RUN_ID" --json headSha -q .headSha' in block
        assert '= "$GITHUB_SHA"' in block
    assert source.index('Require guest QR CI success') < source.index('Publish or refresh GitHub Release')
    assert "get('audit_admission', {}).get('status') == 'verified'" in source


def test_linux_standalone_runs_on_main_and_release_checkout_is_explicit():
    linux=(ROOT/'.github/workflows/linux-standalone.yml').read_text()
    release=(ROOT/'.github/workflows/release.yml').read_text()
    assert "branches: [main, 'release/linux-*']" in linux
    assert 'ref: ${{ github.sha }}' in release
    assert release.index('Require Linux standalone CI success') < release.index('Publish or refresh GitHub Release')
