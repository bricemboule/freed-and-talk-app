import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.core.database import Base
from app.modules.auth.models.entities import Role, User
from app.modules.administration import services
from app.modules.psychologists.models import PsychologistProfile


@pytest.fixture
def admin_db():
    engine = create_engine('sqlite://', connect_args={'check_same_thread': False}, poolclass=StaticPool)
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine, expire_on_commit=False)
    with Session() as db:
        patient_role = Role(id=1, code='patient', name='Patient')
        psych_role = Role(id=2, code='psychologist', name='Psychologue')
        patient = User(fullname='Utilisateur', email='user@admin.test', password_hash='x',
                       role=patient_role, email_verified=True, is_active=True)
        psychologist = User(fullname='Professionnel', email='psych@admin.test', password_hash='x',
                            role=psych_role, country='Cameroun', email_verified=True, is_active=True)
        db.add_all([patient_role, psych_role, patient, psychologist]); db.flush()
        db.add(PsychologistProfile(user_id=psychologist.id, professional_title='Psychologue',
            specialty='Test', years_of_experience=2, bio='bio', languages=['fr'],
            consultation_modes=['online'], verification_status='under_review'))
        db.commit()
        yield db
    Base.metadata.drop_all(engine)
    engine.dispose()


def test_admin_lists_and_reports_use_real_aggregates(admin_db):
    users = services.users(admin_db, page=1, limit=20, role='patient', active=True)
    assert users['total'] == 1 and users['items'][0]['email'] == 'user@admin.test'
    psychologists = services.psychologists(admin_db, page=1, limit=20, status='under_review', country='Cameroun')
    assert psychologists['total'] == 1
    report = services.reports(admin_db)
    assert report['users_by_role'] == {'patient': 1, 'psychologist': 1}
    assert report['psychologists_by_status'] == {'under_review': 1}
    assert services.dashboard(admin_db)['users']['total'] == 2
