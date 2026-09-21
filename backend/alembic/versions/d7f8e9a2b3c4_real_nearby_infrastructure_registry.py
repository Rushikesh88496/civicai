"""real nearby infrastructure registry on critical_locations

Revision ID: d7f8e9a2b3c4
Revises: c2d3e4f5a6b7
Create Date: 2026-09-21 09:30:00.000000

Part 35 — Real Nearby Infrastructure Data System. The verified facility
registry (``critical_locations``) gains real-data provenance and explicit
data-quality semantics:

* ``source`` / ``source_dataset`` / ``source_url`` / ``source_id`` — where each
  record actually came from (OpenStreetMap Overpass, PMC, NIGP, UDISE, ...) plus
  the external id used for idempotent de-duplicated upserts.
* ``verification_status`` — the honest data-quality state (``FOUND`` /
  ``NO_VERIFIED_RECORDS`` / ``DATA_UNAVAILABLE`` / ``PARTIAL_DATA`` /
  ``PENDING_VERIFICATION``), never guessed.
* ``last_verified_at`` — freshness stamp of the registry record.
* ``metadata`` (JSONB) — structured extra fields from the source (OSM tags, the
  import batch, ward provenance, etc.).
* ``ward_id`` — the operational ward (WARD-1..WARD-4) resolved by point-in-
  polygon at ingestion time.
* ``is_active`` — hard-gate flag so records can be retired without deletion.
* latitude / longitude / geom become nullable so records whose coordinates
  could not be resolved are kept as ``PENDING_VERIFICATION`` candidates instead
  of being invented.

Indexes: GiST on geom already exists (``idx_critical_locations_geom``);
add b-tree indexes for status / ward / source / is_active and a partial unique
index on (``source``, ``source_id``) enforcing provenance-level uniqueness for
idempotent ingestion.
"""

from collections.abc import Sequence

from sqlalchemy import text
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "d7f8e9a2b3c4"
down_revision: str | None = "c2d3e4f5a6b7"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    postgresql.ENUM(
        "FOUND",
        "NO_VERIFIED_RECORDS",
        "DATA_UNAVAILABLE",
        "PARTIAL_DATA",
        "PENDING_VERIFICATION",
        name="infrastructure_data_status",
    ).create(op.get_bind(), checkfirst=True)

    # Coordinate + geometry become nullable so unresolvable records stay honest.
    op.alter_column(
        "critical_locations",
        "latitude",
        existing_type=postgresql.DOUBLE_PRECISION(),
        nullable=True,
    )
    op.alter_column(
        "critical_locations",
        "longitude",
        existing_type=postgresql.DOUBLE_PRECISION(),
        nullable=True,
    )
    op.execute("ALTER TABLE critical_locations ALTER COLUMN geom DROP NOT NULL")

    op.execute("ALTER TABLE critical_locations ADD COLUMN source VARCHAR(64)")
    op.execute("ALTER TABLE critical_locations ADD COLUMN source_dataset VARCHAR(255)")
    op.execute("ALTER TABLE critical_locations ADD COLUMN source_url TEXT")
    op.execute("ALTER TABLE critical_locations ADD COLUMN source_id VARCHAR(255)")
    op.execute(
        "ALTER TABLE critical_locations ADD COLUMN verification_status infrastructure_data_status "
        "NOT NULL DEFAULT 'FOUND'"
    )
    op.execute(
        "ALTER TABLE critical_locations ADD COLUMN last_verified_at TIMESTAMP WITH TIME ZONE"
    )
    op.execute('ALTER TABLE critical_locations ADD COLUMN "metadata" JSONB')
    op.execute(
        "ALTER TABLE critical_locations ADD COLUMN ward_id UUID REFERENCES wards(id) ON DELETE RESTRICT"
    )
    op.execute(
        "ALTER TABLE critical_locations ADD COLUMN is_active BOOLEAN NOT NULL DEFAULT TRUE"
    )
    # Existing records that predate the real registry are unverified until a real
    # source re-imports them; none are claimed as verified facts.
    op.execute(
        "UPDATE critical_locations SET verification_status = 'PENDING_VERIFICATION' WHERE is_demo = TRUE"
    )
    op.execute("UPDATE critical_locations SET last_verified_at = updated_at WHERE last_verified_at IS NULL")

    op.create_index("ix_critical_locations_verification_status", "critical_locations", ["verification_status"], unique=False)
    op.create_index("ix_critical_locations_ward_id", "critical_locations", ["ward_id"], unique=False)
    op.create_index("ix_critical_locations_is_active", "critical_locations", ["is_active"], unique=False)
    op.create_index("ix_critical_locations_source_id", "critical_locations", ["source_id"], unique=False)
    op.create_index("ix_critical_locations_source", "critical_locations", ["source"], unique=False)
    op.create_index(
        "uix_critical_locations_source_source_id",
        "critical_locations",
        ["source", "source_id"],
        unique=True,
        postgresql_where=text("source_id IS NOT NULL"),
    )


def downgrade() -> None:
    op.drop_index("uix_critical_locations_source_source_id", table_name="critical_locations")
    op.drop_index("ix_critical_locations_source", table_name="critical_locations")
    op.drop_index("ix_critical_locations_source_id", table_name="critical_locations")
    op.drop_index("ix_critical_locations_is_active", table_name="critical_locations")
    op.drop_index("ix_critical_locations_ward_id", table_name="critical_locations")
    op.drop_index("ix_critical_locations_verification_status", table_name="critical_locations")

    op.execute('ALTER TABLE critical_locations DROP COLUMN IF EXISTS "metadata"')
    op.execute("ALTER TABLE critical_locations DROP COLUMN IF EXISTS is_active")
    op.execute("ALTER TABLE critical_locations DROP COLUMN IF EXISTS ward_id")
    op.execute("ALTER TABLE critical_locations DROP COLUMN IF EXISTS last_verified_at")
    op.execute("ALTER TABLE critical_locations DROP COLUMN IF EXISTS verification_status")
    op.execute("ALTER TABLE critical_locations DROP COLUMN IF EXISTS source_id")
    op.execute("ALTER TABLE critical_locations DROP COLUMN IF EXISTS source_url")
    op.execute("ALTER TABLE critical_locations DROP COLUMN IF EXISTS source_dataset")
    op.execute("ALTER TABLE critical_locations DROP COLUMN IF EXISTS source")
    op.execute("ALTER TABLE critical_locations ALTER COLUMN geom SET NOT NULL")
    op.alter_column(
        "critical_locations",
        "longitude",
        existing_type=postgresql.DOUBLE_PRECISION(),
        nullable=False,
    )
    op.alter_column(
        "critical_locations",
        "latitude",
        existing_type=postgresql.DOUBLE_PRECISION(),
        nullable=False,
    )

    op.execute("DROP TYPE IF EXISTS infrastructure_data_status")