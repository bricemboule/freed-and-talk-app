"""Parcours du module 2, permissions et stockage des justificatifs."""
from contextlib import contextmanager
from io import BytesIO
import json

from PIL import Image
from pypdf import PdfWriter
import pytest
from sqlalchemy import select

from app.core.config import get_settings
from app.core.database import get_db
from app.core.security import password_hash
from app.main import app
from app.modules.auth.models.entities import User
from app.modules.auth.services import logic
from app.modules.psychologists.models import PsychologistProfile, PsychologistVerificationLog
from app.modules.psychologists.services import can_receive_appointments
from app.modules.psychologists.schemas import PsychologistRegister, UserUpdate
from tests.test_auth import client


def test_birth_date_is_optional_private_and_cannot_be_future():
    body = PsychologistRegister(fullname='Marie Nkom', email='marie@example.com', password='Password123!',
        password_confirmation='Password123!', country='Cameroun', city='Douala',
        professional_title='Psychologue', specialty='Clinique', years_of_experience=2,
        bio='Accompagnement psychologique pour adultes.', languages=['Français'],
        consultation_modes=['online'], date_of_birth='1990-04-12')
    assert body.date_of_birth.isoformat() == '1990-04-12'
    assert UserUpdate(date_of_birth=None).date_of_birth is None
    with pytest.raises(ValueError):
        UserUpdate(date_of_birth='2999-01-01')


def png():
    output = BytesIO()
    Image.new('RGB', (16, 16), 'blue').save(output, format='PNG')
    return output.getvalue()


def pdf():
    output = BytesIO()
    writer = PdfWriter()
    writer.add_blank_page(width=100, height=100)
    writer.write(output)
    return output.getvalue()


@pytest.fixture
def system(client, tmp_path, monkeypatch):
    tc, delivered = client
    settings = get_settings()
    monkeypatch.setattr(settings, 'media_directory', str(tmp_path / 'media'))
    monkeypatch.setattr(settings, 'private_documents_directory', str(tmp_path / 'private'))
    monkeypatch.setattr(settings, 'required_professional_documents', 'identity_document,diploma')
    monkeypatch.setattr(settings, 'redis_url', '')
    headers, ids, users = {}, {}, {}
    session = contextmanager(app.dependency_overrides[get_db])
    with session() as db:
        digest = password_hash('Password123!')
        for name, role in [('patient', 1), ('psy', 2), ('other', 2), ('admin', 3)]:
            user = User(fullname=name, email=f'{name}@example.com', country='Cameroun', city='Douala',
                        role_id=role, password_hash=digest, email_verified=True)
            db.add(user)
            db.flush()
            users[name] = user.id
            if role == 2:
                profile = PsychologistProfile(user_id=user.id, professional_title='Psychologue clinicien',
                                              specialty='Psychologie clinique', years_of_experience=5,
                                              professional_registration_number='ORDRE-12345',
                                              bio='Accompagnement des adultes et adolescents.',
                                              languages=['Français', 'Anglais'],
                                              consultation_modes=['online', 'in_person'])
                db.add(profile)
                db.flush()
                ids[name] = profile.id
            tokens, _ = logic.issue_tokens(db, user)
            headers[name] = {'Authorization': 'Bearer ' + tokens['access_token']}
        db.commit()
    return tc, headers, ids, session, tmp_path, delivered, users


def upload(tc, headers, kind='diploma', content=None, filename='diplome.pdf'):
    response = tc.post('/api/psychologists/me/documents', headers=headers,
                       files={'file': (filename, content if content is not None else pdf(), 'application/pdf')},
                       data={'document_type': kind})
    assert response.status_code == 201, response.text
    return response.json()['document']['id']


def submit_complete(system):
    tc, h, ids, *_ = system
    docs = [upload(tc, h['psy']), upload(tc, h['psy'], 'identity_document', png(), 'identite.png')]
    response = tc.post('/api/psychologists/me/submit-verification', headers=h['psy'])
    assert response.status_code == 200, response.text
    assert response.json()['verification_status'] == 'documents_submitted'
    return docs


