from fastapi import FastAPI, HTTPException, Query, Response
from fastapi.middleware.cors import CORSMiddleware

from .db import connection_ctx
from .load_roads import load_geojson
from .seed import seed_mock_traffic
from .tiles import MIN_ZOOM, fetch_mvt_base, fetch_mvt_traffic

app = FastAPI(title="Seattle traffic tiles")

app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:3000",
        "http://127.0.0.1:3000",
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/health")
def health():
    return {"status": "ok"}


@app.get("/meta/time-range")
def meta_time_range():
    """Min/max timestamp from traffic_events for scrubber defaults."""
    with connection_ctx() as conn:
        with conn.cursor() as cur:
            cur.execute('SELECT min("time"), max("time") FROM traffic_events')
            row = cur.fetchone()
    if not row or row[0] is None:
        return {"min": None, "max": None}
    return {"min": row[0].isoformat(), "max": row[1].isoformat()}


@app.get("/meta/traffic-frames")
def meta_traffic_frames():
    """
    Ordered list of distinct traffic timestamps — aligns with MVT properties c0, c1, …
    """
    with connection_ctx() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT array_agg("time" ORDER BY "time")
                FROM (SELECT DISTINCT "time" FROM traffic_events) x
                """
            )
            row = cur.fetchone()
    times_raw = row[0] if row else None
    if not times_raw:
        return {"frame_count": 0, "times": []}
    times = []
    for t in times_raw:
        if hasattr(t, "isoformat"):
            s = t.isoformat()
            times.append(s.replace("+00:00", "Z"))
        else:
            times.append(str(t))
    return {"frame_count": len(times), "times": times}


@app.get("/tiles/base/{z}/{x}/{y}.pbf")
def get_tile_base(z: int, x: int, y: int):
    """Road geometry only (no time dimension); cache-friendly."""
    if z < 0 or x < 0 or y < 0:
        raise HTTPException(status_code=400, detail="invalid tile coordinates")
    try:
        blob = fetch_mvt_base(z, x, y)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e)) from e

    return Response(
        content=blob,
        media_type="application/x-protobuf",
        headers={
            "Cache-Control": "public, max-age=86400"
            if z >= MIN_ZOOM
            else "public, max-age=3600",
        },
    )


@app.get("/tiles/traffic/{z}/{x}/{y}.pbf")
def get_tile_traffic(z: int, x: int, y: int):
    """
    Traffic MVT: full time series per road as c0, c1, … (no query params; cache-friendly).
    """
    if z < 0 or x < 0 or y < 0:
        raise HTTPException(status_code=400, detail="invalid tile coordinates")
    try:
        blob = fetch_mvt_traffic(z, x, y)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e)) from e

    return Response(
        content=blob,
        media_type="application/x-protobuf",
        headers={
            "Cache-Control": "public, max-age=600"
            if z >= MIN_ZOOM
            else "public, max-age=300",
        },
    )


@app.get("/tiles/{z}/{x}/{y}.pbf")
def get_tile_legacy(z: int, x: int, y: int):
    """Backward-compatible path for traffic tiles (time query ignored)."""
    return get_tile_traffic(z, x, y)


@app.post("/admin/seed-mock-traffic")
def admin_seed(
    step_minutes: int = Query(30, ge=5, le=120),
    duration_hours: int = Query(24, ge=1, le=168),
):
    """
    Replace all traffic_events with synthetic speeds/congestion for every road.
    Timestamps run from Seattle 00:00 through the last step before the next local
    midnight; duration_hours is rounded up to whole calendar days (24 → one PT day).
    """
    try:
        return seed_mock_traffic(duration_hours=duration_hours, step_minutes=step_minutes)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e)) from e


@app.post("/admin/load-roads")
def admin_load_roads(replace: bool = Query(False)):
    """
    Load GeoJSON from repo root (seattle-streets.geojson) into roads.
    For large files this can take several minutes.
    """
    from pathlib import Path

    path = Path(__file__).resolve().parents[2] / "seattle-streets.geojson"
    if not path.is_file():
        raise HTTPException(status_code=404, detail=f"missing {path}")
    try:
        return load_geojson(path, replace=replace)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e)) from e
