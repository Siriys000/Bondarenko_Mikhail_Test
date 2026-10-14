"""Create the price history and its idempotency constraint."""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0001"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "prices",
        sa.Column("id", sa.BigInteger(), primary_key=True),
        sa.Column("ticker", sa.String(7), nullable=False),
        sa.Column("price", sa.Numeric(28, 12), nullable=False),
        sa.Column("timestamp", sa.BigInteger(), nullable=False),
        sa.Column("collection_slot", sa.BigInteger(), nullable=False),
        sa.UniqueConstraint("ticker", "collection_slot", name="uq_prices_ticker_slot"),
        sa.CheckConstraint("price > 0", name="ck_prices_positive_price"),
        sa.CheckConstraint("timestamp >= 0", name="ck_prices_timestamp"),
        sa.CheckConstraint(
            "collection_slot >= 0 AND collection_slot % 60 = 0", name="ck_prices_minute_slot"
        ),
        sa.CheckConstraint("ticker IN ('btc_usd', 'eth_usd')", name="ck_prices_ticker"),
    )
    op.create_index("ix_prices_ticker_timestamp_id", "prices", ["ticker", "timestamp", "id"])


def downgrade() -> None:
    op.drop_index("ix_prices_ticker_timestamp_id", table_name="prices")
    op.drop_table("prices")
