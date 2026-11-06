from datetime import datetime

from sqlalchemy import CheckConstraint, DateTime, ForeignKey, Index, Integer, String, Text, UniqueConstraint
from sqlalchemy.dialects.mysql import DATETIME
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base
from app.modules.auth.models.entities import now, uid

Timestamp = DateTime(timezone=True).with_variant(DATETIME(fsp=6), 'mysql')


class Review(Base):
    __tablename__ = 'psychologist_reviews'
    __table_args__ = (
        CheckConstraint('rating >= 1 AND rating <= 5', name='ck_review_rating'),
        CheckConstraint("status IN ('pending','approved','rejected')", name='ck_review_status'),
        UniqueConstraint('appointment_id', name='uq_review_appointment'),
        Index('ix_review_public', 'psychologist_id', 'status', 'created_at'),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    appointment_id: Mapped[str] = mapped_column(ForeignKey('appointments.id'))
    psychologist_id: Mapped[str] = mapped_column(ForeignKey('psychologist_profiles.id'), index=True)
    author_id: Mapped[str] = mapped_column(ForeignKey('users.id'), index=True)
    rating: Mapped[int] = mapped_column(Integer)
    content: Mapped[str] = mapped_column(Text)
    status: Mapped[str] = mapped_column(String(16), default='pending', index=True)
    reviewed_by: Mapped[str | None] = mapped_column(ForeignKey('users.id'))
    reviewed_at: Mapped[datetime | None] = mapped_column(Timestamp)
    rejection_reason: Mapped[str | None] = mapped_column(String(1000))
    deleted_at: Mapped[datetime | None] = mapped_column(Timestamp)
    created_at: Mapped[datetime] = mapped_column(Timestamp, default=now)
    updated_at: Mapped[datetime] = mapped_column(Timestamp, default=now, onupdate=now)