def approve(system):
    tc, h, ids, *_ = system
    docs = submit_complete(system)
    for doc in docs:
        assert tc.post(f'/api/admin/psychologists/{ids["psy"]}/documents/{doc}/approve',
                       headers=h['admin']).status_code == 200
    assert tc.post(f'/api/admin/psychologists/{ids["psy"]}/approve', headers=h['admin']).status_code == 200
    return docs


def test_psychologist_registration_and_email_flow(client):
    tc, delivered = client
    body = {'fullname': 'Marie Nkom', 'email': 'marie@example.com', 'password': 'Password123!',
            'password_confirmation': 'Password123!', 'country': 'Cameroun', 'city': 'Douala',
            'professional_title': 'Psychologue clinicienne', 'specialty': 'Psychologie clinique',
            'years_of_experience': 5, 'bio': 'Accompagnement des adultes et adolescents.',
            'languages': ['Français'], 'consultation_modes': ['online']}
    invalid = tc.post('/api/auth/register/psychologist', json={**body, 'password_confirmation': 'Different123!'})
    assert invalid.status_code == 422
    assert 'Password123!' not in invalid.text
    assert tc.post('/api/auth/register/psychologist', json={**body, 'verification_status': 'approved'}).status_code == 422
    response = tc.post('/api/auth/register/psychologist', json=body)
    assert response.status_code == 201, response.text
    profile_id = response.json()['psychologist_id']
    assert response.json()['verification_status'] == 'pending_documents'
    assert response.json()['role'] == 'psychologist'
    assert tc.post('/api/auth/login', json={'email': body['email'], 'password': body['password']}).status_code == 403
    assert tc.get(f'/api/psychologists/{profile_id}').status_code == 404
    assert tc.post('/api/auth/verify-email', json={'email': body['email'], 'code': delivered[-1][1]}).status_code == 200
    login = tc.post('/api/auth/login', json={'email': body['email'], 'password': body['password']})
    result = tc.post('/api/auth/verify-login-otp', json={
        'challenge_id': login.json()['challenge_id'], 'code': delivered[-1][1]})
    headers = {'Authorization': 'Bearer ' + result.json()['access_token']}
    assert tc.get('/api/users/me', headers=headers).json()['role'] == 'psychologist'
    assert tc.get('/api/psychologists/me', headers=headers).json()['id'] == profile_id
    assert tc.post('/api/auth/register/psychologist', json=body).status_code == 409


def test_user_profile_ownership_and_protected_fields(system):
    tc, h, *_ = system
    assert tc.get('/api/users/me').status_code == 401
    assert tc.put('/api/users/me', headers=h['patient'], json={'fullname': 'Jean Dupont', 'city': 'Yaoundé'}).status_code == 200
    me = tc.get('/api/users/me', headers=h['patient']).json()
    assert me['city'] == 'Yaoundé'
    assert 'password_hash' not in me
    assert tc.get('/api/users/me', headers=h['psy']).json()['city'] == 'Douala'
    for body in ({'email': 'new@example.com'}, {'role_id': 3}, {'is_active': True}, {'fullname': None}):
        assert tc.put('/api/users/me', headers=h['patient'], json=body).status_code == 422
    assert tc.put('/api/users/me', headers=h['patient'], json={'phone': None}).status_code == 200


def test_avatar_real_content_replacement_and_deletion(system):
    tc, h, _, _, root, *_ = system
    response = tc.post('/api/users/me/avatar', headers=h['patient'],
                       files={'file': ('../../fake.exe', png(), 'application/octet-stream')})
    assert response.status_code == 200, response.text
    url = response.json()['avatar_url']
    image = tc.get(url)
    assert image.status_code == 200 and image.headers['content-type'] == 'image/webp'
    assert Image.open(BytesIO(image.content)).format == 'WEBP'
    assert tc.get('/api/users/me', headers=h['patient']).json()['avatar_url'] == url
    assert len(list((root / 'media' / 'avatars').glob('*'))) == 1
    response = tc.post('/api/users/me/avatar', headers=h['patient'], files={'file': ('new.png', png())})
    assert response.status_code == 200
    assert tc.get(url).status_code == 404
    assert len(list((root / 'media' / 'avatars').glob('*'))) == 1
    assert tc.delete('/api/users/me/avatar', headers=h['patient']).status_code == 200
    assert not list((root / 'media' / 'avatars').glob('*'))


