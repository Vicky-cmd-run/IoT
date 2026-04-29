/**
 * TrafficMap.jsx
 *
 * Route overlay logic:
 * - "Original route" = the path a naive GPS would take through the problem corridor
 *   (derived from backend-provided original_zone_path when a journey exists,
 *    or computed locally with scenario-biased naive costs).
 * - "Rerouted path" = the AI-optimized path that avoids congested zones
 *   (derived from backend-provided rerouted_zone_path, or computed with real costs).
 *
 * Risk scores are always computed from live zone congestion on the SAME cost model,
 * ensuring the comparison is mathematically honest.
 */

export const zoneLayout = {
  north: { x: 50, y: 18, label: "Vidhana" },
  west: { x: 20, y: 48, label: "KR" },
  central: { x: 50, y: 52, label: "Cubbon" },
  east: { x: 82, y: 46, label: "MG" },
  south: { x: 46, y: 80, label: "Majestic" },
};

export const corridorDefinitions = [
  { id: "north-central", zones: ["north", "central"], d: "M50 18 C50 24, 52 34, 50 52" },
  { id: "west-central",  zones: ["west", "central"],  d: "M20 48 C28 44, 36 43, 50 52" },
  { id: "central-east",  zones: ["central", "east"],  d: "M50 52 C62 46, 71 44, 82 46" },
  { id: "central-south", zones: ["central", "south"], d: "M50 52 C48 61, 47 70, 46 80" },
  { id: "west-north",    zones: ["west", "north"],    d: "M20 48 C24 39, 33 26, 50 18" },
  { id: "north-east",    zones: ["north", "east"],    d: "M50 18 C63 18, 72 24, 82 46" },
  { id: "west-south",    zones: ["west", "south"],    d: "M20 48 C24 63, 32 74, 46 80" },
  { id: "south-east",    zones: ["south", "east"],    d: "M46 80 C58 73, 69 63, 82 46" },
];

const corridorGraph = corridorDefinitions.reduce((graph, corridor) => {
  const [left, right] = corridor.zones;
  graph[left]  = [...(graph[left]  || []), { zone: right, corridorId: corridor.id }];
  graph[right] = [...(graph[right] || []), { zone: left,  corridorId: corridor.id }];
  return graph;
}, {});

const colorByCongestion = {
  low: "#35d39d",
  medium: "#ffbf47",
  high: "#ff6b6b",
};

const levelRank = { low: 1, medium: 2, high: 3 };

// Cost weights — must match backend LEVEL_COST
const LEVEL_COST = { low: 1.0, medium: 3.5, high: 8.0 };

// Problem zones per scenario — mirrors backend SCENARIO_PROBLEM_ZONES
const SCENARIO_PROBLEM_ZONES = {
  rush_hour:   new Set(["west", "central"]),
  accident:    new Set(["central", "west"]),
  rain_event:  new Set(["central", "north", "west"]),
  event_surge: new Set(["south", "east"]),
};

const defaultSource = "west";
const defaultDestination = "east";

export const buildZoneMap = (zones) =>
  Object.fromEntries(zones.map((zone) => [zone.zone_id, zone]));

const strongestLevel = (levels) =>
  levels.reduce(
    (cur, nxt) => (levelRank[nxt] > levelRank[cur] ? nxt : cur),
    "low",
  );

export const corridorSeverity = (corridor, zoneMap) => {
  const [a, b] = corridor.zones;
  return strongestLevel([
    zoneMap[a]?.congestion_level || "low",
    zoneMap[b]?.congestion_level || "low",
  ]);
};

/**
 * Dijkstra over the zone graph.
 * costFn(zoneId) → number: entry cost of each neighbor zone.
 */
const dijkstra = (source, destination, costFn) => {
  const distances = new Map([[source, 0]]);
  const previous = new Map();
  const queue = [{ zone: source, cost: 0 }];

  while (queue.length) {
    queue.sort((a, b) => a.cost - b.cost);
    const current = queue.shift();
    if (!current) break;
    if (current.zone === destination) break;

    for (const neighbor of corridorGraph[current.zone] || []) {
      const stepCost = costFn(neighbor.zone, neighbor.corridorId);
      const nextCost = current.cost + stepCost;
      if (nextCost < (distances.get(neighbor.zone) ?? Infinity)) {
        distances.set(neighbor.zone, nextCost);
        previous.set(neighbor.zone, { zone: current.zone, corridorId: neighbor.corridorId });
        queue.push({ zone: neighbor.zone, cost: nextCost });
      }
    }
  }

  if (!previous.has(destination) && source !== destination) return [];

  const corridorIds = [];
  let cursor = destination;
  while (cursor !== source) {
    const step = previous.get(cursor);
    if (!step) return [];
    corridorIds.unshift(step.corridorId);
    cursor = step.zone;
  }
  return corridorIds;
};

