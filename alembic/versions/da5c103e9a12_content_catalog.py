"""Articles et ressources de la bibliothèque publique.

Revision ID: da5c103e9a12
Revises: c91a7f02d31e
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import mysql

revision = 'da5c103e9a12'
down_revision = 'c91a7f02d31e'
branch_labels = None
depends_on = None
timestamp = sa.DateTime(timezone=True).with_variant(mysql.DATETIME(fsp=6), 'mysql')


def upgrade():
    op.create_table('articles',
        sa.Column('id', sa.String(36), nullable=False),
        sa.Column('slug', sa.String(180), nullable=False),
        sa.Column('title', sa.String(240), nullable=False),
        sa.Column('excerpt', sa.String(1000), nullable=False),
        sa.Column('body', sa.Text(), nullable=False),
        sa.Column('is_published', sa.Boolean(), nullable=False),
        sa.Column('author_id', sa.String(36), nullable=False),
        sa.Column('published_at', timestamp), sa.Column('deleted_at', timestamp),
        sa.Column('created_at', timestamp, nullable=False), sa.Column('updated_at', timestamp, nullable=False),
        sa.ForeignKeyConstraint(['author_id'], ['users.id']), sa.PrimaryKeyConstraint('id'))
    op.create_index('ix_articles_slug', 'articles', ['slug'], unique=True)
    op.create_index('ix_articles_publication', 'articles', ['is_published', 'published_at'])

    op.create_table('resources',
        sa.Column('id', sa.String(36), nullable=False),
        sa.Column('resource_type', sa.String(16), nullable=False),
        sa.Column('title', sa.String(240), nullable=False),
        sa.Column('description', sa.String(2000), nullable=False),
        sa.Column('url', sa.String(2000), nullable=False),
        sa.Column('is_published', sa.Boolean(), nullable=False),
        sa.Column('author_id', sa.String(36), nullable=False),
        sa.Column('deleted_at', timestamp), sa.Column('created_at', timestamp, nullable=False),
        sa.Column('updated_at', timestamp, nullable=False),
        sa.CheckConstraint("resource_type IN ('article','video','audio','pdf','guide')", name='ck_resource_type'),
        sa.ForeignKeyConstraint(['author_id'], ['users.id']), sa.PrimaryKeyConstraint('id'))
    op.create_index('ix_resources_resource_type', 'resources', ['resource_type'])
    op.create_index('ix_resources_publication', 'resources', ['is_published', 'resource_type', 'created_at'])


def downgrade():
    op.drop_index('ix_resources_publication', table_name='resources')
    op.drop_index('ix_resources_resource_type', table_name='resources')
    op.drop_table('resources')
    op.drop_index('ix_articles_publication', table_name='articles')
    op.drop_index('ix_articles_slug', table_name='articles')
    op.drop_table('articles')
