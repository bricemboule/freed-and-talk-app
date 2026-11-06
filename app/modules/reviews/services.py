from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.modules.appointments.models import Appointment
from app.modules.auth.models.entities import User, now
from app.modules.auth.services.logic import fail, utc
from app.modules.psychologists.models import PsychologistProfile
from .models import Review
from .schemas import ReviewDecision, ReviewWrite


def _view(item: Review, *, admin=False):
    result = {'id': item.id, 'psychologist_id': item.psychologist_id, 'rating': item.rating,
              'content': item.content, 'status': item.status, 'created_at': utc(item.created_at),
              'updated_at': utc(item.updated_at)}
    if admin:
        result.update(author_id=item.author_id, appointment_id=item.appointment_id,
                      reviewed_by=item.reviewed_by, reviewed_at=utc(item.reviewed_at),
                      rejection_reason=item.rejection_reason)
    return result


def create_review(db: Session, patient: User, psychologist_id: str, body: ReviewWrite):
    profile = db.get(PsychologistProfile, psychologist_id)
    if not profile or profile.verification_status != 'approved':
        fail(404, 'PSYCHOLOGIST_NOT_FOUND')
    appointment = db.get(Appointment, body.appointment_id)
    if (not appointment or appointment.patient_id != patient.id
            or appointment.psychologist_id != profile.id or appointment.status != 'completed'):
        fail(403, 'REVIEW_REQUIRES_COMPLETED_APPOINTMENT')
    item = Review(appointment_id=appointment.id, psychologist_id=profile.id,
                  author_id=patient.id, rating=body.rating, content=body.content, status='pending')
    db.add(item)
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        fail(409, 'APPOINTMENT_ALREADY_REVIEWED')
    return _view(item)


def public_reviews(db: Session, psychologist_id: str, page: int, limit: int):
    profile = db.get(PsychologistProfile, psychologist_id)
    if not profile or profile.verification_status != 'approved':
        fail(404, 'PSYCHOLOGIST_NOT_FOUND')
    base = select(Review).where(Review.psychologist_id == profile.id,
        Review.status == 'approved', Review.deleted_at.is_(None))
    total = db.scalar(select(func.count()).select_from(base.subquery())) or 0
    average = db.scalar(select(func.avg(Review.rating)).where(
        Review.psychologist_id == profile.id, Review.status == 'approved', Review.deleted_at.is_(None)))
    items = db.scalars(base.order_by(Review.created_at.desc(), Review.id)
                       .offset((page - 1) * limit).limit(limit))
    # Never expose a patient's name or account identifier on this public route.
    return {'items': [_view(item) for item in items], 'total': total,
            'average_rating': round(float(average), 2) if average is not None else None,
            'page': page, 'limit': limit}


def update_review(db: Session, user: User, review_id: str, body: ReviewWrite):
    item = db.scalar(select(Review).where(Review.id == review_id).with_for_update())
    if not item or item.deleted_at:
        fail(404, 'REVIEW_NOT_FOUND')
    if item.author_id != user.id:
        fail(403, 'REVIEW_ACCESS_DENIED')
    appointment = db.get(Appointment, body.appointment_id)
    if (body.appointment_id != item.appointment_id or not appointment or appointment.patient_id != user.id
            or appointment.psychologist_id != item.psychologist_id or appointment.status != 'completed'):
        fail(400, 'REVIEW_APPOINTMENT_MISMATCH')
    item.rating, item.content, item.status = body.rating, body.content, 'pending'
    item.reviewed_by, item.reviewed_at, item.rejection_reason = None, None, None
    db.commit()
    return _view(item)


def delete_review(db: Session, user: User, review_id: str):
    item = db.scalar(select(Review).where(Review.id == review_id).with_for_update())
    if not item or item.deleted_at:
        fail(404, 'REVIEW_NOT_FOUND')
    if item.author_id != user.id:
        fail(403, 'REVIEW_ACCESS_DENIED')
    item.deleted_at, item.status = now(), 'rejected'
    db.commit()
    return {'message': 'Avis supprimé.'}


def admin_reviews(db: Session, page: int, limit: int, status: str | None):
    base = select(Review).where(Review.deleted_at.is_(None))
    if status:
        base = base.where(Review.status == status)
    total = db.scalar(select(func.count()).select_from(base.subquery())) or 0
    items = db.scalars(base.order_by(Review.created_at.asc(), Review.id)
                       .offset((page - 1) * limit).limit(limit))
    return {'items': [_view(item, admin=True) for item in items], 'total': total,
            'page': page, 'limit': limit}


def decide_review(db: Session, admin: User, review_id: str, *, approve: bool, body: ReviewDecision | None = None):
    from app.modules.administration.services import record_admin_action
    item = db.scalar(select(Review).where(Review.id == review_id).with_for_update())
    if not item or item.deleted_at:
        fail(404, 'REVIEW_NOT_FOUND')
    if item.status not in {'pending', 'rejected'}:
        fail(409, 'INVALID_REVIEW_TRANSITION')
    reason = body.reason if body else None
    if not approve and not reason:
        fail(422, 'REJECTION_REASON_REQUIRED')
    item.status = 'approved' if approve else 'rejected'
    item.reviewed_by, item.reviewed_at, item.rejection_reason = admin.id, now(), None if approve else reason
    record_admin_action(db, admin, 'REVIEW_APPROVED' if approve else 'REVIEW_REJECTED',
                        'review', item.id, {'rating': item.rating})
    db.commit()
    return _view(item, admin=True)
