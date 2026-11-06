"""Conversations privées, événements durables et préférences de communication."""
from datetime import datetime
from sqlalchemy import Boolean, CheckConstraint, ForeignKey, Index, Integer, JSON, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column
from app.core.database import Base
from app.modules.auth.models.entities import now, uid
from app.modules.psychologists.models import Timestamp


class Conversation(Base):
    __tablename__ = 'conversations'
    __table_args__ = (UniqueConstraint('user_low', 'user_high', name='uq_conversation_pair'),
                      CheckConstraint("status IN ('active','closed')", name='ck_conversation_status'),
                      CheckConstraint('user_low < user_high', name='ck_conversation_pair_order'))
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    user_low: Mapped[str] = mapped_column(ForeignKey('users.id'))
    user_high: Mapped[str] = mapped_column(ForeignKey('users.id'))
    created_by: Mapped[str] = mapped_column(ForeignKey('users.id'))
    status: Mapped[str] = mapped_column(String(16), default='active')
    created_at: Mapped[datetime] = mapped_column(Timestamp, default=now)
    updated_at: Mapped[datetime] = mapped_column(Timestamp, default=now, onupdate=now)
    last_message_at: Mapped[datetime | None] = mapped_column(Timestamp)


class ConversationParticipant(Base):
    __tablename__ = 'conversation_participants'
    __table_args__ = (UniqueConstraint('conversation_id', 'user_id', name='uq_conversation_participant'),)
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    conversation_id: Mapped[str] = mapped_column(ForeignKey('conversations.id'), index=True)
    user_id: Mapped[str] = mapped_column(ForeignKey('users.id'), index=True)
    joined_at: Mapped[datetime] = mapped_column(Timestamp, default=now)
    archived_at: Mapped[datetime | None] = mapped_column(Timestamp)
    last_read_at: Mapped[datetime | None] = mapped_column(Timestamp)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)


class Message(Base):
    __tablename__ = 'messages'
    __table_args__ = (CheckConstraint("message_type IN ('text','image','document','system')", name='ck_message_type'),
                      Index('ix_message_conversation_cursor', 'conversation_id', 'id'))
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    conversation_id: Mapped[str] = mapped_column(ForeignKey('conversations.id'))
    sender_id: Mapped[str] = mapped_column(ForeignKey('users.id'), index=True)
    content: Mapped[str | None] = mapped_column(Text)
    message_type: Mapped[str] = mapped_column(String(16), default='text')
    created_at: Mapped[datetime] = mapped_column(Timestamp, default=now)
    updated_at: Mapped[datetime] = mapped_column(Timestamp, default=now, onupdate=now)
    edited_at: Mapped[datetime | None] = mapped_column(Timestamp)
    deleted_at: Mapped[datetime | None] = mapped_column(Timestamp)


class MessageAttachment(Base):
    __tablename__ = 'message_attachments'
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    message_id: Mapped[int] = mapped_column(ForeignKey('messages.id'), unique=True)
    original_filename: Mapped[str] = mapped_column(String(255))
    stored_filename: Mapped[str] = mapped_column(String(100), unique=True)
    storage_path: Mapped[str] = mapped_column(String(100))
    mime_type: Mapped[str] = mapped_column(String(80))
    file_size: Mapped[int] = mapped_column(Integer)
    created_at: Mapped[datetime] = mapped_column(Timestamp, default=now)
    deleted_at: Mapped[datetime | None] = mapped_column(Timestamp)


class MessageRead(Base):
    __tablename__ = 'message_reads'
    __table_args__ = (UniqueConstraint('message_id', 'user_id', name='uq_message_read'),)
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    message_id: Mapped[int] = mapped_column(ForeignKey('messages.id'), index=True)
    user_id: Mapped[str] = mapped_column(ForeignKey('users.id'))
    read_at: Mapped[datetime] = mapped_column(Timestamp, default=now)


class MessageRevision(Base):
    __tablename__ = 'message_revisions'
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    message_id: Mapped[int] = mapped_column(ForeignKey('messages.id'), index=True)
    previous_content: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(Timestamp, default=now)


