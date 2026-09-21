"""expand critical_location_category enum with live-OSM-only values

Revision ID: c2d3e4f5a6b7
Revises: b6c7d8e9f0a1
Create Date: 2026-09-13 12:00:00.000000

Part 10 (spec #3) — extend ``critical_location_category`` with
``PUBLIC_FACILITY`` and ``GOVERNMENT_BUILDING``.

These categories are used ONLY for ``GeoPlace`` rows resolved from live
OpenStreetMap / Overpass responses (community centres, libraries, markets,
places of worship, government offices, town halls, …). No row is ever inserted
into ``critical_locations`` with these values, so the enum values exist purely
so every spatial lookup can filter evenly and the public API / context schema
can surface them without casting. ``ROAD`` remains a separate look-me-up
category (reported as nearby major roads, not infrastructure).

Note: Postgres cannot remove an enum value, so the downgrade is a no-op. The
two extra values simply become unused labels, matching the pre-spec state.
"""

from collections.abc import Sequence

from alembic import op

revision: str = "c2d3e4f5a6b7"
down_revision: str | None = "b6c7d8e9f0a1"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    bind = op.get_bind()
    if bind.dialect.name != "postgresql":
        return
    op.execute("ALTER TYPE critical_location_category ADD VALUE IF NOT EXISTS 'PUBLIC_FACILITY'")
    op.execute(
        "ALTER TYPE critical_location_category ADD VALUE IF NOT EXISTS 'GOVERNMENT_BUILDING'"
    )


def downgrade() -> None:
    # Postgres has no ALTER TYPE ... DROP VALUE; leaving the two extra labels
    # in place is safe (the downgrade restores schema equivalence).
    pass
