"""MVT tiles: static road base + traffic overlay with full time series per feature (c0, c1, …)."""

from .db import connection_ctx

MIN_ZOOM = 11
EXTENT = 4096
BUFFER = 256

BASE_TILE_SQL = """
WITH
bounds AS (
    SELECT ST_TileEnvelope(%(z)s, %(x)s, %(y)s) AS geom3857
),
mvtgeom AS (
    SELECT
        r.road_id,
        COALESCE(r.street_name, '') AS street_name,
        COALESCE(r.speed_limit, 0) AS speed_limit,
        ST_AsMVTGeom(
            ST_Transform(r.geom, 3857),
            (SELECT geom3857 FROM bounds),
            %(extent)s,
            %(buffer)s,
            true
        ) AS geom
    FROM roads r
    CROSS JOIN bounds
    WHERE r.geom
        && ST_Transform((SELECT geom3857 FROM bounds), 4326)
        AND ST_Intersects(
            ST_Transform(r.geom, 3857),
            (SELECT geom3857 FROM bounds)
        )
)
SELECT COALESCE(
    (
        SELECT ST_AsMVT(m.*, 'roads_base', %(extent)s, 'geom', 'road_id')
        FROM mvtgeom m
        WHERE m.geom IS NOT NULL
    ),
    ''::bytea
);
"""

# Per road: jsonb merges into MVT attributes as c0,c1,… congestion scalars (vector tiles are scalar-only).
TRAFFIC_SERIES_TILE_SQL = """
WITH
bounds AS (
    SELECT ST_TileEnvelope(%(z)s, %(x)s, %(y)s) AS geom3857
),
expected AS (
    SELECT COALESCE(COUNT(DISTINCT "time")::int, 0) AS n FROM traffic_events
),
road_series AS (
    SELECT
        te.road_id,
        array_agg(te.congestion ORDER BY te."time") AS congestions
    FROM traffic_events te
    GROUP BY te.road_id
    HAVING
        (SELECT n FROM expected) > 0
        AND COUNT(*) = (SELECT n FROM expected)
),
mvtgeom AS (
    SELECT
        bq.road_id,
        ST_AsMVTGeom(
            ST_Transform(bq.geom, 3857),
            (SELECT geom3857 FROM bounds),
            %(extent)s,
            %(buffer)s,
            true
        ) AS geom,
        bq.attrs
    FROM (
        SELECT
            r.road_id,
            r.geom,
            (
                jsonb_build_object(
                    'street_name', COALESCE(r.street_name, ''),
                    'speed_limit', COALESCE(r.speed_limit, 0)
                )
                || COALESCE(
                    (
                        SELECT jsonb_object_agg(
                            'c' || ((ord - 1))::text,
                            to_jsonb(val)
                        )
                        FROM unnest(rs.congestions)
                            WITH ORDINALITY AS u(val, ord)
                    ),
                    '{}'::jsonb
                )
            ) AS attrs
        FROM roads r
        INNER JOIN road_series rs ON rs.road_id = r.road_id
        CROSS JOIN bounds
        WHERE r.geom
            && ST_Transform((SELECT geom3857 FROM bounds), 4326)
            AND ST_Intersects(
                ST_Transform(r.geom, 3857),
                (SELECT geom3857 FROM bounds)
            )
    ) bq
)
SELECT COALESCE(
    (
        SELECT ST_AsMVT(m.*, 'traffic_roads', %(extent)s, 'geom', 'road_id')
        FROM mvtgeom m
        WHERE m.geom IS NOT NULL
    ),
    ''::bytea
);
"""


def _tile_params(z: int, x: int, y: int) -> dict:
    return {
        "z": z,
        "x": x,
        "y": y,
        "extent": EXTENT,
        "buffer": BUFFER,
    }


def _fetch_bytes(cur, sql: str, params: dict) -> bytes:
    cur.execute(sql, params)
    row = cur.fetchone()
    if not row or row[0] is None:
        return b""
    data = row[0]
    if isinstance(data, memoryview):
        return data.tobytes()
    return bytes(data)


def fetch_mvt_base(z: int, x: int, y: int) -> bytes:
    if z < MIN_ZOOM:
        return b""
    params = _tile_params(z, x, y)
    with connection_ctx() as conn:
        with conn.cursor() as cur:
            return _fetch_bytes(cur, BASE_TILE_SQL, params)


def fetch_mvt_traffic(z: int, x: int, y: int) -> bytes:
    """Traffic MVT: all time steps as c0, c1, … (URL has no time parameter)."""
    if z < MIN_ZOOM:
        return b""
    params = _tile_params(z, x, y)
    with connection_ctx() as conn:
        with conn.cursor() as cur:
            return _fetch_bytes(cur, TRAFFIC_SERIES_TILE_SQL, params)