class Notification(Base):
    __tablename__ = 'notifications'
    __table_args__ = (UniqueConstraint('user_id', 'type', 'event_key', name='uq_notification_event'),
                      Index('ix_notification_user_date', 'user_id', 'created_at'))
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    user_id: Mapped[str] = mapped_column(ForeignKey('users.id'))
    type: Mapped[str] = mapped_column(String(64))
    title: Mapped[str] = mapped_column(String(160))
    content: Mapped[str] = mapped_column(String(1000))
    data: Mapped[dict] = mapped_column(JSON)
    event_key: Mapped[str | None] = mapped_column(String(190))
    security_required: Mapped[bool] = mapped_column(Boolean, default=False)
    is_read: Mapped[bool] = mapped_column(Boolean, default=False)
    read_at: Mapped[datetime | None] = mapped_column(Timestamp)
    deleted_at: Mapped[datetime | None] = mapped_column(Timestamp)
    created_at: Mapped[datetime] = mapped_column(Timestamp, default=now)


class NotificationPreferences(Base):
    __tablename__ = 'notification_preferences'
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    user_id: Mapped[str] = mapped_column(ForeignKey('users.id'), unique=True)
    email_notifications: Mapped[bool] = mapped_column(Boolean, default=True)
    message_email_notifications: Mapped[bool] = mapped_column(Boolean, default=False)
    appointment_reminders: Mapped[bool] = mapped_column(Boolean, default=True)
    push_notifications: Mapped[bool] = mapped_column(Boolean, default=True)
    updated_at: Mapped[datetime] = mapped_column(Timestamp, default=now, onupdate=now)


class NotificationLog(Base):
    __tablename__ = 'notification_logs'
    __table_args__ = (UniqueConstraint('notification_id', 'channel', name='uq_notification_channel'),)
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    notification_id: Mapped[str] = mapped_column(ForeignKey('notifications.id'), index=True)
    channel: Mapped[str] = mapped_column(String(16))
    status: Mapped[str] = mapped_column(String(16), default='pending', index=True)
    error_message: Mapped[str | None] = mapped_column(String(100))
    attempts: Mapped[int] = mapped_column(Integer, default=0)
    next_attempt_at: Mapped[datetime] = mapped_column(Timestamp, default=now)
    sent_at: Mapped[datetime | None] = mapped_column(Timestamp)
    created_at: Mapped[datetime] = mapped_column(Timestamp, default=now)


class RealtimeEvent(Base):
    __tablename__ = 'realtime_events'
    __table_args__ = (Index('ix_realtime_user_cursor', 'user_id', 'id'),)
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[str] = mapped_column(ForeignKey('users.id'))
    event: Mapped[str] = mapped_column(String(64))
    data: Mapped[dict] = mapped_column(JSON)
    created_at: Mapped[datetime] = mapped_column(Timestamp, default=now)


class UserPresence(Base):
    __tablename__ = 'user_presence'
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    user_id: Mapped[str] = mapped_column(ForeignKey('users.id'), unique=True)
    is_online: Mapped[bool] = mapped_column(Boolean, default=False)
    last_seen_at: Mapped[datetime] = mapped_column(Timestamp, default=now)
    updated_at: Mapped[datetime] = mapped_column(Timestamp, default=now, onupdate=now)


class PresenceConnection(Base):
    __tablename__ = 'presence_connections'
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    user_id: Mapped[str] = mapped_column(ForeignKey('users.id'), index=True)
    session_id: Mapped[str] = mapped_column(ForeignKey('auth_sessions.id'))
    expires_at: Mapped[datetime] = mapped_column(Timestamp, index=True)


class MessageQuota(Base):
    __tablename__ = 'message_quotas'
    user_id: Mapped[str] = mapped_column(ForeignKey('users.id'), primary_key=True)
    window_start: Mapped[datetime] = mapped_column(Timestamp, default=now)
    count: Mapped[int] = mapped_column(Integer, default=0)
