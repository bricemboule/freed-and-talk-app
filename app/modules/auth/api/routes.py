from datetime import timedelta
from sqlalchemy import select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session
from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
import jwt
from app.core.database import get_db
from app.core.security import password_hash, verify_password, random_token, hash_secret, decode_access
from app.core.config import get_settings
from app.core.rate_limit import rate_limit
from app.modules.auth.models.entities import (User, Role, OTP, AuthSession, RefreshToken,PasswordResetToken,now)
from app.modules.auth.schemas.contracts import (RegisterRequest, EmailRequest, CodeEmailRequest, LoginRequest,
    CodeChallengeRequest,ChallengeRequest,RefreshRequest,ResetRequest,ChangePasswordRequest,TokenResponse)
from app.modules.auth.services import logic as s
from app.modules.communication.notifications import notify

router=APIRouter(prefix='/api/auth',tags=['Authentication'])
users_router=APIRouter(prefix='/api/users',tags=['Users'])
bearer=HTTPBearer(auto_error=False)

def current_user(credentials:HTTPAuthorizationCredentials|None=Depends(bearer),db:Session=Depends(get_db)):
    if not credentials or credentials.scheme.lower()!='bearer':
        s.fail(401,'INVALID_ACCESS_TOKEN')
    try:
        claims=decode_access(credentials.credentials)
    except jwt.PyJWTError:
        s.fail(401,'INVALID_ACCESS_TOKEN')
    session=db.get(AuthSession,claims['sid'])
    if not session or session.user_id!=claims['sub'] or session.revoked_at or s.utc(session.expires_at)<=now():
        s.fail(401,'INVALID_ACCESS_TOKEN')
    return s.active_user(db,claims['sub'])

def require_role(*codes):
    def dependency(user: User=Depends(current_user)):
        if user.role.code not in codes:
            s.fail(403,'INSUFFICIENT_PERMISSIONS')
        return user
    return dependency

@router.post('/register',status_code=201)
def register(body:RegisterRequest,request:Request,db:Session=Depends(get_db)):
    s_email=s.normalize(str(body.email))
    rate_limit(request,'register',s_email,5,3600)
    if s.get_user(db,s_email):
        s.fail(409,'EMAIL_ALREADY_EXISTS')
    role=db.scalar(select(Role).where(Role.code=='patient',Role.is_active.is_(True)))
    if role is None:
        raise HTTPException(503,detail={'code':'ROLE_SEED_MISSING','message':'Apply migrations and seed roles'})
    user=User(fullname=body.fullname.strip(),email=s_email,phone=body.phone,
        password_hash=password_hash(body.password),role_id=role.id)
    db.add(user)
    try:
        db.flush()
        s.event(db,user.id,'USER_REGISTERED')
        notify(db, user.id, 'account_created', event_key=f'account:{user.id}', email=False)
        db.commit()
    except IntegrityError:
        db.rollback()
        s.fail(409,'EMAIL_ALREADY_EXISTS')
    s.send_otp(db,user,'email_verification')
    return {'message':'Inscription effectuée. Veuillez vérifier votre email.','email_verification_required':True}

@router.post('/verify-email')
def verify_email(body:CodeEmailRequest,request:Request,db:Session=Depends(get_db)):
    rate_limit(request,'verify-email',str(body.email),10,600)
    user=s.get_user(db,str(body.email))
    if not user: s.fail(400,'OTP_INVALID')
    otp=db.scalar(select(OTP).where(OTP.user_id==user.id,OTP.type=='email_verification',
        OTP.used_at.is_(None),OTP.invalidated_at.is_(None)).order_by(OTP.created_at.desc()).with_for_update())
    if not otp: s.fail(400,'OTP_INVALID')
    s.otp_valid(db,otp.challenge_id,'email_verification',body.code)
    user.email_verified=True
    user.email_verified_at=now()
    s.event(db,user.id,'EMAIL_VERIFIED')
    db.commit()
    return {'message':'Email vérifié','email_verified':True}

