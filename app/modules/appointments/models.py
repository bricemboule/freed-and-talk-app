"""Horaires, réservations atomiques, historique et file de notifications."""
from datetime import datetime, time
from sqlalchemy import Boolean, CheckConstraint, ForeignKey, Index, Integer, String, Text, Time, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base
from app.modules.auth.models.entities import now, uid
from app.modules.psychologists.models import Timestamp

ACTIVE_STATUSES = ('pending', 'confirmed', 'reschedule_requested', 'in_progress')
APPOINTMENT_STATUSES = (*ACTIVE_STATUSES, 'rejected', 'cancelled', 'completed', 'no_show')


class Availability(Base):
    __tablename__ = 'psychologist_availabilities'
    __table_args__ = (
        CheckConstraint('day_of_week >= 0 AND day_of_week <= 6', name='ck_availability_day'),
        CheckConstraint('end_time > start_time', name='ck_availability_times'),
        CheckConstraint("consultation_mode IN ('online','in_person')", name='ck_availability_mode'),
    )
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    psychologist_id: Mapped[str] = mapped_column(ForeignKey('psychologist_profiles.id'), index=True)
    day_of_week: Mapped[int] = mapped_column(Integer)
    start_time: Mapped[time] = mapped_column(Time)
    end_time: Mapped[time] = mapped_column(Time)
    consultation_mode: Mapped[str] = mapped_column(String(16))
    location: Mapped[str | None] = mapped_column(String(500))
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(Timestamp, default=now)
    updated_at: Mapped[datetime] = mapped_column(Timestamp, default=now, onupdate=now)


class Unavailability(Base):
    __tablename__ = 'psychologist_unavailabilities'
    __table_args__ = (CheckConstraint('end_datetime > start_datetime', name='ck_unavailability_dates'),)
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    psychologist_id: Mapped[str] = mapped_column(ForeignKey('psychologist_profiles.id'), index=True)
    start_datetime: Mapped[datetime] = mapped_column(Timestamp)
    end_datetime: Mapped[datetime] = mapped_column(Timestamp)
    reason: Mapped[str | None] = mapped_column(String(1000))
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(Timestamp, default=now)
    updated_at: Mapped[datetime] = mapped_column(Timestamp, default=now, onupdate=now)


class Appointment(Base):
    __tablename__ = 'appointments'
    __table_args__ = (
        CheckConstraint('end_datetime > start_datetime', name='ck_appointment_dates'),
        CheckConstraint("status IN ('pending','confirmed','reschedule_requested','in_progress',"
                        "'rejected','cancelled','completed','no_show')", name='ck_appointment_status'),
        CheckConstraint("consultation_mode IN ('online','in_person')", name='ck_appointment_mode'),
        Index('ix_appointment_patient_time', 'patient_id', 'start_datetime'),
        Index('ix_appointment_psychologist_time', 'psychologist_id', 'start_datetime'),
    )
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    patient_id: Mapped[str] = mapped_column(ForeignKey('users.id'))
    psychologist_id: Mapped[str] = mapped_column(ForeignKey('psychologist_profiles.id'))
    availability_id: Mapped[str | None] = mapped_column(ForeignKey('psychologist_availabilities.id', ondelete='SET NULL'))
    start_datetime: Mapped[datetime] = mapped_column(Timestamp)
    end_datetime: Mapped[datetime] = mapped_column(Timestamp)
    consultation_mode: Mapped[str] = mapped_column(String(16))
    timezone: Mapped[str] = mapped_column(String(64))
    location: Mapped[str | None] = mapped_column(String(500))
    reason: Mapped[str | None] = mapped_column(Text)
    notes: Mapped[str | None] = mapped_column(Text)
    fee_amount: Mapped[int | None] = mapped_column(Integer)
    fee_currency: Mapped[str | None] = mapped_column(String(3))
    status: Mapped[str] = mapped_column(String(32), default='pending', index=True)
    cancellation_reason: Mapped[str | None] = mapped_column(Text)
    cancelled_by: Mapped[str | None] = mapped_column(ForeignKey('users.id'))
    confirmed_at: Mapped[datetime | None] = mapped_column(Timestamp)
    cancelled_at: Mapped[datetime | None] = mapped_column(Timestamp)
    created_at: Mapped[datetime] = mapped_column(Timestamp, default=now)
    updated_at: Mapped[datetime] = mapped_column(Timestamp, default=now, onupdate=now)


