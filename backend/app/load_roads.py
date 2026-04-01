"""
Load seattle-streets.geojson into the roads table.

Prefers batched reads via GeoPandas + Pyogrio. OGR alternative (from repo root):

ogr2ogr -f PostgreSQL PG:"host=localhost port=5432 dbname=traffic user=postgres password=postgres" \\
  seattle-streets.geojson -nln roads_ogr -lco GEOMETRY_NAME=geom -overwrite

Then normalize: INSERT INTO roads (road_id, geom, street_name, speed_limit)
SELECT "OBJECTID", geom, "STNAME_ORD", "SPEEDLIMIT"::int FROM roads_ogr;
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

import geopandas as gpd
import psycopg

from .db import get_dsn

BATCH = 4000

INSERT_SQL = """
INSERT INTO roads (road_id, geom, street_name, speed_limit)
VALUES (%s, ST_SetSRID(ST_GeomFromWKB(%s), 4326), %s, %s)
ON CONFLICT (road_id) DO UPDATE SET
  geom = EXCLUDED.geom,
  street_name = EXCLUDED.street_name,
  speed_limit = EXCLUDED.speed_limit
"""


def _pick_column(columns: list[str], *names: str) -> str:
    lower_map = {c.lower(): c for c in columns}
    for name in names:
        if name in columns:
            return name
        if name.lower() in lower_map:
            return lower_map[name.lower()]
    raise KeyError(f"none of {names} found in {columns!r}")


def load_geojson(path: Path, *, replace: bool = False) -> dict:
    path = path.resolve()
    if not path.is_file():
        raise FileNotFoundError(path)

    with psycopg.connect(get_dsn(), autocommit=True) as conn:
        with conn.cursor() as cur:
            if replace:
                cur.execute("TRUNCATE traffic_events")
                cur.execute("TRUNCATE roads CASCADE")

    skip = 0
    total = 0

    while True:
        gdf = gpd.read_file(
            path,
            engine="pyogrio",
            skip_features=skip,
            max_features=BATCH,
        )

        if len(gdf) == 0:
            break

        cols = list(gdf.columns)
        id_col = _pick_column(cols, "OBJECTID", "objectid")
        street_col = _pick_column(
            cols, "STNAME_ORD", "stname_ord", "ONSTREET", "onstreet"
        )
        speed_col = _pick_column(cols, "SPEEDLIMIT", "speedlimit")

        gdf = gdf.rename(
            columns={
                id_col: "_road_id",
                street_col: "_street",
                speed_col: "_speed",
            }
        )
        gdf["_speed"] = gdf["_speed"].fillna(0).astype(int)

        rows: list[tuple] = []
        for _, row in gdf.iterrows():
            geom = row.geometry
            if geom is None:
                continue
            rid = int(row["_road_id"])
            name = row["_street"]
            street_name: str | None
            if name is None or isinstance(name, float):
                street_name = None
            else:
                street_name = str(name)[:500]
            sl = int(row["_speed"])
            rows.append((rid, geom.wkb, street_name, sl))

        if rows:
            with psycopg.connect(get_dsn(), autocommit=True) as conn:
                with conn.cursor() as cur:
                    cur.executemany(INSERT_SQL, rows)

            total += len(rows)

        skip += len(gdf)
        print(f"loaded {total} features …", flush=True)

    return {"features_inserted": total, "path": str(path)}


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description="Load Seattle streets GeoJSON into Postgres")
    p.add_argument(
        "geojson",
        nargs="?",
        default=str(
            Path(__file__).resolve().parents[2] / "seattle-streets.geojson"
        ),
        help="Path to seattle-streets.geojson",
    )
    p.add_argument(
        "--replace",
        action="store_true",
        help="Truncate traffic_events and roads before load",
    )
    args = p.parse_args(argv)

    try:
        stats = load_geojson(Path(args.geojson), replace=args.replace)
    except Exception as e:
        print(f"error: {e}", file=sys.stderr)
        return 1

    print(stats)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
