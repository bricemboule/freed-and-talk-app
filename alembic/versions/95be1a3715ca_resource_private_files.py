"""Fichiers multimédias stockés en privé pour le catalogue de ressources.

Revision ID: 95be1a3715ca
Revises: 4f2c880c3940
"""
from alembic import op
import sqlalchemy as sa

revision = '95be1a3715ca'
down_revision = '4f2c880c3940'
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table('resources') as batch:
        batch.alter_column('url', existing_type=sa.String(length=2000), nullable=True)
        batch.add_column(sa.Column('storage_path', sa.String(100), nullable=True))
        batch.add_column(sa.Column('file_name', sa.String(255), nullable=True))
        batch.add_column(sa.Column('mime_type', sa.String(100), nullable=True))
        batch.add_column(sa.Column('file_size', sa.Integer(), nullable=True))
        batch.create_index('ix_resources_storage_path', ['storage_path'], unique=True)


def downgrade():
    with op.batch_alter_table('resources') as batch:
        batch.drop_index('ix_resources_storage_path')
        batch.drop_column('file_size')
        batch.drop_column('mime_type')
        batch.drop_column('file_name')
        batch.drop_column('storage_path')
    # Keep url nullable so rows represented solely by a private file remain valid.
