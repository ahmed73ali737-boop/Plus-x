import subprocess
from pathlib import Path


def test_phone_signup_and_account_page_dom_contracts():
    root = Path(__file__).resolve().parents[1]
    result = subprocess.run(['node', '--experimental-vm-modules', '--test', 'tests/phone_account_ui_contract.mjs'],
                            cwd=root, capture_output=True, text=True, timeout=30)
    assert result.returncode == 0, result.stdout + result.stderr