def test_upload_validation_and_size_limits(system, monkeypatch):
    tc, h, *_ = system
    for route in ('/api/users/me/avatar', '/api/psychologists/me/documents'):
        response = tc.post(route, headers=h['psy'], files={'file': ('fake.png', b'<script>alert(1)</script>', 'image/png')},
                           data={'document_type': 'diploma'})
        assert response.status_code == 415
    assert tc.post('/api/psychologists/me/documents', headers=h['psy'],
                   files={'file': ('fake.pdf', b'%PDF-this-is-not-a-PDF')},
                   data={'document_type': 'diploma'}).status_code == 400
    monkeypatch.setattr(get_settings(), 'document_max_bytes', 20)
    monkeypatch.setattr(get_settings(), 'avatar_max_bytes', 20)
    assert tc.post('/api/psychologists/me/documents', headers=h['psy'],
                   files={'file': ('large.pdf', pdf())}, data={'document_type': 'diploma'}).status_code == 413
    assert tc.post('/api/users/me/avatar', headers=h['psy'], files={'file': ('large.png', png())}).status_code == 413
    assert tc.post('/api/users/me/avatar', headers=h['psy'], files={'file': ('empty.png', b'')}).status_code == 400


def test_document_privacy_and_admin_download_audit(system):
    tc, h, ids, session, root, *_ = system
    doc = upload(tc, h['psy'], filename='../../secret.pdf')
    listing = tc.get('/api/psychologists/me/documents', headers=h['psy'])
    assert listing.json()['items'][0]['file_name'] == 'secret.pdf'
    assert 'storage_path' not in listing.text and str(root) not in listing.text
    assert tc.get('/api/psychologists/me/documents', headers=h['other']).json()['items'] == []
    assert tc.delete(f'/api/psychologists/me/documents/{doc}', headers=h['other']).status_code == 404
    path = f'/api/admin/psychologists/{ids["psy"]}/documents/{doc}'
    assert tc.get(path).status_code == 401
    assert tc.get(path, headers=h['psy']).status_code == 403
    assert tc.get(f'/api/admin/psychologists/{ids["other"]}/documents/{doc}', headers=h['admin']).status_code == 404
    response = tc.get(path, headers=h['admin'])
    assert response.status_code == 200 and response.content.startswith(b'%PDF-')
    assert response.headers['cache-control'] == 'private, no-store'
    assert response.headers['content-disposition'].startswith('attachment')
    assert tc.get('/media/private/' + doc).status_code == 404
    with session() as db:
        assert db.scalar(select(PsychologistVerificationLog).where(
            PsychologistVerificationLog.action == 'DOCUMENT_ACCESSED')).admin_id is not None


def test_submission_requires_documents_and_locks_changes(system):
    tc, h, ids, *_ = system
    response = tc.post('/api/psychologists/me/submit-verification', headers=h['psy'])
    assert response.status_code == 400
    assert set(response.json()['detail']['missing_documents']) == {'identity_document', 'diploma'}
    docs = submit_complete(system)
    assert tc.post('/api/psychologists/me/submit-verification', headers=h['psy']).status_code == 409
    assert tc.put('/api/psychologists/me', headers=h['psy'], json={'years_of_experience': 6}).status_code == 409
    assert tc.delete(f'/api/psychologists/me/documents/{docs[0]}', headers=h['psy']).status_code == 409
    assert tc.post('/api/psychologists/me/documents', headers=h['psy'], files={'file': ('new.pdf', pdf())},
                   data={'document_type': 'other'}).status_code == 409
    queue = tc.get('/api/admin/psychologists/verifications', headers=h['admin'],
                   params={'status': 'documents_submitted', 'country': 'Cameroun', 'city': 'Douala'})
    assert queue.json()['total'] == 1
    assert queue.json()['items'][0]['psychologist_id'] == ids['psy']
    assert tc.get('/api/psychologists').json()['total'] == 0


