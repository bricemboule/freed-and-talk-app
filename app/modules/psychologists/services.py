"""Règles métier des dossiers, décisions et publications professionnelles."""
from sqlalchemy import cast, exists, func, select
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.security import password_hash
from app.modules.auth.models.entities import Role, User, now
from app.modules.auth.services import logic as auth
from . import storage
from .models import PsychologistDocument as Document
from .models import PsychologistProfile as Profile
from .models import PsychologistVerificationLog as Log
from .schemas import ProfessionalFields, ProfessionalUpdate, PsychologistRegister
from .users import avatar_url, user_view

REVIEW_STATES = {'documents_submitted', 'under_review'}
IMPORTANT_FIELDS = {'professional_title', 'specialty', 'years_of_experience',
                    'professional_registration_number'}


def profile_by_id(db: Session, profile_id: str, *, lock=False):
    query = select(Profile).where(Profile.id == profile_id)
    profile = db.scalar(query.execution_options(populate_existing=True).with_for_update() if lock else query)
    if not profile:
        auth.fail(404, 'PSYCHOLOGIST_NOT_FOUND')
    return profile


def own_profile(db: Session, user: User, *, lock=False):
    query = select(Profile).where(Profile.user_id == user.id)
    profile = db.scalar(query.execution_options(populate_existing=True).with_for_update() if lock else query)
    if not profile:
        auth.fail(404, 'PSYCHOLOGIST_NOT_FOUND')
    return profile


def documents(db: Session, profile: Profile):
    return list(db.scalars(select(Document).where(Document.psychologist_id == profile.id)
                           .order_by(Document.created_at, Document.id)))


def document_by_id(db: Session, profile: Profile, document_id: str):
    document = db.scalar(select(Document).where(
        Document.id == document_id, Document.psychologist_id == profile.id))
    if not document:
        auth.fail(404, 'DOCUMENT_NOT_FOUND')
    return document


def document_view(document: Document):
    # Liste explicite : storage_path n'est jamais sérialisé.
    return {'id': document.id, 'document_type': document.document_type,
            'file_name': document.file_name, 'description': document.description,
            'mime_type': document.mime_type, 'file_size': document.file_size,
            'status': document.status, 'rejection_reason': document.rejection_reason,
            'reviewed_at': document.reviewed_at, 'created_at': document.created_at}


def profile_view(profile: Profile, user: User):
    return {'id': profile.id, 'user_id': user.id,
            **{field: getattr(profile, field) for field in ProfessionalFields.model_fields},
            'country': user.country, 'city': user.city,
            'verification_status': profile.verification_status,
            'submitted_at': profile.submitted_at, 'approved_at': profile.approved_at,
            'suspended_at': profile.suspended_at}


def log_action(db: Session, profile: Profile, actor: User, action: str, *, previous=None,
               reason=None, document_id=None, changes=None):
    db.add(Log(psychologist_id=profile.id, actor_id=actor.id,
               admin_id=actor.id if actor.role.code == 'admin' else None,
               action=action, previous_status=previous or profile.verification_status,
               new_status=profile.verification_status, reason=reason,
               document_id=document_id, changes=changes))


def register_psychologist(db: Session, body: PsychologistRegister, request):
    from app.core.rate_limit import rate_limit
    email = auth.normalize(str(body.email))
    rate_limit(request, 'register', email, 5, 3600)
    if auth.get_user(db, email):
        auth.fail(409, 'EMAIL_ALREADY_EXISTS')
    role = db.scalar(select(Role).where(Role.code == 'psychologist', Role.is_active.is_(True)))
    if not role:
        auth.fail(503, 'ROLE_SEED_MISSING')
    user = User(fullname=body.fullname, email=email, phone=body.phone,
                password_hash=password_hash(body.password), role_id=role.id,
                country=body.country, city=body.city, date_of_birth=body.date_of_birth)
    try:
        db.add(user)
        db.flush()
        profile = Profile(user_id=user.id, **body.model_dump(include=set(ProfessionalFields.model_fields)))
        db.add(profile)
        db.flush()
        auth.event(db, user.id, 'PSYCHOLOGIST_REGISTERED')
        from app.modules.communication.notifications import notify
        notify(db, user.id, 'account_created', event_key=f'account:{user.id}', email=False)
        log_action(db, profile, user, 'PROFILE_CREATED')
        db.commit()
    except IntegrityError:
        db.rollback()
        auth.fail(409, 'EMAIL_ALREADY_EXISTS')
    auth.send_otp(db, user, 'email_verification')
    return {'message': 'Compte créé. Vérifiez votre adresse email pour continuer.',
            'user_id': user.id, 'psychologist_id': profile.id, 'role': 'psychologist',
            'email_verification_required': True, 'verification_status': profile.verification_status}


