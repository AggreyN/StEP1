"""One posting by its public id."""

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.deps import current_user, get_db
from app.models import User
from app.schemas import PostingOut
from app.services import postings

router = APIRouter(tags=["postings"])


@router.get("/postings/{posting_id}", response_model=PostingOut)
def get_posting(posting_id: str, user: User = Depends(current_user), db: Session = Depends(get_db)):
    posting = postings.get_by_public_id(db, posting_id)
    return postings.serialize([posting], db, user.id)[0]
