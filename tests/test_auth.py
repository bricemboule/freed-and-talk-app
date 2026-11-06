import pytest
import os
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, event
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool
from sqlalchemy.engine import make_url
from app.main import app
from app.core.database import Base, get_db
from app.modules.auth.models.entities import Role
from app.modules.auth.services import logic
from app.core.config import get_settings

@pytest.fixture
def client(monkeypatch):
    test_url = os.environ.get('TEST_DATABASE_URL')
    if test_url:
        if not (make_url(test_url).database or '').startswith('free_and_talk_test_'):
            raise RuntimeError('TEST_DATABASE_URL must target an isolated free_and_talk_test_* database')
        engine = create_engine(test_url)
    else:
        engine=create_engine('sqlite://',connect_args={'check_same_thread':False},poolclass=StaticPool)
        @event.listens_for(engine, 'connect')
        def sqlite_foreign_keys(connection, record):
            connection.execute('PRAGMA foreign_keys=ON')
    Base.metadata.create_all(engine)
    Session=sessionmaker(bind=engine,expire_on_commit=False)
    with Session() as db:
        db.add_all([Role(id=1,code='patient',name='Patient'),Role(id=2,code='psychologist',name='Psychologue'),Role(id=3,code='admin',name='Administrateur')])
        db.commit()
    delivered=[]
    monkeypatch.setattr(logic,'email_code',lambda to,code,purpose:delivered.append((to,code,purpose)))
    def override():
        with Session() as db:yield db
    app.dependency_overrides[get_db]=override
    with TestClient(app) as tc:
        yield tc,delivered
    app.dependency_overrides.clear()
    if test_url:
        Base.metadata.drop_all(engine)
    engine.dispose()

def signup(tc, delivered):
    r=tc.post('/api/auth/register',json={'fullname':'Jean Dupont','email':'jean@example.com',
        'phone':'+237600000000','password':'a-very-secure-password-2026'})
    assert r.status_code==201,r.text
    code=delivered[-1][1]
    r=tc.post('/api/auth/verify-email',json={'email':'jean@example.com','code':code})
    assert r.status_code==200,r.text

def login(tc,delivered):
    r=tc.post('/api/auth/login',json={'email':'jean@example.com','password':'a-very-secure-password-2026'})
    assert r.status_code==200,r.text
    challenge=r.json()['challenge_id']
    assert 'access_token' not in r.json()
    r=tc.post('/api/auth/verify-login-otp',json={'challenge_id':challenge,'code':delivered[-1][1]})
    assert r.status_code==200,r.text
    assert tc.post('/api/auth/verify-login-otp',json={'challenge_id':challenge,'code':delivered[-1][1]}).status_code==400
    return r.json()

def test_signup_login_refresh_logout(client):
    tc,delivered=client
    signup(tc,delivered)
    assert tc.post('/api/auth/register',json={'fullname':'Jean Dupont','email':'jean@example.com','password':'a-very-secure-password-2026'}).status_code==409
    tokens=login(tc,delivered)
    h={'Authorization':'Bearer '+tokens['access_token']}
    assert tc.get('/api/auth/me',headers=h).json()['role']['code']=='patient'
    r=tc.post('/api/auth/refresh',json={'refresh_token':tokens['refresh_token']})
    assert r.status_code==200,r.text
    tokens2=r.json()
    assert tokens2['refresh_token']!=tokens['refresh_token']
    assert tc.post('/api/auth/refresh',json={'refresh_token':tokens['refresh_token']}).status_code==401
    # replay revokes the whole session
    assert tc.post('/api/auth/refresh',json={'refresh_token':tokens2['refresh_token']}).status_code==401
    assert tc.get('/api/auth/me',headers=h).status_code==401

def test_password_reset(client):
    tc,delivered=client
    signup(tc,delivered)
    assert tc.post('/api/auth/forgot-password',json={'email':'unknown@example.com'}).status_code==200
    assert tc.post('/api/auth/forgot-password',json={'email':'jean@example.com'}).status_code==200
    code=delivered[-1][1]
    assert tc.post('/api/auth/verify-reset-code',json={'email':'jean@example.com','code':'000000' if code!='000000' else '999999'}).status_code==400
    r=tc.post('/api/auth/verify-reset-code',json={'email':'jean@example.com','code':code})
    assert r.status_code==200,r.text
    token=r.json()['reset_token']
    assert tc.post('/api/auth/reset-password',json={'reset_token':token,'new_password':'new-very-secure-password'}).status_code==200
    assert tc.post('/api/auth/reset-password',json={'reset_token':token,'new_password':'another-secure-password'}).status_code==400
    assert tc.post('/api/auth/login',json={'email':'jean@example.com','password':'a-very-secure-password-2026'}).status_code==401
    assert tc.post('/api/auth/login',json={'email':'jean@example.com','password':'new-very-secure-password'}).status_code==200

