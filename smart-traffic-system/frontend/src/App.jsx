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
  const [traffic, setTraffic]         = useState(null);
  const [mapConfig, setMapConfig]     = useState(null);
  const [simulation, setSimulation]   = useState(null);
  const [commands, setCommands]       = useState([]);
  const [status, setStatus]           = useState("Sign in to access the dashboard.");
  const [lastUpdated, setLastUpdated] = useState(null);
  const [workflowStep, setWorkflowStep] = useState("");
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
      setTraffic(liveData.traffic || null);
      setSimulation(liveData.simulation || null);
      setCommands(liveData.commands || []);
      setMapConfig(mapData);
      setLastUpdated(new Date());
      if (!preserveStatus) {
        setStatus("Dashboard connected.");
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
        setStatus("Session expired or backend is not reachable.");
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
        setStatus("Login failed. Check credentials.");
        return;
      }

      const data = await response.json();
      window.localStorage.setItem(TOKEN_KEY, data.access_token);
      setToken(data.access_token);
      setStatus(`Signed in as ${data.admin_email}.`);
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
      setStatus("Change applied.");
    } catch {
      setStatus("Command failed.");
    }
  };

  const handleJourneyPlan = async ({ source_zone, destination_zone }) => {
    try {
      setStatus("Creating journey...");
      await fetchWithAuth("/journey/plan", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ source_zone, destination_zone }),
      });
      await loadDashboard({ preserveStatus: true });
      setStatus("Journey created.");
    } catch {
      setStatus("Journey planning failed for that route.");
    }
  };

  const handleIngestSnapshot = async (payload) => {
    try {
      setStatus("Sending live snapshot...");
      await fetchWithAuth("/ingest/snapshot", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(payload),
      });
      await loadDashboard({ preserveStatus: true });
      setStatus("Live snapshot ingested.");
    } catch {
      setStatus("Snapshot ingestion failed.");
    }
  };

  const runWorkflow = async () => {
    try {
      setWorkflowStep("Resetting state");
      setStatus("Resetting simulation state...");
      await fetchWithAuth("/simulation/reset", { method: "POST" });
      await sleep(600);

      setWorkflowStep("Starting engine");
      setStatus("Starting simulation engine...");
      await fetchWithAuth("/simulation/start", { method: "POST" });
      await sleep(800);

      setWorkflowStep("Applying scenario");
      setStatus("Applying accident scenario...");
      await fetchWithAuth("/simulation/scenario", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ scenario: "accident" }),
      });

      setWorkflowStep("Collecting updates");
      setStatus("Waiting for live updates...");
      await sleep(4000);
      await loadDashboard({ preserveStatus: true });

      setWorkflowStep("Enabling optimization");
      setStatus("Enabling optimization...");
      await fetchWithAuth("/simulation/optimization", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ enabled: true }),
      });
      await sleep(800);

      setWorkflowStep("Planning journey");
      setStatus("Planning West to East journey...");
      await fetchWithAuth("/journey/plan", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ source_zone: "west", destination_zone: "east" }),
      });

      await sleep(600);
      await loadDashboard({ preserveStatus: true });

      setWorkflowStep("Complete");
      setStatus("Workflow run completed.");
    } catch {
      setWorkflowStep("");
      setStatus("Workflow run failed.");
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
      traffic={traffic}
      mapConfig={mapConfig}
      onScenarioChange={(scenario) => runControl("/simulation/scenario", { scenario })}
      onSimulationStart={() => runControl("/simulation/start")}
      onSimulationStop={() => runControl("/simulation/stop")}
      onSimulationReset={() => runControl("/simulation/reset")}
      onApplySignalPlan={() => runControl("/signal-plan/apply")}
      onToggleOptimization={(enabled) => runControl("/simulation/optimization", { enabled })}
      onPlanJourney={handleJourneyPlan}
      onIngestSnapshot={handleIngestSnapshot}
      onRunWorkflow={runWorkflow}
      status={status}
      lastUpdated={lastUpdated}
      workflowStep={workflowStep}
    />
  );
}
