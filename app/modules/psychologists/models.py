"""Profils professionnels, pièces privées et historique des vérifications."""
from datetime import datetime

from sqlalchemy import CheckConstraint, DateTime, ForeignKey, Integer, JSON, String, Text
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.dialects.mysql import DATETIME

from app.core.database import Base
from app.modules.auth.models.entities import now, uid


Timestamp = DateTime(timezone=True).with_variant(DATETIME(fsp=6), "mysql")


class PsychologistProfile(Base):
    __tablename__ = 'psychologist_profiles'
    __table_args__ = (
        CheckConstraint('years_of_experience >= 0', name='ck_psychologist_experience'),
        CheckConstraint('consultation_fee IS NULL OR consultation_fee >= 0', name='ck_psychologist_fee'),
        CheckConstraint("verification_status IN ('pending_documents', 'documents_submitted', "
                        "'under_review', 'approved', 'rejected', 'suspended')", name='ck_profile_status'),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    user_id: Mapped[str] = mapped_column(ForeignKey('users.id'), unique=True)
    professional_title: Mapped[str] = mapped_column(String(160))
    specialty: Mapped[str] = mapped_column(String(160))
    years_of_experience: Mapped[int] = mapped_column(Integer)
    professional_registration_number: Mapped[str | None] = mapped_column(String(160))
    bio: Mapped[str] = mapped_column(Text)
    languages: Mapped[list] = mapped_column(JSON)
    consultation_modes: Mapped[list] = mapped_column(JSON)
    consultation_fee: Mapped[int | None] = mapped_column(Integer)
    consultation_currency: Mapped[str] = mapped_column(String(3), default='XAF')
    verification_status: Mapped[str] = mapped_column(String(32), default='pending_documents', index=True)
    rejection_reason: Mapped[str | None] = mapped_column(Text)
    suspension_reason: Mapped[str | None] = mapped_column(Text)
    submitted_at: Mapped[datetime | None] = mapped_column(Timestamp)
    approved_at: Mapped[datetime | None] = mapped_column(Timestamp)
    suspended_at: Mapped[datetime | None] = mapped_column(Timestamp)
    created_at: Mapped[datetime] = mapped_column(Timestamp, default=now)
    updated_at: Mapped[datetime] = mapped_column(Timestamp, default=now, onupdate=now)


class PsychologistDocument(Base):
    __tablename__ = 'psychologist_documents'
    __table_args__ = (
        CheckConstraint("status IN ('pending', 'approved', 'rejected')", name='ck_document_status'),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    psychologist_id: Mapped[str] = mapped_column(ForeignKey('psychologist_profiles.id'), index=True)
    document_type: Mapped[str] = mapped_column(String(40))
    description: Mapped[str | None] = mapped_column(String(1000))
    file_name: Mapped[str] = mapped_column(String(255))
    storage_path: Mapped[str] = mapped_column(String(100), unique=True)
    mime_type: Mapped[str] = mapped_column(String(80))
    file_size: Mapped[int] = mapped_column(Integer)
    status: Mapped[str] = mapped_column(String(16), default='pending')
    rejection_reason: Mapped[str | None] = mapped_column(Text)
    reviewed_by: Mapped[str | None] = mapped_column(ForeignKey('users.id'))
    reviewed_at: Mapped[datetime | None] = mapped_column(Timestamp)
    created_at: Mapped[datetime] = mapped_column(Timestamp, default=now)
    updated_at: Mapped[datetime] = mapped_column(Timestamp, default=now, onupdate=now)


class PsychologistVerificationLog(Base):
    __tablename__ = 'psychologist_verification_logs'

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    psychologist_id: Mapped[str] = mapped_column(ForeignKey('psychologist_profiles.id'), index=True)
    admin_id: Mapped[str | None] = mapped_column(ForeignKey('users.id'))
    actor_id: Mapped[str] = mapped_column(ForeignKey('users.id'))
    document_id: Mapped[str | None] = mapped_column(String(36))
    action: Mapped[str] = mapped_column(String(64))
    reason: Mapped[str | None] = mapped_column(Text)
    previous_status: Mapped[str] = mapped_column(String(32))
    new_status: Mapped[str] = mapped_column(String(32))
    changes: Mapped[dict | None] = mapped_column(JSON)
    created_at: Mapped[datetime] = mapped_column(Timestamp, default=now)
