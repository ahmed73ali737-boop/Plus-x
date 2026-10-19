"""Exercise packaged IANA data without relying on the host OS (Windows parity)."""
import os
import subprocess
import sys


def test_event_timezone_available_without_system_zoneinfo():
    result=subprocess.run([sys.executable,'-c',"from datetime import datetime; from zoneinfo import ZoneInfo; assert datetime(2026,10,19,tzinfo=ZoneInfo('Asia/Aden')).utcoffset().total_seconds()==10800"],env={**os.environ,'PYTHONTZPATH':''},capture_output=True,text=True)
    assert result.returncode==0,result.stderr
