from typing import Annotated, Literal

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.modules.auth.api.routes import require_role
from app.modules.auth.models.entities import User
from . import services

router = APIRouter(prefix='/api/admin', tags=['Administration générale'])
Db = Annotated[Session, Depends(get_db)]
Admin = Annotated[User, Depends(require_role('admin'))]


@router.get('/dashboard')
def get_dashboard(admin: Admin, db: Db):
    return services.dashboard(db)


@router.get('/users')
def list_users(admin: Admin, db: Db, page: int = Query(1, ge=1), limit: int = Query(20, ge=1, le=100),
               role: Literal['patient', 'psychologist', 'admin'] | None = None,
               active: bool | None = None):
    return services.users(db, page=page, limit=limit, role=role, active=active)


@router.get('/psychologists')
def list_psychologists(admin: Admin, db: Db, page: int = Query(1, ge=1), limit: int = Query(20, ge=1, le=100),
                       status: Literal['pending_documents', 'documents_submitted', 'under_review',
                                       'approved', 'rejected', 'suspended'] | None = None,
                       country: str | None = Query(default=None, max_length=100)):
    return services.psychologists(db, page=page, limit=limit, status=status, country=country)


@router.get('/reports')
def get_reports(admin: Admin, db: Db):
    return services.reports(db)


@router.get('/audit-log')
def get_audit_log(admin: Admin, db: Db, page: int = Query(1, ge=1),
                  limit: int = Query(50, ge=1, le=100),
                  object_type: Literal['article', 'resource', 'review'] | None = None):
    return services.audit_log(db, page=page, limit=limit, object_type=object_type)
