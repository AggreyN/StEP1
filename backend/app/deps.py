"""Shared FastAPI dependencies, re-exported from one place.

Routes import from here rather than reaching into app.database / app.auth, so
the wiring (session strategy, auth mode) can change without touching every
route module.
"""

from app.auth import current_user
from app.database import get_db

__all__ = ["get_db", "current_user"]
