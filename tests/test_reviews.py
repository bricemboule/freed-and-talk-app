import pytest
from datetime import timedelta
from fastapi import HTTPException
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.core.database import Base
from app.modules.administration.models import AdminAuditLog
from sqlalchemy import func, select
from app.modules.appointments.models import Appointment
from app.modules.auth.models.entities import Role, User, now
from app.modules.psychologists.models import PsychologistProfile
from app.modules.reviews import services
from app.modules.reviews.schemas import ReviewDecision, ReviewWrite


@pytest.fixture
def review_db():
    engine = create_engine('sqlite://', connect_args={'check_same_thread': False}, poolclass=StaticPool)
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine, expire_on_commit=False)
    with Session() as db:
        patient_role = Role(id=1, code='patient', name='Patient')
        psych_role = Role(id=2, code='psychologist', name='Psychologue')
        admin_role = Role(id=3, code='admin', name='Administrateur')
        patient = User(fullname='Patient confidentiel', email='patient@review.test', password_hash='x',
                       role=patient_role, email_verified=True, is_active=True)
        psychologist = User(fullname='Psychologue public', email='psych@review.test', password_hash='x',
                            role=psych_role, email_verified=True, is_active=True)
        admin = User(fullname='Administrateur', email='admin@review.test', password_hash='x',
                     role=admin_role, email_verified=True, is_active=True)
        db.add_all([patient_role, psych_role, admin_role, patient, psychologist, admin]); db.flush()
        profile = PsychologistProfile(user_id=psychologist.id, professional_title='Psychologue',
            specialty='Test', years_of_experience=2, bio='bio', languages=['fr'],
            consultation_modes=['online'], verification_status='approved')
        db.add(profile); db.flush()
        appointment = Appointment(patient_id=patient.id, psychologist_id=profile.id,
            start_datetime=now() - timedelta(days=1), end_datetime=now() - timedelta(days=1) + timedelta(minutes=45),
            consultation_mode='online', timezone='Africa/Douala', status='completed')
        db.add(appointment); db.commit()
        yield db, patient, admin, profile, appointment
    Base.metadata.drop_all(engine)
    engine.dispose()


def test_only_approved_reviews_for_completed_visits_are_public(review_db):
    db, patient, admin, profile, appointment = review_db
    body = ReviewWrite(appointment_id=appointment.id, rating=5, content='Accompagnement très utile.')
    review = services.create_review(db, patient, profile.id, body)
    assert services.public_reviews(db, profile.id, 1, 20)['total'] == 0
    published = services.decide_review(db, admin, review['id'], approve=True)
    assert published['status'] == 'approved'
    assert db.scalar(select(func.count()).select_from(AdminAuditLog)) == 1
    public = services.public_reviews(db, profile.id, 1, 20)
    assert public['total'] == 1 and public['average_rating'] == 5.0
    assert 'author_id' not in public['items'][0]
    assert 'Patient confidentiel' not in str(public)


def test_review_edit_requeues_moderation_and_duplicate_is_rejected(review_db):
    db, patient, admin, profile, appointment = review_db
    body = ReviewWrite(appointment_id=appointment.id, rating=4, content='Écoute attentive et utile.')
    review = services.create_review(db, patient, profile.id, body)
    services.decide_review(db, admin, review['id'], approve=True)
    changed = services.update_review(db, patient, review['id'], ReviewWrite(
        appointment_id=appointment.id, rating=3, content='Je souhaite préciser mon retour.'))
    assert changed['status'] == 'pending'
    assert services.public_reviews(db, profile.id, 1, 20)['total'] == 0
    with pytest.raises(HTTPException) as error:
        services.create_review(db, patient, profile.id, body)
    assert error.value.status_code == 409
    with pytest.raises(HTTPException) as error:
        services.decide_review(db, admin, review['id'], approve=False, body=ReviewDecision())
    assert error.value.status_code == 422
