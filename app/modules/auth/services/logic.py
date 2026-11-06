from datetime import timedelta, timezone
from sqlalchemy import select, update
from sqlalchemy.orm import Session
from fastapi import HTTPException
from app.core.config import get_settings
from app.core.security import (otp_code, random_token, hash_otp, otp_matches, hash_secret,
    access_token, password_hash, verify_password)
from app.modules.auth.models.entities import (now, User, Role, OTP, AuthSession, RefreshToken,
    PasswordResetToken, SecurityEvent)
import smtplib
import ssl
import os
from pathlib import Path
from email.message import EmailMessage


def utc(dt):
    return dt.replace(tzinfo=timezone.utc) if dt is not None and dt.tzinfo is None else dt

def fail(status: int, code: str):
    raise HTTPException(status, detail={'code': code, 'message': code.replace('_', ' ').capitalize()})

def event(db: Session, user_id: str | None, name: str):
    db.add(SecurityEvent(user_id=user_id, event_type=name))

def normalize(email: str):
    return email.strip().lower()

def get_user(db: Session, email: str):
    return db.scalar(select(User).where(User.email == normalize(email)))

def email_code(to: str, code: str, purpose: str):
    email_message(to, f'Votre code FREE & TALK : {code}. Ne le partagez avec personne.')


def email_message(to: str, body: str):
    """Transport partagé entre les OTP et les notifications transactionnelles."""
    settings = get_settings()
    msg = EmailMessage()
    msg['Subject'] = 'FREE & TALK'
    msg['From'] = settings.smtp_from_email
    msg['To'] = to
    msg.set_content(body)
    if settings.email_backend == 'file' and settings.app_env != 'production':
        directory = Path(settings.mail_directory)
        directory.mkdir(parents=True, exist_ok=True, mode=0o700)
        path = directory / f'{random_token()}.eml'
        fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(fd, 'w', encoding='utf-8') as mail:
            mail.write(msg.as_string())
        return
    if not settings.smtp_host:
        raise RuntimeError('SMTP required for email delivery')
    # Le port 465 chiffre la connexion dès son ouverture, sans STARTTLS.
    tls_context = ssl.create_default_context()
    if settings.smtp_ssl:
        transport = smtplib.SMTP_SSL(
            settings.smtp_host, settings.smtp_port, timeout=10, context=tls_context,
        )
    else:
        transport = smtplib.SMTP(settings.smtp_host, settings.smtp_port, timeout=10)
    with transport as client:
        if settings.smtp_starttls and not settings.smtp_ssl:
            client.starttls(context=tls_context)
        if settings.smtp_username:
            client.login(settings.smtp_username, settings.smtp_password)
        client.send_message(msg)


def create_otp(db: Session, user: User, purpose: str, *, challenge: str | None = None):
    s = get_settings()
    minutes = {'email_verification': s.otp_email_minutes, 'login': s.otp_login_minutes,
               'password_reset': s.otp_reset_minutes}[purpose]
    code = otp_code()
    challenge = challenge or random_token()
    otp = OTP(user_id=user.id, type=purpose, challenge_id=challenge,
              code_hash=hash_otp(code, challenge), expires_at=now()+timedelta(minutes=minutes),
              attempts=0, resend_count=0, last_sent_at=now())
    db.add(otp)
    db.flush()
    return otp, code, minutes*60

def otp_valid(db: Session, challenge: str, purpose: str, code: str):
    # MySQL/InnoDB and PostgreSQL serialize competing validations with a row lock.
    # SQLite does not support SELECT FOR UPDATE.
    otp = db.scalar(select(OTP).where(OTP.challenge_id == challenge, OTP.type == purpose).with_for_update())
    if not otp:
        fail(400, 'OTP_INVALID')
    if otp.used_at or otp.invalidated_at:
        fail(400, 'OTP_ALREADY_USED')
    if utc(otp.expires_at) <= now():
        fail(400, 'OTP_EXPIRED')
    if otp.attempts >= get_settings().otp_max_attempts:
        fail(429, 'OTP_ATTEMPTS_EXCEEDED')
    if not otp_matches(code, otp.challenge_id, otp.code_hash):
        otp.attempts += 1
        db.commit()  # attempt counter must survive an HTTP exception
        fail(400, 'OTP_INVALID')
    otp.used_at = now()
    db.flush()
    return otp