def ensure_editable(profile: Profile):
    if profile.verification_status in REVIEW_STATES or profile.verification_status == 'suspended':
        auth.fail(409, 'DOSSIER_LOCKED')


def reopen(profile: Profile):
    profile.verification_status = 'pending_documents'
    profile.rejection_reason = None
    profile.submitted_at = None
    profile.approved_at = None


def update_profile(db: Session, user: User, body: ProfessionalUpdate):
    profile = own_profile(db, user, lock=True)
    ensure_editable(profile)
    changes = {key: {'before': getattr(profile, key), 'after': value}
               for key, value in body.model_dump(exclude_unset=True).items()
               if getattr(profile, key) != value}
    previous = profile.verification_status
    for key, change in changes.items():
        setattr(profile, key, change['after'])
    if changes and previous == 'rejected':
        reopen(profile)
    if IMPORTANT_FIELDS.intersection(changes) and previous == 'approved':
        reopen(profile)
        for document in documents(db, profile):
            if document.status == 'approved':
                document.status = 'pending'
                document.reviewed_by = None
                document.reviewed_at = None
    if changes:
        log_action(db, profile, user, 'PROFILE_UPDATED', previous=previous, changes=changes)
    db.commit()
    return {'message': 'Profil professionnel mis à jour.', 'profile': profile_view(profile, user)}


def upload_document(db: Session, user: User, document_type: str, description: str | None, upload):
    profile = own_profile(db, user, lock=True)
    ensure_editable(profile)
    content, mime, extension, name = upload
    key = storage.save_file(content, extension)
    try:
        previous = profile.verification_status
        if previous in {'rejected', 'approved'}:
            reopen(profile)
        document = Document(psychologist_id=profile.id, document_type=document_type,
                            description=description, file_name=name, storage_path=key,
                            mime_type=mime, file_size=len(content))
        db.add(document)
        db.flush()
        log_action(db, profile, user, 'DOCUMENT_UPLOADED', previous=previous, document_id=document.id)
        db.commit()
    except Exception:
        db.rollback()
        storage.remove_file(key)
        raise
    return {'message': 'Document envoyé avec succès.', 'document': document_view(document)}


def delete_document(db: Session, user: User, document_id: str):
    profile = own_profile(db, user, lock=True)
    document = document_by_id(db, profile, document_id)
    ensure_editable(profile)
    if document.status == 'approved':
        auth.fail(409, 'DOCUMENT_LOCKED')
    key = document.storage_path
    previous = profile.verification_status
    if previous == 'rejected':
        reopen(profile)
    log_action(db, profile, user, 'DOCUMENT_DELETED', previous=previous, document_id=document.id)
    db.delete(document)
    db.commit()
    storage.remove_file(key)
    return {'message': 'Document supprimé.'}


def missing_documents(db: Session, profile: Profile, *, approved=False):
    required = {item.strip() for item in get_settings().required_professional_documents.split(',') if item.strip()}
    accepted = {'approved'} if approved else {'pending', 'approved'}
    present = {document.document_type for document in documents(db, profile) if document.status in accepted}
    return sorted(required - present)


def ensure_complete(db: Session, profile: Profile, *, approved_documents=False):
    user = db.get(User, profile.user_id)
    if not user or not user.email_verified:
        auth.fail(400, 'EMAIL_NOT_VERIFIED')
    if not user.is_active or not user.role.is_active or user.role.code != 'psychologist':
        auth.fail(400, 'ACCOUNT_DISABLED')
    required = ('professional_title', 'specialty', 'bio', 'languages', 'consultation_modes')
    if not user.country or not user.city or any(not getattr(profile, field) for field in required):
        auth.fail(400, 'PROFILE_INCOMPLETE')
    missing = missing_documents(db, profile, approved=approved_documents)
    if missing:
        from fastapi import HTTPException
        raise HTTPException(400, detail={'code': 'REQUIRED_DOCUMENTS_MISSING',
                                        'message': 'Documents obligatoires manquants ou non validés.',
                                        'missing_documents': missing})


def submit_verification(db: Session, user: User):
    profile = own_profile(db, user, lock=True)
    if profile.verification_status not in {'pending_documents', 'rejected'}:
        auth.fail(409, 'INVALID_VERIFICATION_TRANSITION')
    ensure_complete(db, profile)
    previous = profile.verification_status
    profile.verification_status = 'documents_submitted'
    profile.submitted_at = now()
    profile.rejection_reason = None
    log_action(db, profile, user, 'DOSSIER_SUBMITTED', previous=previous)
    db.commit()
    return {'message': "Votre dossier a été soumis à l'administration.",
            'verification_status': profile.verification_status}


