import { startTransition, useEffect, useState } from "react";
import Dashboard from "../components/Dashboard";
import LoginForm from "../components/LoginForm";

const API_BASE = import.meta.env.VITE_API_BASE_URL || "http://localhost:8000";
const TOKEN_KEY = "smart_traffic_token";

const fallbackSummary = {
  timestamp: "Awaiting simulation feed",
  average_speed_kmph: 0,
  average_density: 0,
  congestion_segments: 0,
  total_segments: 0,
  suggested_signal_plan: null,
};

const sleep = (ms) => new Promise((resolve) => setTimeout(resolve, ms));

export default function App() {
  const [summary, setSummary]         = useState(fallbackSummary);
  const [prediction, setPrediction]   = useState({ predictions: [] });
  const [weather, setWeather]         = useState(null);
  const [mapConfig, setMapConfig]     = useState(null);
  const [simulation, setSimulation]   = useState(null);
  const [commands, setCommands]       = useState([]);
  const [status, setStatus]           = useState("Sign in to open the demo control room.");
  const [lastUpdated, setLastUpdated] = useState(null);
  const [demoStep, setDemoStep]       = useState("");
  const [token, setToken]             = useState(() => window.localStorage.getItem(TOKEN_KEY));

  const fetchWithAuth = async (path, options = {}) => {
    const response = await fetch(`${API_BASE}${path}`, {
      ...options,
      headers: {
        ...(options.headers || {}),
        Authorization: `Bearer ${token}`,
      },
    });

    if (response.status === 401) {
      window.localStorage.removeItem(TOKEN_KEY);
      setToken(null);
      throw new Error("Unauthorized");
    }

    return response.json();
  };

  const loadDashboard = async ({ preserveStatus = false } = {}) => {
    const [liveData, mapData] = await Promise.all([
      fetchWithAuth("/dashboard/live"),
      fetch(`${API_BASE}/integrations/map`).then((r) => r.json()),
    ]);

    startTransition(() => {
      setSummary(liveData.summary || fallbackSummary);
      setPrediction(liveData.prediction || { predictions: [] });
      setWeather(liveData.weather || null);
      setSimulation(liveData.simulation || null);
      setCommands(liveData.commands || []);
      setMapConfig(mapData);
      setLastUpdated(new Date());
      if (!preserveStatus) {
        setStatus("Demo live. Controls are connected and updates are streaming.");
      }
    });
  };

  useEffect(() => {
    if (!token) return;

    let active = true;

    const load = async (options = {}) => {
      try {
        await loadDashboard(options);
      } catch {
        if (!active) return;
        setStatus("Session expired or backend not reachable.");
      }
    };

    load();
    const intervalId = window.setInterval(() => {
      if (active) load({ preserveStatus: true });
    }, 2500);

    return () => {
      active = false;
      window.clearInterval(intervalId);
    };
  }, [token]);

  const handleLogin = async ({ email, password }) => {
    try {
      const response = await fetch(`${API_BASE}/auth/login`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ email, password }),
      });

      if (!response.ok) {
        setStatus("Login failed. Check the demo credentials.");
        return;
      }

      const data = await response.json();
      window.localStorage.setItem(TOKEN_KEY, data.access_token);
      setToken(data.access_token);
      setStatus(`Signed in as ${data.admin_email}. Demo is ready.`);
    } catch {
      setStatus("Backend not reachable yet.");
    }
  };

  const runControl = async (path, payload) => {
    try {
      setStatus("Applying change...");
      await fetchWithAuth(path, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: payload ? JSON.stringify(payload) : undefined,
      });
      await loadDashboard({ preserveStatus: true });
      setStatus("Change applied. Demo view refreshed.");
    } catch {
      setStatus("Command failed. Control loop did not confirm execution.");
    }
  };

  const handleJourneyPlan = async ({ source_zone, destination_zone }) => {
    try {
      setStatus("Creating demo journey...");
      await fetchWithAuth("/journey/plan", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ source_zone, destination_zone }),
      });
      await loadDashboard({ preserveStatus: true });
      setStatus("Journey created. Route comparison and ETA are now live.");
    } catch {
      setStatus("Journey planning failed for that zone pair.");
    }
  };

  /**
   * Guided demo — carefully sequenced so:
   * 1. Engine resets and restarts cleanly
   * 2. Scenario congestion is injected
   * 3. We wait for several simulation ticks so zones have realistic varied congestion
   * 4. Only then do we plan the journey — so route comparison is meaningful
   */
  const runGuidedDemo = async () => {
    try {
      setDemoStep("Resetting simulation…");
      setStatus("Guided demo: resetting simulation state…");
      await fetchWithAuth("/simulation/reset", { method: "POST" });
      await sleep(600);

      setDemoStep("Starting engine…");
      setStatus("Guided demo: starting the simulation engine…");
      await fetchWithAuth("/simulation/start", { method: "POST" });
      await sleep(800);

      setDemoStep("Injecting scenario: Accident");
      setStatus("Guided demo: injecting accident congestion scenario…");
      await fetchWithAuth("/simulation/scenario", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ scenario: "accident" }),
      });

      // Wait for congestion to propagate across zones (≥4 simulation ticks)
      setDemoStep("Building congestion…");
      setStatus("Guided demo: waiting for congestion to build across zones…");
      await sleep(4000);
      await loadDashboard({ preserveStatus: true });

      setDemoStep("Enabling AI optimization");
      setStatus("Guided demo: enabling adaptive AI optimization…");
      await fetchWithAuth("/simulation/optimization", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ enabled: true }),
      });
      await sleep(800);

      setDemoStep("Planning West → East journey");
      setStatus("Guided demo: creating a West → East journey through the accident zone…");
      await fetchWithAuth("/journey/plan", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ source_zone: "west", destination_zone: "east" }),
      });

      await sleep(600);
      await loadDashboard({ preserveStatus: true });

      setDemoStep("Demo ready ✓");
      setStatus(
        "Guided demo ready. You should now see heterogeneous zone congestion, a live route, " +
        "and a route comparison with different risk scores.",
      );
    } catch {
      setDemoStep("");
      setStatus("Guided demo could not complete — check backend connectivity.");
    }
  };

  if (!token) {
    return <LoginForm onLogin={handleLogin} status={status} />;
  }

  return (
    <Dashboard
      commands={commands}
      summary={summary}
      simulation={simulation}
      prediction={prediction}
      weather={weather}
      mapConfig={mapConfig}
      onScenarioChange={(scenario) => runControl("/simulation/scenario", { scenario })}
      onSimulationStart={() => runControl("/simulation/start")}
      onSimulationStop={() => runControl("/simulation/stop")}
      onSimulationReset={() => runControl("/simulation/reset")}
      onToggleOptimization={(enabled) => runControl("/simulation/optimization", { enabled })}
      onPlanJourney={handleJourneyPlan}
      onRunGuidedDemo={runGuidedDemo}
      status={status}
      lastUpdated={lastUpdated}
      demoStep={demoStep}
    />
  );
}
