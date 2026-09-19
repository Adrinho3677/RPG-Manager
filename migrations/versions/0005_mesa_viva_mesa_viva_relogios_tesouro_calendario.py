"""mesa viva: relogios, tesouro, calendario, handouts e importacao

Revision ID: 0005_mesa_viva
Revises: 0004_mapa_tatico
Create Date: 2026-09-20 10:00:00

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = '0005_mesa_viva'
down_revision = '0004_mapa_tatico'
branch_labels = None
depends_on = None


def upgrade():
    op.create_table('clocks',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('campaign_id', sa.Integer(), nullable=False),
    sa.Column('title', sa.String(length=120), nullable=False),
    sa.Column('segments', sa.Integer(), nullable=False),
    sa.Column('filled', sa.Integer(), nullable=False),
    sa.Column('color', sa.String(length=9), nullable=True),
    sa.Column('visibility', sa.String(length=12), nullable=True),
    sa.Column('position', sa.Integer(), nullable=True),
    sa.Column('created_at', sa.DateTime(), nullable=True),
    sa.Column('updated_at', sa.DateTime(), nullable=True),
    sa.ForeignKeyConstraint(['campaign_id'], ['campaigns.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id')
    )
    with op.batch_alter_table('clocks', schema=None) as batch_op:
        batch_op.create_index(batch_op.f('ix_clocks_campaign_id'), ['campaign_id'], unique=False)

    with op.batch_alter_table('campaigns', schema=None) as batch_op:
        batch_op.add_column(sa.Column('spotlight', sa.Text(), nullable=True))
        batch_op.add_column(sa.Column('treasure', sa.Text(), nullable=True))
        batch_op.add_column(sa.Column('calendar', sa.Text(), nullable=True))

    with op.batch_alter_table('characters', schema=None) as batch_op:
        batch_op.add_column(sa.Column('imported_owner', sa.String(length=64), nullable=True))

    with op.batch_alter_table('game_sessions', schema=None) as batch_op:
        batch_op.add_column(sa.Column('world_day', sa.Integer(), nullable=True))

    with op.batch_alter_table('timeline_entries', schema=None) as batch_op:
        batch_op.add_column(sa.Column('world_day', sa.Integer(), nullable=True))


def downgrade():
    with op.batch_alter_table('timeline_entries', schema=None) as batch_op:
        batch_op.drop_column('world_day')
    with op.batch_alter_table('game_sessions', schema=None) as batch_op:
        batch_op.drop_column('world_day')
    with op.batch_alter_table('characters', schema=None) as batch_op:
        batch_op.drop_column('imported_owner')
    with op.batch_alter_table('campaigns', schema=None) as batch_op:
        batch_op.drop_column('calendar')
        batch_op.drop_column('treasure')
        batch_op.drop_column('spotlight')
    with op.batch_alter_table('clocks', schema=None) as batch_op:
        batch_op.drop_index(batch_op.f('ix_clocks_campaign_id'))
    op.drop_table('clocks')
