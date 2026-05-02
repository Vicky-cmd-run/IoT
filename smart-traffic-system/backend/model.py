from __future__ import annotations

from collections import deque
from dataclasses import dataclass, field
from statistics import mean
from threading import Lock
from typing import Deque

from pydantic import BaseModel, Field


class SegmentSnapshot(BaseModel):
    segment_id: str
    speed_kmph: float = Field(ge=0)
    density: float = Field(ge=0)
    flow_rate: float = Field(ge=0)
    travel_time_seconds: float = Field(gt=0)
    signal_wait_seconds: float = Field(ge=0, default=0)


class TrafficSnapshot(BaseModel):
    timestamp: str
    intersection_id: str
    segments: list[SegmentSnapshot]
    source: str = "simulation"


class PredictedSegmentState(BaseModel):
    segment_id: str
    future_congestion_level: str
    predicted_speed_kmph: float
    predicted_travel_time_seconds: float
    forecast_minutes: int


class PredictionResponse(BaseModel):
    timestamp: str
    horizon_minutes: int
    predictions: list[PredictedSegmentState]


class RouteRequest(BaseModel):
    vehicle_id: str
    source: str
    destination: str
    graph: dict[str, dict[str, float]]
    congestion_penalties: dict[str, float] = Field(default_factory=dict)


class RouteResponse(BaseModel):
    vehicle_id: str
    best_path: list[str]
    estimated_cost: float
    reasoning: str


class SignalPlan(BaseModel):
    intersection_id: str
    green_duration_seconds: int
    yellow_duration_seconds: int = 4
    red_duration_seconds: int = 30
    mode: str = "adaptive"


class DashboardSummary(BaseModel):
    timestamp: str
    average_speed_kmph: float
    average_density: float
    congestion_segments: int
    total_segments: int
    suggested_signal_plan: SignalPlan | None = None


class ScenarioRequest(BaseModel):
    scenario: str


class OptimizationRequest(BaseModel):
    enabled: bool


class ZoneMetric(BaseModel):
    zone_id: str
    label: str
    density: float
    speed_kmph: float
    travel_time_seconds: float
    congestion_level: str
    active_signal_green_seconds: int
    rerouted_vehicles: int


class MapEdgeMetric(BaseModel):
    edge_id: str
    coordinates: list[list[float]]
    vehicle_count: int
    speed_kmph: float
    travel_time_seconds: float
    density: float
    congestion_level: str
    zone_id: str


class SimulationSnapshotMetric(BaseModel):
    timestamp: str
    average_speed_kmph: float
    average_density: float
    baseline_travel_time_seconds: float
    optimized_travel_time_seconds: float


class ImprovementMetrics(BaseModel):
    travel_time_saved_pct: float
    congestion_reduced_pct: float
    average_speed_gain_pct: float


class JourneyRequest(BaseModel):
    source_zone: str
    destination_zone: str


class SnapshotIngestionRequest(BaseModel):
    timestamp: str | None = None
    intersection_id: str = "BLR-CBD-LIVE"
    source: str = "iot_gateway"
    segments: list[SegmentSnapshot]


class SnapshotIngestionResponse(BaseModel):
    accepted: bool
    source: str
    timestamp: str
    segment_count: int
    mode: str


class JourneyState(BaseModel):
    journey_id: str
    vehicle_id: str
    source_zone: str
    destination_zone: str
    status: str
    current_edge: str | None
    route_edges: list[str]
    estimated_travel_time_seconds: float
    rerouted: bool
    # Route comparison fields — computed by backend from live zone state
    original_zone_path: list[str] = Field(default_factory=list)
    rerouted_zone_path: list[str] = Field(default_factory=list)
    original_risk_score: float = 0.0
    rerouted_risk_score: float = 0.0
    reroute_reason: str = ""
    decision_source: str = "simulation"


class SimulationStateResponse(BaseModel):
    running: bool
    scenario: str
    optimization_enabled: bool
    tick: int
    city_name: str
    active_alert: str
    data_source: str = "simulation"
    last_ingested_at: str | None = None
    zones: list[ZoneMetric]
    map_edges: list[MapEdgeMetric]
    history: list[SimulationSnapshotMetric]
    improvement: ImprovementMetrics
    selected_journey: JourneyState | None = None


class LiveDashboardResponse(BaseModel):
    summary: DashboardSummary | None
    prediction: PredictionResponse
    weather: dict
    traffic: dict
    simulation: SimulationStateResponse
    commands: list[dict]


@dataclass
class TrafficStateStore:
    max_history: int = 24
    snapshots: Deque[TrafficSnapshot] = field(default_factory=deque)
    _lock: Lock = field(default_factory=Lock)

    def add(self, snapshot: TrafficSnapshot) -> None:
        with self._lock:
            self.snapshots.append(snapshot)
            while len(self.snapshots) > self.max_history:
                self.snapshots.popleft()

    def latest(self) -> TrafficSnapshot | None:
        with self._lock:
            return self.snapshots[-1] if self.snapshots else None

    def segment_history(self, segment_id: str) -> list[SegmentSnapshot]:
        history: list[SegmentSnapshot] = []
        with self._lock:
            for snap in self.snapshots:
                for segment in snap.segments:
                    if segment.segment_id == segment_id:
                        history.append(segment)
        return history


class TrafficPredictor:
    def __init__(self, store: TrafficStateStore):
        self.store = store

    def predict(self, horizon_minutes: int = 10) -> PredictionResponse:
        latest = self.store.latest()
        if latest is None:
            return PredictionResponse(
                timestamp="",
                horizon_minutes=horizon_minutes,
                predictions=[],
            )

        predictions: list[PredictedSegmentState] = []
        for segment in latest.segments:
            history = self.store.segment_history(segment.segment_id) or [segment]
            avg_speed = mean(item.speed_kmph for item in history)
            avg_density = mean(item.density for item in history)
            avg_wait = mean(item.signal_wait_seconds for item in history)

            density_growth = 1 + min(avg_density / 200, 0.35)
            predicted_speed = max(5.0, round(avg_speed / density_growth, 2))
            predicted_travel_time = round(
                segment.travel_time_seconds * density_growth + avg_wait,
                2,
            )

            if avg_density >= 80 or predicted_speed <= 15:
                level = "high"
            elif avg_density >= 40 or predicted_speed <= 30:
                level = "medium"
            else:
                level = "low"

            predictions.append(
                PredictedSegmentState(
                    segment_id=segment.segment_id,
                    future_congestion_level=level,
                    predicted_speed_kmph=predicted_speed,
                    predicted_travel_time_seconds=predicted_travel_time,
                    forecast_minutes=horizon_minutes,
                )
            )

        return PredictionResponse(
            timestamp=latest.timestamp,
            horizon_minutes=horizon_minutes,
            predictions=predictions,
        )