const corridorIdsToZonePath = (source, corridorIds) => {
  const path = [source];
  let current = source;
  for (const corridorId of corridorIds) {
    const corridor = corridorDefinitions.find((c) => c.id === corridorId);
    if (!corridor) continue;
    const nextZone = corridor.zones[0] === current ? corridor.zones[1] : corridor.zones[0];
    path.push(nextZone);
    current = nextZone;
  }
  return path;
};

/**
 * Compute zone-path risk: sum LEVEL_COST for each zone in the path (skip source).
 */
const routeRiskScore = (zonePath, zoneMap) =>
  zonePath
    .slice(1)
    .reduce((total, zoneId) => {
      const level = zoneMap[zoneId]?.congestion_level || "low";
      return total + (LEVEL_COST[level] ?? 1.0);
    }, 0);

/**
 * Zone path → corridor IDs (for rendering on the SVG).
 */
const zonePathToCorridorIds = (zonePath) => {
  const ids = [];
  for (let i = 0; i < zonePath.length - 1; i++) {
    const a = zonePath[i];
    const b = zonePath[i + 1];
    const corridor = corridorDefinitions.find(
      (c) => (c.zones[0] === a && c.zones[1] === b) || (c.zones[0] === b && c.zones[1] === a),
    );
    if (corridor) ids.push(corridor.id);
  }
  return ids;
};

/**
 * Build naive route: prefers problem-corridor zones (low cost → naive driver attracted to main road).
 * This simulates a GPS that doesn't know about the current scenario.
 */
const naiveCostFn = (scenario) => (zoneId) => {
  const problemZones = SCENARIO_PROBLEM_ZONES[scenario] || new Set();
  return problemZones.has(zoneId) ? 0.3 : 1.5;
};

/**
 * Build AI cost function: uses real congestion levels from live zone data.
 */
const aiCostFn = (zoneMap) => (zoneId) => {
  const level = zoneMap[zoneId]?.congestion_level || "low";
  return LEVEL_COST[level] ?? 1.0;
};

/**
 * computeRouteOverlay
 *
 * Prefers backend-provided zone paths (from selectedJourney) when available.
 * Falls back to local Dijkstra computation when no journey is selected.
 *
 * Returns:
 *   source, destination,
 *   original (corridor IDs), optimized (corridor IDs),
 *   originalZones, optimizedZones,
 *   originalRisk, optimizedRisk,
 *   changed (boolean — paths are topologically different),
 *   identicalPath (boolean — same path, no reroute possible),
 *   rerouted (boolean — optimization actually improved the route),
 *   reroute_reason (string)
 */
export const computeRouteOverlay = ({ selectedJourney, zoneMap, optimizationEnabled, scenario }) => {
  const source = selectedJourney?.source_zone || defaultSource;
  const destination = selectedJourney?.destination_zone || defaultDestination;

  let originalZones;
  let rerouttedZones;
  let originalRisk;
  let rerouttedRisk;
  let reroute_reason = "";

  // --- Use backend-computed paths when available ---
  if (
    selectedJourney?.original_zone_path?.length > 1 &&
    selectedJourney?.rerouted_zone_path?.length > 1
  ) {
    originalZones = selectedJourney.original_zone_path;
    rerouttedZones = selectedJourney.rerouted_zone_path;
    // Always recompute risk scores from current zone state so they reflect live congestion
    originalRisk = routeRiskScore(originalZones, zoneMap);
    rerouttedRisk = routeRiskScore(rerouttedZones, zoneMap);
    reroute_reason = selectedJourney.reroute_reason || "";
  } else {
    // --- Fallback: compute locally ---
    const sc = scenario || "accident";
    const naiveCorrIds = dijkstra(source, destination, naiveCostFn(sc));
    const aiCorrIds = dijkstra(source, destination, aiCostFn(zoneMap));
    originalZones = corridorIdsToZonePath(source, naiveCorrIds);
    const tempRerouted = corridorIdsToZonePath(source, aiCorrIds);
    originalRisk = routeRiskScore(originalZones, zoneMap);
    const tempRisk = routeRiskScore(tempRerouted, zoneMap);
    // Only adopt AI path if it genuinely costs less
    rerouttedZones = tempRisk < originalRisk ? tempRerouted : originalZones;
    rerouttedRisk = tempRisk < originalRisk ? tempRisk : originalRisk;
    reroute_reason = "";
  }

  const original = zonePathToCorridorIds(originalZones);
  const changed = originalZones.join("|") !== rerouttedZones.join("|");
  const rerouted = changed && optimizationEnabled && rerouttedRisk < originalRisk;

  const optimized = rerouted ? zonePathToCorridorIds(rerouttedZones) : original;
  const optimizedZones = rerouted ? rerouttedZones : originalZones;
  const optimizedRisk = rerouted ? rerouttedRisk : originalRisk;

  const identicalPath = !rerouted;

  if (!optimizationEnabled) {
    return {
      source, destination,
      original, optimized: original,
      originalZones, optimizedZones: originalZones,
      originalRisk, optimizedRisk: originalRisk,
      changed: false, identicalPath: true, rerouted: false,
      reroute_reason: "Optimization is disabled — AI routing is off.",
    };
  }

  return {
    source, destination,
    original, optimized,
    originalZones, optimizedZones,
    originalRisk, optimizedRisk,
    changed, identicalPath, rerouted,
    reroute_reason,
  };
};

