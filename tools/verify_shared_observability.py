#!/usr/bin/env python3
import hashlib,json,pathlib,sys
root=pathlib.Path(__file__).resolve().parents[1]
lock=json.loads((root/'components/g-observability/source-lock.json').read_text())
bad=[r['path'] for r in lock['files'] if not (root/r['path']).is_file() or hashlib.sha256((root/r['path']).read_bytes()).hexdigest()!=r['sha256']]
if bad:raise SystemExit('Shared observability dependency drift: '+', '.join(bad))
print('Shared observability dependency hashes verified')