def test_approval_publication_suspend_reactivate_and_history(system):
    tc, h, ids, session, *_ = system
    docs = submit_complete(system)
    base = f'/api/admin/psychologists/{ids["psy"]}'
    assert tc.post(base + '/approve', headers=h['psy']).status_code == 403
    assert tc.post(base + '/approve', headers=h['admin']).status_code == 400
    for doc in docs:
        assert tc.post(base + f'/documents/{doc}/approve', headers=h['admin']).status_code == 200
    assert tc.get('/api/psychologists/me/verification-status', headers=h['psy']).json()['verification_status'] == 'under_review'
    assert tc.post(base + '/approve', headers=h['admin']).status_code == 200
    assert tc.post(base + '/approve', headers=h['admin']).status_code == 409
    assert tc.get('/api/psychologists').json()['total'] == 1
    detail = tc.get(f'/api/psychologists/{ids["psy"]}')
    assert detail.status_code == 200
    for field in ('email', 'phone', 'documents', 'rejection_reason', 'professional_registration_number'):
        assert field not in detail.json()
    with session() as db:
        assert can_receive_appointments(db, ids['psy'])
    assert tc.delete(f'/api/psychologists/me/documents/{docs[0]}', headers=h['psy']).status_code == 409
    assert tc.post(base + '/suspend', headers=h['admin'], json={'reason': ' '}).status_code == 422
    assert tc.post(base + '/suspend', headers=h['admin'], json={'reason': 'Contrôle administratif'}).status_code == 200
    assert tc.get('/api/psychologists').json()['total'] == 0
    assert tc.get(f'/api/psychologists/{ids["psy"]}').status_code == 404
    with session() as db:
        assert not can_receive_appointments(db, ids['psy'])
    assert tc.post(base + '/reactivate', headers=h['admin']).status_code == 200
    assert tc.get('/api/psychologists').json()['total'] == 1
    history = tc.get(base + '/verification', headers=h['admin']).json()['history']
    actions = {item['action'] for item in history}
    assert {'REVIEW_STARTED', 'PROFILE_APPROVED', 'PROFILE_SUSPENDED', 'PROFILE_REACTIVATED'} <= actions
    suspension, = [item for item in history if item['action'] == 'PROFILE_SUSPENDED']
    assert suspension['reason'] == 'Contrôle administratif' and suspension['admin_id']


def test_rejected_document_replacement_and_resubmission(system):
    tc, h, ids, *_ = system
    docs = submit_complete(system)
    base = f'/api/admin/psychologists/{ids["psy"]}'
    assert tc.post(base + f'/documents/{docs[0]}/reject', headers=h['admin'], json={}).status_code == 422
    assert tc.post(base + f'/documents/{docs[0]}/reject', headers=h['admin'],
                   json={'reason': 'Document illisible'}).status_code == 200
    assert tc.post(base + '/reject', headers=h['admin'], json={'reason': 'Diplôme à remplacer'}).status_code == 200
    assert tc.get('/api/psychologists').json()['total'] == 0
    assert tc.post('/api/psychologists/me/submit-verification', headers=h['psy']).status_code == 400
    assert tc.delete(f'/api/psychologists/me/documents/{docs[0]}', headers=h['psy']).status_code == 200
    upload(tc, h['psy'])
    assert tc.post('/api/psychologists/me/submit-verification', headers=h['psy']).status_code == 200


def test_important_change_requires_new_verification(system):
    tc, h, ids, *_ = system
    approve(system)
    assert tc.put('/api/psychologists/me', headers=h['psy'], json={'bio': 'Une nouvelle présentation professionnelle.'}).status_code == 200
    assert tc.get('/api/psychologists').json()['total'] == 1
    response = tc.put('/api/psychologists/me', headers=h['psy'], json={'specialty': 'Psychologie du travail'})
    assert response.json()['profile']['verification_status'] == 'pending_documents'
    assert tc.get('/api/psychologists').json()['total'] == 0
    assert all(item['status'] == 'pending' for item in tc.get('/api/psychologists/me/documents', headers=h['psy']).json()['items'])
    history = tc.get(f'/api/admin/psychologists/{ids["psy"]}/verification', headers=h['admin']).json()['history']
    change, = [item for item in history if item['changes'] and 'specialty' in item['changes']]
    assert change['changes']['specialty']['before'] == 'Psychologie clinique'
    assert change['new_status'] == 'pending_documents'


