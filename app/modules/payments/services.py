from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.modules.appointments.models import Appointment
from app.modules.auth.models.entities import User, uid
from app.modules.auth.services.logic import fail, utc
from .models import Payment, PaymentEvent
from .schemas import PaymentCreate


def payment_view(item: Payment):
    return {'id': item.id, 'appointment_id': item.appointment_id, 'provider': item.provider,
            'provider_reference': item.provider_reference, 'amount': item.amount,
            'currency': item.currency, 'status': item.status,
            'mode': 'test', 'created_at': utc(item.created_at), 'updated_at': utc(item.updated_at)}


def create_payment(db: Session, user: User, body: PaymentCreate):
    existing = db.scalar(select(Payment).where(
        Payment.user_id == user.id, Payment.idempotency_key == body.idempotency_key))
    if existing:
        if existing.appointment_id != body.appointment_id or existing.provider != body.provider:
            fail(409, 'IDEMPOTENCY_KEY_REUSED')
        return {'message': 'Demande de paiement déjà enregistrée.', 'payment': payment_view(existing)}

    appointment = db.scalar(select(Appointment).where(Appointment.id == body.appointment_id)
                             .with_for_update())
    if not appointment:
        fail(404, 'APPOINTMENT_NOT_FOUND')
    if appointment.patient_id != user.id:
        fail(403, 'PAYMENT_ACCESS_DENIED')
    if appointment.status != 'confirmed':
        fail(409, 'APPOINTMENT_NOT_PAYABLE')
    if appointment.fee_amount is None or not appointment.fee_currency:
        fail(409, 'APPOINTMENT_PRICE_NOT_CONFIGURED')
    existing_appointment = db.scalar(select(Payment).where(
        Payment.appointment_id == appointment.id, Payment.status.in_(['pending', 'processing', 'paid'])))
    if existing_appointment:
        fail(409, 'APPOINTMENT_PAYMENT_ALREADY_EXISTS')

    # This is an explicit test adapter. Never assert payment success without a
    # verified callback from an actual provider.
    reference = f'test_{uid()}'
    item = Payment(appointment_id=appointment.id, user_id=user.id, provider=body.provider,
                   provider_reference=reference, idempotency_key=body.idempotency_key,
                   amount=appointment.fee_amount, currency=appointment.fee_currency,
                   status='pending')
    db.add(item)
    db.flush()
    db.add(PaymentEvent(payment_id=item.id, status='pending', source='test_adapter',
                        details='Aucun paiement réel effectué.'))
    from app.modules.communication.notifications import notify
    notify(db, user.id, 'payment_pending', event_key=f'payment:{item.id}',
           data={'payment_id': item.id, 'appointment_id': appointment.id}, email=False)
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        existing = db.scalar(select(Payment).where(
            Payment.user_id == user.id, Payment.idempotency_key == body.idempotency_key))
        if existing and existing.appointment_id == body.appointment_id and existing.provider == body.provider:
            return {'message': 'Demande de paiement déjà enregistrée.', 'payment': payment_view(existing)}
        fail(409, 'IDEMPOTENCY_KEY_REUSED')
    return {'message': 'Paiement créé en mode test. Aucun débit réel effectué.',
            'payment': payment_view(item)}


def list_payments(db: Session, user: User, *, page: int, limit: int):
    query = select(Payment).where(Payment.user_id == user.id)
    total = db.scalar(select(func.count()).select_from(query.subquery())) or 0
    rows = db.scalars(query.order_by(Payment.created_at.desc(), Payment.id)
                      .offset((page - 1) * limit).limit(limit))
    return {'items': [payment_view(item) for item in rows], 'total': total,
            'page': page, 'limit': limit}


def get_payment(db: Session, user: User, payment_id: str):
    item = db.get(Payment, payment_id)
    if not item:
        fail(404, 'PAYMENT_NOT_FOUND')
    if item.user_id != user.id and user.role.code != 'admin':
        fail(403, 'PAYMENT_ACCESS_DENIED')
    return payment_view(item)


def admin_payments(db: Session, *, page: int, limit: int, status: str | None = None):
    query = select(Payment)
    if status:
        query = query.where(Payment.status == status)
    total = db.scalar(select(func.count()).select_from(query.subquery())) or 0
    rows = db.scalars(query.order_by(Payment.created_at.desc(), Payment.id)
                      .offset((page - 1) * limit).limit(limit))
    return {'items': [payment_view(item) for item in rows], 'total': total,
            'page': page, 'limit': limit}
