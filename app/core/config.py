from functools import lru_cache
from typing import Literal
from pydantic_settings import BaseSettings, SettingsConfigDict
from pydantic import model_validator
from sqlalchemy.engine import make_url
from urllib.parse import urlsplit
from zoneinfo import ZoneInfo

class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file='.env', extra='ignore')
    app_env: str = 'development'
    database_url: str = 'sqlite:///./dev.sqlite3'
    jwt_secret_key: str = 'LOCAL_DEV_ONLY_CHANGE_ME_01234567890123456789'
    otp_secret_key: str = 'LOCAL_OTP_ONLY_CHANGE_ME_01234567890123456789'
    jwt_issuer: str = 'free-and-talk'
    jwt_audience: str = 'free-and-talk-api'
    access_minutes: int = 15
    refresh_days: int = 7
    otp_login_minutes: int = 5
    otp_email_minutes: int = 10
    otp_reset_minutes: int = 10
    otp_max_attempts: int = 5
    otp_resend_seconds: int = 60
    otp_max_resends_per_hour: int = 5
    reset_token_minutes: int = 10
    cors_origins: str = 'http://localhost:5173'
    smtp_host: str = ''
    email_backend: Literal['file', 'smtp'] = 'file'
    mail_directory: str = '.local/mail'
    smtp_port: int = 587
    smtp_username: str = ''
    smtp_password: str = ''
    smtp_from_email: str = 'noreply@example.com'
    smtp_ssl: bool = False
    smtp_starttls: bool = True
    redis_url: str = ''
    media_directory: str = '.local/media'
    private_documents_directory: str = '.local/private/documents'
    avatar_max_bytes: int = 5 * 1024 * 1024
    document_max_bytes: int = 5 * 1024 * 1024
    required_professional_documents: str = 'identity_document,diploma'
    appointment_timezone: str = 'Africa/Douala'
    consultation_default_minutes: int = 45
    consultation_allowed_minutes: str = '30,45,60'
    appointment_slot_step_minutes: int = 15
    appointment_max_advance_days: int = 180
    appointment_cancel_notice_minutes: int = 60
    consultation_early_join_minutes: int = 15
    consultation_access_grace_minutes: int = 15
    meeting_token_minutes: int = 5
    jitsi_base_url: str = ''
    jitsi_app_id: str = ''
    jitsi_jwt_secret: str = ''
    jitsi_jwt_subject: str = ''
    jitsi_jwt_audience: str = ''
    message_max_characters: int = 10000
    message_edit_minutes: int = 10
    message_rate_limit: int = 30
    message_attachment_max_bytes: int = 5 * 1024 * 1024
    private_message_directory: str = '.local/private/messages'
    websocket_poll_seconds: float = 1.0
    websocket_presence_seconds: int = 45
    appointment_reminder_minutes: int = 60
    resource_max_bytes: int = 25 * 1024 * 1024
    private_resource_directory: str = '.local/private/resources'

    @model_validator(mode='after')
    def production_safety(self):
        if not 1 <= self.message_max_characters <= 20000 or not 1 <= self.message_rate_limit <= 1000:
            raise ValueError('Invalid message limits')
        if self.message_edit_minutes < 0 or self.message_attachment_max_bytes <= 0:
            raise ValueError('Invalid message edit or attachment limits')
        if not .1 <= self.websocket_poll_seconds <= 5 or self.websocket_presence_seconds < 15 or self.appointment_reminder_minutes < 1:
            raise ValueError('Invalid realtime or reminder limits')
        try:
            ZoneInfo(self.appointment_timezone)
            durations = {int(value.strip()) for value in self.consultation_allowed_minutes.split(',')}
        except (ValueError, KeyError):
            raise ValueError('Invalid appointment timezone or durations')
        if not durations or min(durations) < 5 or max(durations) > 240 or self.consultation_default_minutes not in durations:
            raise ValueError('Consultation durations must be between 5 and 240 minutes')
        if not 1 <= self.appointment_slot_step_minutes <= 240 or not 1 <= self.appointment_max_advance_days <= 730:
            raise ValueError('Invalid appointment scheduling limits')
        if min(self.appointment_cancel_notice_minutes, self.consultation_early_join_minutes,
               self.consultation_access_grace_minutes) < 0 or not 1 <= self.meeting_token_minutes <= 15:
            raise ValueError('Invalid consultation access limits')
        if self.jitsi_base_url:
            url = urlsplit(self.jitsi_base_url)
            if url.scheme != 'https' or not url.hostname or url.username or url.password or url.query or url.fragment or url.path not in ('', '/'):
                raise ValueError('Jitsi requires an HTTPS server URL without credentials or path')
        if self.jitsi_jwt_secret and (len(self.jitsi_jwt_secret) < 32 or self.jitsi_jwt_secret in (self.jwt_secret_key, self.otp_secret_key)):
            raise ValueError('Jitsi requires a distinct secret of at least 32 characters')
        document_types = {'identity_document', 'diploma', 'professional_license',
                          'professional_registration', 'cv', 'other'}
        required = {item.strip() for item in self.required_professional_documents.split(',') if item.strip()}
        if not required or not required <= document_types:
            raise ValueError('Invalid required professional documents')
        if min(self.avatar_max_bytes, self.document_max_bytes, self.resource_max_bytes) <= 0:
            raise ValueError('Upload size limits must be positive')
        if self.app_env == 'production':
            if len(self.jwt_secret_key) < 32 or len(self.otp_secret_key) < 32:
                raise ValueError('Production requires strong secrets')
            if self.jwt_secret_key == self.otp_secret_key or 'CHANGE_ME' in self.jwt_secret_key or 'CHANGE_ME' in self.otp_secret_key:
                raise ValueError('Production requires distinct real secrets')
            if make_url(self.database_url).drivername not in ('mysql+pymysql', 'postgresql+psycopg'):
                raise ValueError('Production requires MySQL (mysql+pymysql) or PostgreSQL (postgresql+psycopg)')
            if self.email_backend != 'smtp' or not self.smtp_host or not self.redis_url:
                raise ValueError('Production requires SMTP and Redis')
        return self

@lru_cache
def get_settings() -> Settings:
    return Settings()
