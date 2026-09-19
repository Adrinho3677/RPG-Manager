"""mapa tatico dos combates

Revision ID: 0004_mapa_tatico
Revises: 0003_historico_login
Create Date: 2026-09-19 10:00:00

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = '0004_mapa_tatico'
down_revision = '0003_historico_login'
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table('encounters', schema=None) as batch_op:
        batch_op.add_column(sa.Column('board', sa.Text(), nullable=True))


def downgrade():
    with op.batch_alter_table('encounters', schema=None) as batch_op:
        batch_op.drop_column('board')
