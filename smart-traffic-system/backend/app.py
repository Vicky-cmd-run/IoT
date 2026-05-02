from __future__ import annotations

import time

from fastapi import FastAPI, Depends, HTTPException
from fastapi.middleware.cors import CORSMiddleware

from auth import LoginRequest, LoginResponse, authenticate_admin, require_auth
from config import settings
from integrations import current_traffic, current_weather, map_config, zone_traffic_overview
from model import (
    DashboardSummary,
    JourneyRequest,
    LiveDashboardResponse,
    OptimizationRequest,
    PredictionResponse,
    RouteRequest,
    RouteResponse,
    ScenarioRequest,
    SignalPlan,
    SnapshotIngestionRequest,
    SnapshotIngestionResponse,
    TrafficPredictor,
    TrafficSnapshot,
    TrafficStateStore,
)
from routing import compute_best_route
from traci_handler import TraCICommandExecutor

# Choose engine based on runtime mode
if settings.traci_enabled:
    from simulation_engine import RealSUMOSimulationEngine as SimEngine
else:
    from demo_engine import DemoSimulationEngine as SimEngine  # type: ignore[assignment]

app = FastAPI(
    title="Smart Traffic System API",
    description="Backend API for ingestion, prediction, rerouting, and dashboard visualization.",
    version="0.2.0",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

store = TrafficStateStore()
predictor = TrafficPredictor(store)
traci = TraCICommandExecutor(enabled=settings.traci_enabled)
simulation = SimEngine(store=store, traci_executor=traci)


@app.on_event("startup")
def startup() -> None:
    simulation.start()


@app.get("/health")
def health() -> dict:
    return {
        "status": "ok",
        "environment": settings.app_env,
        "traci_enabled": settings.traci_enabled,
        "map_provider": settings.map_provider,
        "engine": "sumo" if settings.traci_enabled else "demo",
    }


@app.post("/auth/login", response_model=LoginResponse)
def login(payload: LoginRequest) -> LoginResponse:
    return authenticate_admin(payload.email, payload.password)


@app.get("/auth/me")
def me(claims: dict = Depends(require_auth)) -> dict:
    return {"email": claims["sub"], "expires_at": claims["exp"]}


@app.get("/config/requirements")
def config_requirements() -> dict:
    return {
        "required_user_inputs": [
            "SUMO_HOME",
            "SUMO binary path",
            "database credentials",
            "map provider choice",
        ],
        "optional_integrations": [
            "Mapbox API key",
            "TomTom API key",
            "Google Maps API key",
            "OpenWeather API key",
            "MQTT broker credentials",
            "Kafka bootstrap servers",
            "JWT secret for auth",
        ],
    }


@app.get("/integrations/map")
def integration_map() -> dict:
    return map_config()


@app.get("/integrations/weather")
def integration_weather(
    lat: float = 12.9716,
    lon: float = 77.5946,
    _: dict = Depends(require_auth),
) -> dict:
    return current_weather(lat=lat, lon=lon)


@app.get("/integrations/traffic")
def integration_traffic(
    lat: float = 12.9716,
    lon: float = 77.5946,
    _: dict = Depends(require_auth),
) -> dict:
    if lat == 12.9716 and lon == 77.5946:
        return zone_traffic_overview()
    return current_traffic(lat=lat, lon=lon)


@app.get("/predict", response_model=PredictionResponse)
def predict(
    horizon_minutes: int = 10,
    _: dict = Depends(require_auth),
) -> PredictionResponse:
    return predictor.predict(horizon_minutes=horizon_minutes)


@app.post("/reroute", response_model=RouteResponse)
def reroute(
    request: RouteRequest,
    _: dict = Depends(require_auth),
) -> RouteResponse:
    response = compute_best_route(request)
    traci.apply_route_update(response)
    return response


@app.get("/signal-plan", response_model=SignalPlan | None)
def signal_plan(_: dict = Depends(require_auth)) -> SignalPlan | None:
    summary = simulation.latest_summary()
    return summary.suggested_signal_plan if summary else None


@app.post("/signal-plan/apply")
def apply_signal_plan(_: dict = Depends(require_auth)) -> dict:
    summary = simulation.latest_summary()
    plan = summary.suggested_signal_plan if summary else None
    if plan is None:
        raise HTTPException(status_code=400, detail="No signal plan is available")
    command = traci.apply_signal_plan(plan)
    return {"message": "Signal plan applied", "command": command}


@app.get("/dashboard/summary", response_model=DashboardSummary | None)
def dashboard_summary(_: dict = Depends(require_auth)) -> DashboardSummary | None:
    return simulation.latest_summary()


@app.get("/dashboard/live", response_model=LiveDashboardResponse)
def dashboard_live(_: dict = Depends(require_auth)) -> LiveDashboardResponse:
    weather = current_weather(lat=12.9716, lon=77.5946)
    traffic = zone_traffic_overview()
    return LiveDashboardResponse(
        summary=simulation.latest_summary(),
        prediction=predictor.predict(horizon_minutes=10),
        weather=weather,
        traffic=traffic,
        simulation=simulation.state(),
        commands=traci.recent_commands(),
    )


@app.get("/commands")
def commands(_: dict = Depends(require_auth)) -> dict:
    return {"commands": traci.recent_commands()}


@app.get("/simulation/state")
def simulation_state(_: dict = Depends(require_auth)) -> dict:
    return simulation.state().model_dump()


@app.post("/ingest/snapshot", response_model=SnapshotIngestionResponse)
def ingest_snapshot(
    request: SnapshotIngestionRequest,
    _: dict = Depends(require_auth),
) -> SnapshotIngestionResponse:
    latest_summary = simulation.latest_summary()
    timestamp = request.timestamp or (latest_summary.timestamp if latest_summary else None)
    if not timestamp:
        timestamp = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())

    snapshot = TrafficSnapshot(
        timestamp=timestamp,
        intersection_id=request.intersection_id,
        segments=request.segments,
        source=request.source,
    )
    result = simulation.ingest_snapshot(snapshot)
    return SnapshotIngestionResponse(
        accepted=result["accepted"],
        source=request.source,
        timestamp=timestamp,
        segment_count=result["segment_count"],
        mode=result["mode"],
    )


