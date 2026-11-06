"""Communication privée, notifications et préférences.

Revision ID: c91a7f02d31e
Revises: 2e3b635c9ee6
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import mysql

revision = 'c91a7f02d31e'
down_revision = '2e3b635c9ee6'
branch_labels = None
depends_on = None
timestamp = sa.DateTime(timezone=True).with_variant(mysql.DATETIME(fsp=6), 'mysql')


def upgrade():
    op.create_table('conversations',
        sa.Column('id', sa.String(36), primary_key=True),
        sa.Column('user_low', sa.String(36), sa.ForeignKey('users.id'), nullable=False),
        sa.Column('user_high', sa.String(36), sa.ForeignKey('users.id'), nullable=False),
        sa.Column('created_by', sa.String(36), sa.ForeignKey('users.id'), nullable=False),
        sa.Column('status', sa.String(16), nullable=False),
        sa.Column('created_at', timestamp, nullable=False),
        sa.Column('updated_at', timestamp, nullable=False),
        sa.Column('last_message_at', timestamp),
        sa.CheckConstraint("status IN ('active','closed')", name='ck_conversation_status'),
        sa.CheckConstraint('user_low < user_high', name='ck_conversation_pair_order'),
        sa.UniqueConstraint('user_low', 'user_high', name='uq_conversation_pair'))

    op.create_table('conversation_participants',
        sa.Column('id', sa.String(36), primary_key=True),
        sa.Column('conversation_id', sa.String(36), sa.ForeignKey('conversations.id'), nullable=False),
        sa.Column('user_id', sa.String(36), sa.ForeignKey('users.id'), nullable=False),
        sa.Column('joined_at', timestamp, nullable=False),
        sa.Column('archived_at', timestamp), sa.Column('last_read_at', timestamp),
        sa.Column('is_active', sa.Boolean(), nullable=False),
        sa.UniqueConstraint('conversation_id', 'user_id', name='uq_conversation_participant'))
    op.create_index('ix_conversation_participants_conversation_id', 'conversation_participants', ['conversation_id'])
    op.create_index('ix_conversation_participants_user_id', 'conversation_participants', ['user_id'])

    op.create_table('messages',
        sa.Column('id', sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column('conversation_id', sa.String(36), sa.ForeignKey('conversations.id'), nullable=False),
        sa.Column('sender_id', sa.String(36), sa.ForeignKey('users.id'), nullable=False),
        sa.Column('content', sa.Text()), sa.Column('message_type', sa.String(16), nullable=False),
        sa.Column('created_at', timestamp, nullable=False), sa.Column('updated_at', timestamp, nullable=False),
        sa.Column('edited_at', timestamp), sa.Column('deleted_at', timestamp),
        sa.CheckConstraint("message_type IN ('text','image','document','system')", name='ck_message_type'))
    op.create_index('ix_messages_sender_id', 'messages', ['sender_id'])
    op.create_index('ix_message_conversation_cursor', 'messages', ['conversation_id', 'id'])

    op.create_table('message_attachments',
        sa.Column('id', sa.String(36), primary_key=True),
        sa.Column('message_id', sa.Integer(), sa.ForeignKey('messages.id'), nullable=False, unique=True),
        sa.Column('original_filename', sa.String(255), nullable=False),
        sa.Column('stored_filename', sa.String(100), nullable=False, unique=True),
        sa.Column('storage_path', sa.String(100), nullable=False),
        sa.Column('mime_type', sa.String(80), nullable=False), sa.Column('file_size', sa.Integer(), nullable=False),
        sa.Column('created_at', timestamp, nullable=False), sa.Column('deleted_at', timestamp))

    op.create_table('message_reads',
        sa.Column('id', sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column('message_id', sa.Integer(), sa.ForeignKey('messages.id'), nullable=False),
        sa.Column('user_id', sa.String(36), sa.ForeignKey('users.id'), nullable=False),
        sa.Column('read_at', timestamp, nullable=False),
        sa.UniqueConstraint('message_id', 'user_id', name='uq_message_read'))
    op.create_index('ix_message_reads_message_id', 'message_reads', ['message_id'])

    op.create_table('message_revisions',
        sa.Column('id', sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column('message_id', sa.Integer(), sa.ForeignKey('messages.id'), nullable=False),
        sa.Column('previous_content', sa.Text()), sa.Column('created_at', timestamp, nullable=False))
    op.create_index('ix_message_revisions_message_id', 'message_revisions', ['message_id'])

    op.create_table('notifications',
        sa.Column('id', sa.String(36), primary_key=True),
        sa.Column('user_id', sa.String(36), sa.ForeignKey('users.id'), nullable=False),
        sa.Column('type', sa.String(64), nullable=False), sa.Column('title', sa.String(160), nullable=False),
        sa.Column('content', sa.String(1000), nullable=False), sa.Column('data', sa.JSON(), nullable=False),
        sa.Column('event_key', sa.String(190)), sa.Column('security_required', sa.Boolean(), nullable=False),
        sa.Column('is_read', sa.Boolean(), nullable=False), sa.Column('read_at', timestamp),
        sa.Column('deleted_at', timestamp), sa.Column('created_at', timestamp, nullable=False),
        sa.UniqueConstraint('user_id', 'type', 'event_key', name='uq_notification_event'))
    op.create_index('ix_notification_user_date', 'notifications', ['user_id', 'created_at'])

    op.create_table('notification_preferences',
        sa.Column('id', sa.String(36), primary_key=True),
        sa.Column('user_id', sa.String(36), sa.ForeignKey('users.id'), nullable=False, unique=True),
        sa.Column('email_notifications', sa.Boolean(), nullable=False),
        sa.Column('message_email_notifications', sa.Boolean(), nullable=False),
        sa.Column('appointment_reminders', sa.Boolean(), nullable=False),
        sa.Column('push_notifications', sa.Boolean(), nullable=False), sa.Column('updated_at', timestamp, nullable=False))

    op.create_table('notification_logs',
        sa.Column('id', sa.String(36), primary_key=True),
        sa.Column('notification_id', sa.String(36), sa.ForeignKey('notifications.id'), nullable=False),
        sa.Column('channel', sa.String(16), nullable=False), sa.Column('status', sa.String(16), nullable=False),
        sa.Column('error_message', sa.String(100)), sa.Column('attempts', sa.Integer(), nullable=False),
        sa.Column('next_attempt_at', timestamp, nullable=False), sa.Column('sent_at', timestamp),
        sa.Column('created_at', timestamp, nullable=False),
        sa.UniqueConstraint('notification_id', 'channel', name='uq_notification_channel'))
    op.create_index('ix_notification_logs_notification_id', 'notification_logs', ['notification_id'])
    op.create_index('ix_notification_logs_status', 'notification_logs', ['status'])

    op.create_table('realtime_events',
        sa.Column('id', sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column('user_id', sa.String(36), sa.ForeignKey('users.id'), nullable=False),
        sa.Column('event', sa.String(64), nullable=False), sa.Column('data', sa.JSON(), nullable=False),
        sa.Column('created_at', timestamp, nullable=False))
    op.create_index('ix_realtime_user_cursor', 'realtime_events', ['user_id', 'id'])

    op.create_table('user_presence',
        sa.Column('id', sa.String(36), primary_key=True),
        sa.Column('user_id', sa.String(36), sa.ForeignKey('users.id'), nullable=False, unique=True),
        sa.Column('is_online', sa.Boolean(), nullable=False), sa.Column('last_seen_at', timestamp, nullable=False),
        sa.Column('updated_at', timestamp, nullable=False))

    op.create_table('presence_connections',
        sa.Column('id', sa.String(36), primary_key=True),
        sa.Column('user_id', sa.String(36), sa.ForeignKey('users.id'), nullable=False),
        sa.Column('session_id', sa.String(36), sa.ForeignKey('auth_sessions.id'), nullable=False),
        sa.Column('expires_at', timestamp, nullable=False))
    op.create_index('ix_presence_connections_user_id', 'presence_connections', ['user_id'])
    op.create_index('ix_presence_connections_expires_at', 'presence_connections', ['expires_at'])

    op.create_table('message_quotas',
        sa.Column('user_id', sa.String(36), sa.ForeignKey('users.id'), primary_key=True),
        sa.Column('window_start', timestamp, nullable=False), sa.Column('count', sa.Integer(), nullable=False))


def downgrade():
    op.drop_table('message_quotas')
    op.drop_index('ix_presence_connections_expires_at', table_name='presence_connections')
    op.drop_index('ix_presence_connections_user_id', table_name='presence_connections')
    op.drop_table('presence_connections')
    op.drop_table('user_presence')
    op.drop_index('ix_realtime_user_cursor', table_name='realtime_events')
    op.drop_table('realtime_events')
    op.drop_index('ix_notification_logs_status', table_name='notification_logs')
    op.drop_index('ix_notification_logs_notification_id', table_name='notification_logs')
    op.drop_table('notification_logs')
    op.drop_table('notification_preferences')
    op.drop_index('ix_notification_user_date', table_name='notifications')
    op.drop_table('notifications')
    op.drop_index('ix_message_revisions_message_id', table_name='message_revisions')
    op.drop_table('message_revisions')
    op.drop_index('ix_message_reads_message_id', table_name='message_reads')
    op.drop_table('message_reads')
    op.drop_table('message_attachments')
    op.drop_index('ix_message_conversation_cursor', table_name='messages')
    op.drop_index('ix_messages_sender_id', table_name='messages')
    op.drop_table('messages')
    op.drop_index('ix_conversation_participants_user_id', table_name='conversation_participants')
    op.drop_index('ix_conversation_participants_conversation_id', table_name='conversation_participants')
    op.drop_table('conversation_participants')
    op.drop_table('conversations')
