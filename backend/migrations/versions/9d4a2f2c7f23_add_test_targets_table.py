"""add test targets table

Revision ID: 9d4a2f2c7f23
Revises: 418e1d2f64eb
Create Date: 2026-03-23 11:18:00.000000

"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "9d4a2f2c7f23"
down_revision: Union[str, Sequence[str], None] = "418e1d2f64eb"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Dlya sebya: dobavlyaem profile podklyucheniya k raznym VM/sborkam.
    op.create_table(
        "test_targets",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("name", sa.String(length=120), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column("ishd_host", sa.String(length=255), nullable=False),
        sa.Column("ishd_port", sa.Integer(), nullable=False, server_default="50200"),
        sa.Column("ishd_host_id", sa.String(length=255), nullable=False),
        sa.Column("ishd_software_name", sa.String(length=255), nullable=False),
        sa.Column("ishd_login", sa.String(length=255), nullable=True),
        sa.Column("ishd_password", sa.String(length=255), nullable=True),
        sa.Column("ishd_target_host_id", sa.String(length=255), nullable=False, server_default="paragraf"),
        sa.Column("ishd_target_host_ids", sa.String(length=1024), nullable=False, server_default="paragraf"),
        sa.Column("ishd_target_recipient", sa.String(length=255), nullable=True),
        sa.Column("ishd_default_port", sa.Integer(), nullable=False, server_default="8080"),
        sa.Column("ishd_request_timeout_sec", sa.Float(), nullable=False, server_default="5"),
        sa.Column("ishd_doc_response_timeout_sec", sa.Float(), nullable=False, server_default="10"),
        sa.Column("ishd_action_direct_timeout_sec", sa.Float(), nullable=False, server_default="1"),
        sa.Column("ishd_action_result_timeout_sec", sa.Float(), nullable=False, server_default="5"),
        sa.Column("paragraph_rest_base_url", sa.String(length=255), nullable=True),
        sa.Column("paragraph_db_dsn", sa.String(length=1024), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("name"),
    )
    op.create_index(op.f("ix_test_targets_id"), "test_targets", ["id"], unique=False)
    op.create_index(op.f("ix_test_targets_name"), "test_targets", ["name"], unique=True)
    op.create_index(op.f("ix_test_targets_is_active"), "test_targets", ["is_active"], unique=False)


def downgrade() -> None:
    # Dlya sebya: otkat migracii test-target profiley.
    op.drop_index(op.f("ix_test_targets_is_active"), table_name="test_targets")
    op.drop_index(op.f("ix_test_targets_name"), table_name="test_targets")
    op.drop_index(op.f("ix_test_targets_id"), table_name="test_targets")
    op.drop_table("test_targets")