@app.post("/simulation/start")
def simulation_start(_: dict = Depends(require_auth)) -> dict:
    simulation.start()
    return {"message": "Simulation started", "running": True}


@app.post("/simulation/stop")
def simulation_stop(_: dict = Depends(require_auth)) -> dict:
    simulation.stop()
    return {"message": "Simulation stopped", "running": False}


@app.post("/simulation/reset")
def simulation_reset(_: dict = Depends(require_auth)) -> dict:
    simulation.reset()
    traci.clear()
    return {"message": "Simulation state reset"}


@app.post("/simulation/scenario")
def simulation_scenario(
    request: ScenarioRequest,
    _: dict = Depends(require_auth),
) -> dict:
    simulation.set_scenario(request)
    return {"message": "Scenario updated", "scenario": request.scenario}


@app.post("/simulation/optimization")
def simulation_optimization(
    request: OptimizationRequest,
    _: dict = Depends(require_auth),
) -> dict:
    simulation.set_optimization(request.enabled)
    return {"message": "Optimization updated", "enabled": request.enabled}


@app.post("/journey/plan")
def journey_plan(
    request: JourneyRequest,
    _: dict = Depends(require_auth),
) -> dict:
    try:
        journey = simulation.create_user_journey(request)
    except RuntimeError as error:
        raise HTTPException(status_code=400, detail=str(error)) from error
    traci.apply_route_update(
        RouteResponse(
            vehicle_id=journey.vehicle_id,
            best_path=journey.route_edges,
            estimated_cost=journey.estimated_travel_time_seconds,
            reasoning=journey.reroute_reason,
        )
    )
    return {"message": "Journey created", "journey": journey.model_dump()}
