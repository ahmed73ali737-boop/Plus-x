import subprocess
from pathlib import Path


def test_access_choices_signup_and_download_contract():
    root=Path(__file__).resolve().parents[1]
    result=subprocess.run(['node','--experimental-vm-modules','--test','tests/access_ui_contract.mjs'],cwd=root,text=True,capture_output=True,timeout=30)
    assert result.returncode==0,result.stdout+result.stderr
