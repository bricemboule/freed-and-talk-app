"""Tarifs par psychologue et demandes de paiement en mode test."""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.mysql import DATETIME

revision = '6d2c90ab11f7'
down_revision = '95be1a3715ca'
branch_labels = None
depends_on = None

Timestamp = sa.DateTime(timezone=True).with_variant(DATETIME(fsp=6), 'mysql')


def upgrade():
    op.add_column('psychologist_profiles', sa.Column('consultation_fee', sa.Integer(), nullable=True))
    op.add_column('psychologist_profiles', sa.Column('consultation_currency', sa.String(3), nullable=False, server_default='XAF'))
    with op.batch_alter_table('psychologist_profiles') as batch:
        batch.create_check_constraint('ck_psychologist_fee',
                                      'consultation_fee IS NULL OR consultation_fee >= 0')
    op.add_column('appointments', sa.Column('fee_amount', sa.Integer(), nullable=True))
    op.add_column('appointments', sa.Column('fee_currency', sa.String(3), nullable=True))
    op.create_table(
        'payments',
        sa.Column('id', sa.String(36), primary_key=True),
        sa.Column('appointment_id', sa.String(36), sa.ForeignKey('appointments.id'), nullable=False),
        sa.Column('user_id', sa.String(36), sa.ForeignKey('users.id'), nullable=False),
        sa.Column('provider', sa.String(24), nullable=False),
        sa.Column('provider_reference', sa.String(100), nullable=False, unique=True),
        sa.Column('idempotency_key', sa.String(100), nullable=False),
        sa.Column('amount', sa.Integer(), nullable=False),
        sa.Column('currency', sa.String(3), nullable=False),
        sa.Column('status', sa.String(16), nullable=False),
        sa.Column('created_at', Timestamp, nullable=False),
        sa.Column('updated_at', Timestamp, nullable=False),
        sa.CheckConstraint("status IN ('pending','processing','paid','failed','cancelled','refunded')", name='ck_payment_status'),
        sa.CheckConstraint("provider IN ('orange_money','mtn_momo','mobile_money','card')", name='ck_payment_provider'),
        sa.CheckConstraint('amount >= 0', name='ck_payment_amount'),
        sa.UniqueConstraint('user_id', 'idempotency_key', name='uq_payment_idempotency'),
    )
    op.create_index('ix_payments_appointment_id', 'payments', ['appointment_id'])
    op.create_index('ix_payments_user_id', 'payments', ['user_id'])
    op.create_index('ix_payments_status', 'payments', ['status'])
    op.create_index('ix_payment_user_created', 'payments', ['user_id', 'created_at'])
    op.create_index('ix_payment_status_created', 'payments', ['status', 'created_at'])
    op.create_table(
        'payment_events',
        sa.Column('id', sa.String(36), primary_key=True),
        sa.Column('payment_id', sa.String(36), sa.ForeignKey('payments.id', ondelete='CASCADE'), nullable=False),
        sa.Column('status', sa.String(16), nullable=False),
        sa.Column('source', sa.String(32), nullable=False),
        sa.Column('details', sa.JSON(), nullable=True),
        sa.Column('created_at', Timestamp, nullable=False),
    )
    op.create_index('ix_payment_event_payment_date', 'payment_events', ['payment_id', 'created_at'])


def downgrade():
    op.drop_index('ix_payment_event_payment_date', table_name='payment_events')
    op.drop_table('payment_events')
    op.drop_index('ix_payment_status_created', table_name='payments')
    op.drop_index('ix_payment_user_created', table_name='payments')
    op.drop_index('ix_payments_status', table_name='payments')
    op.drop_index('ix_payments_user_id', table_name='payments')
    op.drop_index('ix_payments_appointment_id', table_name='payments')
    op.drop_table('payments')
    op.drop_column('appointments', 'fee_currency')
    op.drop_column('appointments', 'fee_amount')
    with op.batch_alter_table('psychologist_profiles') as batch:
        batch.drop_constraint('ck_psychologist_fee', type_='check')
    op.drop_column('psychologist_profiles', 'consultation_currency')
    op.drop_column('psychologist_profiles', 'consultation_fee')
