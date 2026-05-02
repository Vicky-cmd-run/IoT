import React, { useEffect, useState } from "react";
import MetricCard from "./MetricCard";
import TrafficMap, { buildZoneMap, computeRouteOverlay } from "./TrafficMap";

const scenarios = [
  { id: "accident", label: "Accident" },
  { id: "rush_hour", label: "Rush Hour" },
  { id: "rain_event", label: "Rain Event" },
  { id: "event_surge", label: "Event Surge" },
];

const routeCases = [
  { id: "west-east", label: "West to East", source_zone: "west", destination_zone: "east" },
  { id: "south-north", label: "South to North", source_zone: "south", destination_zone: "north" },
  { id: "central-east", label: "Central to East", source_zone: "central", destination_zone: "east" },
];

const zoneOrder = ["north", "west", "central", "east", "south"];

const defaultZoneDraft = {
  speed_kmph: 30,
  density: 40,
  travel_time_seconds: 120,
};

const formatClock = (value) => {
  if (!value) return "Not available";
  return value.toLocaleTimeString([], { hour: "2-digit", minute: "2-digit", second: "2-digit" });
};

const formatMode = (value) => (value ? value.replace(/_/g, " ") : "unknown");

const buildSnapshotDraft = (zones) =>
  zoneOrder.reduce((draft, zoneId) => {
    const zone = zones.find((item) => item.zone_id === zoneId);
    draft[zoneId] = zone
      ? {
          speed_kmph: zone.speed_kmph,
          density: zone.density,
          travel_time_seconds: zone.travel_time_seconds,
        }
      : { ...defaultZoneDraft };
    return draft;
  }, {});

const getRoutingBadge = (traffic, selectedJourney) => {
  if (selectedJourney?.decision_source !== "tomtom") {
    return { label: "Fallback", className: "badge-fallback" };
  }
  const cacheStatuses = Object.values(traffic?.zones || {}).map((zone) => zone.cache_status);
  if (cacheStatuses.some((status) => status === "stale")) {
    return { label: "Cached", className: "badge-cached" };
  }
  return { label: "Live", className: "badge-live" };
};

