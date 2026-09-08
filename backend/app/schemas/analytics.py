"""Civic analytics schemas (Part 22).

The analytics dashboard exposes three complementary shapes:

* ``AnalyticsOverview`` — headline KPIs plus the chart series (complaints over
  time, resolution trend, category / ward / department / SLA breakdowns).
* ``HeatmapOut`` — pre-aggregated complaint clusters for the Leaflet heatmap.
* ``RatingIn`` / ``RatingOut`` — (kept in ``app.schemas.rating``) citizen
  satisfaction input and output.
"""

from __future__ import annotations

import uuid
from datetime import datetime

from pydantic import BaseModel, Field


class AnalyticsFilters(BaseModel):
    """The filters that were applied (echoed so the UI can display them)."""

    date_from: datetime | None = None
    date_to: datetime | None = None
    ward_id: uuid.UUID | None = None
    department: str | None = None
    category: str | None = None
    priority: str | None = None


class SatisfactionBucket(BaseModel):
    rating: int
    count: int


class AnalyticsKpis(BaseModel):
    total_complaints: int = 0
    resolved: int = 0
    resolution_rate: float = 0.0
    # Operational response / resolution time (seconds over measured complaints).
    response_seconds_avg: float | None = None
    response_seconds_median: float | None = None
    response_count: int = 0
    resolution_seconds_avg: float | None = None
    resolution_seconds_median: float | None = None
    resolution_count: int = 0
    # SLA compliance over work orders that carried a deadline.
    sla_compliance_rate: float | None = None
    sla_within: int = 0
    sla_overdue: int = 0
    sla_orders_with_deadline: int = 0
    # AI pipeline reach.
    ai_triaged: int = 0
    ai_triage_rate: float = 0.0
    # Escalation.
    escalated: int = 0
    escalation_rate: float = 0.0
    # Citizen satisfaction (1..5).
    satisfaction_avg: float | None = None
    satisfaction_count: int = 0
    satisfaction_distribution: list[SatisfactionBucket] = Field(default_factory=list)


class TimePoint(BaseModel):
    period: str  # "YYYY-MM-DD" (daily) or "YYYY-MM" (monthly)
    total: int = 0
    resolved: int = 0


class CategoryPoint(BaseModel):
    category: str
    total: int = 0
    resolved: int = 0
    rate: float = 0.0


class WardPoint(BaseModel):
    ward_id: uuid.UUID | None = None
    ward_name: str
    total: int = 0
    resolved: int = 0


class DepartmentPoint(BaseModel):
    department: str
    total: int = 0
    completed: int = 0
    avg_completion_seconds: float | None = None
    sla_within: int = 0
    sla_overdue: int = 0
    compliance_rate: float | None = None
    escalated: int = 0


class SlaPoint(BaseModel):
    priority: str
    total: int = 0
    within: int = 0
    overdue: int = 0


class AnalyticsCharts(BaseModel):
    complaints_over_time: list[TimePoint] = Field(default_factory=list)
    resolution_trend: list[TimePoint] = Field(default_factory=list)
    categories: list[CategoryPoint] = Field(default_factory=list)
    wards: list[WardPoint] = Field(default_factory=list)
    departments: list[DepartmentPoint] = Field(default_factory=list)
    sla_performance: list[SlaPoint] = Field(default_factory=list)


class AnalyticsOverview(BaseModel):
    applied_filters: AnalyticsFilters = Field(default_factory=AnalyticsFilters)
    kpis: AnalyticsKpis = Field(default_factory=AnalyticsKpis)
    charts: AnalyticsCharts = Field(default_factory=AnalyticsCharts)


class HeatmapCluster(BaseModel):
    latitude: float
    longitude: float
    count: int = 1
    weight: float = 0.0


class HeatmapOut(BaseModel):
    total_points: int = 0
    clusters: list[HeatmapCluster] = Field(default_factory=list)
