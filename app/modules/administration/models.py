from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Index, JSON, String
from sqlalchemy.dialects.mysql import DATETIME
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base
from app.modules.auth.models.entities import now, uid

Timestamp = DateTime(timezone=True).with_variant(DATETIME(fsp=6), 'mysql')


class AdminAuditLog(Base):
    __tablename__ = 'admin_audit_logs'
    __table_args__ = (Index('ix_admin_audit_actor_date', 'actor_id', 'created_at'),
                      Index('ix_admin_audit_object', 'object_type', 'object_id'))

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    actor_id: Mapped[str] = mapped_column(ForeignKey('users.id'), index=True)
    action: Mapped[str] = mapped_column(String(64))
    object_type: Mapped[str] = mapped_column(String(32))
    object_id: Mapped[str] = mapped_column(String(36))
    details: Mapped[dict | None] = mapped_column(JSON)
    created_at: Mapped[datetime] = mapped_column(Timestamp, default=now)
