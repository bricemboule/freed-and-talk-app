"""Module 2 : profils utilisateurs et vérification professionnelle.

Revision ID: b73d2a814e60
Revises: a409de1d7d59
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.mysql import DATETIME

revision = 'b73d2a814e60'
down_revision = 'a409de1d7d59'
branch_labels = None
depends_on = None

Timestamp = sa.DateTime(timezone=True).with_variant(DATETIME(fsp=6), "mysql")


def upgrade():
    op.add_column('users', sa.Column('country', sa.String(100), nullable=True))
    op.add_column('users', sa.Column('city', sa.String(100), nullable=True))
    op.add_column('users', sa.Column('avatar_path', sa.String(100), nullable=True))
    op.create_table(
        'psychologist_profiles',
        sa.Column('id', sa.String(36), primary_key=True),
        sa.Column('user_id', sa.String(36), sa.ForeignKey('users.id'), nullable=False, unique=True),
        sa.Column('professional_title', sa.String(160), nullable=False),
        sa.Column('specialty', sa.String(160), nullable=False),
        sa.Column('years_of_experience', sa.Integer(), nullable=False),
        sa.Column('professional_registration_number', sa.String(160), nullable=True),
        sa.Column('bio', sa.Text(), nullable=False),
        sa.Column('languages', sa.JSON(), nullable=False),
        sa.Column('consultation_modes', sa.JSON(), nullable=False),
        sa.Column('verification_status', sa.String(32), nullable=False),
        sa.Column('rejection_reason', sa.Text(), nullable=True),
        sa.Column('suspension_reason', sa.Text(), nullable=True),
        sa.Column('submitted_at', Timestamp, nullable=True),
        sa.Column('approved_at', Timestamp, nullable=True),
        sa.Column('suspended_at', Timestamp, nullable=True),
        sa.Column('created_at', Timestamp, nullable=False),
        sa.Column('updated_at', Timestamp, nullable=False),
        sa.CheckConstraint('years_of_experience >= 0', name='ck_psychologist_experience'),
        sa.CheckConstraint("verification_status IN ('pending_documents', 'documents_submitted', "
                           "'under_review', 'approved', 'rejected', 'suspended')", name='ck_profile_status'),
    )
    op.create_index('ix_psychologist_profiles_verification_status', 'psychologist_profiles', ['verification_status'])
    op.create_table(
        'psychologist_documents',
        sa.Column('id', sa.String(36), primary_key=True),
        sa.Column('psychologist_id', sa.String(36), sa.ForeignKey('psychologist_profiles.id'), nullable=False),
        sa.Column('document_type', sa.String(40), nullable=False),
        sa.Column('description', sa.String(1000), nullable=True),
        sa.Column('file_name', sa.String(255), nullable=False),
        sa.Column('storage_path', sa.String(100), nullable=False, unique=True),
        sa.Column('mime_type', sa.String(80), nullable=False),
        sa.Column('file_size', sa.Integer(), nullable=False),
        sa.Column('status', sa.String(16), nullable=False),
        sa.Column('rejection_reason', sa.Text(), nullable=True),
        sa.Column('reviewed_by', sa.String(36), sa.ForeignKey('users.id'), nullable=True),
        sa.Column('reviewed_at', Timestamp, nullable=True),
        sa.Column('created_at', Timestamp, nullable=False),
        sa.Column('updated_at', Timestamp, nullable=False),
        sa.CheckConstraint("status IN ('pending', 'approved', 'rejected')", name='ck_document_status'),
    )
    op.create_index('ix_psychologist_documents_psychologist_id', 'psychologist_documents', ['psychologist_id'])
    op.create_table(
        'psychologist_verification_logs',
        sa.Column('id', sa.String(36), primary_key=True),
        sa.Column('psychologist_id', sa.String(36), sa.ForeignKey('psychologist_profiles.id'), nullable=False),
        sa.Column('admin_id', sa.String(36), sa.ForeignKey('users.id'), nullable=True),
        sa.Column('actor_id', sa.String(36), sa.ForeignKey('users.id'), nullable=False),
        sa.Column('document_id', sa.String(36), nullable=True),
        sa.Column('action', sa.String(64), nullable=False),
        sa.Column('reason', sa.Text(), nullable=True),
        sa.Column('previous_status', sa.String(32), nullable=False),
        sa.Column('new_status', sa.String(32), nullable=False),
        sa.Column('changes', sa.JSON(), nullable=True),
        sa.Column('created_at', Timestamp, nullable=False),
    )
    op.create_index('ix_psychologist_verification_logs_psychologist_id', 'psychologist_verification_logs', ['psychologist_id'])


def downgrade():
    op.drop_table('psychologist_verification_logs')
    op.drop_table('psychologist_documents')
    op.drop_table('psychologist_profiles')
    op.drop_column('users', 'avatar_path')
    op.drop_column('users', 'city')
    op.drop_column('users', 'country')