class Reservation(Base):
    __tablename__ = 'appointment_reservations'
    __table_args__ = (
        UniqueConstraint('resource_kind', 'resource_id', 'minute', name='uq_reservation_resource_minute'),
    )
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    appointment_id: Mapped[str] = mapped_column(ForeignKey('appointments.id', ondelete='CASCADE'), index=True)
    resource_kind: Mapped[str] = mapped_column(String(16))
    resource_id: Mapped[str] = mapped_column(String(36))
    minute: Mapped[datetime] = mapped_column(Timestamp)


class AppointmentHistory(Base):
    __tablename__ = 'appointment_history'
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    appointment_id: Mapped[str] = mapped_column(ForeignKey('appointments.id'), index=True)
    actor_id: Mapped[str] = mapped_column(ForeignKey('users.id'))
    action: Mapped[str] = mapped_column(String(64))
    previous_status: Mapped[str | None] = mapped_column(String(32))
    new_status: Mapped[str] = mapped_column(String(32))
    old_start_datetime: Mapped[datetime | None] = mapped_column(Timestamp)
    old_end_datetime: Mapped[datetime | None] = mapped_column(Timestamp)
    new_start_datetime: Mapped[datetime] = mapped_column(Timestamp)
    new_end_datetime: Mapped[datetime] = mapped_column(Timestamp)
    reason: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(Timestamp, default=now)


class Consultation(Base):
    __tablename__ = 'consultations'
    __table_args__ = (
        CheckConstraint("status IN ('scheduled','in_progress','completed','cancelled','no_show')",
                        name='ck_consultation_status'),
        CheckConstraint("consultation_type IN ('video','audio','phone','in_person')",
                        name='ck_consultation_type'),
    )
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    appointment_id: Mapped[str] = mapped_column(ForeignKey('appointments.id'), unique=True)
    provider: Mapped[str | None] = mapped_column(String(32))
    consultation_type: Mapped[str] = mapped_column(String(16), default='video')
    meeting_room: Mapped[str | None] = mapped_column(String(100))
    meeting_url: Mapped[str | None] = mapped_column(String(500))
    status: Mapped[str] = mapped_column(String(32), default='scheduled')
    started_at: Mapped[datetime | None] = mapped_column(Timestamp)
    ended_at: Mapped[datetime | None] = mapped_column(Timestamp)
    created_at: Mapped[datetime] = mapped_column(Timestamp, default=now)
    updated_at: Mapped[datetime] = mapped_column(Timestamp, default=now, onupdate=now)


class AppointmentNotification(Base):
    __tablename__ = 'appointment_notifications'
    __table_args__ = (UniqueConstraint('history_id', 'recipient_id', name='uq_appointment_notification'),)
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    history_id: Mapped[str] = mapped_column(ForeignKey('appointment_history.id'))
    recipient_id: Mapped[str] = mapped_column(ForeignKey('users.id'))
    body: Mapped[str] = mapped_column(Text)
    status: Mapped[str] = mapped_column(String(16), default='pending', index=True)
    attempts: Mapped[int] = mapped_column(Integer, default=0)
    next_attempt_at: Mapped[datetime] = mapped_column(Timestamp, default=now)
    sent_at: Mapped[datetime | None] = mapped_column(Timestamp)
    created_at: Mapped[datetime] = mapped_column(Timestamp, default=now)
