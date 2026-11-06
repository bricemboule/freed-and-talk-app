"""Expose consultations as participant-owned resources with a type."""
from alembic import op
import sqlalchemy as sa

revision = '8ab7130c5f22'
down_revision = '6d2c90ab11f7'
branch_labels = None
depends_on = None


def upgrade():
    op.add_column('consultations', sa.Column(
        'consultation_type', sa.String(16), nullable=False, server_default='video'))
    op.execute("UPDATE consultations SET consultation_type='in_person' WHERE appointment_id IN "
               "(SELECT id FROM appointments WHERE consultation_mode='in_person')")
    with op.batch_alter_table('consultations') as batch:
        batch.create_check_constraint('ck_consultation_type',
            "consultation_type IN ('video','audio','phone','in_person')")


def downgrade():
    with op.batch_alter_table('consultations') as batch:
        batch.drop_constraint('ck_consultation_type', type_='check')
        batch.drop_column('consultation_type')