@router.post('/resend-email-code')
def resend_email(body:EmailRequest,request:Request,db:Session=Depends(get_db)):
    rate_limit(request,'resend-email',str(body.email),5,3600)
    user=s.get_user(db,str(body.email))
    if user and not user.email_verified:
        otp=db.scalar(select(OTP).where(OTP.user_id==user.id,OTP.type=='email_verification',
            OTP.used_at.is_(None),OTP.invalidated_at.is_(None)).order_by(OTP.created_at.desc()).with_for_update())
        if otp:
            s.resend_otp(db,otp,'email_verification')
        else:
            s.send_otp(db,user,'email_verification')
    return {'message':'Si une vérification est nécessaire, un code sera envoyé.'}

@router.post('/login')
def login(body:LoginRequest,request:Request,db:Session=Depends(get_db)):
    rate_limit(request,'login',str(body.email),10,600)
    user=s.get_user(db,str(body.email))
    # Dummy hash mitigates basic account existence timing leaks.
    if user is None:
        verify_password(body.password,password_hash('dummy_constant_password'))
        s.fail(401,'INVALID_CREDENTIALS')
    if not verify_password(body.password,user.password_hash):
        s.event(db,user.id,'LOGIN_FAILED');db.commit()
        s.fail(401,'INVALID_CREDENTIALS')
    if not user.is_active or not user.role.is_active:s.fail(403,'ACCOUNT_DISABLED')
    if not user.email_verified:s.fail(403,'EMAIL_NOT_VERIFIED')
    s.invalidate_other_otps(db,user.id,'login')
    otp,ttl=s.send_otp(db,user,'login')
    return {'status':'otp_required','challenge_id':otp.challenge_id,'expires_in':ttl}

@router.post('/verify-login-otp',response_model=TokenResponse)
def verify_login_otp(body:CodeChallengeRequest,request:Request,db:Session=Depends(get_db)):
    rate_limit(request,'login-otp',body.challenge_id,10,600)
    otp=s.otp_valid(db,body.challenge_id,'login',body.code)
    user=s.active_user(db,otp.user_id)
    tokens,_=s.issue_tokens(db,user)
    s.event(db,user.id,'LOGIN_SUCCESS')
    db.commit()
    return tokens

@router.post('/resend-login-otp')
def resend_login_otp(body:ChallengeRequest,request:Request,db:Session=Depends(get_db)):
    rate_limit(request,'resend-login',body.challenge_id,5,3600)
    otp=db.scalar(select(OTP).where(OTP.challenge_id==body.challenge_id,OTP.type=='login').with_for_update())
    if not otp:s.fail(400,'OTP_INVALID')
    s.active_user(db,otp.user_id)
    ttl=s.resend_otp(db,otp,'login')
    return {'message':'Nouveau code envoyé','expires_in':ttl}

@router.post('/refresh',response_model=TokenResponse)
def refresh(body:RefreshRequest,request:Request,db:Session=Depends(get_db)):
    rate_limit(request,'refresh',body.refresh_token,30,600)
    return s.refresh_session(db,body.refresh_token)

@router.post('/logout')
def logout(body:RefreshRequest,db:Session=Depends(get_db)):
    token=db.scalar(select(RefreshToken).where(RefreshToken.token_hash==hash_secret(body.refresh_token)).with_for_update())
    if token:
        session=db.get(AuthSession,token.session_id)
        if session and not session.revoked_at:
            session.revoked_at=now()
            db.execute(update(RefreshToken).where(RefreshToken.session_id==session.id,
                RefreshToken.revoked_at.is_(None)).values(revoked_at=now()))
            s.event(db,token.user_id,'LOGOUT')
            db.commit()
    return {'message':'Déconnexion effectuée'}

