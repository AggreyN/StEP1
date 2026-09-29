"""Nightly ghosting rule (§6), runnable by hand or from a scheduler:

    python -m app.jobs.ghost

Writes a source='system' 'ghosted' event for every application that has sat
in applied|acknowledged with no status event for GHOST_AFTER_DAYS.
"""

from __future__ import annotations

import logging

from app.database import SessionLocal
from app.logging_config import setup as setup_logging
from app.services.timeline import ghost_stale_applications

log = logging.getLogger("jobs.ghost")


def main() -> int:
    setup_logging()
    with SessionLocal() as db:
        count = ghost_stale_applications(db)
    log.info("ghost job finished", extra={"ghosted": count})
    return count


if __name__ == "__main__":
    main()
