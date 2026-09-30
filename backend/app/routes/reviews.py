"""Reviews of the app: any signed-in person writes one; only the owner reads them.

    POST /reviews          write a review; it is emailed to the owner
    GET  /admin/reviews    every review, newest first (admins only)

To anyone who is not an admin, signed in or not, /admin/reviews answers
exactly as a path that does not exist does: 404 {"detail": "Not found."}.
"""

from __future__ import annotations

import logging
import math
import time

from fastapi import APIRouter, BackgroundTasks, Depends, Query, Request, status
from fastapi.responses import JSONResponse
from limits import parse
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app import config
from app.auth import current_admin
from app.deps import current_user, get_db
from app.middleware import client_ip
from app.models import Review, User
from app.ratelimit import limiter
from app.schemas import AdminReviewOut, AdminReviewsOut, ReviewerOut, ReviewIn, ReviewOut
from app.services import notify

router = APIRouter(tags=["reviews"])
log = logging.getLogger(__name__)

TOO_MANY = "You've sent a lot of reviews today. Try again tomorrow."


def _over_the_limit(request: Request, user: User) -> JSONResponse | None:
    """REVIEW_RATE_LIMIT, counted twice: per person and per client address.
    Either one running out refuses. Only a review that is accepted counts,
    so a form sent back with a 422 does not use up the day.

    Counted here rather than by the limiter's decorator because the person
    is only known once the token has been checked, which the decorator runs
    before.
    """
    if not limiter.enabled:
        return None
    item = parse(config.REVIEW_RATE_LIMIT)
    keys = [("reviews", "user", str(user.id)), ("reviews", "address", client_ip(request.scope))]
    strategy = limiter.limiter
    blocked = [key for key in keys if not strategy.test(item, *key)]
    if not blocked:
        for key in keys:
            strategy.hit(item, *key)
        return None
    reset = max(strategy.get_window_stats(item, *key).reset_time for key in blocked)
    seconds = max(1, math.ceil(reset - time.time()))
    return JSONResponse(
        status_code=status.HTTP_429_TOO_MANY_REQUESTS,
        content={"detail": TOO_MANY},
        headers={"Retry-After": str(seconds)},
    )


@router.post(
    "/reviews",
    response_model=ReviewOut,
    status_code=status.HTTP_201_CREATED,
    responses={429: {"description": TOO_MANY}},
)
def create_review(
    body: ReviewIn,
    request: Request,
    background: BackgroundTasks,
    user: User = Depends(current_user),
    db: Session = Depends(get_db),
):
    refused = _over_the_limit(request, user)
    if refused is not None:
        return refused

    review = Review(user_id=user.id, rating=body.rating, body=body.body)
    db.add(review)
    db.commit()
    db.refresh(review)
    log.info("review received", extra={"user_id": user.id, "rating": review.rating})

    # After the response, with plain values: the session is closed by then.
    background.add_task(
        notify.review_received,
        rating=review.rating,
        body=review.body,
        email=user.email,
        display_name=user.display_name,
        created_at=review.created_at,
    )
    return ReviewOut(
        id=review.id, rating=review.rating, body=review.body, created_at=review.created_at
    )


@router.get("/admin/reviews", response_model=AdminReviewsOut)
def list_reviews(
    page: int = Query(1, ge=1, le=100_000),
    page_size: int = Query(20, ge=1, le=100),
    admin: User = Depends(current_admin),
    db: Session = Depends(get_db),
):
    total, average = db.execute(select(func.count(Review.id), func.avg(Review.rating))).one()
    rows = db.execute(
        select(Review, User.email, User.display_name)
        .outerjoin(User, User.id == Review.user_id)
        .order_by(Review.created_at.desc(), Review.id.desc())
        .limit(page_size)
        .offset((page - 1) * page_size)
    ).all()
    items = [
        AdminReviewOut(
            id=review.id,
            rating=review.rating,
            body=review.body,
            created_at=review.created_at,
            user=ReviewerOut(email=email, display_name=name) if email is not None else None,
        )
        for review, email, name in rows
    ]
    return AdminReviewsOut(
        items=items,
        page=page,
        total=total,
        has_more=page * page_size < total,
        average_rating=round(float(average), 1) if average is not None else None,
    )
