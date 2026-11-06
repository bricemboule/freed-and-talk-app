"""Avis soumis après rendez-vous terminé et modération administrative.

Revision ID: ef8a24d507c1
Revises: da5c103e9a12
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import mysql

revision = 'ef8a24d507c1'
down_revision = 'da5c103e9a12'
branch_labels = None
depends_on = None
timestamp = sa.DateTime(timezone=True).with_variant(mysql.DATETIME(fsp=6), 'mysql')


def upgrade():
    op.create_table('psychologist_reviews',
        sa.Column('id', sa.String(36), nullable=False),
        sa.Column('appointment_id', sa.String(36), nullable=False),
        sa.Column('psychologist_id', sa.String(36), nullable=False),
        sa.Column('author_id', sa.String(36), nullable=False),
        sa.Column('rating', sa.Integer(), nullable=False), sa.Column('content', sa.Text(), nullable=False),
        sa.Column('status', sa.String(16), nullable=False),
        sa.Column('reviewed_by', sa.String(36)), sa.Column('reviewed_at', timestamp),
        sa.Column('rejection_reason', sa.String(1000)), sa.Column('deleted_at', timestamp),
        sa.Column('created_at', timestamp, nullable=False), sa.Column('updated_at', timestamp, nullable=False),
        sa.CheckConstraint('rating >= 1 AND rating <= 5', name='ck_review_rating'),
        sa.CheckConstraint("status IN ('pending','approved','rejected')", name='ck_review_status'),
        sa.ForeignKeyConstraint(['appointment_id'], ['appointments.id']),
        sa.ForeignKeyConstraint(['author_id'], ['users.id']),
        sa.ForeignKeyConstraint(['psychologist_id'], ['psychologist_profiles.id']),
        sa.ForeignKeyConstraint(['reviewed_by'], ['users.id']),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('appointment_id', name='uq_review_appointment'))
    op.create_index('ix_psychologist_reviews_psychologist_id', 'psychologist_reviews', ['psychologist_id'])
    op.create_index('ix_psychologist_reviews_author_id', 'psychologist_reviews', ['author_id'])
    op.create_index('ix_psychologist_reviews_status', 'psychologist_reviews', ['status'])
    op.create_index('ix_review_public', 'psychologist_reviews', ['psychologist_id', 'status', 'created_at'])


def downgrade():
    op.drop_index('ix_review_public', table_name='psychologist_reviews')
    op.drop_index('ix_psychologist_reviews_status', table_name='psychologist_reviews')
    op.drop_index('ix_psychologist_reviews_author_id', table_name='psychologist_reviews')
    op.drop_index('ix_psychologist_reviews_psychologist_id', table_name='psychologist_reviews')
    op.drop_table('psychologist_reviews')
