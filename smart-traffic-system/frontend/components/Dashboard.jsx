import React from "react";
import {
  Activity,
  AlertTriangle,
  BrainCircuit,
  CheckCircle2,
  Gauge,
  GitBranch,
  Play,
  RefreshCcw,
  Route,
  ShieldAlert,
  Sparkles,
  WandSparkles,
  Waves,
} from "lucide-react";
import MetricCard from "./MetricCard";
import TrafficMap, { buildZoneMap, computeRouteOverlay } from "./TrafficMap";

const scenarios = [
  { id: "rush_hour",   label: "Rush Hour",   issue: "commuter overload on west-central",      severity: "medium" },
  { id: "accident",   label: "Accident",    issue: "lane-blocking incident in central zone",  severity: "high" },
  { id: "rain_event", label: "Rain Event",  issue: "network-wide speed degradation",         severity: "medium" },
  { id: "event_surge",label: "Event Surge", issue: "localized demand spike at south-east",    severity: "high" },
];

const scenarioNarratives = {
  rush_hour: {
    problem:  "Commuter demand rises across the west-central corridor and queues begin stacking at shared intersections.",
    solution: "The controller smooths signal timing and diverts cross-town journeys away from the densest middle corridor.",
    corridor: "West → Central (primary overload zone)",
  },
  accident: {
    problem:  "A major incident blocks a critical city link in the central zone, creating spillback into the west corridor.",
    solution: "The platform isolates the affected corridor, protects alternative paths, and actively reroutes exposed journeys.",
    corridor: "Central + West (blocked by incident)",
  },
  rain_event: {
    problem:  "Rain lowers operating speed across multiple zones, so even moderate volume creates unstable travel times.",
    solution: "The controller redistributes flow, slows route commitments into risky links, and preserves the most reliable corridors.",
    corridor: "North → Central (rain-degraded primary link)",
  },
  event_surge: {
    problem:  "A venue release sends concentrated demand into the south-east side of the network, creating sudden directional pressure.",
    solution: "The system shifts priority toward the surge direction and moves through-traffic around the event-heavy side.",
    corridor: "South + East (venue demand surge)",
  },
};

const controlLoop = [
  { id: "detect",    title: "Detect problem",    text: "Identify the overloaded corridor or disrupted zone." },
  { id: "predict",   title: "Predict spread",    text: "Estimate where congestion will spill next." },
  { id: "reroute",   title: "Reroute flow",      text: "Move exposed journeys onto safer corridors." },
  { id: "stabilize", title: "Stabilize network", text: "Rebalance signals and recover travel time." },
];

const routeCases = [
  { id: "west-east",    label: "West → East",    source_zone: "west",    destination_zone: "east"  },
  { id: "south-north",  label: "South → North",  source_zone: "south",   destination_zone: "north" },
  { id: "central-east", label: "Central → East", source_zone: "central", destination_zone: "east"  },
];

const formatTime = (value) => {
  if (!value) return "just now";
  return value.toLocaleTimeString([], { hour: "2-digit", minute: "2-digit", second: "2-digit" });
};

const formatGain = (value) => {
  const numeric = Number(value || 0);
  if (!numeric) return null;
  if (numeric > 900) return "Major reroute applied";
  if (numeric >= 60) return `Saved ${(numeric / 60).toFixed(1)} min`;
  return `Saved ${numeric.toFixed(1)}s`;
};

const riskLabel = (risk) => {
  if (risk >= 8) return { text: "HIGH RISK", cls: "risk-badge-high" };
  if (risk >= 3) return { text: "MEDIUM RISK", cls: "risk-badge-medium" };
  return { text: "LOW RISK", cls: "risk-badge-low" };
};

