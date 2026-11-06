"""Tests métier HTTP-independent pour les données privées de communication."""
import pytest
from io import BytesIO
from types import SimpleNamespace
from fastapi import HTTPException
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.core.database import Base
from app.modules.auth.models.entities import Role, User
from app.modules.communication import notifications, services
from app.modules.psychologists.models import PsychologistProfile
from PIL import Image


@pytest.fixture
def communication_db():
    engine = create_engine('sqlite://', connect_args={'check_same_thread': False}, poolclass=StaticPool)
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine, expire_on_commit=False)
    with Session() as db:
        patient_role = Role(id=1, code='patient', name='Patient')
        psych_role = Role(id=2, code='psychologist', name='Psychologue')
        admin_role = Role(id=3, code='admin', name='Administrateur')
        patient = User(fullname='Patient test', email='patient@example.test', password_hash='x',
                       role=patient_role, email_verified=True, is_active=True)
        psychologist = User(fullname='Psychologue test', email='psychologist@example.test', password_hash='x',
                            role=psych_role, email_verified=True, is_active=True)
        other = User(fullname='Autre patient', email='other@example.test', password_hash='x',
                     role=patient_role, email_verified=True, is_active=True)
        db.add_all([patient_role, psych_role, admin_role, patient, psychologist, other])
        db.flush()
        db.add(PsychologistProfile(user_id=psychologist.id, professional_title='Psychologue',
            specialty='Accompagnement', years_of_experience=3, bio='Présentation', languages=['fr'],
            consultation_modes=['online'], verification_status='approved'))
        db.commit()
        yield db, patient, psychologist, other
    Base.metadata.drop_all(engine)
    engine.dispose()


def test_private_conversation_messages_and_reads(communication_db):
    db, patient, psychologist, other = communication_db
    opened = services.create_conversation(db, patient, psychologist.id, 'Bonjour')
    conversation_id = opened['conversation']['id']
    message = services.create_message(db, psychologist, conversation_id, 'Bonjour, comment puis-je aider ?')
    assert message['message']['sender_id'] == psychologist.id
    inbox = services.list_conversations(db, patient, 1, 20)
    assert inbox['total'] == 1
    assert inbox['items'][0]['unread_count'] == 1
    history = services.list_messages(db, patient, conversation_id, None, 1, 50)
    assert len(history['items']) == 2
    assert history['items'][1]['is_read'] is True
    with pytest.raises(HTTPException) as error:
        services.list_messages(db, other, conversation_id, None, 1, 50)
    assert error.value.status_code == 404


def test_patient_starts_only_with_approved_psychologist_and_edits_own_message(communication_db):
    db, patient, psychologist, other = communication_db
    conversation = services.create_conversation(db, patient, psychologist.id, None)['conversation']
    message = services.create_message(db, patient, conversation['id'], 'Texte initial')['message']
    changed = services.edit_message(db, patient, conversation['id'], message['id'], 'Texte corrigé')
    assert changed['message']['content'] == 'Texte corrigé'
    with pytest.raises(HTTPException) as error:
        services.create_conversation(db, patient, other.id, None)
    assert error.value.status_code == 403
    with pytest.raises(HTTPException) as error:
        services.list_messages(db, other, conversation['id'], None, 1, 50)
    assert error.value.status_code == 404


def test_notification_preferences_and_read_all(communication_db):
    db, patient, psychologist, _ = communication_db
    notifications.notify(db, patient.id, 'system_announcement', event_key='announcement-test')
    db.commit()
    assert notifications.list_notifications(db, patient, 1, 20, unread_only=True)['total'] == 1
    result = notifications.read_all(db, patient)
    assert result['updated_count'] == 1
    assert notifications.list_notifications(db, patient, 1, 20, unread_only=True)['total'] == 0


def test_attachment_private_storage_and_cleanup(communication_db, tmp_path, monkeypatch):
    db, patient, psychologist, _ = communication_db
    settings = SimpleNamespace(message_rate_limit=30, message_edit_minutes=10,
                               message_max_characters=10000,
                               private_message_directory=str(tmp_path / 'private'))
    monkeypatch.setattr(services, 'get_settings', lambda: settings)
    conversation = services.create_conversation(db, patient, psychologist.id, None)['conversation']
    image = BytesIO()
    Image.new('RGB', (12, 12), 'blue').save(image, format='PNG')
    from app.modules.psychologists.storage import validate_content
    payload, mime_type, extension = validate_content(image.getvalue(), avatar=False)
    response = services.save_attachment(db, patient, conversation['id'], content=payload,
        mime_type=mime_type, extension=extension, filename='image.png', caption='Illustration')
    attachment_meta = response['message']['attachment']
    attachment, path = services.attachment_path(db, psychologist, conversation['id'], attachment_meta['id'])
    assert path.is_file() and (path.stat().st_mode & 0o777) == 0o600
    assert attachment.mime_type == 'image/png'
    services.delete_message(db, patient, conversation['id'], response['message']['id'])
    assert not path.exists()
