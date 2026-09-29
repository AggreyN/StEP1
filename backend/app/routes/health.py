"""Liveness + database reachability. The first thing that works, and what the
container HEALTHCHECK and App Runner both probe."""

import logging

from fastapi import APIRouter, Depends
from fastapi.responses import JSONResponse
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.deps import get_db
from app.schemas import HealthOut

router = APIRouter(tags=["health"])
log = logging.getLogger(__name__)


@router.get("/health", response_model=HealthOut, responses={503: {"model": HealthOut}})
def health(db: Session = Depends(get_db)):
    try:
        db.execute(text("SELECT 1"))
    except Exception as exc:
        log.error("health: database unreachable: %s", type(exc).__name__)
        # 503 so an orchestrator stops routing here, but the body still says
        # which half is broken. Built from the model, like every other body.
        degraded = HealthOut(status="degraded", db="error")
        return JSONResponse(status_code=503, content=degraded.model_dump())
    return HealthOut(status="ok", db="ok")
