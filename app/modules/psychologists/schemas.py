"""Contrats d'entrée : aucun statut administratif n'est modifiable par le client."""
import re
from datetime import date
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, StringConstraints, field_validator, model_validator

from app.modules.auth.schemas.contracts import RegisterRequest

VerificationStatus = Literal['pending_documents', 'documents_submitted', 'under_review',
                             'approved', 'rejected', 'suspended']
DocumentType = Literal['identity_document', 'diploma', 'professional_license',
                       'professional_registration', 'cv', 'other']
ConsultationMode = Literal['online', 'in_person']
ShortText = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=100)]
Title = Annotated[str, StringConstraints(strip_whitespace=True, min_length=2, max_length=160)]
Biography = Annotated[str, StringConstraints(strip_whitespace=True, min_length=10, max_length=5000)]


class UserUpdate(BaseModel):
    model_config = ConfigDict(extra='forbid')
    fullname: Title | None = None
    phone: str | None = None
    country: ShortText | None = None
    city: ShortText | None = None
    date_of_birth: date | None = None

    @field_validator('date_of_birth')
    @classmethod
    def birth_date_not_in_future(cls, value):
        if value is not None and value > date.today():
            raise ValueError('Date of birth cannot be in the future')
        return value

    @field_validator('phone')
    @classmethod
    def validate_phone(cls, value):
        if value is not None and not re.fullmatch(r'\+[1-9][0-9]{7,14}', value):
            raise ValueError('Use international E.164 telephone format')
        return value

    @field_validator('fullname')
    @classmethod
    def fullname_cannot_be_null(cls, value):
        if value is None:
            raise ValueError('Fullname cannot be null')
        return value


class ProfessionalFields(BaseModel):
    model_config = ConfigDict(extra='forbid')
    professional_title: Title
    specialty: Title
    years_of_experience: int = Field(ge=0, le=80)
    professional_registration_number: Title | None = None
    bio: Biography
    languages: list[ShortText] = Field(min_length=1, max_length=20)
    consultation_modes: list[ConsultationMode] = Field(min_length=1, max_length=2)
    consultation_fee: int | None = Field(default=None, ge=0, le=100_000_000)
    consultation_currency: Annotated[str, StringConstraints(pattern=r'^[A-Z]{3}$')] = 'XAF'

    @field_validator('languages', 'consultation_modes')
    @classmethod
    def unique_values(cls, value):
        return list(dict.fromkeys(value))


class PsychologistRegister(RegisterRequest, ProfessionalFields):
    model_config = ConfigDict(extra='forbid')
    password_confirmation: str = Field(min_length=8, max_length=256)
    country: ShortText
    city: ShortText
    date_of_birth: date | None = None

    @field_validator('date_of_birth')
    @classmethod
    def birth_date_not_in_future(cls, value):
        if value is not None and value > date.today():
            raise ValueError('Date of birth cannot be in the future')
        return value

    @model_validator(mode='after')
    def matching_passwords(self):
        if self.password != self.password_confirmation:
            raise ValueError('Passwords do not match')
        return self


class ProfessionalUpdate(BaseModel):
    model_config = ConfigDict(extra='forbid')
    professional_title: Title | None = None
    specialty: Title | None = None
    years_of_experience: int | None = Field(default=None, ge=0, le=80)
    professional_registration_number: Title | None = None
    bio: Biography | None = None
    languages: list[ShortText] | None = Field(default=None, min_length=1, max_length=20)
    consultation_modes: list[ConsultationMode] | None = Field(default=None, min_length=1, max_length=2)
    consultation_fee: int | None = Field(default=None, ge=0, le=100_000_000)
    consultation_currency: Annotated[str, StringConstraints(pattern=r'^[A-Z]{3}$')] | None = None

    @field_validator('professional_title', 'specialty', 'years_of_experience', 'bio',
                     'languages', 'consultation_modes', 'consultation_currency')
    @classmethod
    def cannot_clear_required_field(cls, value):
        if value is None:
            raise ValueError('Required field cannot be null')
        return value


class DecisionReason(BaseModel):
    model_config = ConfigDict(extra='forbid')
    reason: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=2000)]
