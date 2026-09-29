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
#
# --no-proxy-headers: uvicorn would otherwise rewrite the client address and
# scheme from X-Forwarded-For and X-Forwarded-Proto for any connection from a
# host it trusts. The app reads those headers itself, under TRUST_PROXY and
# TRUSTED_PROXY_HOPS, and should be the only thing that does.
#
# --timeout-graceful-shutdown 10: on SIGTERM, requests in progress get ten
# seconds to finish. After that the app stops the refresh of the listings if
# one is running, which can take up to INGEST_SHUTDOWN_GRACE_S (15). Together
# they fit inside the 30 seconds ECS allows before it kills the task.
exec uvicorn app.main:app --host 0.0.0.0 --port 8000 --no-proxy-headers \
  --timeout-graceful-shutdown 10
