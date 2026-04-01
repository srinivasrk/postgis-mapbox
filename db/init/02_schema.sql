-- Road centerlines (loaded from GeoJSON via scripts/load_roads.py)
CREATE TABLE IF NOT EXISTS roads (
    road_id bigint PRIMARY KEY,
    geom geometry(Geometry, 4326) NOT NULL,
    street_name text,
    speed_limit int
);

CREATE INDEX IF NOT EXISTS roads_geom_gist ON roads USING GIST (geom);

-- Time-series traffic; hypertable partitioned on time
CREATE TABLE IF NOT EXISTS traffic_events (
    "time" timestamptz NOT NULL,
    road_id bigint NOT NULL REFERENCES roads (road_id) ON DELETE CASCADE,
    speed_kph real,
    congestion real CHECK (congestion IS NULL OR (congestion >= 0 AND congestion <= 1)),
    duration_s real,
    PRIMARY KEY (road_id, "time")
);

SELECT public.create_hypertable(
    relation => 'traffic_events',
    time_column_name => 'time',
    if_not_exists => TRUE
);

CREATE INDEX IF NOT EXISTS traffic_events_road_time_desc
    ON traffic_events (road_id, "time" DESC);
