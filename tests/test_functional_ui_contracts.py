"""New admission desk lifecycle/fault contracts execute actual JavaScript modules."""
from pathlib import Path
import subprocess


def test_admission_desk_and_live_dashboard_functional_contracts():
    root=Path(__file__).resolve().parents[1]
    result=subprocess.run(['node','--experimental-vm-modules','tests/admission_desk_ui_contract.mjs'],cwd=root,text=True,capture_output=True,timeout=40)
    assert result.returncode==0,result.stdout+result.stderr
