from datetime import timedelta
from hashlib import sha256
import hmac, secrets, jwt
from argon2 import PasswordHasher
from argon2.exceptions import VerifyMismatchError, InvalidHashError, VerificationError
from app.modules.auth.models.entities import now
from app.core.config import get_settings

hasher = PasswordHasher()

def password_hash(password: str) -> str:
    return hasher.hash(password)

def verify_password(password: str, digest: str) -> bool:
    try:
        return hasher.verify(digest, password)
    except (VerifyMismatchError, InvalidHashError, VerificationError):
        return False

def otp_code() -> str:
    return f'{secrets.randbelow(1000000):06d}'

def random_token() -> str:
    return secrets.token_urlsafe(48)

def hash_secret(token: str) -> str:
    return sha256(token.encode()).hexdigest()

def hash_otp(code: str, challenge: str) -> str:
    return hmac.new(get_settings().otp_secret_key.encode(), f'{challenge}:{code}'.encode(), sha256).hexdigest()

def otp_matches(code: str, challenge: str, stored: str) -> bool:
    return hmac.compare_digest(hash_otp(code, challenge), stored)

def access_token(user_id: str, session_id: str) -> str:
    settings = get_settings()
    timestamp = now()
    claims = dict(sub=user_id, sid=session_id, type='access', jti=random_token(), iat=timestamp,
                  nbf=timestamp, exp=timestamp + timedelta(minutes=settings.access_minutes),
                  iss=settings.jwt_issuer, aud=settings.jwt_audience)
    return jwt.encode(claims, settings.jwt_secret_key, algorithm='HS256')

def decode_access(token: str) -> dict:
    s = get_settings()
    claims = jwt.decode(token, s.jwt_secret_key, algorithms=['HS256'], audience=s.jwt_audience,
                        issuer=s.jwt_issuer, options={'require': ['sub', 'sid', 'exp', 'iat', 'nbf', 'type']})
    if claims.get('type') != 'access':
        raise jwt.InvalidTokenError('Wrong token type')
    return claims
