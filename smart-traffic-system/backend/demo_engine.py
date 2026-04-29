"""
demo_engine.py — Scenario-driven simulation engine for demo/interview mode.

Runs without SUMO. Produces realistic, dynamic congestion profiles that differ
meaningfully across zones based on the active scenario. Computes genuine route
comparison (naive GPS path vs AI-optimized path) using the backend zone graph.
"""
from __future__ import annotations

import heapq
import math
import random
import threading
import time
from collections import deque
from dataclasses import dataclass, field

from model import (
    DashboardSummary,
    ImprovementMetrics,
    JourneyRequest,
    JourneyState,
    ScenarioRequest,
    SegmentSnapshot,
    SignalPlan,
    SimulationSnapshotMetric,
    SimulationStateResponse,
    TrafficSnapshot,
    TrafficStateStore,
    ZoneMetric,
)
from traci_handler import TraCICommandExecutor


def _congestion_band(density: float, speed_kmph: float) -> str:
    if density >= 80 or speed_kmph <= 12:
        return "high"
    if density >= 45 or speed_kmph <= 24:
        return "medium"
    return "low"


# ---------------------------------------------------------------------------
# Static zone topology — mirrors the frontend corridorGraph exactly
# ---------------------------------------------------------------------------
ZONE_GRAPH: dict[str, list[str]] = {
    "north": ["central", "west", "east"],
    "central": ["north", "west", "east", "south"],
    "east": ["north", "central", "south"],
    "west": ["north", "central", "south"],
    "south": ["central", "east", "west"],
}

ZONE_LABELS: dict[str, str] = {
    "north": "Vidhana Soudha Belt",
    "south": "Majestic Link",
    "east": "MG Road Axis",
    "west": "KR Circle Corridor",
    "central": "Cubbon Core",
}

# Risk cost weights — must match frontend baseZoneCost
LEVEL_COST: dict[str, float] = {"low": 1.0, "medium": 3.5, "high": 8.0}

# ---------------------------------------------------------------------------
# Per-scenario congestion profiles  (density %, speed km/h, travel_time s)
# These are the "with-AI-optimization" states.
# ---------------------------------------------------------------------------
SCENARIO_PROFILES: dict[str, dict[str, tuple[float, float, float]]] = {
    "rush_hour": {
        "north": (62, 18, 185),
        "west": (74, 14, 220),
        "central": (70, 15, 210),
        "east": (40, 33, 120),
        "south": (32, 40, 95),
    },
    "accident": {
        "central": (91, 8, 380),
        "west": (84, 10, 310),
        "north": (52, 22, 165),
        "east": (30, 40, 110),
        "south": (25, 44, 90),
    },
    "rain_event": {
        "north": (55, 18, 195),
        "west": (58, 17, 205),
        "central": (62, 16, 215),
        "east": (50, 21, 175),
        "south": (46, 23, 160),
    },
    "event_surge": {
        "south": (88, 9, 360),
        "east": (80, 12, 290),
        "central": (68, 17, 220),
        "north": (36, 36, 105),
        "west": (28, 42, 88),
    },
}

# Pre-optimization baseline — what traffic looked like before AI intervention
BASELINE_PROFILES: dict[str, dict[str, tuple[float, float, float]]] = {
    "rush_hour": {
        "north": (78, 12, 255),
        "west": (89, 8, 320),
        "central": (85, 9, 295),
        "east": (58, 22, 178),
        "south": (48, 27, 148),
    },
    "accident": {
        "central": (97, 5, 490),
        "west": (93, 6, 415),
        "north": (70, 14, 230),
        "east": (48, 26, 158),
        "south": (40, 30, 132),
    },
    "rain_event": {
        "north": (72, 12, 268),
        "west": (76, 11, 282),
        "central": (79, 10, 298),
        "east": (66, 15, 238),
        "south": (63, 17, 218),
    },
    "event_surge": {
        "south": (97, 5, 465),
        "east": (91, 7, 385),
        "central": (83, 10, 308),
        "north": (52, 22, 168),
        "west": (42, 28, 132),
    },
}

# Zones that are the PRIMARY problem corridor for each scenario.
# A naive GPS (unaware of conditions) will naturally route through these.
SCENARIO_PROBLEM_ZONES: dict[str, set[str]] = {
    "rush_hour": {"west", "central"},
    "accident": {"central", "west"},
    "rain_event": {"central", "north", "west"},
    "event_surge": {"south", "east"},
}

# Human-readable reroute explanation per scenario
SCENARIO_REROUTE_REASON: dict[str, str] = {
    "rush_hour": "Rush-hour overload on the west-central corridor. AI routes via south or east bypass.",
    "accident": "Accident blocks central zone. AI redirects via north or south to avoid the incident.",
    "rain_event": "Rain degrades the main north-central link. AI preserves the east and south corridors.",
    "event_surge": "Event surge fills south-east. AI shifts through-traffic to the north-west path.",
}


