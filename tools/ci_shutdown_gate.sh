#!/usr/bin/env bash
# Source from the shell that launched the child: wait only works for a child PID.
pulsex_assert_sigterm_shutdown() {
  local app_pid="${1:?app PID required}" health_url="${2:?health URL required}"
  local status=0 i
  if ! kill -0 "$app_pid" 2>/dev/null; then
    echo 'ERROR: application exited before the shutdown assertion' >&2
    return 1
  fi
  kill -TERM "$app_pid" || return 1
  wait "$app_pid" || status=$?
  # 143 = 128 + SIGTERM(15): normal for a process without a signal handler.
  if [[ "$status" -ne 0 && "$status" -ne 143 ]]; then
    echo "ERROR: unexpected application shutdown exit code: $status" >&2
    return 1
  fi
  for i in 1 2 3 4 5; do
    if ! curl --max-time 1 --fail --silent "$health_url" >/dev/null; then
      echo "PASS: shutdown exit=$status and health endpoint stopped"
      return 0
    fi
    sleep 0.2
  done
  echo 'ERROR: health endpoint remains online after SIGTERM' >&2
  return 1
}
