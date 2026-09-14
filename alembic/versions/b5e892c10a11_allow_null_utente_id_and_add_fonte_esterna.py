"""allow_null_utente_id_and_add_fonte_esterna

Revision ID: b5e892c10a11
Revises: a4540615c800
Create Date: 2026-09-14 23:40:00.000000

"""
from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'b5e892c10a11'
down_revision: Union[str, Sequence[str], None] = 'a4540615c800'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema: disaccoppia annunci scraped dagli account utente."""
    with op.batch_alter_table('annunci', schema=None) as batch_op:
        batch_op.alter_column('utente_id', existing_type=sa.Integer(), nullable=True)
        batch_op.add_column(sa.Column('fonte_esterna', sa.String(length=200), nullable=True))
        batch_op.create_index(batch_op.f('ix_annunci_fonte_esterna'), ['fonte_esterna'], unique=False)
        batch_op.add_column(sa.Column('source_id_esterno', sa.String(length=100), nullable=True))
        batch_op.create_index(batch_op.f('ix_annunci_source_id_esterno'), ['source_id_esterno'], unique=False)


def downgrade() -> None:
    """Downgrade schema."""
    with op.batch_alter_table('annunci', schema=None) as batch_op:
        batch_op.drop_index(batch_op.f('ix_annunci_source_id_esterno'))
        batch_op.drop_column('source_id_esterno')
        batch_op.drop_index(batch_op.f('ix_annunci_fonte_esterna'))
        batch_op.drop_column('fonte_esterna')
        batch_op.alter_column('utente_id', existing_type=sa.Integer(), nullable=False)
