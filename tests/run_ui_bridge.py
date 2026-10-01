"""Isolated developer harness. Requires requirements-qa.txt and Chromium.
Does not pretend that the browser native network or offline platform was tested.
"""
from pathlib import Path
import os, socket, subprocess, sys, tempfile, time, urllib.request
ROOT=Path(__file__).resolve().parents[1]
with tempfile.TemporaryDirectory(prefix="px03-ui-qa-") as td:
    tmp=Path(td)
    with socket.socket() as sock:
        sock.bind(("127.0.0.1",0)); port=sock.getsockname()[1]
    url=f"http://127.0.0.1:{port}"
    env={**os.environ,"PYTHONUTF8":"1","HOST":"127.0.0.1","PORT":str(port),"PUBLIC_ORIGIN":url,
         "DATABASE_URL":"sqlite:///"+str(tmp/"db.sqlite"),"CREDENTIALS_PATH":str(tmp/"accounts.json"),
         "MEDIA_DIR":str(tmp/"media"),"REQUIRE_POSTGRES":"false","SEED_DEMO":"true",
         "PX_QA_URL":url,"PX_QA_ACCOUNTS":str(tmp/"accounts.json")}
    log=open(tmp/"server.log","w",encoding="utf-8")
    proc=subprocess.Popen([sys.executable,str(ROOT/"run.py")],cwd=ROOT,env=env,stdout=log,stderr=log)
    code=1
    try:
        opener=urllib.request.build_opener(urllib.request.ProxyHandler({}))
        for _ in range(100):
            try:
                with opener.open(url+"/api/health",timeout=.5):break
            except Exception:
                if proc.poll() is not None:raise RuntimeError((tmp/"server.log").read_text(encoding="utf-8"))
                time.sleep(.1)
        else:raise RuntimeError("QA server startup timeout")
        code=subprocess.call([sys.executable,str(ROOT/"tests/browser_windows03.py")],cwd=ROOT,env=env)
    finally:
        if proc.poll() is None:proc.terminate();proc.wait(timeout=10)
        log.close()
    raise SystemExit(code)
