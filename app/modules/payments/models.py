from datetime import datetime

from sqlalchemy import CheckConstraint, ForeignKey, Index, Integer, JSON, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base
from app.modules.auth.models.entities import now, uid
from app.modules.psychologists.models import Timestamp


class Payment(Base):
    __tablename__ = 'payments'
    __table_args__ = (
        CheckConstraint("status IN ('pending','processing','paid','failed','cancelled','refunded')",
                        name='ck_payment_status'),
        CheckConstraint("provider IN ('orange_money','mtn_momo','mobile_money','card')",
                        name='ck_payment_provider'),
        CheckConstraint('amount >= 0', name='ck_payment_amount'),
        UniqueConstraint('user_id', 'idempotency_key', name='uq_payment_idempotency'),
        Index('ix_payment_user_created', 'user_id', 'created_at'),
        Index('ix_payment_status_created', 'status', 'created_at'),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    appointment_id: Mapped[str] = mapped_column(ForeignKey('appointments.id'), index=True)
    user_id: Mapped[str] = mapped_column(ForeignKey('users.id'), index=True)
    provider: Mapped[str] = mapped_column(String(24))
    provider_reference: Mapped[str] = mapped_column(String(100), unique=True)
    idempotency_key: Mapped[str] = mapped_column(String(100))
    amount: Mapped[int] = mapped_column(Integer)
    currency: Mapped[str] = mapped_column(String(3))
    status: Mapped[str] = mapped_column(String(16), default='pending', index=True)
    created_at: Mapped[datetime] = mapped_column(Timestamp, default=now)
    updated_at: Mapped[datetime] = mapped_column(Timestamp, default=now, onupdate=now)


class PaymentEvent(Base):
    __tablename__ = 'payment_events'
    __table_args__ = (Index('ix_payment_event_payment_date', 'payment_id', 'created_at'),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    payment_id: Mapped[str] = mapped_column(ForeignKey('payments.id', ondelete='CASCADE'))
    status: Mapped[str] = mapped_column(String(16))
    source: Mapped[str] = mapped_column(String(32))
    details: Mapped[dict | None] = mapped_column(JSON)
    created_at: Mapped[datetime] = mapped_column(Timestamp, default=now)
