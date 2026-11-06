"""Routes du module 2 ; les services portent les contrôles métier."""
from datetime import datetime
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, File, Form, Query, Request, UploadFile
from fastapi.responses import FileResponse
from sqlalchemy import select
from sqlalchemy.orm import Session
from starlette.concurrency import run_in_threadpool

from app.core.database import get_db
from app.modules.auth.api.routes import current_user, require_role
from app.modules.auth.models.entities import User
from app.modules.auth.services.logic import fail
from . import services, storage, users
from .schemas import (ConsultationMode, DecisionReason, DocumentType, ProfessionalUpdate,
                      PsychologistRegister, UserUpdate, VerificationStatus)

router = APIRouter()
profiles_router = APIRouter(prefix='/api/users', tags=['Profils utilisateurs'])
psychologists_router = APIRouter(prefix='/api/psychologists', tags=['Psychologues'])
admin_router = APIRouter(prefix='/api/admin/psychologists', tags=['Vérification administrative'])

Db = Annotated[Session, Depends(get_db)]
ConnectedUser = Annotated[User, Depends(current_user)]
Psychologist = Annotated[User, Depends(require_role('psychologist'))]
Administrator = Annotated[User, Depends(require_role('admin'))]
Page = Annotated[int, Query(ge=1)]
PageSize = Annotated[int, Query(ge=1, le=100)]


@profiles_router.get('/me')
def get_user_profile(user: ConnectedUser):
    return users.user_view(user)


@profiles_router.put('/me')
def update_user_profile(body: UserUpdate, user: ConnectedUser, db: Db):
    return users.update_user(db, user, body)


@profiles_router.post('/me/avatar')
async def upload_avatar(user: ConnectedUser, db: Db, file: UploadFile = File(...)):
    upload = await storage.prepare_upload(file, avatar=True)
    return await run_in_threadpool(users.replace_avatar, db, user, upload)


@profiles_router.delete('/me/avatar')
def remove_avatar(user: ConnectedUser, db: Db):
    return users.delete_avatar(db, user)


@router.get('/media/avatars/{filename}', include_in_schema=False)
def get_avatar(filename: str, db: Db):
    path = storage.file_path(filename, avatar=True)
    if not db.scalar(select(User.id).where(User.avatar_path == filename)) or not path.is_file():
        fail(404, 'FILE_NOT_FOUND')
    return FileResponse(path, media_type='image/webp', headers={'X-Content-Type-Options': 'nosniff'})


@router.post('/api/auth/register/psychologist', status_code=201, tags=['Authentication'])
def register_psychologist(body: PsychologistRegister, request: Request, db: Db):
    return services.register_psychologist(db, body, request)


# Les routes /me doivent précéder la route publique /{psychologist_id}.
@psychologists_router.get('/me')
def get_professional_profile(user: Psychologist, db: Db):
    return services.profile_view(services.own_profile(db, user), user)


@psychologists_router.put('/me')
def update_professional_profile(body: ProfessionalUpdate, user: Psychologist, db: Db):
    return services.update_profile(db, user, body)


@psychologists_router.post('/me/documents', status_code=201)
async def upload_document(
    user: Psychologist, db: Db, file: UploadFile = File(...),
    document_type: DocumentType = Form(...),
    description: str | None = Form(default=None, max_length=1000),
):
    upload = await storage.prepare_upload(file)
    return await run_in_threadpool(services.upload_document, db, user, document_type, description, upload)


@psychologists_router.get('/me/documents')
def get_documents(user: Psychologist, db: Db):
    profile = services.own_profile(db, user)
    return {'items': [services.document_view(item) for item in services.documents(db, profile)]}


@psychologists_router.delete('/me/documents/{document_id}')
def remove_document(document_id: str, user: Psychologist, db: Db):
    return services.delete_document(db, user, document_id)


@psychologists_router.post('/me/submit-verification')
def submit_verification(user: Psychologist, db: Db):
    return services.submit_verification(db, user)


@psychologists_router.get('/me/verification-status')
def get_verification_status(user: Psychologist, db: Db):
    return services.verification_status(db, user)


@psychologists_router.get('')
def list_psychologists(
    db: Db, country: str | None = None, city: str | None = None,
    specialty: str | None = None, language: str | None = None,
    consultation_mode: ConsultationMode | None = None,
    page: Page = 1, page_size: PageSize = 20,
    sort: Literal['name', 'experience', 'newest'] = 'name',
):
    return services.public_directory(db, country=country, city=city, specialty=specialty,
                                     language=language, consultation_mode=consultation_mode,
                                     page=page, page_size=page_size, sort=sort)


@psychologists_router.get('/{psychologist_id}')
def get_public_psychologist(psychologist_id: str, db: Db):
    return services.public_detail(db, psychologist_id)


@admin_router.get('/verifications')
def list_verifications(
    admin: Administrator, db: Db, status: VerificationStatus | None = None,
    country: str | None = None, city: str | None = None,
    submitted_from: datetime | None = None, submitted_to: datetime | None = None,
    page: Page = 1, page_size: PageSize = 20,
):
    return services.verification_queue(db, status=status, country=country, city=city,
                                       submitted_from=submitted_from, submitted_to=submitted_to,
                                       page=page, page_size=page_size)


@admin_router.get('/{psychologist_id}/verification')
def get_verification(psychologist_id: str, admin: Administrator, db: Db):
    return services.dossier(db, admin, psychologist_id)


@admin_router.get('/{psychologist_id}/documents/{document_id}')
def download_document(psychologist_id: str, document_id: str, admin: Administrator, db: Db):
    document, path = services.private_document(db, admin, psychologist_id, document_id)
    return FileResponse(path, media_type=document.mime_type, filename=document.file_name,
                        headers={'Cache-Control': 'private, no-store', 'X-Content-Type-Options': 'nosniff'})


@admin_router.post('/{psychologist_id}/documents/{document_id}/approve')
def approve_document(psychologist_id: str, document_id: str, admin: Administrator, db: Db):
    return services.review_document(db, admin, psychologist_id, document_id, approved=True)


@admin_router.post('/{psychologist_id}/documents/{document_id}/reject')
def reject_document(psychologist_id: str, document_id: str, body: DecisionReason, admin: Administrator, db: Db):
    return services.review_document(db, admin, psychologist_id, document_id, approved=False, reason=body.reason)


@admin_router.post('/{psychologist_id}/approve')
def approve_psychologist(psychologist_id: str, admin: Administrator, db: Db):
    return services.decide_profile(db, admin, psychologist_id, 'approve')


@admin_router.post('/{psychologist_id}/reject')
def reject_psychologist(psychologist_id: str, body: DecisionReason, admin: Administrator, db: Db):
    return services.decide_profile(db, admin, psychologist_id, 'reject', body.reason)


@admin_router.post('/{psychologist_id}/suspend')
def suspend_psychologist(psychologist_id: str, body: DecisionReason, admin: Administrator, db: Db):
    return services.decide_profile(db, admin, psychologist_id, 'suspend', body.reason)


@admin_router.post('/{psychologist_id}/reactivate')
def reactivate_psychologist(psychologist_id: str, admin: Administrator, db: Db):
    return services.decide_profile(db, admin, psychologist_id, 'reactivate')


router.include_router(profiles_router)
router.include_router(psychologists_router)
router.include_router(admin_router)