export default function TrafficMap({
  selectedJourney,
  zones = [],
  optimizationEnabled = false,
  scenario = "accident",
}) {
  const zoneMap = buildZoneMap(zones);
  const routeOverlay = computeRouteOverlay({ selectedJourney, zoneMap, optimizationEnabled, scenario });

  return (
    <div className="schematic-map">
      <div className="schematic-map-bg" />
      <svg
        className="schematic-svg"
        viewBox="0 0 100 100"
        preserveAspectRatio="none"
        role="img"
        aria-label="Traffic demo map"
      >
        <defs>
          <linearGradient id="routeGlow" x1="0" y1="0" x2="1" y2="1">
            <stop offset="0%"   stopColor="#58b6ff" />
            <stop offset="100%" stopColor="#84f3ff" />
          </linearGradient>
          <linearGradient id="originalGrad" x1="0" y1="0" x2="1" y2="1">
            <stop offset="0%"   stopColor="rgba(245,115,115,0.9)" />
            <stop offset="100%" stopColor="rgba(245,115,115,0.4)" />
          </linearGradient>
        </defs>

        <g className="schematic-grid">
          <line x1="0" y1="20" x2="100" y2="20" />
          <line x1="0" y1="40" x2="100" y2="40" />
          <line x1="0" y1="60" x2="100" y2="60" />
          <line x1="0" y1="80" x2="100" y2="80" />
          <line x1="20" y1="0" x2="20" y2="100" />
          <line x1="40" y1="0" x2="40" y2="100" />
          <line x1="60" y1="0" x2="60" y2="100" />
          <line x1="80" y1="0" x2="80" y2="100" />
        </g>

        <g className="map-glow-zones">
          <circle cx="18" cy="18" r="18" />
          <circle cx="81" cy="72" r="14" />
        </g>

        {/* Base corridor network — coloured by live congestion */}
        {corridorDefinitions.map((corridor) => {
          const level = corridorSeverity(corridor, zoneMap);
          return (
            <path
              key={`base-${corridor.id}`}
              className={`corridor-line ${level === "high" ? "corridor-high" : ""} ${level === "medium" ? "corridor-medium" : ""}`}
              d={corridor.d}
              stroke={colorByCongestion[level]}
              strokeWidth={level === "high" ? 1.7 : 1.3}
            />
          );
        })}

        {/* Original route — dashed, visible whether or not rerouted */}
        {routeOverlay.original.map((id) => {
          const corridor = corridorDefinitions.find((c) => c.id === id);
          if (!corridor) return null;
          return (
            <path
              key={`original-${id}`}
              className="original-route-line"
              d={corridor.d}
            />
          );
        })}

        {/* Optimised / rerouted route — only drawn when routes differ */}
        {routeOverlay.rerouted &&
          routeOverlay.optimized.map((id) => {
            const corridor = corridorDefinitions.find((c) => c.id === id);
            if (!corridor) return null;
            return (
              <path
                key={`optimized-${id}`}
                className="corridor-line corridor-active"
                d={corridor.d}
                stroke="url(#routeGlow)"
                strokeWidth={2.4}
              />
            );
          })}

        {/* Zone nodes */}
        {Object.entries(zoneLayout).map(([zoneId, layout]) => {
          const zone = zoneMap[zoneId];
          const fill = colorByCongestion[zone?.congestion_level || "low"];
          const isSource = routeOverlay.source === zoneId;
          const isDestination = routeOverlay.destination === zoneId;
          const isEndpoint = isSource || isDestination;

          return (
            <g key={zoneId} transform={`translate(${layout.x} ${layout.y})`}>
              <circle className={isEndpoint ? "zone-ring endpoint-ring" : "zone-ring"} r="4.7" />
              <circle className={isEndpoint ? "zone-dot endpoint-dot" : "zone-dot"} r="2.6" fill={fill} />
              <text className="zone-label" x="0" y="-7.8">{layout.label}</text>
              {isEndpoint ? (
                <text className="endpoint-label" x="0" y="9.6">
                  {isSource ? "start" : "end"}
                </text>
              ) : null}
            </g>
          );
        })}
      </svg>
    </div>
  );
}
