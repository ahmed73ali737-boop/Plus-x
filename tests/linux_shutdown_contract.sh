#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/.."
source tools/ci_shutdown_gate.sh
curl() { return 7; } # An already-stopped endpoint.
python3 -c 'import time;time.sleep(60)' & pid=$!
pulsex_assert_sigterm_shutdown "$pid" http://127.0.0.1:49999/api/health/live
python3 -u -c 'import signal,sys,time;signal.signal(signal.SIGTERM,lambda *_:sys.exit(0));print("ready",flush=True);time.sleep(60)' > /tmp/pulsex-test-signal-ready & pid=$!
for i in 1 2 3 4 5 6 7 8 9 10; do
  grep -q ready /tmp/pulsex-test-signal-ready && break
  sleep 0.05
done
pulsex_assert_sigterm_shutdown "$pid" http://127.0.0.1:49999/api/health/live
bash -c 'trap "exit 7" TERM; while :; do sleep 0.1; done' & pid=$!
sleep 0.2
if pulsex_assert_sigterm_shutdown "$pid" http://127.0.0.1:49999/api/health/live; then
  echo 'FAIL: abnormal shutdown was accepted' >&2
  exit 1
fi
curl() { return 0; } # An endpoint still reachable after shutdown.
python3 -c 'import time;time.sleep(60)' & pid=$!
if pulsex_assert_sigterm_shutdown "$pid" http://127.0.0.1:49999/api/health/live; then
  echo 'FAIL: live endpoint was accepted after shutdown' >&2
  exit 1
fi
echo 'PASS: exit 143, graceful 0, abnormal exit and still-live health cases'
