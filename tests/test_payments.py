from datetime import timedelta

import pytest
from fastapi import HTTPException
from pydantic import ValidationError
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.core.database import Base
from app.modules.appointments.models import Appointment
from app.modules.auth.models.entities import Role, User, now
from app.modules.communication.models import Notification
from app.modules.payments.models import PaymentEvent
from app.modules.payments.schemas import PaymentCreate
from app.modules.payments import services
from app.modules.psychologists.models import PsychologistProfile


@pytest.fixture
def payment_db():
    engine = create_engine('sqlite://', connect_args={'check_same_thread': False}, poolclass=StaticPool)
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine, expire_on_commit=False)
    with Session() as db:
        patient_role = Role(id=1, code='patient', name='Patient')
        psychologist_role = Role(id=2, code='psychologist', name='Psychologue')
        admin_role = Role(id=3, code='admin', name='Administrateur')
        patient = User(fullname='Patient', email='patient@payment.test', password_hash='x',
                       role=patient_role, email_verified=True, is_active=True)
        other = User(fullname='Autre patient', email='other@payment.test', password_hash='x',
                     role=patient_role, email_verified=True, is_active=True)
        admin = User(fullname='Admin', email='admin@payment.test', password_hash='x',
                     role=admin_role, email_verified=True, is_active=True)
        psychologist = User(fullname='Psychologue', email='psych@payment.test', password_hash='x',
                            role=psychologist_role, email_verified=True, is_active=True)
        db.add_all([patient_role, psychologist_role, admin_role, patient, other, admin, psychologist])
        db.flush()
        profile = PsychologistProfile(user_id=psychologist.id, professional_title='Psychologue',
            specialty='Test', years_of_experience=2, bio='Bio de test', languages=['fr'],
            consultation_modes=['online'], verification_status='approved', consultation_fee=15000,
            consultation_currency='XAF')
        db.add(profile)
        db.flush()
        appointment = Appointment(patient_id=patient.id, psychologist_id=profile.id,
            start_datetime=now() + timedelta(days=2), end_datetime=now() + timedelta(days=2, minutes=45),
            consultation_mode='online', timezone='Africa/Douala', status='confirmed',
            fee_amount=15000, fee_currency='XAF')
        db.add(appointment)
        db.commit()
        yield db, patient, other, admin, profile, appointment
    Base.metadata.drop_all(engine)
    engine.dispose()


def test_payment_uses_server_price_and_idempotency(payment_db):
    db, patient, _, _, _, appointment = payment_db
    body = PaymentCreate(appointment_id=appointment.id, provider='orange_money',
                         idempotency_key='checkout-req-001')
    created = services.create_payment(db, patient, body)
    payment = created['payment']
    assert payment['amount'] == 15000 and payment['currency'] == 'XAF'
    assert payment['status'] == 'pending' and payment['mode'] == 'test'
    assert created['message'].find('Aucun débit réel') >= 0
    repeated = services.create_payment(db, patient, body)
    assert repeated['payment']['id'] == payment['id']
    assert db.query(PaymentEvent).count() == 1
    assert db.query(Notification).filter_by(type='payment_pending').count() == 1
    with pytest.raises(HTTPException) as error:
        services.create_payment(db, patient, PaymentCreate(
            appointment_id=appointment.id, provider='card', idempotency_key='checkout-req-001'))
    assert error.value.status_code == 409
    with pytest.raises(ValidationError):
        PaymentCreate(appointment_id=appointment.id, provider='card',
                      idempotency_key='checkout-req-004', amount=1)


def test_payment_rejects_wrong_owner_unconfirmed_and_unpriced(payment_db):
    db, patient, other, _, _, appointment = payment_db
    body = PaymentCreate(appointment_id=appointment.id, provider='card', idempotency_key='checkout-req-002')
    with pytest.raises(HTTPException) as error:
        services.create_payment(db, other, body)
    assert error.value.status_code == 403
    appointment.status = 'pending'
    db.commit()
    with pytest.raises(HTTPException) as error:
        services.create_payment(db, patient, body)
    assert error.value.status_code == 409
    appointment.status, appointment.fee_amount = 'confirmed', None
    db.commit()
    with pytest.raises(HTTPException) as error:
        services.create_payment(db, patient, body)
    assert error.value.status_code == 409


def test_payment_list_and_admin_filter(payment_db):
    db, patient, _, admin, _, appointment = payment_db
    payment = services.create_payment(db, patient, PaymentCreate(
        appointment_id=appointment.id, provider='mtn_momo', idempotency_key='checkout-req-003'))['payment']
    assert services.list_payments(db, patient, page=1, limit=20)['total'] == 1
    assert services.get_payment(db, admin, payment['id'])['id'] == payment['id']
    assert services.admin_payments(db, page=1, limit=20, status='pending')['total'] == 1
    assert services.admin_payments(db, page=1, limit=20, status='paid')['total'] == 0
