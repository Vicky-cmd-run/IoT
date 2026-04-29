# FlowSync AI — Smart Traffic Intelligence Demo

> An interview-quality IoT + AI traffic rerouting demo built with FastAPI, React/Vite, and a scenario-driven simulation engine.

[![Deploy Backend on Railway](https://railway.com/button.svg)](https://railway.com)
[![Deploy Frontend on Vercel](https://vercel.com/button)](https://vercel.com)

---

## Live Demo Architecture

```
Vercel (React/Vite)  ──HTTPS──▶  Railway (FastAPI)
        │                               │
        │   /dashboard/live             │  DemoSimulationEngine
        │   /journey/plan               │  ├─ Scenario-driven zone congestion
        │   /simulation/scenario        │  ├─ Dijkstra route comparison
        └───────────────────────────────┘  └─ Honest risk scoring
```

---

## What This Demo Shows

| Feature | How |
|---------|-----|
| Scenario-driven congestion | Each scenario produces heterogeneous zone density (accident: central+west HIGH, others LOW) |
| Genuine route comparison | Naive GPS path vs AI-optimized path via Dijkstra on a live cost model |
| Mathematically honest risk scores | Both routes scored with the same LEVEL_COST model from live zone data |
| Clear reroute explanation | "Risk improved by 7.0 pts (78%) — Accident blocks central zone, AI redirects via north" |
| Dynamic map | Corridors coloured by live congestion, blue glow only when AI found a genuinely better route |

---

## Quick Start (Local)

```bash
# 1. Clone
git clone https://github.com/Vicky-cmd-run/IoT.git
cd IoT/smart-traffic-system

# 2. Backend
cd backend
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
cp ../.env.example ../.env
# Edit .env: set JWT_SECRET, ADMIN_EMAIL, ADMIN_PASSWORD, TRACI_ENABLED=false
uvicorn app:app --reload --port 8000

# 3. Frontend (new terminal)
cd frontend
npm install
# Edit .env.local: VITE_API_BASE_URL=http://localhost:8000
npm run dev
```

---

## Deploy to Railway (Backend)

### Step 1 — Create Railway project
1. Go to [railway.com](https://railway.com) → **New Project** → **Deploy from GitHub repo**
2. Select `Vicky-cmd-run/IoT`
3. Set **Root Directory** → `smart-traffic-system/backend`
4. Railway auto-detects `nixpacks.toml`

### Step 2 — Set environment variables in Railway dashboard

| Variable | Value |
|----------|-------|
| `APP_ENV` | `production` |
| `TRACI_ENABLED` | `false` |
| `JWT_SECRET` | *(run `python3 -c "import secrets; print(secrets.token_hex(32))"`)* |
| `ADMIN_EMAIL` | your email |
| `ADMIN_PASSWORD` | your password |
| `OPENWEATHER_API_KEY` | *(optional — get free key at openweathermap.org)* |

### Step 3 — Deploy
Click **Deploy**. Railway builds with Nixpacks (Python 3.13), installs requirements, starts uvicorn.

**Expected deploy URL:** `https://your-app.up.railway.app`

**Health check:** `GET https://your-app.up.railway.app/health` → `{"status":"ok","engine":"demo"}`

---

## Deploy to Vercel (Frontend)

### Step 1 — Import project
1. Go to [vercel.com](https://vercel.com) → **Add New Project** → **Import Git Repository**
2. Select `Vicky-cmd-run/IoT`
3. Set **Root Directory** → `smart-traffic-system/frontend`

### Step 2 — Set environment variable

| Variable | Value |
|----------|-------|
| `VITE_API_BASE_URL` | `https://your-railway-app.up.railway.app` *(from Railway deploy)* |

### Step 3 — Deploy
Vercel auto-detects Vite, runs `npm run build`, serves `dist/`. The `vercel.json` handles SPA routing.

---

## Project Structure

```
smart-traffic-system/
├── backend/
│   ├── app.py                  # FastAPI app — routes, engine selection
│   ├── demo_engine.py          # DemoSimulationEngine — scenario congestion, route comparison
│   ├── simulation_engine.py    # RealSUMOSimulationEngine — for SUMO deployments
│   ├── routing.py              # Dijkstra weighted routing (used by /reroute API)
│   ├── model.py                # Pydantic models — JourneyState, ZoneMetric, etc.
│   ├── auth.py                 # HMAC-SHA256 JWT auth (stdlib only)
│   ├── config.py               # Settings from environment
│   ├── integrations.py         # OpenWeather + map config
│   ├── nixpacks.toml           # Railway build config
│   ├── railway.json            # Railway deploy config
│   └── requirements.txt        # Python deps
├── frontend/
│   ├── src/
│   │   ├── App.jsx             # Auth, polling, guided demo orchestration
│   │   └── styles.css          # Full design system (dark glassmorphism)
│   ├── components/
│   │   ├── TrafficMap.jsx      # SVG map, route overlay, Dijkstra path rendering
│   │   ├── Dashboard.jsx       # Main dashboard — all panels and metrics
│   │   ├── LoginForm.jsx       # Auth form
│   │   └── MetricCard.jsx      # Reusable metric tile
│   ├── vercel.json             # Vercel build + SPA rewrite config
│   └── package.json
├── .env.example                # Template for environment variables
├── .gitignore
└── README.md
```

---

## Demo Credentials

> Set these in Railway environment variables before deploying.  
> The defaults below are for local dev only — **change them for production**.

| Field | Default |
|-------|---------|
| Email | `vigneshgnanasekaran8@gmail.com` |
| Password | `Viggu@2005` |

---

## Route Comparison — How It Works

```
Original route (naive GPS):
  cost_fn: problem zones = 0.3 (looks attractive), others = 1.5
  Dijkstra → goes through the congested corridor (e.g. west→central→east)

AI-optimized route:
  cost_fn: live congestion → {low:1.0, medium:3.5, high:8.0}
  Dijkstra → avoids high-cost zones (e.g. west→north→east or west→south→east)

Risk scoring (same model for both):
  risk = Σ LEVEL_COST[zone.congestion_level] for each zone in path (skip source)
  original risk = 9.0 (high+low = 8+1)
  rerouted risk = 2.0 (medium+low = 1+1)
  delta = −7.0 pts (78% improvement)
```

---

## Scenarios

| Scenario | Problem zones | Naive path goes through | AI reroutes via |
|----------|--------------|------------------------|-----------------|
| `accident` | central, west | central (blocked) | north or south |
| `rush_hour` | west, central | central (congested) | south |
| `rain_event` | central, north, west | central (degraded) | east |
| `event_surge` | south, east | south/east (surge) | north or west |
