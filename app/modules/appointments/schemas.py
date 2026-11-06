"""Contrats du planning : horaires locaux à la minute et instants normalisés UTC."""
from datetime import datetime, time, timezone
from typing import Annotated, Literal
from zoneinfo import ZoneInfo

from pydantic import BaseModel, ConfigDict, Field, StringConstraints, field_validator, model_validator

from app.core.config import get_settings
from app.modules.psychologists.schemas import ConsultationMode

AppointmentStatus = Literal['pending', 'confirmed', 'rejected', 'reschedule_requested',
                            'cancelled', 'in_progress', 'completed', 'no_show']
ConsultationStatus = Literal['scheduled', 'in_progress', 'completed', 'cancelled', 'no_show']
Reason = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=2000)]


def local_instant(value: datetime):
    """Refuser les heures locales inexistantes ou ambiguës lors du changement d'heure."""
    zone = ZoneInfo(get_settings().appointment_timezone)
    first = value.replace(tzinfo=zone, fold=0)
    second = value.replace(tzinfo=zone, fold=1)
    if first.utcoffset() != second.utcoffset() or first.astimezone(timezone.utc).astimezone(zone).replace(tzinfo=None) != value:
        raise ValueError('Ambiguous or nonexistent local time; use an explicit UTC offset')
    return first.astimezone(timezone.utc)


def instant(value: datetime):
    return local_instant(value) if value.tzinfo is None else value.astimezone(timezone.utc)


class StrictBody(BaseModel):
    model_config = ConfigDict(extra='forbid')


class AvailabilityBody(StrictBody):
    day_of_week: int = Field(ge=0, le=6)
    start_time: time
    end_time: time
    consultation_mode: ConsultationMode
    location: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=500)] | None = None
    is_active: bool = True

    @field_validator('start_time', 'end_time')
    @classmethod
    def minute_precision(cls, value):
        if value.tzinfo is not None or value.second or value.microsecond:
            raise ValueError('Use local HH:MM without seconds or timezone')
        return value

    @model_validator(mode='after')
    def coherent_times(self):
        if self.end_time <= self.start_time:
            raise ValueError('End time must be after start time')
        if self.consultation_mode == 'in_person' and not self.location:
            raise ValueError('In-person availability requires a consultation location')
        return self


class UnavailabilityBody(StrictBody):
    start_datetime: datetime
    end_datetime: datetime
    reason: Reason | None = None
    is_active: bool = True

    @field_validator('start_datetime', 'end_datetime')
    @classmethod
    def normalize(cls, value):
        return instant(value)

    @model_validator(mode='after')
    def coherent_dates(self):
        if self.end_datetime <= self.start_datetime:
            raise ValueError('End must be after start')
        return self


class BookingBody(StrictBody):
    psychologist_id: str = Field(min_length=1, max_length=36)
    start_datetime: datetime
    consultation_mode: ConsultationMode
    duration: int | None = Field(default=None, ge=5, le=240)
    reason: Reason | None = None
    notes: Annotated[str, StringConstraints(strip_whitespace=True, max_length=5000)] | None = None

    @field_validator('start_datetime')
    @classmethod
    def normalize(cls, value):
        value = instant(value)
        if value.second or value.microsecond:
            raise ValueError('Booking times must have minute precision')
        return value


class RescheduleBody(StrictBody):
    new_start_datetime: datetime
    reason: Reason

    @field_validator('new_start_datetime')
    @classmethod
    def normalize(cls, value):
        return BookingBody.normalize(value)


class CancellationBody(StrictBody):
    reason: Reason


class AppointmentFilters(BaseModel):
    status: AppointmentStatus | None = None
    date_from: datetime | None = None
    date_to: datetime | None = None
    page: int = Field(default=1, ge=1)
    page_size: int = Field(default=20, ge=1, le=100)


class AdminAppointmentFilters(AppointmentFilters):
    patient_id: str | None = None
    psychologist_id: str | None = None
    consultation_mode: ConsultationMode | None = None


class ConsultationFilters(BaseModel):
    status: ConsultationStatus | None = None
    patient_id: str | None = None
    psychologist_id: str | None = None
    date_from: datetime | None = None
    date_to: datetime | None = None
    page: int = Field(default=1, ge=1)
    page_size: int = Field(default=20, ge=1, le=100)


class ConsultationStart(StrictBody):
    appointment_id: str = Field(min_length=1, max_length=36)
    consultation_type: Literal['video', 'audio', 'phone', 'in_person'] | None = None
