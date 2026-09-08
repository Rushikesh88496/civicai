"""Hotspot grid geometry (Part 23).

A uniform lat/lon mesh over the demo city bounding box. Each ~1.1 km cell is a
prediction unit for the Predictive Civic Hotspots model. Cell identities are
deterministic so training, live inference and the map all agree on the same set
of cells.

Only pure-python geometry lives here (no DB, no ML), so it is trivially
testable and reusable by every pipeline stage.
"""

from __future__ import annotations

import math


class HotspotGrid:
    """A fixed mesh of ``cell_deg`` x ``cell_deg`` squares over a bounding box.

    Cells are indexed by ``"r{c_row}c{c_col}"`` where ``row`` grows with
    latitude and ``column`` grows with longitude. The cell id is derived from
    the cell's *lower-left* corner so the mapping (lat, lon) -> cell -> id is
    deterministic and invertible.
    """

    def __init__(
        self,
        min_lat: float,
        min_lon: float,
        max_lat: float,
        max_lon: float,
        cell_deg: float,
    ):
        if not (min_lat < max_lat and min_lon < max_lon and cell_deg > 0):
            raise ValueError("Grid requires min < max coordinates and cell_deg > 0")
        self.min_lat = min_lat
        self.min_lon = min_lon
        self.max_lat = max_lat
        self.max_lon = max_lon
        self.cell_deg = cell_deg
        self.n_rows = max(1, math.ceil((max_lat - min_lat) / cell_deg))
        self.n_cols = max(1, math.ceil((max_lon - min_lon) / cell_deg))
        self._cells = sorted(self.all_cells())

    def _row_col(self, lat: float, lon: float) -> tuple[int, int] | None:
        """Lower-left cell index for a point, or None when outside the grid."""
        if not (self.min_lat <= lat < self.max_lat and self.min_lon <= lon < self.max_lon):
            return None
        row = math.floor((lat - self.min_lat) / self.cell_deg)
        col = math.floor((lon - self.min_lon) / self.cell_deg)
        row = min(row, self.n_rows - 1)
        col = min(col, self.n_cols - 1)
        return row, col

    def cell_id(self, lat: float, lon: float) -> str | None:
        rc = self._row_col(lat, lon)
        if rc is None:
            return None
        return f"r{rc[0]}c{rc[1]}"

    def cell_bounds(self, cell_id: str) -> tuple[float, float, float, float]:
        """Lower-left (lat, lon) and upper-right (lat, lon) of a cell."""
        row, col = self.parse(cell_id)
        lat0 = self.min_lat + row * self.cell_deg
        lon0 = self.min_lon + col * self.cell_deg
        return lat0, lon0, lat0 + self.cell_deg, lon0 + self.cell_deg

    def cell_centroid(self, cell_id: str) -> tuple[float, float]:
        lat0, lon0, lat1, lon1 = self.cell_bounds(cell_id)
        return (lat0 + lat1) / 2, (lon0 + lon1) / 2

    def neighbors(self, cell_id: str) -> list[str]:
        """4-connectivity neighbors that exist inside the grid."""
        row, col = self.parse(cell_id)
        out = []
        for dr, dc in ((1, 0), (-1, 0), (0, 1), (0, -1)):
            r, c = row + dr, col + dc
            if 0 <= r < self.n_rows and 0 <= c < self.n_cols:
                out.append(f"r{r}c{c}")
        return out

    @staticmethod
    def parse(cell_id: str) -> tuple[int, int]:
        """``r{c_row}c{c_col}`` -> ``(row, col)``."""
        body = cell_id[len("r") :]
        row_str, col_str = body.split("c", 1)
        return int(row_str), int(col_str)

    def all_cells(self) -> list[str]:
        return [f"r{r}c{c}" for r in range(self.n_rows) for c in range(self.n_cols)]

    def __len__(self) -> int:
        return len(self._cells)

    def __iter__(self):
        return iter(self._cells)
