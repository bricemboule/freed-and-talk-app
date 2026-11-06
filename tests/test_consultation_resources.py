from datetime import timedelta

import pytest
from fastapi import HTTPException
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.core.database import Base
from app.modules.appointments.models import Appointment, Consultation
from app.modules.appointments.services import participant_consultation, participant_consultations
from app.modules.auth.models.entities import Role, User, now
from app.modules.psychologists.models import PsychologistProfile


@pytest.fixture
def consultation_db():
    engine = create_engine('sqlite://', connect_args={'check_same_thread': False}, poolclass=StaticPool)
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine, expire_on_commit=False)
    with Session() as db:
        patient_role = Role(id=1, code='patient', name='Patient')
        psychologist_role = Role(id=2, code='psychologist', name='Psychologue')
        patient = User(fullname='Patient', email='patient@consultation.test', password_hash='x', role=patient_role)
        other = User(fullname='Autre', email='other@consultation.test', password_hash='x', role=patient_role)
        psychologist = User(fullname='Psychologue', email='psych@consultation.test', password_hash='x', role=psychologist_role)
        db.add_all([patient_role, psychologist_role, patient, other, psychologist]); db.flush()
        profile = PsychologistProfile(user_id=psychologist.id, professional_title='Psychologue',
            specialty='Test', years_of_experience=2, bio='Description professionnelle', languages=['fr'],
            consultation_modes=['online'], verification_status='approved')
        db.add(profile); db.flush()
        appointment = Appointment(patient_id=patient.id, psychologist_id=profile.id,
            start_datetime=now() + timedelta(days=1), end_datetime=now() + timedelta(days=1, minutes=45),
            consultation_mode='online', timezone='Africa/Douala', status='confirmed')
        db.add(appointment); db.flush()
        consultation = Consultation(appointment_id=appointment.id, status='scheduled', consultation_type='video')
        db.add(consultation); db.commit()
        yield db, patient, other, psychologist, consultation
    Base.metadata.drop_all(engine)
    engine.dispose()


def test_participant_consultation_routes_use_appointment_ownership(consultation_db):
    db, patient, other, psychologist, consultation = consultation_db
    listing = participant_consultations(db, patient, page=1, page_size=20)
    assert listing['total'] == 1
    assert listing['items'][0]['type'] == 'video'
    assert participant_consultation(db, psychologist, consultation.id)['id'] == consultation.id
    with pytest.raises(HTTPException) as error:
        participant_consultation(db, other, consultation.id)
    assert error.value.status_code == 403


def test_participant_consultation_list_does_not_expose_other_appointments(consultation_db):
    db, patient, other, _, _ = consultation_db
    assert participant_consultations(db, other, page=1, page_size=20)['items'] == []
    assert participant_consultations(db, patient, status='completed', page=1, page_size=20)['items'] == []
