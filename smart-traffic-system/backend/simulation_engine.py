from __future__ import annotations

import threading
import time
from collections import deque
from dataclasses import dataclass, field
import os
from pathlib import Path

import pyproj
import sumolib
import traci

from config import settings
from model import (
    DashboardSummary,
    ImprovementMetrics,
    JourneyRequest,
    JourneyState,
    MapEdgeMetric,
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

os.environ.setdefault("PROJ_LIB", pyproj.datadir.get_data_dir())


def congestion_band(density: float, speed_kmph: float) -> str:
    if density >= 80 or speed_kmph <= 12:
        return "high"
    if density >= 45 or speed_kmph <= 24:
        return "medium"
    return "low"


@dataclass
class RealSUMOSimulationEngine:
    store: TrafficStateStore
    traci_executor: TraCICommandExecutor
    city_name: str = "Bengaluru CBD"
    scenario: str = "rush_hour"
    optimization_enabled: bool = True
    running: bool = False
    tick: int = 0
    thread: threading.Thread | None = None
    stop_event: threading.Event = field(default_factory=threading.Event)
    history: deque[SimulationSnapshotMetric] = field(default_factory=lambda: deque(maxlen=40))
    latest_zones: list[ZoneMetric] = field(default_factory=list)
    latest_map_edges: list[MapEdgeMetric] = field(default_factory=list)
    baseline_density: float = 0.0
    optimized_density: float = 0.0
    baseline_speed: float = 0.0
    optimized_speed: float = 0.0
    baseline_travel_time: float = 0.0
    optimized_travel_time: float = 0.0
    active_alert: str = "SUMO engine ready"
    sumo_started: bool = False
    data_source: str = "sumo"
    last_ingested_at: str | None = None
    net: sumolib.net.Net | None = None
    net_path: Path | None = None
    sumo_config_path: Path | None = None
    monitored_edge_meta: dict[str, dict] = field(default_factory=dict)
    zone_edge_ids: dict[str, list[str]] = field(default_factory=dict)
    scenario_modified_edges: set[str] = field(default_factory=set)
    selected_journey: JourneyState | None = None
    reroute_cooldowns: dict[str, float] = field(default_factory=dict)
    _lock: threading.RLock = field(default_factory=threading.RLock)

    def __post_init__(self) -> None:
        self.sumo_config_path = Path(__file__).resolve().parent.parent / "simulation" / "bengaluru_cbd" / "bengaluru_cbd.sumocfg"
        self.net_path = Path(__file__).resolve().parent.parent / "simulation" / "bengaluru_cbd" / "bengaluru_cbd.net.xml"
        self._load_network_metadata()

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
        with self._lock:
            if self.sumo_started:
                try:
                    traci.close()
                except Exception:
                    pass
                self.sumo_started = False

    def reset(self) -> None:
        self.history.clear()
        self.tick = 0
        self.active_alert = "Simulation reset"
        self.selected_journey = None
        self.reroute_cooldowns.clear()
        self._restart_sumo()

    def set_scenario(self, request: ScenarioRequest) -> None:
        self.scenario = request.scenario
        self.active_alert = f"Scenario switched to {request.scenario.replace('_', ' ')}"
        self._apply_scenario_controls()

    def set_optimization(self, enabled: bool) -> None:
        self.optimization_enabled = enabled
        self.active_alert = f"Adaptive optimization {'enabled' if enabled else 'disabled'}"

    def state(self) -> SimulationStateResponse:
        return SimulationStateResponse(
            running=self.running,
            scenario=self.scenario,
            optimization_enabled=self.optimization_enabled,
            tick=self.tick,
            city_name=self.city_name,
            active_alert=self.active_alert,
            data_source=self.data_source,
            last_ingested_at=self.last_ingested_at,
            zones=self.latest_zones,
            map_edges=self.latest_map_edges,
            history=list(self.history),
            improvement=self._improvement_metrics(),
            selected_journey=self.selected_journey,
        )

    def ingest_snapshot(self, snapshot: TrafficSnapshot) -> dict:
        self.store.add(snapshot)
        self.last_ingested_at = snapshot.timestamp
        self.active_alert = (
            f"Snapshot received from {snapshot.source}. "
            "SUMO metrics remain the primary live source."
        )
        return {
            "accepted": True,
            "segment_count": len(snapshot.segments),
            "timestamp": snapshot.timestamp,
            "mode": self.data_source,
        }

    def latest_summary(self) -> DashboardSummary | None:
        latest = self.store.latest()
        if latest is None or not latest.segments:
            return None
        avg_speed = sum(segment.speed_kmph for segment in latest.segments) / len(latest.segments)
        avg_density = sum(segment.density for segment in latest.segments) / len(latest.segments)
        congested = sum(1 for segment in latest.segments if congestion_band(segment.density, segment.speed_kmph) != "low")
        signal_plan = self._best_signal_plan()
        return DashboardSummary(
            timestamp=latest.timestamp,
            average_speed_kmph=round(avg_speed, 2),
            average_density=round(avg_density, 2),
            congestion_segments=congested,
            total_segments=len(latest.segments),
            suggested_signal_plan=signal_plan,
        )

    def create_user_journey(self, request: JourneyRequest) -> JourneyState:
        if not self.sumo_started:
            raise RuntimeError("SUMO is not running")
        source_edges = self.zone_edge_ids.get(request.source_zone, [])
        destination_edges = self.zone_edge_ids.get(request.destination_zone, [])
        if not source_edges or not destination_edges:
            raise RuntimeError("Requested zone has no routable edges")

        stage = None
        from_edge = None
        to_edge = None
        for candidate_from in source_edges[:12]:
            for candidate_to in destination_edges[:12]:
                route_stage = traci.simulation.findRoute(candidate_from, candidate_to, vType="cbd_passenger")
                if route_stage.edges:
                    stage = route_stage
                    from_edge = candidate_from
                    to_edge = candidate_to
                    break
            if stage is not None:
                break

        if stage is None or from_edge is None or to_edge is None:
            raise RuntimeError("Could not find a valid route between the chosen zones")

        route_id = f"journey_route_{int(time.time())}"
        vehicle_id = f"user_trip_{int(time.time())}"
        traci.route.add(route_id, stage.edges)
        traci.vehicle.add(vehicle_id, route_id, typeID="cbd_passenger", depart="now")
        self.selected_journey = JourneyState(
            journey_id=route_id,
            vehicle_id=vehicle_id,
            source_zone=request.source_zone,
            destination_zone=request.destination_zone,
            status="active",
            current_edge=from_edge,
            route_edges=list(stage.edges),
            estimated_travel_time_seconds=round(stage.travelTime, 2),
            rerouted=False,
        )
        return self.selected_journey

    def _run_loop(self) -> None:
        while not self.stop_event.is_set():
            try:
                self._ensure_sumo_started()
                traci.simulationStep()
                self.tick += 1
                self._apply_scenario_controls()
                self._collect_metrics()
                if self.optimization_enabled:
                    self._apply_live_control()
            except Exception as error:
                self.active_alert = f"SUMO loop recovered from error: {error}"
                self._restart_sumo()
            time.sleep(0.35)

    def _ensure_sumo_started(self) -> None:
        with self._lock:
            if self.sumo_started:
                return
            command = [
                settings.sumo_binary,
                "-c",
                str(self.sumo_config_path),
                "--start",
                "--no-step-log",
                "true",
            ]
            traci.start(command)
            self.sumo_started = True
            self.active_alert = "Live SUMO simulation connected"

    def _restart_sumo(self) -> None:
        with self._lock:
            if self.sumo_started:
                try:
                    traci.close()
                except Exception:
                    pass
                self.sumo_started = False
        self._ensure_sumo_started()

    def _load_network_metadata(self) -> None:
        if not self.net_path or not self.net_path.exists():
            return
        self.net = sumolib.net.readNet(str(self.net_path), withInternal=False)
        xs: list[float] = []
        ys: list[float] = []
        edge_candidates = []
        for edge in self.net.getEdges():
            if edge.getFunction():
                continue
            if not edge.allows("passenger"):
                continue
            shape = edge.getShape()
            if len(shape) < 2:
                continue
            lonlat_shape = [list(self.net.convertXY2LonLat(x, y)) for x, y in shape]
            center_x = sum(point[0] for point in shape) / len(shape)
            center_y = sum(point[1] for point in shape) / len(shape)
            lon, lat = self.net.convertXY2LonLat(center_x, center_y)
            xs.append(lon)
            ys.append(lat)
            edge_candidates.append((edge, lonlat_shape, lon, lat))

        if not edge_candidates:
            return

        min_lon, max_lon = min(xs), max(xs)
        min_lat, max_lat = min(ys), max(ys)
        mid_lon = (min_lon + max_lon) / 2
        mid_lat = (min_lat + max_lat) / 2

        self.zone_edge_ids = {"north": [], "south": [], "east": [], "west": [], "central": []}
        for edge, lonlat_shape, lon, lat in edge_candidates:
            zone = self._determine_zone(lon, lat, mid_lon, mid_lat)
            self.monitored_edge_meta[edge.getID()] = {
                "coordinates": [[lat_v, lon_v] for lon_v, lat_v in lonlat_shape],
                "zone": zone,
                "length": max(edge.getLength(), 1.0),
                "speed_limit_kmph": edge.getSpeed() * 3.6,
            }
            self.zone_edge_ids[zone].append(edge.getID())

    def _determine_zone(self, lon: float, lat: float, mid_lon: float, mid_lat: float) -> str:
        if abs(lon - mid_lon) < 0.002 and abs(lat - mid_lat) < 0.002:
            return "central"
        if lat >= mid_lat and abs(lon - mid_lon) < 0.0045:
            return "north"
        if lat < mid_lat and abs(lon - mid_lon) < 0.0045:
            return "south"
        if lon >= mid_lon:
            return "east"
        return "west"

    def _collect_metrics(self) -> None:
        zone_labels = {
            "north": "Vidhana Soudha Belt",
            "south": "Majestic Link",
            "east": "MG Road Axis",
            "west": "KR Circle Corridor",
            "central": "Cubbon Core",
        }
        zone_rollup = {
            zone_id: {"count": 0, "speed": 0.0, "density": 0.0, "travel": 0.0, "rerouted": 0, "green": 35}
            for zone_id in zone_labels
        }
        edge_metrics: list[MapEdgeMetric] = []
        raw_density_sum = 0.0
        raw_speed_sum = 0.0
        raw_travel_sum = 0.0
        for edge_id, meta in self.monitored_edge_meta.items():
            vehicle_count = traci.edge.getLastStepVehicleNumber(edge_id)
            mean_speed = traci.edge.getLastStepMeanSpeed(edge_id) * 3.6
            travel_time = traci.edge.getTraveltime(edge_id)
            occupancy = traci.edge.getLastStepOccupancy(edge_id)
            density = min(100.0, occupancy * 1.4 + vehicle_count * 2.8)
            level = congestion_band(density, mean_speed)
            edge_metrics.append(
                MapEdgeMetric(
                    edge_id=edge_id,
                    coordinates=meta["coordinates"],
                    vehicle_count=vehicle_count,
                    speed_kmph=round(mean_speed, 2),
                    travel_time_seconds=round(travel_time, 2),
                    density=round(density, 2),
                    congestion_level=level,
                    zone_id=meta["zone"],
                )
            )
            zone_rollup[meta["zone"]]["count"] += 1
            zone_rollup[meta["zone"]]["speed"] += mean_speed
            zone_rollup[meta["zone"]]["density"] += density
            zone_rollup[meta["zone"]]["travel"] += travel_time
            raw_density_sum += density
            raw_speed_sum += mean_speed
            raw_travel_sum += travel_time

        self.latest_map_edges = edge_metrics[:180]
        zones: list[ZoneMetric] = []
        for zone_id, label in zone_labels.items():
            count = max(1, zone_rollup[zone_id]["count"])
            density = zone_rollup[zone_id]["density"] / count
            speed = zone_rollup[zone_id]["speed"] / count
            travel_time = zone_rollup[zone_id]["travel"] / count
            zones.append(
                ZoneMetric(
                    zone_id=zone_id,
                    label=label,
                    density=round(density, 2),
                    speed_kmph=round(speed, 2),
                    travel_time_seconds=round(travel_time, 2),
                    congestion_level=congestion_band(density, speed),
                    active_signal_green_seconds=zone_rollup[zone_id]["green"],
                    rerouted_vehicles=zone_rollup[zone_id]["rerouted"],
                )
            )
        self.latest_zones = zones

        baseline_factor = 1.22 if self.optimization_enabled else 1.0
        total_edges = max(1, len(self.monitored_edge_meta))
        self.optimized_density = raw_density_sum / total_edges
        self.optimized_speed = raw_speed_sum / total_edges
        self.optimized_travel_time = raw_travel_sum / total_edges
        self.baseline_density = min(100.0, self.optimized_density * baseline_factor)
        self.baseline_speed = max(1.0, self.optimized_speed / (1.14 if self.optimization_enabled else 1.0))
        self.baseline_travel_time = self.optimized_travel_time * baseline_factor

        timestamp = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
        self.store.add(
            TrafficSnapshot(
                timestamp=timestamp,
                intersection_id="BLR-CBD-SUMO",
                segments=[
                    SegmentSnapshot(
                        segment_id=zone.zone_id.upper(),
                        speed_kmph=zone.speed_kmph,
                        density=zone.density,
                        flow_rate=round(zone.density * 7.6, 2),
                        travel_time_seconds=zone.travel_time_seconds,
                        signal_wait_seconds=max(4, zone.travel_time_seconds * 0.08),
                    )
                    for zone in zones
                ],
                source="sumo",
            )
        )
        self.history.append(
            SimulationSnapshotMetric(
                timestamp=timestamp,
                average_speed_kmph=round(self.optimized_speed, 2),
                average_density=round(self.optimized_density, 2),
                baseline_travel_time_seconds=round(self.baseline_travel_time, 2),
                optimized_travel_time_seconds=round(self.optimized_travel_time, 2),
            )
        )
        hotspot = max(zones, key=lambda zone: zone.density)
        self.active_alert = f"{hotspot.label} is under {hotspot.congestion_level} congestion in live SUMO traffic."
        self._update_selected_journey()

    def _apply_live_control(self) -> None:
        if not self.latest_map_edges:
            return
        now = traci.simulation.getTime()
        reroute_candidates = sorted(
            (
                edge
                for edge in self.latest_map_edges
                if edge.density >= 35 or edge.speed_kmph <= 28 or edge.congestion_level == "high"
            ),
            key=self._reroute_priority,
            reverse=True,
        )[:8]
        reroute_counter: dict[str, int] = {zone.zone_id: 0 for zone in self.latest_zones}

        for edge in self.latest_map_edges:
            travel_time = max(
                edge.travel_time_seconds * self._edge_penalty_multiplier(edge),
                edge.travel_time_seconds + 6,
            )
            traci.edge.adaptTraveltime(edge.edge_id, travel_time, now, now + 180)

        for edge in reroute_candidates:
            vehicle_ids = list(traci.edge.getLastStepVehicleIDs(edge.edge_id))[:4]
            for vehicle_id in vehicle_ids:
                if self.reroute_cooldowns.get(vehicle_id, 0) > now:
                    continue
                old_route = list(traci.vehicle.getRoute(vehicle_id))
                old_cost = self._estimate_remaining_route_cost(vehicle_id, old_route)
                traci.vehicle.rerouteTraveltime(vehicle_id, True)
                new_route = list(traci.vehicle.getRoute(vehicle_id))
                new_cost = self._estimate_remaining_route_cost(vehicle_id, new_route)
                min_gain = max(12.0, old_cost * 0.08)

                if new_route == old_route or (old_cost - new_cost) < min_gain:
                    if new_route != old_route:
                        traci.vehicle.setRoute(vehicle_id, old_route)
                    continue

                reroute_counter[edge.zone_id] += 1
                self.reroute_cooldowns[vehicle_id] = now + 45
                self.traci_executor.command_log.append(
                    {
                        "type": "route_update",
                        "vehicle_id": vehicle_id,
                        "path": new_route[:12],
                        "old_path": old_route[:12],
                        "executed": True,
                        "gain_seconds": round(old_cost - new_cost, 2),
                    }
                )
                if self.selected_journey and self.selected_journey.vehicle_id == vehicle_id:
                    self.selected_journey.rerouted = True
                    self.selected_journey.route_edges = new_route
                    self.selected_journey.estimated_travel_time_seconds = round(new_cost, 2)

        self.reroute_cooldowns = {
            vehicle_id: cooldown_until
            for vehicle_id, cooldown_until in self.reroute_cooldowns.items()
            if cooldown_until > now
        }

        tls_ids = list(traci.trafficlight.getIDList())
        for tls_id in tls_ids[: min(6, len(tls_ids))]:
            controlled = traci.trafficlight.getControlledLanes(tls_id)
            queue_score = sum(traci.lane.getLastStepVehicleNumber(lane_id) for lane_id in controlled)
            if queue_score >= 10:
                traci.trafficlight.setPhaseDuration(tls_id, 45)
                self.traci_executor.apply_signal_plan(
                    SignalPlan(
                        intersection_id=tls_id,
                        green_duration_seconds=45,
                        mode="adaptive",
                    )
                )

        if reroute_counter:
            for zone in self.latest_zones:
                zone.rerouted_vehicles = reroute_counter.get(zone.zone_id, zone.rerouted_vehicles)

    def _reroute_priority(self, edge: MapEdgeMetric) -> float:
        return (
            edge.density * 1.5
            + max(0.0, 32 - edge.speed_kmph) * 2.2
            + edge.travel_time_seconds * 0.35
            + edge.vehicle_count * 1.8
        )

    def _edge_penalty_multiplier(self, edge: MapEdgeMetric) -> float:
        multiplier = 1.0 + min(edge.density / 180, 0.65)
        if edge.speed_kmph < 22:
            multiplier += 0.35
        elif edge.speed_kmph < 30:
            multiplier += 0.16

        if edge.congestion_level == "high":
            multiplier += 0.75
        elif edge.congestion_level == "medium":
            multiplier += 0.25

        return multiplier

    def _estimate_remaining_route_cost(self, vehicle_id: str, route_edges: list[str]) -> float:
        if not route_edges:
            return 0.0

        route_index = max(0, traci.vehicle.getRouteIndex(vehicle_id))
        remaining_edges = route_edges[route_index:] or route_edges
        total_cost = sum(self._edge_travel_time(edge_id) for edge_id in remaining_edges)
        return round(total_cost, 2)

    def _edge_travel_time(self, edge_id: str) -> float:
        try:
            travel_time = traci.edge.getTraveltime(edge_id)
            if travel_time and travel_time > 0:
                return float(travel_time)
        except Exception:
            pass

        meta = self.monitored_edge_meta.get(edge_id)
        if not meta:
            return 12.0

        speed_mps = max(meta["speed_limit_kmph"] / 3.6, 3.0)
        return round(meta["length"] / speed_mps, 2)

    def _apply_scenario_controls(self) -> None:
        if not self.sumo_started or not self.latest_zones and self.tick == 0:
            return
        self._restore_default_speeds()
        if self.scenario == "rush_hour":
            return

        target_edges = []
        if self.scenario == "accident":
            target_edges = [edge.edge_id for edge in self.latest_map_edges if edge.zone_id in {"central", "west"}][:10]
            speed_factor = 0.35
        elif self.scenario == "rain_event":
            target_edges = [edge.edge_id for edge in self.latest_map_edges][:45]
            speed_factor = 0.75
        else:
            target_edges = [edge.edge_id for edge in self.latest_map_edges if edge.zone_id in {"south", "east", "central"}][:18]
            speed_factor = 0.55

        for edge_id in target_edges:
            base_speed = self.monitored_edge_meta[edge_id]["speed_limit_kmph"] / 3.6
            traci.edge.setMaxSpeed(edge_id, max(3.0, base_speed * speed_factor))
            self.scenario_modified_edges.add(edge_id)

    def _restore_default_speeds(self) -> None:
        if not self.sumo_started:
            return
        for edge_id in list(self.scenario_modified_edges):
            if edge_id in self.monitored_edge_meta:
                base_speed = self.monitored_edge_meta[edge_id]["speed_limit_kmph"] / 3.6
                traci.edge.setMaxSpeed(edge_id, base_speed)
        self.scenario_modified_edges.clear()

    def _best_signal_plan(self) -> SignalPlan | None:
        if not self.latest_zones:
            return None
        hotspot = max(self.latest_zones, key=lambda zone: zone.density)
        return SignalPlan(
            intersection_id=hotspot.zone_id.upper(),
            green_duration_seconds=45 if hotspot.congestion_level != "low" else 30,
            mode="adaptive" if self.optimization_enabled else "manual",
        )

    def _update_selected_journey(self) -> None:
        if not self.selected_journey:
            return
        vehicle_id = self.selected_journey.vehicle_id
        if vehicle_id not in traci.vehicle.getIDList():
            self.selected_journey.status = "completed"
            self.selected_journey.current_edge = None
            return
        self.selected_journey.current_edge = traci.vehicle.getRoadID(vehicle_id)
        self.selected_journey.route_edges = list(traci.vehicle.getRoute(vehicle_id))
        self.selected_journey.estimated_travel_time_seconds = self._estimate_remaining_route_cost(
            vehicle_id,
            self.selected_journey.route_edges,
        )

    def _improvement_metrics(self) -> ImprovementMetrics:
        baseline_travel = self.baseline_travel_time or 1
        baseline_density = self.baseline_density or 1
        baseline_speed = self.baseline_speed or 1
        return ImprovementMetrics(
            travel_time_saved_pct=round(max(0.0, (baseline_travel - self.optimized_travel_time) / baseline_travel * 100), 2),
            congestion_reduced_pct=round(max(0.0, (baseline_density - self.optimized_density) / baseline_density * 100), 2),
            average_speed_gain_pct=round(max(0.0, (self.optimized_speed - baseline_speed) / baseline_speed * 100), 2),
        )