def _dijkstra(source: str, destination: str, cost_fn: dict[str, float]) -> list[str]:
    """Dijkstra over the zone graph. cost_fn maps zone_id → entry cost."""
    queue: list[tuple[float, str, list[str]]] = [(0.0, source, [source])]
    visited: dict[str, float] = {}

    while queue:
        cost, node, path = heapq.heappop(queue)
        if node == destination:
            return path
        if node in visited and visited[node] <= cost:
            continue
        visited[node] = cost
        for neighbor in ZONE_GRAPH.get(node, []):
            step = cost_fn.get(neighbor, 1.0)
            heapq.heappush(queue, (cost + step, neighbor, path + [neighbor]))

    return []


def _zone_path_risk(path: list[str], zone_congestion: dict[str, str]) -> float:
    """Sum of LEVEL_COST for each zone in the path (excluding source)."""
    return sum(LEVEL_COST.get(zone_congestion.get(z, "low"), 1.0) for z in path[1:])


def _compute_route_comparison(
    source: str,
    destination: str,
    scenario: str,
    zone_congestion: dict[str, str],
) -> tuple[list[str], list[str], float, float, str]:
    """
    Returns (original_path, rerouted_path, original_risk, rerouted_risk, reason).

    Original path: naive GPS — zero awareness of congestion, but problem zones
    appear attractive (low cost) because a naive driver takes the direct road.
    Rerouted path: AI — avoids high-cost zones using real congestion data.
    """
    problem_zones = SCENARIO_PROBLEM_ZONES.get(scenario, set())

    # Naive cost: problem zones look attractive (naive driver takes the "direct" road)
    naive_cost: dict[str, float] = {}
    for zone in ZONE_GRAPH:
        if zone in problem_zones:
            naive_cost[zone] = 0.3   # low cost → naive driver prefers them
        else:
            naive_cost[zone] = 1.5   # slight penalty for detours

    # AI cost: derived from live congestion levels
    ai_cost: dict[str, float] = {
        z: LEVEL_COST.get(zone_congestion.get(z, "low"), 1.0) for z in ZONE_GRAPH
    }

    original_path = _dijkstra(source, destination, naive_cost)
    rerouted_path = _dijkstra(source, destination, ai_cost)

    # If rerouted path costs more or equal, keep it but flag it honestly
    original_risk = _zone_path_risk(original_path, zone_congestion)
    rerouted_risk = _zone_path_risk(rerouted_path, zone_congestion)

    reason = SCENARIO_REROUTE_REASON.get(scenario, "AI optimized route based on live congestion.")

    return original_path, rerouted_path, original_risk, rerouted_risk, reason


