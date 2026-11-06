from typing import Annotated, Literal

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.modules.auth.api.routes import current_user, require_role
from app.modules.auth.models.entities import User
from . import services
from .schemas import PaymentCreate

router = APIRouter(tags=['Paiements'])
Db = Annotated[Session, Depends(get_db)]
Patient = Annotated[User, Depends(require_role('patient'))]
Connected = Annotated[User, Depends(current_user)]
Administrator = Annotated[User, Depends(require_role('admin'))]


@router.post('/api/payments', status_code=201)
def create_payment(body: PaymentCreate, user: Patient, db: Db):
    return services.create_payment(db, user, body)


@router.get('/api/payments')
def get_my_payments(user: Patient, db: Db, page: int = Query(1, ge=1),
                    limit: int = Query(20, ge=1, le=100)):
    return services.list_payments(db, user, page=page, limit=limit)


@router.get('/api/payments/{payment_id}')
def get_payment(payment_id: str, user: Connected, db: Db):
    return services.get_payment(db, user, payment_id)


@router.get('/api/admin/payments')
def get_admin_payments(admin: Administrator, db: Db, page: int = Query(1, ge=1),
                       limit: int = Query(20, ge=1, le=100),
                       status: Literal['pending', 'processing', 'paid', 'failed', 'cancelled', 'refunded'] | None = None):
    return services.admin_payments(db, page=page, limit=limit, status=status)
