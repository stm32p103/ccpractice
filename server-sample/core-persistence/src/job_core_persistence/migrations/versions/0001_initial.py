"""最初のスキーマ(001・002・003 の表)。

以後の変更は、この版を変えず、新しい版として明示の操作(op.add_column など)で書く。
"""

from __future__ import annotations

from alembic import op

from job_core_persistence.models import metadata

revision = "0001"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    metadata.create_all(op.get_bind())


def downgrade() -> None:
    metadata.drop_all(op.get_bind())