def issue_tokens(db: Session, user: User, session: AuthSession | None = None):
    s=get_settings()
    if session is None:
        session = AuthSession(user_id=user.id, expires_at=now()+timedelta(days=s.refresh_days))
        db.add(session)
        db.flush()
    raw=random_token()
    record=RefreshToken(user_id=user.id, session_id=session.id, token_hash=hash_secret(raw),
                        expires_at=now()+timedelta(days=s.refresh_days))
    db.add(record)
    db.flush()
    return {'access_token': access_token(user.id, session.id), 'refresh_token':raw,
            'token_type':'bearer','expires_in':s.access_minutes*60}, record

def revoke_all(db:Session, user_id:str):
    ids=select(AuthSession.id).where(AuthSession.user_id==user_id)
    db.execute(update(AuthSession).where(AuthSession.user_id==user_id,AuthSession.revoked_at.is_(None)).values(revoked_at=now()))
    db.execute(update(RefreshToken).where(RefreshToken.session_id.in_(ids),RefreshToken.revoked_at.is_(None)).values(revoked_at=now()))

def active_user(db:Session, user_id:str):
    user=db.get(User,user_id)
    if not user or not user.is_active or not user.role.is_active:
        fail(403,'ACCOUNT_DISABLED')
    if not user.email_verified:
        fail(403,'EMAIL_NOT_VERIFIED')
    return user

def refresh_session(db:Session, raw:str):
    token=db.scalar(select(RefreshToken).where(RefreshToken.token_hash==hash_secret(raw)).with_for_update())
    if token is None:
        fail(401,'INVALID_REFRESH_TOKEN')
    session=db.scalar(select(AuthSession).where(AuthSession.id==token.session_id).with_for_update())
    if token.revoked_at is not None:
        # Reuse of a rotated token indicates possible compromise. Revoke entire session.
        if token.replaced_by_token_id and session and session.revoked_at is None:
            session.revoked_at=now()
            db.execute(update(RefreshToken).where(RefreshToken.session_id==session.id,
                RefreshToken.revoked_at.is_(None)).values(revoked_at=now()))
            event(db,token.user_id,'REFRESH_TOKEN_REUSED')
            db.commit()
        fail(401,'INVALID_REFRESH_TOKEN')
    if utc(token.expires_at)<=now() or not session or session.revoked_at or utc(session.expires_at)<=now():
        fail(401,'INVALID_REFRESH_TOKEN')
    user=active_user(db, token.user_id)
    token.revoked_at=now()
    token.last_used_at=now()
    session.last_activity_at=now()
    result,new=issue_tokens(db,user,session)
    token.replaced_by_token_id=new.id
    event(db,user.id,'TOKEN_REFRESHED')
    db.commit()
    return result

def send_otp(db, user, purpose, *, challenge=None):
    otp, code, ttl=create_otp(db,user,purpose,challenge=challenge)
    db.commit()
    # A persisted request can be retried when email provider is unavailable.
    # For high-reliability production deployment, use transactional outbox + worker.
    try:
        email_code(user.email,code,purpose)
    except Exception:
        fail(503,'EMAIL_SERVICE_UNAVAILABLE')
    return otp, ttl

def invalidate_other_otps(db, user_id, purpose):
    db.execute(update(OTP).where(OTP.user_id==user_id,OTP.type==purpose,
        OTP.used_at.is_(None),OTP.invalidated_at.is_(None)).values(invalidated_at=now()))

def resend_otp(db, otp:OTP, purpose):
    s=get_settings()
    if otp.used_at or otp.invalidated_at:
        fail(400,'OTP_EXPIRED')
    if (now()-utc(otp.last_sent_at)).total_seconds()<s.otp_resend_seconds:
        fail(429,'RATE_LIMIT_EXCEEDED')
    if otp.resend_count>=s.otp_max_resends_per_hour:
        fail(429,'RATE_LIMIT_EXCEEDED')
    new_code=otp_code()
    otp.code_hash=hash_otp(new_code,otp.challenge_id)
    otp.last_sent_at=now()
    otp.resend_count+=1
    otp.attempts=0
    minutes={'login':s.otp_login_minutes,'email_verification':s.otp_email_minutes}[purpose]
    otp.expires_at=now()+timedelta(minutes=minutes)
    db.commit()
    try:
        user=db.get(User,otp.user_id)
        email_code(user.email,new_code,purpose)
    except Exception:
        fail(503,'EMAIL_SERVICE_UNAVAILABLE')
    return minutes*60
