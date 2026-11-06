from typing import Annotated, Literal

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.modules.auth.api.routes import current_user, require_role
from app.modules.auth.models.entities import User
from . import services
from .schemas import ReviewDecision, ReviewWrite

router = APIRouter()
reviews = APIRouter(tags=['Avis'])
admin_reviews_router = APIRouter(prefix='/api/admin/reviews', tags=['Modération des avis'])
Db = Annotated[Session, Depends(get_db)]
Connected = Annotated[User, Depends(current_user)]
Patient = Annotated[User, Depends(require_role('patient'))]
Admin = Annotated[User, Depends(require_role('admin'))]


@reviews.post('/api/psychologists/{psychologist_id}/reviews', status_code=201)
def post_review(psychologist_id: str, body: ReviewWrite, user: Patient, db: Db):
    return services.create_review(db, user, psychologist_id, body)


@reviews.get('/api/psychologists/{psychologist_id}/reviews')
def get_reviews(psychologist_id: str, db: Db, page: int = Query(1, ge=1), limit: int = Query(20, ge=1, le=100)):
    return services.public_reviews(db, psychologist_id, page, limit)


@reviews.put('/api/reviews/{review_id}')
def put_review(review_id: str, body: ReviewWrite, user: Connected, db: Db):
    return services.update_review(db, user, review_id, body)


@reviews.delete('/api/reviews/{review_id}')
def remove_review(review_id: str, user: Connected, db: Db):
    return services.delete_review(db, user, review_id)


@admin_reviews_router.get('')
def list_reviews(admin: Admin, db: Db, page: int = Query(1, ge=1), limit: int = Query(20, ge=1, le=100),
                 status: Literal['pending', 'approved', 'rejected'] | None = None):
    return services.admin_reviews(db, page, limit, status)


@admin_reviews_router.post('/{review_id}/approve')
def approve_review(review_id: str, admin: Admin, db: Db):
    return services.decide_review(db, admin, review_id, approve=True)


@admin_reviews_router.post('/{review_id}/reject')
def reject_review(review_id: str, body: ReviewDecision, admin: Admin, db: Db):
    return services.decide_review(db, admin, review_id, approve=False, body=body)


router.include_router(reviews)
router.include_router(admin_reviews_router)