def test_change_password_and_authz(client):
    tc,delivered=client
    signup(tc,delivered)
    tokens=login(tc,delivered)
    h={'Authorization':'Bearer '+tokens['access_token']}
    assert tc.get('/api/auth/me').status_code==401
    assert tc.put('/api/users/me/password',headers=h,json={'current_password':'wrong','new_password':'another-long-password'}).status_code==401
    assert tc.put('/api/users/me/password',headers=h,json={'current_password':'a-very-secure-password-2026','new_password':'another-long-password'}).status_code==200
    assert tc.get('/api/auth/me',headers=h).status_code==401

def test_logout_and_user_access(client):
    tc, delivered=client
    signup(tc,delivered)
    tokens=login(tc,delivered)
    assert tc.post('/api/auth/logout',json={'refresh_token':tokens['refresh_token']}).status_code==200
    assert tc.post('/api/auth/refresh',json={'refresh_token':tokens['refresh_token']}).status_code==401
    assert tc.get('/api/auth/me',headers={'Authorization':'Bearer '+tokens['access_token']}).status_code==401

def test_invalid_register_and_login(client):
    tc,delivered=client
    response=tc.post('/api/auth/register',json={'fullname':'A','email':'wrong','password':'short','role':'admin'})
    assert response.status_code==422
    assert tc.post('/api/auth/login',json={'email':'unknown@example.com','password':'wrong'}).status_code==401
    signup(tc,delivered)
    assert tc.post('/api/auth/verify-email',json={'email':'jean@example.com','code':delivered[0][1]}).status_code==400


def test_resend_expired_email_code(client):
    from contextlib import contextmanager
    from datetime import timedelta
    from app.modules.auth.models.entities import OTP, now
    from app.core.database import get_db
    from sqlalchemy import select

    tc, delivered = client
    body = {'fullname': 'Jean Dupont', 'email': 'jean@example.com',
            'password': 'a-very-secure-password-2026'}
    assert tc.post('/api/auth/register', json=body).status_code == 201
    with contextmanager(app.dependency_overrides[get_db])() as db:
        otp = db.scalar(select(OTP))
        otp.expires_at = now() - timedelta(minutes=1)
        otp.last_sent_at = now() - timedelta(minutes=20)
        db.commit()
    assert tc.post('/api/auth/resend-email-code', json={'email': body['email']}).status_code == 200
    assert len(delivered) == 2
    assert tc.post('/api/auth/verify-email', json={
        'email': body['email'], 'code': delivered[-1][1]}).status_code == 200


def test_blank_fullname_is_rejected(client):
    tc, _ = client
    assert tc.post('/api/auth/register', json={'fullname': '   ',
        'email': 'jean@example.com', 'password': 'a-very-secure-password-2026'}).status_code == 422


def test_validation_identifies_fields_without_exposing_input(client):
    tc, _ = client
    password = 'secret7'
    response = tc.post('/api/auth/register', json={
        'fullname': 'Jean Dupont', 'email': 'invalid-email',
        'password': password, 'phone': '600000000',
    })
    assert response.status_code == 422
    error = response.json()['error']
    assert error['code'] == 'VALIDATION_ERROR'
    details = {item['field']: item for item in error['details']}
    assert set(details) == {'body.email', 'body.password', 'body.phone'}
    assert '8' in details['body.password']['message']
    assert password not in response.text
    assert 'invalid-email' not in response.text
    assert all(set(item) == {'field', 'code', 'message'} for item in error['details'])


def test_register_accepts_eight_character_password(client):
    tc, delivered = client
    body = {'fullname': 'Jean Dupont', 'email': 'jean@example.com', 'password': 'Abcd123'}
    assert tc.post('/api/auth/register', json=body).status_code == 422
    body['password'] = 'Abcd1234'
    assert tc.post('/api/auth/register', json=body).status_code == 201
    assert tc.post('/api/auth/verify-email', json={
        'email': body['email'], 'code': delivered[-1][1]}).status_code == 200
    assert tc.post('/api/auth/login', json={
        'email': body['email'], 'password': body['password']}).status_code == 200
