"""Journaliser les actions de modération et de publication administratives.

Revision ID: 4f2c880c3940
Revises: ef8a24d507c1
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import mysql

revision = '4f2c880c3940'
down_revision = 'ef8a24d507c1'
branch_labels = None
depends_on = None
timestamp = sa.DateTime(timezone=True).with_variant(mysql.DATETIME(fsp=6), 'mysql')


def upgrade():
    op.create_table('admin_audit_logs',
        sa.Column('id', sa.String(36), nullable=False),
        sa.Column('actor_id', sa.String(36), nullable=False),
        sa.Column('action', sa.String(64), nullable=False),
        sa.Column('object_type', sa.String(32), nullable=False),
        sa.Column('object_id', sa.String(36), nullable=False),
        sa.Column('details', sa.JSON()), sa.Column('created_at', timestamp, nullable=False),
        sa.ForeignKeyConstraint(['actor_id'], ['users.id']), sa.PrimaryKeyConstraint('id'))
    op.create_index('ix_admin_audit_logs_actor_id', 'admin_audit_logs', ['actor_id'])
    op.create_index('ix_admin_audit_actor_date', 'admin_audit_logs', ['actor_id', 'created_at'])
    op.create_index('ix_admin_audit_object', 'admin_audit_logs', ['object_type', 'object_id'])


def downgrade():
    op.drop_index('ix_admin_audit_object', table_name='admin_audit_logs')
    op.drop_index('ix_admin_audit_actor_date', table_name='admin_audit_logs')
    op.drop_index('ix_admin_audit_logs_actor_id', table_name='admin_audit_logs')
    op.drop_table('admin_audit_logs')
