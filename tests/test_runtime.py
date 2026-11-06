import os
from email import policy
from email.parser import BytesParser
from pathlib import Path
import subprocess
import sys

import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError
from sqlalchemy import create_engine, inspect, text

from app.core.config import Settings
from app.main import app
from app.modules.auth.services import logic


def test_health_and_documentation():
    with TestClient(app) as client:
        assert client.get('/health').json() == {'status': 'ok'}
        assert client.get('/', follow_redirects=False).headers['location'] == '/docs'
        assert client.get('/docs').status_code == 200
        assert '/api/auth/register' in client.get('/openapi.json').json()['paths']


def test_local_mail_delivery(tmp_path, monkeypatch):
    settings = Settings(_env_file=None, email_backend='file', mail_directory=str(tmp_path / 'mail'))
    monkeypatch.setattr(logic, 'get_settings', lambda: settings)
    logic.email_code('jean@example.com', '123456', 'email_verification')
    mail_path, = (tmp_path / 'mail').glob('*.eml')
    message = BytesParser(policy=policy.default).parsebytes(mail_path.read_bytes())
    assert message['To'] == 'jean@example.com'
    assert '123456' in message.get_content()
    assert mail_path.stat().st_mode & 0o777 == 0o600


def test_smtp_without_host_fails(monkeypatch):
    settings = Settings(_env_file=None, email_backend='smtp', smtp_host='')
    monkeypatch.setattr(logic, 'get_settings', lambda: settings)
    with pytest.raises(RuntimeError, match='SMTP required'):
        logic.email_code('jean@example.com', '123456', 'login')


@pytest.mark.parametrize('use_ssl, starttls, port', [
    (True, False, 465), (True, True, 465),
    (False, True, 587), (False, False, 1025),
])
def test_smtp_transport(monkeypatch, use_ssl, starttls, port):
    import ssl
    from unittest.mock import MagicMock

    settings = Settings(_env_file=None, email_backend='smtp', smtp_host='smtp.example.com',
                        smtp_port=port, smtp_ssl=use_ssl, smtp_starttls=starttls,
                        smtp_username='user', smtp_password='password')
    monkeypatch.setattr(logic, 'get_settings', lambda: settings)
    smtp = MagicMock()
    smtp_ssl = MagicMock()
    monkeypatch.setattr(logic.smtplib, 'SMTP', smtp)
    monkeypatch.setattr(logic.smtplib, 'SMTP_SSL', smtp_ssl)

    logic.email_code('jean@example.com', '123456', 'login')

    constructor = smtp_ssl if use_ssl else smtp
    (smtp if use_ssl else smtp_ssl).assert_not_called()
    assert constructor.call_args.args == ('smtp.example.com', port)
    if use_ssl:
        context = constructor.call_args.kwargs['context']
        assert context.check_hostname
        assert context.verify_mode == ssl.CERT_REQUIRED
    client = constructor.return_value.__enter__.return_value
    if starttls and not use_ssl:
        client.starttls.assert_called_once()
        assert client.starttls.call_args.kwargs['context'].check_hostname
    else:
        client.starttls.assert_not_called()
    client.login.assert_called_once_with('user', 'password')
    client.send_message.assert_called_once()


def test_production_rejects_file_delivery():
    with pytest.raises(ValidationError, match='SMTP and Redis'):
        Settings(_env_file=None, app_env='production', email_backend='file',
                 database_url='postgresql+psycopg://localhost/test',
                 jwt_secret_key='a' * 48, otp_secret_key='b' * 48,
                 smtp_host='localhost', redis_url='redis://localhost:6379')


def test_migrations_on_fresh_database(tmp_path):
    url = f'sqlite:///{tmp_path / "test.sqlite3"}'
    env = dict(os.environ, APP_ENV='development', DATABASE_URL=url)
    root = Path(__file__).resolve().parents[1]
    for _ in range(2):
        result = subprocess.run([sys.executable, '-m', 'alembic', 'upgrade', 'head'],
                                cwd=root, env=env, capture_output=True, text=True)
        assert result.returncode == 0, result.stderr
    engine = create_engine(url)
    with engine.connect() as connection:
        assert {'users', 'otp_codes', 'auth_sessions', 'psychologist_profiles',
                'psychologist_documents', 'psychologist_verification_logs', 'conversations',
                'conversation_participants', 'messages', 'message_attachments', 'notifications',
                'notification_preferences', 'notification_logs', 'realtime_events',
                'payments', 'payment_events'} <= set(inspect(connection).get_table_names())
        assert set(connection.execute(text('SELECT code FROM roles')).scalars()) == {
            'patient', 'psychologist', 'admin'}
    engine.dispose()


