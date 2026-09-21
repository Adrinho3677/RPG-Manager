"""hora no mundo e edicao da linha do tempo

Revision ID: 0007_horas_no_mundo
Revises: 0006_ferramentas
Create Date: 2026-09-21 10:00:00

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = '0007_horas_no_mundo'
down_revision = '0006_ferramentas'
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table('game_sessions', schema=None) as batch_op:
        batch_op.add_column(sa.Column('world_minute', sa.Integer(), nullable=True))

    with op.batch_alter_table('timeline_entries', schema=None) as batch_op:
        batch_op.add_column(sa.Column('world_minute', sa.Integer(), nullable=True))
        batch_op.add_column(sa.Column('updated_at', sa.DateTime(), nullable=True))


def downgrade():
    with op.batch_alter_table('timeline_entries', schema=None) as batch_op:
        batch_op.drop_column('updated_at')
        batch_op.drop_column('world_minute')

    with op.batch_alter_table('game_sessions', schema=None) as batch_op:
        batch_op.drop_column('world_minute')