export default function Dashboard({
  commands,
  summary,
  simulation,
  prediction,
  weather,
  traffic,
  onScenarioChange,
  onSimulationStart,
  onSimulationStop,
  onSimulationReset,
  onApplySignalPlan,
  onToggleOptimization,
  onPlanJourney,
  onIngestSnapshot,
  onRunWorkflow,
  status,
  lastUpdated,
  workflowStep,
}) {
  const zones = simulation?.zones ?? [];
  const zoneMap = buildZoneMap(zones);
  const selectedJourney = simulation?.selected_journey;
  const routeOverlay = computeRouteOverlay({
    selectedJourney,
    zoneMap,
    optimizationEnabled: simulation?.optimization_enabled,
    scenario: simulation?.scenario ?? "accident",
  });

  const [ingestionSource, setIngestionSource] = useState("control_room_ui");
  const [snapshotDraft, setSnapshotDraft] = useState({});

  useEffect(() => {
    setSnapshotDraft((current) => (
      Object.keys(current).length ? current : buildSnapshotDraft(zones)
    ));
  }, [zones]);

  const congestedZones = zones.filter((zone) => zone.congestion_level !== "low").length;
  const highRiskPredictions = (prediction?.predictions ?? []).filter(
    (item) => item.future_congestion_level === "high",
  ).length;
  const hotspot = zones.length
    ? [...zones].sort((left, right) => right.density - left.density)[0]
    : null;
  const latestCommand = commands?.[commands.length - 1] ?? null;
  const routeRiskDelta = Math.max(0, routeOverlay.originalRisk - routeOverlay.optimizedRisk);
  const activePath = routeOverlay.optimizedZones.length > 1
    ? routeOverlay.optimizedZones
    : routeOverlay.originalZones;
  const trafficZones = Object.values(traffic?.zones || {});
  const tomtomHighZones = trafficZones.filter((zone) => zone.congestion_level === "high").length;
  const routingBadge = getRoutingBadge(traffic, selectedJourney);

  const handleSnapshotChange = (zoneId, field, rawValue) => {
    const value = Number(rawValue);
    setSnapshotDraft((current) => ({
      ...current,
      [zoneId]: {
        ...(current[zoneId] || defaultZoneDraft),
        [field]: Number.isFinite(value) ? value : 0,
      },
    }));
  };

  const handleIngestionSubmit = async (event) => {
    event.preventDefault();
    const segments = zoneOrder.map((zoneId) => {
      const zone = snapshotDraft[zoneId] || defaultZoneDraft;
      return {
        segment_id: zoneId.toUpperCase(),
        speed_kmph: Number(zone.speed_kmph),
        density: Number(zone.density),
        flow_rate: Number((Number(zone.density) * 7.2).toFixed(2)),
        travel_time_seconds: Number(zone.travel_time_seconds),
        signal_wait_seconds: Number(Math.max(4, Number(zone.travel_time_seconds) * 0.08).toFixed(2)),
      };
    });

    await onIngestSnapshot({
      source: ingestionSource,
      intersection_id: "BLR-CBD-LIVE",
      segments,
    });
  };

  return (
    <main className="app-shell">
      <section className="panel page-header">
        <div>
          <h1>Traffic Control Dashboard</h1>
          <p className="subtle-text">
            Real-time monitoring, ingestion, routing, and simulation control.
          </p>
        </div>
        <div className="header-status-group">
          <div className="header-status-card">
            <span>Source</span>
            <strong>{formatMode(simulation?.data_source)}</strong>
          </div>
          <div className="header-status-card">
            <span>Engine</span>
            <strong>{simulation?.running ? "Running" : "Stopped"}</strong>
          </div>
          <div className="header-status-card">
            <span>Last refresh</span>
            <strong>{formatClock(lastUpdated)}</strong>
          </div>
        </div>
      </section>

      <div className="status-banner">{status}</div>

      <section className="metric-grid">
        <MetricCard
          title="Average Speed"
          value={summary?.average_speed_kmph ?? 0}
          suffix="km/h"
          trend={`${simulation?.improvement?.average_speed_gain_pct ?? 0}% vs baseline`}
          trendDirection={Number(simulation?.improvement?.average_speed_gain_pct ?? 0) > 0 ? "up" : "neutral"}
        />
        <MetricCard
          title="Average Density"
          value={summary?.average_density ?? 0}
          suffix="%"
          trend={`${congestedZones} congested zones`}
          trendDirection={congestedZones > 0 ? "down" : "neutral"}
        />
        <MetricCard
          title="High-Risk Forecasts"
          value={highRiskPredictions}
          suffix=""
          trend={`${prediction?.predictions?.length ?? 0} monitored segments`}
          trendDirection={highRiskPredictions > 0 ? "down" : "neutral"}
        />
        <MetricCard
          title="Active Alert"
          value={hotspot ? hotspot.label : "No data"}
          suffix=""
          trend={simulation?.active_alert ?? "No live alert"}
          trendDirection={hotspot?.congestion_level === "high" ? "down" : "neutral"}
        />
      </section>

      <section className="primary-grid">
        <article className="panel map-panel">
          <div className="section-header">
            <h2>Network Map</h2>
            <span className={`badge ${simulation?.optimization_enabled ? "badge-ok" : "badge-muted"}`}>
              Optimization {simulation?.optimization_enabled ? "On" : "Off"}
            </span>
          </div>

          <TrafficMap
            selectedJourney={selectedJourney}
            zones={zones}
            scenario={simulation?.scenario ?? "accident"}
            optimizationEnabled={simulation?.optimization_enabled}
          />

          <div className="route-summary-grid">
            <div className="route-summary-card">
              <span className="summary-label">Original route</span>
              <strong>
                {routeOverlay.originalZones.length > 1
                  ? routeOverlay.originalZones.map((zoneId) => zoneMap[zoneId]?.label || zoneId).join(" -> ")
                  : "No active journey"}
              </strong>
              <small>Risk score: {routeOverlay.originalRisk.toFixed(1)}</small>
            </div>
            <div className="route-summary-card">
              <span className="summary-label">Active route</span>
              <strong>
                {activePath.length > 1
                  ? activePath.map((zoneId) => zoneMap[zoneId]?.label || zoneId).join(" -> ")
                  : "No active journey"}
              </strong>
              <small>
                {routeOverlay.rerouted
                  ? `Improved by ${routeRiskDelta.toFixed(1)} points`
                  : "No alternate route applied"}
              </small>
            </div>
            <div className="route-summary-card">
              <span className="summary-label">Journey</span>
              <strong>{selectedJourney?.status ?? "Not created"}</strong>
              <small>
                ETA {selectedJourney?.estimated_travel_time_seconds
                  ? `${selectedJourney.estimated_travel_time_seconds}s`
                  : "Not available"}
              </small>
              <small>Decision source: {formatMode(selectedJourney?.decision_source || "simulation")}</small>
            </div>
          </div>
        </article>

        <aside className="panel control-panel">
          <div className="section-header">
            <h2>Controls</h2>
            <span className="badge badge-muted">{workflowStep || "Manual"}</span>
          </div>

          <div className="control-block">
            <h3>Simulation</h3>
            <div className="button-grid">
              <button className="primary-button" onClick={onSimulationStart} type="button">Start</button>
              <button className="secondary-button" onClick={onSimulationStop} type="button">Stop</button>
              <button className="secondary-button" onClick={onSimulationReset} type="button">Reset</button>
              <button className="secondary-button" onClick={onRunWorkflow} type="button">Run workflow</button>
            </div>
            <button className="secondary-button full-width-button" onClick={onApplySignalPlan} type="button">
              Apply signal plan
            </button>
          </div>

          <div className="control-block">
            <h3>Scenario</h3>
            <div className="button-grid compact-grid">
              {scenarios.map((scenario) => (
                <button
                  key={scenario.id}
                  className={simulation?.scenario === scenario.id ? "selected-button" : "secondary-button"}
                  onClick={() => onScenarioChange(scenario.id)}
                  type="button"
                >
                  {scenario.label}
                </button>
              ))}
            </div>
          </div>

          <div className="control-block">
            <h3>Routing</h3>
            <div className="button-grid compact-grid">
              {routeCases.map((routeCase) => (
                <button
                  className="secondary-button"
                  key={routeCase.id}
                  onClick={() => onPlanJourney(routeCase)}
                  type="button"
                >
                  {routeCase.label}
                </button>
              ))}
            </div>
            <button
              className={simulation?.optimization_enabled ? "selected-button full-width-button" : "secondary-button full-width-button"}
              onClick={() => onToggleOptimization(!simulation?.optimization_enabled)}
              type="button"
            >
              {simulation?.optimization_enabled ? "Disable optimization" : "Enable optimization"}
            </button>
          </div>

          <div className="control-block">
            <h3>System</h3>
            <div className={`routing-status-badge ${routingBadge.className}`}>
              {routingBadge.label}
            </div>
            <dl className="detail-list">
              <div>
                <dt>Alert</dt>
                <dd>{simulation?.active_alert ?? "No active alert"}</dd>
              </div>
              <div>
                <dt>Signal plan</dt>
                <dd>{summary?.suggested_signal_plan?.intersection_id ?? "Not available"}</dd>
              </div>
              <div>
                <dt>Latest command</dt>
                <dd>{latestCommand ? latestCommand.type.replace(/_/g, " ") : "No commands"}</dd>
              </div>
              <div>
                <dt>Weather</dt>
                <dd>
                  {weather?.status === "ok"
                    ? `${weather.location}: ${weather.temperature_c}°C, ${weather.description}`
                    : weather?.message || "Not configured"}
                </dd>
              </div>
              <div>
                <dt>Traffic provider</dt>
                <dd>{traffic?.provider ? formatMode(traffic.provider) : "Not available"}</dd>
              </div>
              <div>
                <dt>TomTom traffic</dt>
                <dd>
                  {traffic?.status === "ok" || traffic?.status === "partial"
                    ? `${traffic.successful_zones ?? 0} of ${trafficZones.length || 5} zones updated, ${tomtomHighZones} high congestion zones from live feed`
                    : traffic?.message || "Not available"}
                </dd>
              </div>
              <div>
                <dt>Routing mode</dt>
                <dd>
                  {selectedJourney?.decision_source === "tomtom"
                    ? "A* with TomTom live traffic"
                    : "A* with internal fallback model"}
                </dd>
              </div>
            </dl>
          </div>
        </aside>
      </section>

      <section className="secondary-grid">
        <article className="panel ingestion-panel">
          <div className="section-header">
            <h2>Live Data Ingestion</h2>
            <span className="badge badge-muted">
              {simulation?.last_ingested_at ? `Last ingest ${simulation.last_ingested_at}` : "Awaiting input"}
            </span>
          </div>

          <form className="ingestion-form" onSubmit={handleIngestionSubmit}>
            <label className="field-label" htmlFor="ingestion-source">
              Source
            </label>
            <input
              id="ingestion-source"
              className="text-input"
              onChange={(event) => setIngestionSource(event.target.value)}
              type="text"
              value={ingestionSource}
            />

            <div className="table-wrap">
              <table className="data-table input-table">
                <thead>
                  <tr>
                    <th>Zone</th>
                    <th>Speed (km/h)</th>
                    <th>Density (%)</th>
                    <th>Travel time (s)</th>
                  </tr>
                </thead>
                <tbody>
                  {zoneOrder.map((zoneId) => {
                    const values = snapshotDraft[zoneId] || defaultZoneDraft;
                    return (
                      <tr key={zoneId}>
                        <td>{zoneMap[zoneId]?.label || zoneId}</td>
                        <td>
                          <input
                            className="table-input"
                            min="0"
                            onChange={(event) => handleSnapshotChange(zoneId, "speed_kmph", event.target.value)}
                            step="0.1"
                            type="number"
                            value={values.speed_kmph}
                          />
                        </td>
                        <td>
                          <input
                            className="table-input"
                            max="100"
                            min="0"
                            onChange={(event) => handleSnapshotChange(zoneId, "density", event.target.value)}
                            step="0.1"
                            type="number"
                            value={values.density}
                          />
                        </td>
                        <td>
                          <input
                            className="table-input"
                            min="0"
                            onChange={(event) => handleSnapshotChange(zoneId, "travel_time_seconds", event.target.value)}
                            step="0.1"
                            type="number"
                            value={values.travel_time_seconds}
                          />
                        </td>
                      </tr>
                    );
                  })}
                </tbody>
              </table>
            </div>

            <button className="primary-button submit-button" type="submit">
              Send snapshot
            </button>
          </form>
        </article>

        <article className="panel data-panel">
          <div className="section-header">
            <h2>Operational Data</h2>
            <span className="badge badge-muted">{commands?.length ?? 0} commands</span>
          </div>

          <h3 className="table-heading">Zones</h3>
          <div className="table-wrap">
            <table className="data-table">
              <thead>
                <tr>
                  <th>Zone</th>
                  <th>Density</th>
                  <th>Speed</th>
                  <th>Travel time</th>
                  <th>Level</th>
                </tr>
              </thead>
              <tbody>
                {zones.map((zone) => (
                  <tr key={zone.zone_id}>
                    <td>{zone.label}</td>
                    <td>{zone.density}%</td>
                    <td>{zone.speed_kmph} km/h</td>
                    <td>{zone.travel_time_seconds}s</td>
                    <td>
                      <span className={`level-pill level-${zone.congestion_level}`}>
                        {zone.congestion_level}
                      </span>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>

          <h3 className="table-heading">Predictions</h3>
          <div className="table-wrap">
            <table className="data-table">
              <thead>
                <tr>
                  <th>Segment</th>
                  <th>Forecast</th>
                  <th>Speed</th>
                  <th>Travel time</th>
                </tr>
              </thead>
              <tbody>
                {(prediction?.predictions ?? []).map((item) => (
                  <tr key={item.segment_id}>
                    <td>{item.segment_id}</td>
                    <td>
                      <span className={`level-pill level-${item.future_congestion_level}`}>
                        {item.future_congestion_level}
                      </span>
                    </td>
                    <td>{item.predicted_speed_kmph} km/h</td>
                    <td>{item.predicted_travel_time_seconds}s</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </article>
      </section>
    </main>
  );
}
