from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))

from app.server import create_app
DEFAULT=ROOT/"ops/openapi.generated.json"


def generated_text() -> str:
    app=create_app("sqlite:///:memory:",origin="http://testserver",seed_demo=False)
    return json.dumps(app.openapi(),ensure_ascii=False,indent=2,sort_keys=True)+"\n"


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument("--output",default=str(DEFAULT))
    parser.add_argument("--check",action="store_true")
    args=parser.parse_args()
    output=Path(args.output)
    content=generated_text()
    if args.check:
        if not output.is_file() or output.read_text(encoding="utf-8")!=content:
            raise SystemExit("OPENAPI_ARTIFACT_OUT_OF_DATE")
        print("openapi-artifact-current")
        return
    output.parent.mkdir(parents=True,exist_ok=True)
    output.write_text(content,encoding="utf-8")
    print(str(output))


if __name__=="__main__":
    main()
