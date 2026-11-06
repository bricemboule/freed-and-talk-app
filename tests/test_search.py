import pytest
from datetime import time
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.core.database import Base
from app.modules.appointments.models import Availability
from app.modules.auth.models.entities import Role, User
from app.modules.content.models import Article, Resource
from app.modules.psychologists.models import PsychologistProfile
from app.modules.search.services import search


@pytest.fixture
def search_db():
    engine = create_engine('sqlite://', connect_args={'check_same_thread': False}, poolclass=StaticPool)
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine, expire_on_commit=False)
    with Session() as db:
        patient_role = Role(id=1, code='patient', name='Patient')
        psychologist_role = Role(id=2, code='psychologist', name='Psychologue')
        patient = User(fullname='Patient', email='patient@search.test', password_hash='x', role=patient_role,
                       email_verified=True, is_active=True)
        psychologist = User(fullname='Amina Search', email='psych@search.test', password_hash='x',
                            role=psychologist_role, country='Cameroun', city='Douala',
                            email_verified=True, is_active=True)
        db.add_all([patient_role, psychologist_role, patient, psychologist]); db.flush()
        profile = PsychologistProfile(user_id=psychologist.id, professional_title='Psychologue',
            specialty='Stress', years_of_experience=4, bio='Accompagnement du stress', languages=['fr'],
            consultation_modes=['online'], verification_status='approved')
        db.add(profile)
        db.add(Article(slug='stress-au-travail', title='Comprendre le stress au travail', excerpt='Stress',
            body='Contenu publié', is_published=True, author_id=patient.id))
        db.add(Article(slug='draft-stress', title='Stress en brouillon', excerpt='Stress', body='Secret',
            is_published=False, author_id=patient.id))
        db.add(Resource(resource_type='guide', title='Guide anti-stress', description='Conseils',
            url='https://example.org/stress', is_published=True, author_id=patient.id))
        db.flush()
        db.add(Availability(psychologist_id=profile.id, day_of_week=1, start_time=time(9), end_time=time(12),
            consultation_mode='online', is_active=True))
        db.commit()
        yield db, profile
    Base.metadata.drop_all(engine)
    engine.dispose()


def test_global_search_returns_only_public_content_and_applies_filters(search_db):
    db, profile = search_db
    result = search(db, q='stress', country='Cameroun', city='Douala', specialty='Stress',
                    language='fr', online=True, availability=True, page=1, limit=20)
    assert {item['type'] for item in result['items']} == {'psychologist', 'article', 'resource'}
    assert result['total'] == 3
    assert all(item.get('title') != 'Stress en brouillon' for item in result['items'])
    psychologist = next(item for item in result['items'] if item['type'] == 'psychologist')
    assert psychologist['id'] == profile.id
    assert 'email' not in psychologist['psychologist']


def test_global_search_honors_type_filter(search_db):
    db, _ = search_db
    result = search(db, q='stress', kind='article')
    assert result['total'] == 1
    assert all(item['type'] == 'article' for item in result['items'])
