"""Liveness + database reachability. The first thing that works, and what the
container HEALTHCHECK and App Runner both probe."""

import logging

from fastapi import APIRouter, Depends, Response
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.deps import get_db
from app.schemas import HealthOut

router = APIRouter(tags=["health"])
log = logging.getLogger(__name__)


@router.get("/health", response_model=HealthOut, responses={503: {"model": HealthOut}})
def health(response: Response, db: Session = Depends(get_db)):
    try:
        db.execute(text("SELECT 1"))
    except Exception as exc:
        log.error("health: database unreachable: %s", type(exc).__name__)
        # 503 so an orchestrator stops routing here, but the body still says
        # which half is broken.
        response.status_code = 503
        return HealthOut(status="degraded", db="error")
    return HealthOut(status="ok", db="ok")
