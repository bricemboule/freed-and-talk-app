"""Store optional birth date for psychologist registration and private profiles."""
from alembic import op
import sqlalchemy as sa

revision = 'b1a77d5c30e4'
down_revision = '8ab7130c5f22'
branch_labels = None
depends_on = None


def upgrade():
    op.add_column('users', sa.Column('date_of_birth', sa.Date(), nullable=True))


def downgrade():
    op.drop_column('users', 'date_of_birth')
