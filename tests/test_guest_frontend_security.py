"""Run the scanner's actual JavaScript policies, with browser storage/network stubs."""
import subprocess
from pathlib import Path


def test_scanner_javascript_security_contracts():
    root=Path(__file__).resolve().parents[1]
    result=subprocess.run(
        ["node","--experimental-vm-modules","--test","tests/test_guest_frontend_security.mjs"],
        cwd=root,text=True,capture_output=True,timeout=30,
    )
    assert result.returncode==0,result.stdout+result.stderr
