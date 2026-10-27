"""Portable synthetic certificate QA artifacts; never selects a live database."""
import os
from pathlib import Path
import pytest
from app.application.self_certificate_sandbox import availability


def require_isolated_runtime():
    if not availability():
        pytest.skip('Certificate processing requires Linux Landlock ABI3+ and libseccomp; covered by dedicated Linux CI')


def evidence_root(tmp_path):
    root=Path(os.environ.get('PX_CERTIFICATE_TEST_EVIDENCE_DIR') or tmp_path)
    root.mkdir(parents=True,exist_ok=True)
    return root