@dataclass
class DemoSimulationEngine:
    """
    Scenario-driven mock engine for interview/demo mode (no SUMO required).

    Key guarantees:
    - Zone congestion levels are heterogeneous and scenario-specific.
    - Original vs rerouted paths are derived from the same zone graph.
    - Route comparison is mathematically consistent and explainable.
    - Improvement metrics are computed from real baseline vs optimized profiles.
    - All state evolves dynamically (tick-based oscillation + noise).
    """

    store: TrafficStateStore
    traci_executor: TraCICommandExecutor
    city_name: str = "Bengaluru CBD"
    scenario: str = "accident"
    optimization_enabled: bool = True
    running: bool = False
    tick: int = 0
    thread: threading.Thread | None = None
    stop_event: threading.Event = field(default_factory=threading.Event)
    history: deque = field(default_factory=lambda: deque(maxlen=40))
    latest_zones: list[ZoneMetric] = field(default_factory=list)
    latest_map_edges: list = field(default_factory=list)
    baseline_density: float = 0.0
    optimized_density: float = 0.0
    baseline_speed: float = 0.0
    optimized_speed: float = 0.0
    baseline_travel_time: float = 0.0
    optimized_travel_time: float = 0.0
    active_alert: str = "Demo engine ready — press Run Guided Demo"
    sumo_started: bool = False
    selected_journey: JourneyState | None = None
    _lock: threading.RLock = field(default_factory=threading.RLock)
    _rng: random.Random = field(default_factory=lambda: random.Random(42))

    def start(self) -> None:
        if self.running:
            return
        self.running = True
        self.stop_event.clear()
        self.thread = threading.Thread(target=self._run_loop, daemon=True)
        self.thread.start()

    def stop(self) -> None:
        self.running = False
        self.stop_event.set()

    def reset(self) -> None:
        with self._lock:
            self.history.clear()
            self.tick = 0
            self.selected_journey = None
            self.latest_zones = []
            self.active_alert = "Simulation reset — ready for new demo"
            self._rng = random.Random(42)

    def set_scenario(self, request: ScenarioRequest) -> None:
        self.scenario = request.scenario
        self.active_alert = f"Scenario switched to '{request.scenario.replace('_', ' ')}' — congestion updating"

    def set_optimization(self, enabled: bool) -> None:
        self.optimization_enabled = enabled
        self.active_alert = f"Adaptive AI optimization {'enabled' if enabled else 'disabled'}"

    def state(self) -> SimulationStateResponse:
        return SimulationStateResponse(
            running=self.running,
            scenario=self.scenario,
            optimization_enabled=self.optimization_enabled,
            tick=self.tick,
            city_name=self.city_name,
            active_alert=self.active_alert,
            zones=self.latest_zones,
            map_edges=[],
            history=list(self.history),
            improvement=self._improvement_metrics(),
            selected_journey=self.selected_journey,
        )

    def latest_summary(self) -> DashboardSummary | None:
        if not self.latest_zones:
            return None
        avg_speed = sum(z.speed_kmph for z in self.latest_zones) / len(self.latest_zones)
        avg_density = sum(z.density for z in self.latest_zones) / len(self.latest_zones)
        congested = sum(1 for z in self.latest_zones if z.congestion_level != "low")
        return DashboardSummary(
            timestamp=time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            average_speed_kmph=round(avg_speed, 2),
            average_density=round(avg_density, 2),
            congestion_segments=congested,
            total_segments=len(self.latest_zones),
            suggested_signal_plan=self._best_signal_plan(),
        )

    def create_user_journey(self, request: JourneyRequest) -> JourneyState:
        src = request.source_zone
        dst = request.destination_zone
        if src not in ZONE_GRAPH or dst not in ZONE_GRAPH:
            raise RuntimeError(f"Unknown zone: {src} or {dst}")

        zone_congestion = {z.zone_id: z.congestion_level for z in self.latest_zones}

        original_path, rerouted_path, orig_risk, rerou_risk, reason = _compute_route_comparison(
            src, dst, self.scenario, zone_congestion
        )

        paths_differ = original_path != rerouted_path
        rerouted = paths_differ and self.optimization_enabled and rerou_risk < orig_risk

        # Estimate travel time from zone travel times
        zone_travel = {z.zone_id: z.travel_time_seconds for z in self.latest_zones}
        active_path = rerouted_path if rerouted else original_path
        eta = sum(zone_travel.get(z, 120.0) for z in active_path[1:])

        journey_id = f"demo_route_{int(time.time())}"
        vehicle_id = f"demo_vehicle_{int(time.time())}"

        self.selected_journey = JourneyState(
            journey_id=journey_id,
            vehicle_id=vehicle_id,
            source_zone=src,
            destination_zone=dst,
            status="active",
            current_edge=None,
            route_edges=active_path,
            estimated_travel_time_seconds=round(eta, 2),
            rerouted=rerouted,
            original_zone_path=original_path,
            rerouted_zone_path=rerouted_path if rerouted else original_path,
            original_risk_score=round(orig_risk, 2),
            rerouted_risk_score=round(rerou_risk, 2) if rerouted else round(orig_risk, 2),
            reroute_reason=reason if rerouted else "No better route found — original path is already optimal.",
        )
        return self.selected_journey

    # -----------------------------------------------------------------------
    # Internal loop
    # -----------------------------------------------------------------------

    def _run_loop(self) -> None:
        while not self.stop_event.is_set():
            with self._lock:
                self._tick_update()
            time.sleep(0.8)

    def _tick_update(self) -> None:
        t = self.tick
        self.tick += 1

        profile = SCENARIO_PROFILES.get(self.scenario, SCENARIO_PROFILES["accident"])
        baseline_profile = BASELINE_PROFILES.get(self.scenario, BASELINE_PROFILES["accident"])

        opt_factor = 0.86 if self.optimization_enabled else 1.0
        zones: list[ZoneMetric] = []

        opt_d_sum = opt_s_sum = opt_t_sum = 0.0
        bl_d_sum = bl_s_sum = bl_t_sum = 0.0

        for zone_id, label in ZONE_LABELS.items():
            base_d, base_s, base_t = profile[zone_id]
            bl_d, bl_s, bl_t = baseline_profile[zone_id]

            osc = math.sin(t * 0.07 + abs(hash(zone_id)) % 8) * 3.5
            noise_d = self._rng.gauss(0, 1.8)
            noise_s = self._rng.gauss(0, 0.9)
            noise_t = self._rng.gauss(0, 4.5)

            density = min(100.0, max(0.0, base_d * opt_factor + osc + noise_d))
            speed = max(5.0, base_s / opt_factor + osc * 0.2 + noise_s)
            travel = max(30.0, base_t * opt_factor + osc * 1.8 + noise_t)

            level = _congestion_band(density, speed)

            zones.append(ZoneMetric(
                zone_id=zone_id,
                label=label,
                density=round(density, 2),
                speed_kmph=round(speed, 2),
                travel_time_seconds=round(travel, 2),
                congestion_level=level,
                active_signal_green_seconds=45 if level != "low" else 30,
                rerouted_vehicles=self._rng.randint(2, 8) if level == "high" else 0,
            ))

            opt_d_sum += density
            opt_s_sum += speed
            opt_t_sum += travel
            bl_d_sum += bl_d
            bl_s_sum += bl_s
            bl_t_sum += bl_t

        n = len(zones)
        self.latest_zones = zones
        self.optimized_density = opt_d_sum / n
        self.optimized_speed = opt_s_sum / n
        self.optimized_travel_time = opt_t_sum / n
        self.baseline_density = bl_d_sum / n
        self.baseline_speed = bl_s_sum / n
        self.baseline_travel_time = bl_t_sum / n

        # Advance selected journey ETA
        if self.selected_journey and self.selected_journey.status == "active":
            remaining = max(0.0, self.selected_journey.estimated_travel_time_seconds - 2.0)
            if remaining <= 0:
                self.selected_journey.status = "completed"
            else:
                self.selected_journey.estimated_travel_time_seconds = round(remaining, 2)

            # Refresh route comparison with latest congestion
            if self.selected_journey.status == "active":
                zone_congestion = {z.zone_id: z.congestion_level for z in zones}
                orig_p, rerou_p, orig_r, rerou_r, reason = _compute_route_comparison(
                    self.selected_journey.source_zone,
                    self.selected_journey.destination_zone,
                    self.scenario,
                    zone_congestion,
                )
                paths_differ = orig_p != rerou_p
                rerouted = paths_differ and self.optimization_enabled and rerou_r < orig_r
                self.selected_journey.original_zone_path = orig_p
                self.selected_journey.rerouted_zone_path = rerou_p if rerouted else orig_p
                self.selected_journey.original_risk_score = round(orig_r, 2)
                self.selected_journey.rerouted_risk_score = round(rerou_r, 2) if rerouted else round(orig_r, 2)
                self.selected_journey.rerouted = rerouted
                self.selected_journey.reroute_reason = (
                    reason if rerouted else "No better route found — original path is already optimal."
                )

        timestamp = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
        self.store.add(TrafficSnapshot(
            timestamp=timestamp,
            intersection_id="BLR-CBD-DEMO",
            segments=[
                SegmentSnapshot(
                    segment_id=z.zone_id.upper(),
                    speed_kmph=z.speed_kmph,
                    density=z.density,
                    flow_rate=round(z.density * 7.2, 2),
                    travel_time_seconds=z.travel_time_seconds,
                    signal_wait_seconds=max(4.0, z.travel_time_seconds * 0.08),
                )
                for z in zones
            ],
            source="demo",
        ))
        self.history.append(SimulationSnapshotMetric(
            timestamp=timestamp,
            average_speed_kmph=round(self.optimized_speed, 2),
            average_density=round(self.optimized_density, 2),
            baseline_travel_time_seconds=round(self.baseline_travel_time, 2),
            optimized_travel_time_seconds=round(self.optimized_travel_time, 2),
        ))

        hotspot = max(zones, key=lambda z: z.density)
        self.active_alert = (
            f"{hotspot.label} is under {hotspot.congestion_level} congestion "
            f"({hotspot.density:.0f}% density, {hotspot.speed_kmph:.0f} km/h)."
        )

    def _best_signal_plan(self) -> SignalPlan | None:
        if not self.latest_zones:
            return None
        hotspot = max(self.latest_zones, key=lambda z: z.density)
        return SignalPlan(
            intersection_id=hotspot.zone_id.upper(),
            green_duration_seconds=45 if hotspot.congestion_level != "low" else 30,
            mode="adaptive" if self.optimization_enabled else "manual",
        )

    def _improvement_metrics(self) -> ImprovementMetrics:
        bl_travel = self.baseline_travel_time or 1.0
        bl_density = self.baseline_density or 1.0
        bl_speed = self.baseline_speed or 1.0
        return ImprovementMetrics(
            travel_time_saved_pct=round(
                max(0.0, (bl_travel - self.optimized_travel_time) / bl_travel * 100), 2
            ),
            congestion_reduced_pct=round(
                max(0.0, (bl_density - self.optimized_density) / bl_density * 100), 2
            ),
            average_speed_gain_pct=round(
                max(0.0, (self.optimized_speed - bl_speed) / bl_speed * 100), 2
            ),
        )