def verification_status(db: Session, user: User):
    profile = own_profile(db, user)
    return {'verification_status': profile.verification_status,
            'submitted_at': profile.submitted_at, 'missing_documents': missing_documents(db, profile),
            'documents': [document_view(document) for document in documents(db, profile)],
            'rejection_reason': profile.rejection_reason, 'suspension_reason': profile.suspension_reason}


def require_review(profile: Profile):
    if profile.verification_status not in REVIEW_STATES:
        auth.fail(409, 'INVALID_VERIFICATION_TRANSITION')


def start_review(db: Session, profile: Profile, admin: User):
    if profile.verification_status == 'documents_submitted':
        previous = profile.verification_status
        profile.verification_status = 'under_review'
        log_action(db, profile, admin, 'REVIEW_STARTED', previous=previous)


def review_document(db: Session, admin: User, profile_id: str, document_id: str, *, approved: bool, reason=None):
    profile = profile_by_id(db, profile_id, lock=True)
    require_review(profile)
    document = document_by_id(db, profile, document_id)
    if document.status != 'pending':
        auth.fail(409, 'DOCUMENT_ALREADY_REVIEWED')
    start_review(db, profile, admin)
    document.status = 'approved' if approved else 'rejected'
    document.rejection_reason = None if approved else reason
    document.reviewed_by = admin.id
    document.reviewed_at = now()
    log_action(db, profile, admin, 'DOCUMENT_APPROVED' if approved else 'DOCUMENT_REJECTED',
               reason=reason, document_id=document.id)
    db.commit()
    return {'message': 'Document approuvé.' if approved else 'Document rejeté.',
            'document_id': document.id, 'status': document.status,
            'rejection_reason': document.rejection_reason}


def decide_profile(db: Session, admin: User, profile_id: str, action: str, reason=None):
    profile = profile_by_id(db, profile_id, lock=True)
    previous = profile.verification_status
    if action == 'approve':
        require_review(profile)
        ensure_complete(db, profile, approved_documents=True)
        profile.verification_status = 'approved'
        profile.approved_at = now()
        profile.rejection_reason = None
    elif action == 'reject':
        require_review(profile)
        profile.verification_status = 'rejected'
        profile.rejection_reason = reason
    elif action == 'suspend':
        if previous != 'approved':
            auth.fail(409, 'INVALID_VERIFICATION_TRANSITION')
        profile.verification_status = 'suspended'
        profile.suspended_at = now()
        profile.suspension_reason = reason
    elif action == 'reactivate':
        if previous != 'suspended':
            auth.fail(409, 'INVALID_VERIFICATION_TRANSITION')
        ensure_complete(db, profile, approved_documents=True)
        profile.verification_status = 'approved'
        profile.suspended_at = None
        profile.suspension_reason = None
    else:
        auth.fail(400, 'INVALID_ACTION')
    log_action(db, profile, admin, 'PROFILE_' + {
        'approve': 'APPROVED', 'reject': 'REJECTED', 'suspend': 'SUSPENDED',
        'reactivate': 'REACTIVATED'}[action], previous=previous, reason=reason)
    if action in {'approve', 'reject'}:
        from app.modules.communication.notifications import notify
        notify(db, profile.user_id,
               'psychologist_approved' if action == 'approve' else 'psychologist_rejected',
               event_key=f'{profile.id}:{action}:{now().isoformat()}',
               data={'psychologist_id': profile.id})
    db.commit()
    return {'message': {'approve': 'Psychologue approuvé.', 'reject': 'Dossier rejeté.',
                        'suspend': 'Psychologue suspendu.', 'reactivate': 'Psychologue réactivé.'}[action],
            'psychologist_id': profile.id, 'verification_status': profile.verification_status,
            'rejection_reason': profile.rejection_reason}


def dossier(db: Session, admin: User, profile_id: str):
    profile = profile_by_id(db, profile_id)
    user = db.get(User, profile.user_id)
    history = list(db.scalars(select(Log).where(Log.psychologist_id == profile.id)
                             .order_by(Log.created_at, Log.id)))
    return {'user': user_view(user), 'profile': profile_view(profile, user),
            'rejection_reason': profile.rejection_reason, 'suspension_reason': profile.suspension_reason,
            'documents': [document_view(document) for document in documents(db, profile)],
            'history': [{'id': item.id, 'admin_id': item.admin_id, 'actor_id': item.actor_id,
                         'action': item.action, 'reason': item.reason, 'document_id': item.document_id,
                         'previous_status': item.previous_status, 'new_status': item.new_status,
                         'changes': item.changes, 'created_at': item.created_at} for item in history]}


def private_document(db: Session, admin: User, profile_id: str, document_id: str):
    profile = profile_by_id(db, profile_id, lock=True)
    document = document_by_id(db, profile, document_id)
    path = storage.file_path(document.storage_path)
    if not path.is_file():
        auth.fail(404, 'DOCUMENT_FILE_NOT_FOUND')
    log_action(db, profile, admin, 'DOCUMENT_ACCESSED', document_id=document.id)
    db.commit()
    return document, path


