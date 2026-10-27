"""Read-only certificate ownership preflight; no credentials in output."""
import argparse,json
from pathlib import Path
from app.db import make_engine
from app.application.self_certificate_integrity import preflight

def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('--output',type=Path)
    args=parser.parse_args()
    engine=make_engine()
    try:
        with engine.connect() as conn:
            report=preflight(conn)
        if args.output:
            args.output.write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
        print(json.dumps({'ok':report['ok'],'invalid_relations':len(report['problems'])}))
        return 0 if report['ok'] else 2
    finally:
        engine.dispose()

if __name__=='__main__':
    raise SystemExit(main())
