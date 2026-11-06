from pydantic import BaseModel, EmailStr, Field, field_validator
import re

class RegisterRequest(BaseModel):
    fullname: str = Field(min_length=2, max_length=160)
    email: EmailStr
    phone: str | None = None
    password: str = Field(min_length=8, max_length=256)
    @field_validator('fullname', mode='before')
    @classmethod
    def trim_fullname(cls, value):
        return value.strip() if isinstance(value, str) else value
    @field_validator('phone')
    @classmethod
    def phone_format(cls, value):
        if value is not None and not re.fullmatch(r'\+[1-9][0-9]{7,14}', value):
            raise ValueError('Use international E.164 telephone format')
        return value

class EmailRequest(BaseModel):
    email: EmailStr

class CodeEmailRequest(EmailRequest):
    code: str = Field(pattern=r'^\d{6}$')

class LoginRequest(EmailRequest):
    password: str

class ChallengeRequest(BaseModel):
    challenge_id: str = Field(min_length=16, max_length=100)

class CodeChallengeRequest(ChallengeRequest):
    code: str = Field(pattern=r'^\d{6}$')

class RefreshRequest(BaseModel):
    refresh_token: str = Field(min_length=32, max_length=512)

class ResetRequest(BaseModel):
    reset_token: str = Field(min_length=32, max_length=512)
    new_password: str = Field(min_length=8, max_length=256)

class ChangePasswordRequest(BaseModel):
    current_password: str
    new_password: str = Field(min_length=8, max_length=256)

class TokenResponse(BaseModel):
    access_token: str
    refresh_token: str
    token_type: str = 'bearer'
    expires_in: int = 900
