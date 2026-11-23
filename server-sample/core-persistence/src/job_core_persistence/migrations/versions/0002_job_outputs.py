"""004: ジョブのログのチャンクと成果物の参照の表を加える。

0001(最初の版)は metadata.create_all で、その時点の models のすべての表を作る。新しい表は、0001
の実行で既に作られることが
あるため、この版は checkfirst で冪等にする(空の DB から最新まで、003 の最新からの更新の両方で同じ結果になる)。
"""

from __future__ import annotations

from alembic import op

from job_core_persistence.models import job_artifacts, job_log_chunks

revision = "0002"
down_revision = "0001"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    job_log_chunks.create(bind, checkfirst=True)
    job_artifacts.create(bind, checkfirst=True)


def downgrade() -> None:
    bind = op.get_bind()
    job_artifacts.drop(bind, checkfirst=True)
    job_log_chunks.drop(bind, checkfirst=True)
