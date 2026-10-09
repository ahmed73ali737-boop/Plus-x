"""Create/check a project-local virtual environment separately from application startup."""
from __future__ import annotations
import argparse
import json
import os
import platform
import subprocess
import sys
import venv
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
VENV = ROOT / ".venv"

def executable() -> Path:
    return VENV / ("Scripts/python.exe" if os.name == "nt" else "bin/python")

def _run(args: list[str]) -> subprocess.CompletedProcess:
    return subprocess.run(args, cwd=ROOT, capture_output=True, text=True)

def check(profile: str) -> dict:
    exe = executable()
    result = {"profile":profile,"system":platform.system(),"architecture":platform.machine(),
              "host_python":platform.python_version(),"venv_python":str(exe),
              "exists":exe.is_file(),"platform_compatible":False,"dependencies_ok":False}
    if not exe.is_file():
        result["reason"]="VENV_NOT_PREPARED"
        return result
    script = ("import json,sys,platform;print(json.dumps(dict(prefix=sys.prefix,"
              "version=list(sys.version_info[:2]),system=platform.system(),exe=sys.executable)))")
    try:
        probe = _run([str(exe),"-c",script])
        if probe.returncode != 0:
            raise RuntimeError("VENV_INTERPRETER_FAILED")
        actual = json.loads(probe.stdout)
        compatible = (actual["system"] == platform.system() and
                      tuple(actual["version"]) == sys.version_info[:2] and
                      Path(actual["prefix"]).resolve() == VENV.resolve() and
                      Path(actual["exe"]).resolve() == exe.resolve())
        result["platform_compatible"]=compatible
        if not compatible:
            result["reason"]="FOREIGN_OR_MISMATCHED_VENV"
            return result
        if _run([str(exe),"-m","pip","check"]).returncode != 0:
            result["reason"]="PIP_DEPENDENCIES_BROKEN"
            return result
        modules=["fastapi","sqlalchemy","uvicorn","qrcode","PIL"]
        if profile in ("postgres","qa-postgres"):
            modules.append("psycopg")
        if profile in ("qa","qa-postgres"):
            modules.extend(["pytest","httpx","playwright","psutil","coverage"])
        ok=_run([str(exe),"-c","import "+",".join(modules)]).returncode == 0
        result["dependencies_ok"]=ok
        if not ok:
            result["reason"]="REQUIRED_MODULE_MISSING"
    except (OSError,ValueError,RuntimeError) as exc:
        result["reason"]=type(exc).__name__
    return result

def main(argv: list[str] | None = None) -> int:
    parser=argparse.ArgumentParser(description="PulseX isolated environment setup")
    parser.add_argument("--profile",choices=["local","postgres","qa","qa-postgres"],default="local")
    parser.add_argument("--check",action="store_true",help="Read-only validation; no install")
    args=parser.parse_args(argv)
    if not (3,11) <= sys.version_info[:2] < (3,14):
        raise RuntimeError("PYTHON_3_11_TO_3_13_REQUIRED")
    if not args.check:
        if not executable().is_file():
            if VENV.exists():
                raise RuntimeError("INCOMPATIBLE_VENV_DO_NOT_OVERWRITE")
            venv.EnvBuilder(with_pip=True).create(VENV)
        if not check("local")["platform_compatible"]:
            raise RuntimeError("FOREIGN_OR_MISMATCHED_VENV_DO_NOT_OVERWRITE")
        required=["requirements.txt"]
        if args.profile in ("postgres","qa-postgres"):
            required.append("requirements-postgres.txt")
        if args.profile in ("qa","qa-postgres"):
            required.append("requirements-qa.txt")
        cmd=[str(executable()),"-m","pip","install","--disable-pip-version-check"]
        for name in required:
            cmd.extend(["-r",str(ROOT/name)])
        subprocess.run(cmd,cwd=ROOT,check=True)
    result=check(args.profile)
    print(json.dumps(result,ensure_ascii=False,indent=2))
    return 0 if result["platform_compatible"] and result["dependencies_ok"] else 2

if __name__ == "__main__":
    raise SystemExit(main())
