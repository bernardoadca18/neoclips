"""Add completed_with_errors status to discovery_runs.

Revision ID: 0009_discovery_run_completed_with_errors
Revises: 0008_durable_orchestration
Create Date: 2026-08-31

"""
from collections.abc import Sequence

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0009_discovery_run_completed_with_errors"
down_revision: str | None = "0008_durable_orchestration"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # Drop the old check constraint
    op.drop_constraint("ck_discovery_run_status", "discovery_runs", type_="check")

    # Create new check constraint with completed_with_errors status
    op.create_check_constraint(
        "ck_discovery_run_status",
        "discovery_runs",
        "status IN ('pending', 'running', 'completed', 'completed_with_errors', 'failed')",
    )


def downgrade() -> None:
    # Drop the new check constraint
    op.drop_constraint("ck_discovery_run_status", "discovery_runs", type_="check")

    # Recreate the old check constraint without completed_with_errors
    op.create_check_constraint(
        "ck_discovery_run_status",
        "discovery_runs",
        "status IN ('pending', 'running', 'completed', 'failed')",
    )
