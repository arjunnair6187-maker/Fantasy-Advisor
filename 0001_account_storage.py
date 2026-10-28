"""Create owner-scoped account and league storage.

Revision ID: 0001_account_storage
Revises:
"""

from alembic import op
import sqlalchemy as sa


revision = "0001_account_storage"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "app_users",
        sa.Column("user_id", sa.String(length=64), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("user_id"),
    )
    op.create_table(
        "provider_connections",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("user_id", sa.String(length=64), nullable=False),
        sa.Column("provider", sa.String(length=32), nullable=False),
        sa.Column("label", sa.String(length=120), nullable=False),
        sa.Column("credentials_ciphertext", sa.LargeBinary(), nullable=False),
        sa.Column("status", sa.String(length=20), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["user_id"], ["app_users.user_id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("user_id", "id", name="uq_provider_connection_owner_id"),
    )
    op.create_table(
        "fantasy_leagues",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("user_id", sa.String(length=64), nullable=False),
        sa.Column("provider_connection_id", sa.String(length=36), nullable=False),
        sa.Column("provider_league_id", sa.String(length=128), nullable=False),
        sa.Column("sport", sa.String(length=8), nullable=False),
        sa.Column("season", sa.Integer(), nullable=False),
        sa.Column("name", sa.String(length=200), nullable=False),
        sa.Column("scoring_settings", sa.JSON(), nullable=False),
        sa.Column("roster_settings", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["user_id"], ["app_users.user_id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(
            ["user_id", "provider_connection_id"],
            ["provider_connections.user_id", "provider_connections.id"],
            name="fk_league_owned_provider_connection",
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("user_id", "id", name="uq_league_owner_id"),
        sa.UniqueConstraint(
            "user_id", "provider_connection_id", "provider_league_id", "sport", "season",
            name="uq_user_provider_league_season",
        ),
    )
    op.create_table(
        "private_records",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("user_id", sa.String(length=64), nullable=False),
        sa.Column("league_id", sa.String(length=36), nullable=False),
        sa.Column("record_type", sa.String(length=48), nullable=False),
        sa.Column("record_key", sa.String(length=200), nullable=False),
        sa.Column("payload", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["user_id", "league_id"],
            ["fantasy_leagues.user_id", "fantasy_leagues.id"],
            name="fk_private_record_owned_league",
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "user_id", "league_id", "record_type", "record_key",
            name="uq_private_record_owner_key",
        ),
    )


def downgrade() -> None:
    op.drop_table("private_records")
    op.drop_table("fantasy_leagues")
    op.drop_table("provider_connections")
    op.drop_table("app_users")
