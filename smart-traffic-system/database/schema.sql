CREATE TABLE IF NOT EXISTS traffic_snapshots (
    id SERIAL PRIMARY KEY,
    observed_at TIMESTAMP NOT NULL,
    intersection_id VARCHAR(64) NOT NULL,
    segment_id VARCHAR(64) NOT NULL,
    source VARCHAR(32) NOT NULL DEFAULT 'simulation',
    speed_kmph NUMERIC(10, 2) NOT NULL,
    density NUMERIC(10, 2) NOT NULL,
    flow_rate NUMERIC(10, 2) NOT NULL,
    travel_time_seconds NUMERIC(10, 2) NOT NULL,
    signal_wait_seconds NUMERIC(10, 2) NOT NULL DEFAULT 0
);

CREATE TABLE IF NOT EXISTS congestion_predictions (
    id SERIAL PRIMARY KEY,
    predicted_at TIMESTAMP NOT NULL,
    segment_id VARCHAR(64) NOT NULL,
    forecast_minutes INTEGER NOT NULL,
    congestion_level VARCHAR(16) NOT NULL,
    predicted_speed_kmph NUMERIC(10, 2) NOT NULL,
    predicted_travel_time_seconds NUMERIC(10, 2) NOT NULL
);

CREATE TABLE IF NOT EXISTS reroute_decisions (
    id SERIAL PRIMARY KEY,
    decided_at TIMESTAMP NOT NULL DEFAULT NOW(),
    vehicle_id VARCHAR(64) NOT NULL,
    source_node VARCHAR(64) NOT NULL,
    destination_node VARCHAR(64) NOT NULL,
    best_path TEXT NOT NULL,
    estimated_cost NUMERIC(10, 2) NOT NULL,
    reasoning TEXT
);