def test_production_accepts_mysql():
    settings = Settings(_env_file=None, app_env='production',
                        database_url='mysql+pymysql://user:password@localhost/free_and_talk?charset=utf8mb4',
                        jwt_secret_key='a' * 48, otp_secret_key='b' * 48,
                        email_backend='smtp', smtp_host='localhost',
                        redis_url='redis://localhost:6379')
    engine = create_engine(settings.database_url)
    assert engine.dialect.name == 'mysql'
    assert engine.dialect.driver == 'pymysql'
    engine.dispose()


def test_production_rejects_sqlite():
    with pytest.raises(ValidationError, match='Production requires MySQL'):
        Settings(_env_file=None, app_env='production', database_url='sqlite://',
                 jwt_secret_key='a' * 48, otp_secret_key='b' * 48,
                 email_backend='smtp', smtp_host='localhost', redis_url='redis://localhost:6379')


def test_mysql_migration_sql():
    env = dict(os.environ, APP_ENV='development',
               DATABASE_URL='mysql+pymysql://user:password@localhost/free_and_talk?charset=utf8mb4')
    result = subprocess.run([sys.executable, '-m', 'alembic', 'upgrade', 'head', '--sql'],
                            cwd=Path(__file__).resolve().parents[1], env=env,
                            capture_output=True, text=True)
    assert result.returncode == 0, result.stderr
    assert 'AUTO_INCREMENT' in result.stdout
    assert 'FOREIGN KEY(role_id) REFERENCES roles (id)' in result.stdout
    assert "'patient'" in result.stdout
    assert 'CREATE TABLE users' in result.stdout
    assert 'CREATE TABLE psychologist_profiles' in result.stdout
    assert 'CREATE TABLE psychologist_documents' in result.stdout
    assert 'CREATE TABLE conversations' in result.stdout
    assert 'CREATE TABLE notification_logs' in result.stdout


def test_upgrade_preserves_existing_users(tmp_path):
    url = f'sqlite:///{tmp_path / "existing.sqlite3"}'
    env = dict(os.environ, APP_ENV='development', DATABASE_URL=url)
    root = Path(__file__).resolve().parents[1]
    result = subprocess.run([sys.executable, '-m', 'alembic', 'upgrade', 'a409de1d7d59'],
                            cwd=root, env=env, capture_output=True, text=True)
    assert result.returncode == 0, result.stderr
    engine = create_engine(url)
    with engine.begin() as connection:
        connection.execute(text("INSERT INTO users (id, fullname, email, password_hash, role_id, "
                                "email_verified, is_active, created_at, updated_at) "
                                "VALUES ('existing-user', 'Jean Dupont', 'existing@example.com', 'hash', "
                                "1, 1, 1, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)"))
    result = subprocess.run([sys.executable, '-m', 'alembic', 'upgrade', 'head'],
                            cwd=root, env=env, capture_output=True, text=True)
    assert result.returncode == 0, result.stderr
    with engine.connect() as connection:
        row = connection.execute(text("SELECT email, country, city, avatar_path, date_of_birth "
                                      "FROM users WHERE id='existing-user'")).one()
        assert tuple(row) == ('existing@example.com', None, None, None, None)
    engine.dispose()


def test_postgresql_module3_migration_sql():
    env = dict(os.environ, APP_ENV='development',
               DATABASE_URL='postgresql+psycopg://user:password@localhost/free_and_talk_test')
    result = subprocess.run([sys.executable, '-m', 'alembic', 'upgrade', 'head', '--sql'],
                            cwd=Path(__file__).resolve().parents[1], env=env,
                            capture_output=True, text=True)
    assert result.returncode == 0, result.stderr
    assert 'CREATE TABLE appointments' in result.stdout
    assert 'uq_reservation_resource_minute' in result.stdout
    assert 'TIMESTAMP WITH TIME ZONE' in result.stdout
