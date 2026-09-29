"""The API, with a listing source that never finishes on its own.

Run as a script by tests/test_shutdown.py, which then sends it SIGTERM:

    python tests/support/refreshing_server.py <port> <polite|deaf>

`polite` looks for the request to stop, as a real source does between the
pieces of a download. `deaf` never looks, like a call stuck in something
that cannot be interrupted.
"""

import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

import uvicorn  # noqa: E402

from app.sources import backfill, base  # noqa: E402
from app.sources.base import Source  # noqa: E402


class Polite(Source):
    name = "simplify"

    def fetch(self):
        while True:
            base.check_cancelled()
            time.sleep(0.05)


class Deaf(Source):
    name = "simplify"

    def fetch(self):
        time.sleep(600)
        return []


if __name__ == "__main__":
    port, manner = int(sys.argv[1]), sys.argv[2]
    backfill.SOURCES.clear()
    backfill.SOURCES["simplify"] = Polite if manner == "polite" else Deaf

    from app.main import app

    # The same flags as entrypoint.sh.
    uvicorn.run(
        app,
        host="127.0.0.1",
        port=port,
        proxy_headers=False,
        timeout_graceful_shutdown=10,
        log_level="warning",
    )