def test_directory_filters_pagination_and_account_visibility(system):
    tc, h, ids, session, _, _, users = system
    approve(system)
    filters = {'country': 'Cameroun', 'city': 'Douala', 'specialty': 'Psychologie clinique',
               'language': 'Français', 'consultation_mode': 'online', 'sort': 'experience'}
    assert tc.get('/api/psychologists', params=filters).json()['total'] == 1
    assert tc.get('/api/psychologists', params={'language': 'Fran'}).json()['total'] == 0
    assert tc.get('/api/psychologists', params={'language': 'Espagnol'}).json()['total'] == 0
    assert tc.get('/api/psychologists', params={'language': '%'}).json()['total'] == 0
    assert tc.get('/api/psychologists', params={'language': 'Fran_ais'}).json()['total'] == 0
    assert tc.get('/api/psychologists', params={'page': 2, 'page_size': 1}).json()['items'] == []
    for params in ({'page': 0}, {'page_size': 101}, {'sort': 'unknown'}, {'consultation_mode': 'anything'}):
        assert tc.get('/api/psychologists', params=params).status_code == 422
    for field in ('is_active', 'email_verified'):
        with session() as db:
            setattr(db.get(User, users['psy']), field, False)
            db.commit()
        assert tc.get('/api/psychologists').json()['total'] == 0
        with session() as db:
            setattr(db.get(User, users['psy']), field, True)
            db.commit()


def test_reactivation_checks_conditions_and_suspended_edits(system):
    tc, h, ids, session, _, _, users = system
    approve(system)
    base = f'/api/admin/psychologists/{ids["psy"]}'
    assert tc.post(base + '/suspend', headers=h['admin'], json={'reason': 'Contrôle'}).status_code == 200
    assert tc.put('/api/psychologists/me', headers=h['psy'], json={'years_of_experience': 6}).status_code == 409
    with session() as db:
        db.get(User, users['psy']).email_verified = False
        db.commit()
    assert tc.post(base + '/reactivate', headers=h['admin']).status_code == 400
    assert tc.get('/api/psychologists').json()['total'] == 0


def test_role_permissions_and_status_injection(system):
    tc, h, ids, *_ = system
    assert tc.get('/api/psychologists/me', headers=h['patient']).status_code == 403
    assert tc.get('/api/psychologists/me/documents', headers=h['admin']).status_code == 403
    assert tc.get('/api/admin/psychologists/verifications', headers=h['psy']).status_code == 403
    assert tc.get(f'/api/admin/psychologists/{ids["psy"]}/verification', headers=h['patient']).status_code == 403
    assert tc.put('/api/psychologists/me', headers=h['psy'], json={'verification_status': 'approved'}).status_code == 422
    assert tc.put('/api/psychologists/me', headers=h['psy'], json={'user_id': 'other'}).status_code == 422
    assert tc.put('/api/psychologists/me', headers=h['psy'], json={'years_of_experience': None}).status_code == 422
    assert tc.get('/api/admin/psychologists/verifications', headers=h['admin'], params={
        'submitted_from': '2026-11-10T00:00:00Z', 'submitted_to': '2026-11-01T00:00:00Z'}).status_code == 422


def test_storage_failure_does_not_save_document(system, monkeypatch):
    from app.modules.psychologists import storage

    tc, h, *_ = system
    def denied(*args, **kwargs):
        raise PermissionError('Storage not writable')
    monkeypatch.setattr(storage.os, 'open', denied)
    response = tc.post('/api/psychologists/me/documents', headers=h['psy'],
                       files={'file': ('diplome.pdf', pdf())}, data={'document_type': 'diploma'})
    assert response.status_code == 503
    assert response.json()['detail']['code'] == 'FILE_STORAGE_UNAVAILABLE'
    assert tc.get('/api/psychologists/me/documents', headers=h['psy']).json()['items'] == []