def public_view(profile: Profile, user: User, *, detailed=False):
    result = {'id': profile.id, 'fullname': user.fullname,
              'professional_title': profile.professional_title, 'specialty': profile.specialty,
              'country': user.country, 'city': user.city, 'languages': profile.languages,
              'consultation_modes': profile.consultation_modes, 'avatar_url': avatar_url(user)}
    if detailed:
        result.update(bio=profile.bio, years_of_experience=profile.years_of_experience,
                      consultation_fee=profile.consultation_fee,
                      consultation_currency=profile.consultation_currency)
    return result


def publication_conditions():
    return (Profile.verification_status == 'approved', User.is_active.is_(True),
            User.email_verified.is_(True), Role.is_active.is_(True), Role.code == 'psychologist')


def can_receive_appointments(db: Session, profile_id: str) -> bool:
    """Condition commune à l'annuaire et aux futurs rendez-vous du module 3."""
    return bool(db.scalar(select(Profile.id).join(User, User.id == Profile.user_id)
                          .join(Role, Role.id == User.role_id)
                          .where(Profile.id == profile_id, *publication_conditions())))


def json_has(db: Session, column, value: str):
    dialect = db.get_bind().dialect.name
    if dialect == 'mysql':
        # JSON_SEARCH décode aussi les accents échappés par le sérialiseur JSON
        # sur MariaDB. Échapper les jokers pour conserver un filtre exact.
        pattern = value.replace('!', '!!').replace('%', '!%').replace('_', '!_')
        return func.json_search(column, 'one', pattern, '!').is_not(None)
    if dialect == 'postgresql':
        return func.jsonb_exists(cast(column, JSONB), value)
    element = func.json_each(column).table_valued('value')
    return exists(select(1).select_from(element).where(element.c.value == value))


def public_directory(db: Session, *, country=None, city=None, specialty=None,
                     language=None, consultation_mode=None, page=1, page_size=20, sort='name'):
    query = select(Profile, User).join(User, User.id == Profile.user_id).join(Role, Role.id == User.role_id)
    query = query.where(*publication_conditions())
    for column, value in ((User.country, country), (User.city, city), (Profile.specialty, specialty)):
        if value:
            query = query.where(column == value)
    if language:
        query = query.where(json_has(db, Profile.languages, language))
    if consultation_mode:
        query = query.where(json_has(db, Profile.consultation_modes, consultation_mode))
    total = db.scalar(select(func.count()).select_from(query.subquery()))
    order = {'name': User.fullname.asc(), 'experience': Profile.years_of_experience.desc(),
             'newest': Profile.approved_at.desc()}[sort]
    rows = db.execute(query.order_by(order, Profile.id).offset((page - 1) * page_size).limit(page_size)).all()
    return {'items': [public_view(profile, user) for profile, user in rows],
            'total': total, 'page': page, 'page_size': page_size}


def public_detail(db: Session, profile_id: str):
    row = db.execute(select(Profile, User).join(User, User.id == Profile.user_id)
                     .join(Role, Role.id == User.role_id)
                     .where(Profile.id == profile_id, *publication_conditions())).first()
    if not row:
        auth.fail(404, 'PSYCHOLOGIST_NOT_FOUND')
    return public_view(*row, detailed=True)


def verification_queue(db: Session, *, status=None, country=None, city=None,
                       submitted_from=None, submitted_to=None, page=1, page_size=20):
    if submitted_from and submitted_to and auth.utc(submitted_from) > auth.utc(submitted_to):
        auth.fail(422, 'INVALID_DATE_RANGE')
    query = select(Profile, User).join(User, User.id == Profile.user_id)
    query = query.where(Profile.verification_status == status if status else Profile.verification_status.in_(REVIEW_STATES))
    for column, value in ((User.country, country), (User.city, city)):
        if value:
            query = query.where(column == value)
    if submitted_from:
        query = query.where(Profile.submitted_at >= auth.utc(submitted_from))
    if submitted_to:
        query = query.where(Profile.submitted_at <= auth.utc(submitted_to))
    total = db.scalar(select(func.count()).select_from(query.subquery()))
    rows = db.execute(query.order_by(Profile.submitted_at, Profile.id)
                      .offset((page - 1) * page_size).limit(page_size)).all()
    return {'items': [{'psychologist_id': profile.id, 'fullname': user.fullname, 'email': user.email,
                       'country': user.country, 'city': user.city,
                       'verification_status': profile.verification_status,
                       'submitted_at': profile.submitted_at} for profile, user in rows],
            'total': total, 'page': page, 'page_size': page_size}
