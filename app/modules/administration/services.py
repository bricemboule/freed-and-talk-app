from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.modules.appointments.models import Appointment, Consultation
from app.modules.auth.models.entities import Role, User, now
from app.modules.auth.services.logic import utc
from app.modules.content.models import Article, Resource
from app.modules.psychologists.models import PsychologistProfile
from app.modules.reviews.models import Review
from app.modules.payments.models import Payment
from .models import AdminAuditLog


def _count(db: Session, model, *conditions):
    query = select(func.count()).select_from(model)
    if conditions:
        query = query.where(*conditions)
    return db.scalar(query) or 0


def dashboard(db: Session):
    return {
        'generated_at': now(),
        'users': {'total': _count(db, User), 'active': _count(db, User, User.is_active.is_(True))},
        'psychologists': {
            'total': _count(db, PsychologistProfile),
            'approved': _count(db, PsychologistProfile, PsychologistProfile.verification_status == 'approved'),
            'pending_review': _count(db, PsychologistProfile,
                PsychologistProfile.verification_status.in_(['documents_submitted', 'under_review']))},
        'appointments': {'total': _count(db, Appointment)},
        'payments': {'total': _count(db, Payment),
                     'pending': _count(db, Payment, Payment.status == 'pending'),
                     'paid': _count(db, Payment, Payment.status == 'paid')},
        'consultations': {'total': _count(db, Consultation)},
        'reviews': {'pending': _count(db, Review, Review.status == 'pending', Review.deleted_at.is_(None))},
        'content': {
            'published_articles': _count(db, Article, Article.is_published.is_(True), Article.deleted_at.is_(None)),
            'published_resources': _count(db, Resource, Resource.is_published.is_(True), Resource.deleted_at.is_(None)),
        },
    }


def users(db: Session, *, page: int, limit: int, role: str | None, active: bool | None):
    query = select(User, Role).join(Role, Role.id == User.role_id)
    if role:
        query = query.where(Role.code == role)
    if active is not None:
        query = query.where(User.is_active.is_(active))
    total = db.scalar(select(func.count()).select_from(query.subquery())) or 0
    rows = db.execute(query.order_by(User.created_at.desc(), User.id)
                      .offset((page - 1) * limit).limit(limit)).all()
    return {'items': [{'id': user.id, 'fullname': user.fullname, 'email': user.email,
                       'role': role_item.code, 'is_active': user.is_active,
                       'email_verified': user.email_verified, 'created_at': utc(user.created_at)}
                      for user, role_item in rows], 'total': total, 'page': page, 'limit': limit}


def psychologists(db: Session, *, page: int, limit: int, status: str | None, country: str | None):
    query = select(PsychologistProfile, User).join(User, User.id == PsychologistProfile.user_id)
    if status:
        query = query.where(PsychologistProfile.verification_status == status)
    if country:
        query = query.where(User.country == country)
    total = db.scalar(select(func.count()).select_from(query.subquery())) or 0
    rows = db.execute(query.order_by(PsychologistProfile.created_at.desc(), PsychologistProfile.id)
                      .offset((page - 1) * limit).limit(limit)).all()
    return {'items': [{'id': profile.id, 'user_id': user.id, 'fullname': user.fullname,
                       'email': user.email, 'country': user.country, 'city': user.city,
                       'specialty': profile.specialty, 'verification_status': profile.verification_status,
                       'submitted_at': utc(profile.submitted_at), 'approved_at': utc(profile.approved_at)}
                      for profile, user in rows], 'total': total, 'page': page, 'limit': limit}


def reports(db: Session):
    def grouped(model, column, *conditions):
        query = select(column, func.count()).select_from(model)
        if conditions:
            query = query.where(*conditions)
        return {str(key): value for key, value in db.execute(query.group_by(column)).all()}
    role_counts = select(Role.code, func.count(User.id)).select_from(User).join(
        Role, Role.id == User.role_id).group_by(Role.code)
    return {
        'generated_at': now(),
        'users_by_role': {code: count for code, count in db.execute(role_counts).all()},
        'psychologists_by_status': grouped(PsychologistProfile, PsychologistProfile.verification_status),
        'appointments_by_status': grouped(Appointment, Appointment.status),
        'payments_by_status': grouped(Payment, Payment.status),
        'consultations_by_status': grouped(Consultation, Consultation.status),
        'reviews_by_status': grouped(Review, Review.status, Review.deleted_at.is_(None)),
    }


def record_admin_action(db: Session, actor: User, action: str, object_type: str,
                        object_id: str, details: dict | None = None):
    db.add(AdminAuditLog(actor_id=actor.id, action=action, object_type=object_type,
                         object_id=object_id, details=details or {}))


def audit_log(db: Session, *, page: int, limit: int, object_type: str | None):
    query = select(AdminAuditLog)
    if object_type:
        query = query.where(AdminAuditLog.object_type == object_type)
    total = db.scalar(select(func.count()).select_from(query.subquery())) or 0
    items = db.scalars(query.order_by(AdminAuditLog.created_at.desc(), AdminAuditLog.id)
                       .offset((page - 1) * limit).limit(limit))
    return {'items': [{'id': item.id, 'actor_id': item.actor_id, 'action': item.action,
                       'object_type': item.object_type, 'object_id': item.object_id,
                       'details': item.details, 'created_at': utc(item.created_at)} for item in items],
            'total': total, 'page': page, 'limit': limit}
