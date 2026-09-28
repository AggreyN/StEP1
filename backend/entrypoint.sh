#!/bin/sh
# Migrate, then serve. The container may boot against a database whose schema
# is behind — or, on first run, absent. Retry briefly because the database can
# be unreachable for a container's first seconds; if migrations still fail,
# exit nonzero so the orchestrator restarts us instead of serving a
# wrong-schema DB. Each failure prints alembic's own error, not just a counter.

LOG=/tmp/alembic-boot.log
attempt=1
while :; do
  if alembic upgrade head >"$LOG" 2>&1; then
    cat "$LOG"
    break
  fi
  echo "=== alembic upgrade head FAILED (attempt $attempt of 5) — underlying error: ===" >&2
  tail -40 "$LOG" >&2
  if [ "$attempt" -ge 5 ]; then
    echo "giving up after $attempt attempts; the error above is the real cause" >&2
    exit 1
  fi
  attempt=$((attempt + 1))
  sleep 3
done

# exec so uvicorn is PID 1 and receives SIGTERM directly.
exec uvicorn app.main:app --host 0.0.0.0 --port 8000