@router.get('/me')
def me(user:User=Depends(current_user)):
    return {'id':user.id,'fullname':user.fullname,'email':user.email,'phone':user.phone,
        'role':{'code':user.role.code,'name':user.role.name},'email_verified':user.email_verified,'is_active':user.is_active}

@router.post('/forgot-password')
def forgot(body:EmailRequest,request:Request,db:Session=Depends(get_db)):
    rate_limit(request,'forgot',str(body.email),5,3600)
    user=s.get_user(db,str(body.email))
    if user and user.is_active and user.email_verified:
        s.invalidate_other_otps(db,user.id,'password_reset')
        s.send_otp(db,user,'password_reset')
        s.event(db,user.id,'PASSWORD_RESET_REQUESTED');db.commit()
    return {'message':'Si un compte correspond à cette adresse, un code sera envoyé.'}

@router.post('/verify-reset-code')
def verify_reset(body:CodeEmailRequest,request:Request,db:Session=Depends(get_db)):
    rate_limit(request,'verify-reset',str(body.email),10,600)
    user=s.get_user(db,str(body.email))
    if not user:s.fail(400,'OTP_INVALID')
    otp=db.scalar(select(OTP).where(OTP.user_id==user.id,OTP.type=='password_reset',
        OTP.used_at.is_(None),OTP.invalidated_at.is_(None)).order_by(OTP.created_at.desc()).with_for_update())
    if not otp:s.fail(400,'OTP_INVALID')
    s.otp_valid(db,otp.challenge_id,'password_reset',body.code)
    raw=random_token()
    db.add(PasswordResetToken(user_id=user.id,token_hash=hash_secret(raw),
        expires_at=now()+timedelta(minutes=get_settings().reset_token_minutes)))
    db.commit()
    return {'reset_token':raw,'expires_in':get_settings().reset_token_minutes*60}

@router.post('/reset-password')
def reset_password(body:ResetRequest,request:Request,db:Session=Depends(get_db)):
    rate_limit(request,'reset-password',body.reset_token,10,600)
    reset=db.scalar(select(PasswordResetToken).where(
        PasswordResetToken.token_hash==hash_secret(body.reset_token)).with_for_update())
    if not reset or reset.used_at or s.utc(reset.expires_at)<=now():
        s.fail(400,'RESET_TOKEN_INVALID')
    user=db.get(User,reset.user_id)
    if not user or not user.is_active:s.fail(403,'ACCOUNT_DISABLED')
    if verify_password(body.new_password,user.password_hash):s.fail(422,'PASSWORD_REUSED')
    user.password_hash=password_hash(body.new_password)
    user.password_changed_at=now()
    reset.used_at=now()
    db.execute(update(PasswordResetToken).where(PasswordResetToken.user_id==user.id,
        PasswordResetToken.used_at.is_(None)).values(used_at=now()))
    s.revoke_all(db,user.id)
    s.event(db,user.id,'PASSWORD_CHANGED')
    notify(db, user.id, 'security_alert', security=True,
           event_key=f'password-reset:{user.id}:{now().isoformat()}')
    db.commit()
    return {'message':'Mot de passe réinitialisé'}

@users_router.put('/me/password')
def change_password(body:ChangePasswordRequest,user:User=Depends(current_user),db:Session=Depends(get_db)):
    if not verify_password(body.current_password,user.password_hash):s.fail(401,'INVALID_CURRENT_PASSWORD')
    if verify_password(body.new_password,user.password_hash):s.fail(422,'PASSWORD_REUSED')
    user.password_hash=password_hash(body.new_password)
    user.password_changed_at=now()
    s.revoke_all(db,user.id)
    s.event(db,user.id,'PASSWORD_CHANGED')
    notify(db, user.id, 'security_alert', security=True,
           event_key=f'password-change:{user.id}:{now().isoformat()}')
    db.commit()
    return {'message':'Mot de passe modifié. Reconnectez-vous.'}