export default function Dashboard({
  commands,
  summary,
  simulation,
  prediction,
  weather,
  onScenarioChange,
  onSimulationStart,
  onSimulationReset,
  onToggleOptimization,
  onPlanJourney,
  onRunGuidedDemo,
  status,
  lastUpdated,
  demoStep,
}) {
  const zones = simulation?.zones ?? [];
  const selectedJourney = simulation?.selected_journey;
  const improvement = simulation?.improvement ?? {};
  const history = simulation?.history ?? [];
  const latestHistory = history.at(-1);
  const scenarioId = simulation?.scenario ?? "accident";
  const scenarioInfo = scenarioNarratives[scenarioId] || scenarioNarratives.accident;
  const zoneMap = buildZoneMap(zones);

  const routeOverlay = computeRouteOverlay({
    selectedJourney,
    zoneMap,
    optimizationEnabled: simulation?.optimization_enabled,
    scenario: scenarioId,
  });

  const travelSaved = Math.max(
    0,
    Number(latestHistory?.baseline_travel_time_seconds ?? 0) -
      Number(latestHistory?.optimized_travel_time_seconds ?? 0),
  );
  const hotspot = zones.length ? [...zones].sort((a, b) => b.density - a.density)[0] : null;
  const commandCount = commands?.length ?? 0;
  const highRiskCount = (prediction?.predictions ?? []).filter(
    (item) => item.future_congestion_level === "high",
  ).length;

  const baselineTravelTime  = Number(latestHistory?.baseline_travel_time_seconds  ?? 0);
  const optimizedTravelTime = Number(latestHistory?.optimized_travel_time_seconds ?? 0);

  const latestActionLabel = formatGain(commands?.[commands.length - 1]?.gain_seconds);
  const impactHeadline = travelSaved > 0
    ? `Optimization is saving ${travelSaved.toFixed(1)} seconds on the active network loop.`
    : "The demo is live — trigger a scenario and plan a journey to see route comparison.";
  const actionHeadline = latestActionLabel
    ? `Latest reroute: ${latestActionLabel}.`
    : "Use the guided demo to force a route update and visible response.";

  const highCorridorCount  = zones.filter((z) => z.congestion_level === "high").length;
  const mediumCorridorCount = zones.filter((z) => z.congestion_level === "medium").length;

  const loopState = {
    detect:    Boolean(simulation?.scenario),
    predict:   Boolean(prediction?.predictions?.length),
    reroute:   routeOverlay.rerouted,
    stabilize: Boolean(commandCount),
  };

  // --- Route comparison decision copy ---
  const routeRiskDelta = routeOverlay.originalRisk - routeOverlay.optimizedRisk;

  let routeDecisionText;
  let routeDecisionClass = "decision-card";

  if (!selectedJourney) {
    routeDecisionText = "No journey selected yet. Use the route buttons below the map to create one.";
  } else if (!simulation?.optimization_enabled) {
    routeDecisionText = "AI optimization is off — the system is not computing alternate routes. Enable it to see reroute analysis.";
  } else if (routeOverlay.rerouted && routeRiskDelta > 0) {
    routeDecisionText = `Route shifted away from the problem corridor. Risk score improved by ${routeRiskDelta.toFixed(1)} points (${((routeRiskDelta / routeOverlay.originalRisk) * 100).toFixed(0)}% reduction). ${routeOverlay.reroute_reason}`;
    routeDecisionClass = "decision-card decision-success";
  } else if (routeOverlay.identicalPath) {
    routeDecisionText =
      "The AI evaluated all alternate corridors and found the original route is already the best available option under current conditions. No reroute was applied.";
    routeDecisionClass = "decision-card decision-neutral";
  } else {
    routeDecisionText = routeOverlay.reroute_reason || "Monitoring route for improvement opportunities.";
  }

  const rerouteStatusText = selectedJourney?.rerouted
    ? `Rerouted successfully — ETA now ${selectedJourney?.estimated_travel_time_seconds ?? 0}s via safer corridor.`
    : selectedJourney
    ? "Journey is live. AI is monitoring for a better route."
    : "No active journey — use the route buttons to create one.";

  const origRiskInfo = riskLabel(routeOverlay.originalRisk);
  const reroRiskInfo = riskLabel(routeOverlay.optimizedRisk);

  return (
    <main className="app-shell">
      {/* ── Hero ── */}
      <section className="simple-hero panel">
        <div className="simple-hero-copy">
          <div className="eyebrow">
            <Sparkles size={14} />
            FlowSync AI — Traffic Intelligence Demo
          </div>
          <h1 className="simple-title">
            Interview-quality traffic rerouting with real cost-model comparison.
          </h1>
          <p className="hero-text">
            Each scenario creates genuine heterogeneous congestion. The AI picks
            the lowest-cost route using live zone data — the original and rerouted
            paths always reflect the same cost model.
          </p>
          <div className="status-pill">
            <Activity size={16} /> {status}
          </div>
        </div>

        <div className="demo-actions">
          <button className="demo-button primary" onClick={onRunGuidedDemo} type="button">
            <WandSparkles size={18} />
            Run guided demo
          </button>
          <button className="demo-button" onClick={onSimulationStart} type="button">
            <Play size={18} />
            Start engine
          </button>
          <button className="demo-button" onClick={onSimulationReset} type="button">
            <RefreshCcw size={18} />
            Reset
          </button>
          {demoStep ? (
            <div className="demo-step-indicator">
              <Activity size={14} /> {demoStep}
            </div>
          ) : null}
        </div>
      </section>

      {/* ── Step cards ── */}
      <section className="demo-overview">
        <article className="panel quick-panel">
          <h3>Step 1 — Inject a problem</h3>
          <p className="section-intro">
            Choose the failure mode you want to explain. Each scenario affects specific zones.
          </p>
          <div className="scenario-grid simple-grid">
            {scenarios.map((scenario) => (
              <button
                key={scenario.id}
                className={`scenario-card interview-card ${simulation?.scenario === scenario.id ? "selected" : ""}`}
                onClick={() => onScenarioChange(scenario.id)}
                type="button"
              >
                <span>{scenario.label}</span>
                <small>{scenario.issue}</small>
              </button>
            ))}
          </div>
          {scenarioInfo.corridor && (
            <div className="corridor-callout">
              <AlertTriangle size={14} />
              <span>Problem corridor: <strong>{scenarioInfo.corridor}</strong></span>
            </div>
          )}
        </article>

        <article className="panel quick-panel">
          <h3>Step 2 — AI control loop</h3>
          <p className="section-intro">
            What does the system do after detecting the problem?
          </p>
          <div className="loop-grid">
            {controlLoop.map((step) => (
              <div className={`loop-card ${loopState[step.id] ? "active" : ""}`} key={step.id}>
                <strong>{step.title}</strong>
                <span>{step.text}</span>
              </div>
            ))}
          </div>
          <div className="simple-action-stack">
            <button
              className={`demo-button ${simulation?.optimization_enabled ? "enabled" : ""}`}
              onClick={() => onToggleOptimization(!simulation?.optimization_enabled)}
              type="button"
            >
              <BrainCircuit size={18} />
              {simulation?.optimization_enabled ? "AI optimization ON" : "Turn AI optimization ON"}
            </button>
            <div className="route-cases">
              {routeCases.map((routeCase) => (
                <button
                  className="demo-button route-case-button"
                  key={routeCase.id}
                  onClick={() => onPlanJourney(routeCase)}
                  type="button"
                >
                  <Route size={18} />
                  {routeCase.label}
                </button>
              ))}
            </div>
          </div>
        </article>

        <article className="panel quick-panel">
          <h3>Step 3 — Explain the outcome</h3>
          <div className="result-list">
            <div><strong>Scenario:</strong> {simulation?.scenario?.replace(/_/g, " ") ?? "not set"}</div>
            <div><strong>Engine:</strong> {simulation?.running ? "running" : "paused"}</div>
            <div><strong>Last update:</strong> {formatTime(lastUpdated)}</div>
            <div><strong>AI actions:</strong> {commandCount}</div>
            <div><strong>High-congestion zones:</strong> {highCorridorCount}</div>
            <div><strong>Medium-congestion zones:</strong> {mediumCorridorCount}</div>
            <div>
              <strong>Route rerouted:</strong>{" "}
              {routeOverlay.rerouted ? (
                <span className="status-ok">✓ Yes — lower risk path found</span>
              ) : selectedJourney ? (
                <span className="status-neutral">— Original route is optimal</span>
              ) : (
                <span className="status-neutral">— No journey active</span>
              )}
            </div>
          </div>
        </article>
      </section>

      {/* ── Metrics ── */}
      <section className="hero-grid simple-metric-grid">
        <MetricCard
          title="Congestion Hotspot"
          value={hotspot ? hotspot.label : "Waiting"}
          suffix=""
          trend={hotspot ? `${hotspot.density.toFixed(0)}% density · ${hotspot.congestion_level} level` : "No live data yet"}
          trendDirection={hotspot?.congestion_level === "high" ? "down" : "neutral"}
        />
        <MetricCard
          title="Average Speed"
          value={summary?.average_speed_kmph ?? 0}
          suffix="km/h"
          trend={`${improvement?.average_speed_gain_pct ?? 0}% gain vs unoptimized baseline`}
          trendDirection={Number(improvement?.average_speed_gain_pct ?? 0) > 0 ? "up" : "neutral"}
        />
        <MetricCard
          title="Travel Time Saved"
          value={travelSaved.toFixed(1)}
          suffix="s"
          trend={travelSaved > 0 ? "Optimization is working" : "Awaiting live data"}
          trendDirection={travelSaved > 0 ? "up" : "neutral"}
        />
        <MetricCard
          title="High-Risk Predictions"
          value={highRiskCount}
          suffix=""
          trend={`${summary?.congestion_segments ?? 0} congested segments right now`}
          trendDirection={highRiskCount > 0 ? "down" : "neutral"}
        />
      </section>

      {/* ── Story strip ── */}
      <section className="demo-story-grid">
        <article className="panel story-banner">
          <div className="story-banner-icon">
            <Route size={20} />
          </div>
          <div>
            <h3>What the audience should notice</h3>
            <p>{impactHeadline}</p>
            <span>{actionHeadline}</span>
          </div>
        </article>

        <article className="panel compare-card before-state">
          <div className="compare-label">Without AI Optimization</div>
          <strong>{baselineTravelTime ? `${baselineTravelTime.toFixed(1)}s` : "Waiting"}</strong>
          <p>Traffic stays on overloaded corridors — queues keep building.</p>
        </article>

        <article className="panel compare-card after-state">
          <div className="compare-label">With AI Optimization</div>
          <strong>{optimizedTravelTime ? `${optimizedTravelTime.toFixed(1)}s` : "Waiting"}</strong>
          <p>Signals adapt, route is protected, travel time compresses.</p>
        </article>
      </section>

      {/* ── Map + Side panel ── */}
      <section className="demo-main">
        <article className="panel map-panel">
          <div className="panel-heading">
            <h3>Problem Corridor &amp; Route Comparison</h3>
            <div className="live-dot active">LIVE</div>
          </div>
          <p className="section-intro">
            Red = heavy congestion · Amber = medium congestion ·
            Dashed white = original route (naive GPS) ·
            Blue glow = AI-rerouted path (only shown when a better route exists).
          </p>

          <TrafficMap
            selectedJourney={selectedJourney}
            zones={zones}
            scenario={scenarioId}
            optimizationEnabled={simulation?.optimization_enabled}
          />

          <div className="map-legend">
            <span><i className="legend-swatch route" />     AI-rerouted path</span>
            <span><i className="legend-swatch original" />  original route</span>
            <span><i className="legend-swatch high" />      heavy congestion</span>
            <span><i className="legend-swatch medium" />    medium congestion</span>
          </div>

          {/* Route comparison cards */}
          <div className="route-compare-panel">
            <div className="route-compare-card">
              <span className="route-compare-label">Original route (naive GPS)</span>
              <strong>
                {routeOverlay.originalZones.length > 1
                  ? routeOverlay.originalZones
                      .map((z) => zoneMap[z]?.label || z)
                      .join(" → ")
                  : "Waiting for journey"}
              </strong>
              <p>
                Risk score:{" "}
                <span className={origRiskInfo.cls}>
                  {routeOverlay.originalRisk.toFixed(1)} — {origRiskInfo.text}
                </span>
              </p>
              {routeOverlay.originalZones.length > 1 && (
                <p className="route-explain">
                  Goes through:{" "}
                  {routeOverlay.originalZones
                    .slice(1)
                    .map((z) => `${zoneMap[z]?.label || z} (${zoneMap[z]?.congestion_level || "?"})`)
                    .join(", ")}
                </p>
              )}
            </div>

            <div className={`route-compare-card ${routeOverlay.rerouted ? "rerouted-card" : ""}`}>
              <span className="route-compare-label">
                {routeOverlay.rerouted ? "AI-rerouted path ✓" : "AI evaluation result"}
              </span>
              <strong>
                {routeOverlay.rerouted
                  ? routeOverlay.optimizedZones.map((z) => zoneMap[z]?.label || z).join(" → ")
                  : routeOverlay.identicalPath && selectedJourney
                  ? "Same as original — no better option"
                  : "Waiting for journey"}
              </strong>
              <p>
                Risk score:{" "}
                {routeOverlay.rerouted ? (
                  <span className={reroRiskInfo.cls}>
                    {routeOverlay.optimizedRisk.toFixed(1)} — {reroRiskInfo.text}
                    {routeRiskDelta > 0 && (
                      <> · <strong className="risk-improvement">−{routeRiskDelta.toFixed(1)} improvement</strong></>
                    )}
                  </span>
                ) : (
                  <span className="route-explain">
                    {selectedJourney
                      ? "Original route is already lowest-cost"
                      : "No journey active"}
                  </span>
                )}
              </p>
              {routeOverlay.rerouted && routeOverlay.optimizedZones.length > 1 && (
                <p className="route-explain">
                  Avoids:{" "}
                  {routeOverlay.originalZones
                    .filter((z) => !routeOverlay.optimizedZones.includes(z))
                    .map((z) => `${zoneMap[z]?.label || z} (${zoneMap[z]?.congestion_level || "?"})`)
                    .join(", ") || "—"}
                </p>
              )}
            </div>
          </div>
        </article>

        {/* Side panel */}
        <article className="panel side-panel">
          <div className="panel-heading">
            <h3>Solution Explanation</h3>
          </div>

          <div className={selectedJourney?.rerouted ? "live-banner success" : "live-banner"}>
            {rerouteStatusText}
          </div>

          <div className="explain-card problem-card">
            <div className="explain-header">
              <ShieldAlert size={18} />
              <strong>Problem</strong>
            </div>
            <p>{scenarioInfo.problem}</p>
          </div>

          <div className="explain-card solution-card">
            <div className="explain-header">
              <Waves size={18} />
              <strong>Solution</strong>
            </div>
            <p>{scenarioInfo.solution}</p>
          </div>

          <div className={routeDecisionClass}>
            <div className="explain-header">
              <GitBranch size={18} />
              <strong>Reroute decision</strong>
            </div>
            <p>{routeDecisionText}</p>
          </div>

          <div className="journey-status simple-journey-status">
            <strong>Journey status:</strong>{" "}
            {selectedJourney?.status ?? "none"}
            <br />
            <strong>Vehicle:</strong>{" "}
            {selectedJourney?.vehicle_id ?? "not created"}
            <br />
            <strong>ETA:</strong>{" "}
            {selectedJourney?.estimated_travel_time_seconds
              ? `${selectedJourney.estimated_travel_time_seconds}s`
              : "—"}
            <br />
            <strong>Risk delta:</strong>{" "}
            {routeOverlay.rerouted
              ? <span className="status-ok">−{routeRiskDelta.toFixed(1)} pts ({((routeRiskDelta / (routeOverlay.originalRisk || 1)) * 100).toFixed(0)}% better)</span>
              : <span className="status-neutral">No reroute applied</span>}
          </div>

          <div className="weather-card">
            <strong className="card-title">System metrics</strong>
            <div className="prediction-meta">
              <Gauge size={16} />
              Speed gain vs baseline: {improvement?.average_speed_gain_pct ?? 0}%
            </div>
            <div className="prediction-meta">
              <AlertTriangle size={16} />
              Congestion reduction: {improvement?.congestion_reduced_pct ?? 0}%
            </div>
            <div className="prediction-meta">
              <CheckCircle2 size={16} />
              Travel time saved: {improvement?.travel_time_saved_pct ?? 0}%
            </div>
            <div className="prediction-meta">
              <Route size={16} />
              Weather: {weather?.status === "ok" ? weather.condition : "not active"}
            </div>
          </div>

          <div className="command-card">
            <strong className="card-title">Latest AI actions</strong>
            {commands?.length ? (
              commands
                .slice(-5)
                .reverse()
                .map((command, index) => (
                  <div
                    className="prediction-meta command-item"
                    key={`${command.type}-${index}`}
                  >
                    <span className="command-type">{command.type}</span>
                    <span>
                      {command.gain_seconds
                        ? formatGain(command.gain_seconds)
                        : command.description || "Action applied"}
                    </span>
                  </div>
                ))
            ) : (
              <div className="prediction-meta">
                No AI actions logged yet — run the guided demo first.
              </div>
            )}
          </div>
        </article>
      </section>
    </main>
  );
}
