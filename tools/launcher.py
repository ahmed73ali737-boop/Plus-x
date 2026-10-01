"""Windows-friendly, loopback-only launcher. No admin rights or execution-policy changes.
The application stays a Python web application, not a fabricated native .exe.
"""
from __future__ import annotations
import argparse
import hashlib
import importlib.metadata
import json
import os
from pathlib import Path
import socket
import subprocess
import sys
import threading
import time
import urllib.request
import venv
import webbrowser

ROOT = Path(__file__).resolve().parents[1]
ENV = ROOT / '.venv'
PYTHON = ENV / ('Scripts/python.exe' if os.name == 'nt' else 'bin/python')
REQUIREMENTS = ROOT / 'requirements.txt'

def available_port(port: int) -> bool:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        try:
            sock.bind(('127.0.0.1', port))
            return True
        except OSError:
            return False

def env_check() -> bool:
    if not PYTHON.is_file():
        return False
    code = "import importlib.metadata as m,json; pairs=json.loads(__import__('sys').argv[1]); assert all(m.version(k)==v for k,v in pairs.items())"
    pairs = {}
    for line in REQUIREMENTS.read_text(encoding='utf-8').splitlines():
        if '==' in line and not line.lstrip().startswith('#'):
            k,v = line.split('==',1)
            pairs[k.strip()] = v.strip()
    try:
        return subprocess.run([str(PYTHON), '-c', code, json.dumps(pairs)], capture_output=True, timeout=30).returncode == 0
    except (OSError, subprocess.SubprocessError):
        return False

def prepare() -> None:
    if not (3,11) <= sys.version_info[:2] < (3,14):
        raise RuntimeError('This package targets Python 3.11-3.13; Python 3.13 is recommended. See START_WINDOWS_AR.html.')
    if not PYTHON.is_file():
        print('Creating a project-only virtual environment...', flush=True)
        venv.EnvBuilder(with_pip=True).create(ENV)
    if not env_check():
        print('Installing pinned application dependencies. First setup needs internet.', flush=True)
        subprocess.run([str(PYTHON), '-m', 'pip', 'install', '--disable-pip-version-check', '-r', str(REQUIREMENTS)], check=True)
        subprocess.run([str(PYTHON), '-m', 'pip', 'check'], check=True)
    if not env_check():
        raise RuntimeError('Dependency check failed. No application was started.')

def open_when_ready(url: str) -> None:
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    for _ in range(120):
        try:
            with opener.open(url + '/api/health', timeout=1) as response:
                data = json.load(response)
            if data.get('build') == 'windows-04':
                webbrowser.open(url)
                return
        except Exception:
            time.sleep(.5)
    print('Automatic opening timed out. Read the server error and open the printed URL manually.', flush=True)

def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument('--check', action='store_true')
    parser.add_argument('--no-browser', action='store_true')
    args = parser.parse_args()
    os.chdir(ROOT)
    if args.check:
        report = {'python': sys.version, 'platform': sys.platform, 'runtime_target_ok': (3,11) <= sys.version_info[:2] < (3,14),
                  'project_directory': str(ROOT), 'venv_dependencies_ok': env_check(), 'port_4310_free': available_port(4310),
                  'source_exists': (ROOT/'app/server.py').is_file(), 'native_windows_acceptance': 'Run Windows UAT locally; Linux checks are not Windows acceptance.'}
        print(json.dumps(report, ensure_ascii=True, indent=2))
        return 0 if report['runtime_target_ok'] and report['venv_dependencies_ok'] and report['source_exists'] else 1
    prepare()
    port = int(os.environ.get('PULSEX_PORT', '4310'))
    if not 1024 <= port <= 65535:
        raise RuntimeError('PULSEX_PORT must be between 1024 and 65535.')
    if not available_port(port):
        raise RuntimeError(f'Port {port} is already in use. Close the existing instance or set PULSEX_PORT to another port. Nothing was killed.')
    url = f'http://127.0.0.1:{port}'
    env = {**os.environ, 'HOST':'127.0.0.1', 'PORT':str(port), 'PUBLIC_ORIGIN':url, 'PYTHONUTF8':'1'}
    print('\nPulseX Windows 04 — supervised local trial\n'+url+'\nAdmin: '+url+'/admin\nAccounts: data/first-run-accounts.json\nKeep this window open. Press Ctrl+C to stop.\n', flush=True)
    if not args.no_browser:
        threading.Thread(target=open_when_ready, args=(url,), daemon=True).start()
    process = subprocess.Popen([str(PYTHON), str(ROOT/'run.py')], cwd=ROOT, env=env)
    try:
        return process.wait()
    except KeyboardInterrupt:
        # Parent and child normally receive the console Ctrl+C; do not kill unrelated processes.
        try:
            return process.wait(timeout=6)
        except subprocess.TimeoutExpired:
            process.terminate()
            return process.wait(timeout=6)

if __name__ == '__main__':
    try:
        raise SystemExit(main())
    except Exception as error:
        print('\nPulseX could not start: '+str(error)+'\nSee START_WINDOWS_AR.html. No existing user data was reset.', file=sys.stderr)
        raise SystemExit(1)
