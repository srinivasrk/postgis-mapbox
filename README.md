# Seattle traffic map (PostGIS + Mapbox + Next.js)

## Demo

Screen recording of the Seattle traffic map: time scrubber, blended congestion on road lines, and dual MVT layers (base + traffic).

<video controls playsinline width="100%">
  <source src="https://raw.githubusercontent.com/srinivasrk/postgis-mapbox/main/docs/demo.mp4" type="video/mp4" />
</video>

---

Animated road congestion on a Mapbox map. Road geometry and a **full time series per road** live in **PostgreSQL** (PostGIS + TimescaleDB). The browser loads **two vector tile layers**: a static road base and a traffic overlay whose MVT attributes include **`c0`, `c1`, …** (one scalar per timestep). The UI animates by updating paint from those properties—**no per-frame tile URL changes**.

## System diagram

```mermaid
flowchart TB
  subgraph browser [Browser]
    UI[Next.js app + Mapbox GL]
  end

  subgraph mapbox [Mapbox]
    Base[Raster/vector basemap tiles]
  end

  subgraph dev [Your machine]
    Next[Next.js dev server :3000]
    API[FastAPI uvicorn :8000]
    subgraph docker [Docker]
      DB[(PostgreSQL 16\nPostGIS + TimescaleDB :5432)]
    end
  end

  UI --> Next
  UI --> Base
  UI -->|GET /meta JSON| API
  Next -->|rewrites vector tile requests| API
  API -->|"ST_AsMVT, seed, load"| DB
```

**Data flow (tiles):**

1. **`roads`** — centerlines (4326), loaded from `seattle-streets.geojson`.
2. **`traffic_events`** — hypertable keyed by `(road_id, time)`; `congestion` in `[0, 1]`.
3. **Base MVT** — geometry + road metadata, layer `roads_base`.
4. **Traffic MVT** — same features with merged JSON attributes **`c0`…`c_{N-1}`** (ordered congestion series). The frontend blends between consecutive values for smooth scrubbing.

## Prerequisites

- **Docker Desktop** (for the database)
- **Node.js 20+** (for the web app)
- **Python 3.11+** with **[uv](https://docs.astral.sh/uv/)** (for the API)
- **Mapbox** public token ([account](https://www.mapbox.com/))
- **`seattle-streets.geojson`** at the **repository root** (or pass a path when loading roads)

## Quick start

### 1. Start the database

From the repo root:

```bash
docker compose up -d
```

Wait until the container is healthy. First run applies `db/init/*.sql` (PostGIS, TimescaleDB, `roads`, `traffic_events`).

Default DB URL (matches `docker-compose.yml`):

`postgresql://postgres:postgres@localhost:5432/traffic`

### 2. Load road geometry

With the DB up, from `backend/`:

```bash
uv sync
uv run python -m app.load_roads
```

Or use **`POST /admin/load-roads`** on the API (after step 3) if the GeoJSON is in the default location.

Use **`--replace`** to truncate `roads` (and related `traffic_events`) before loading.

### 3. Run the API

From `backend/`:

```bash
uv run uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
```

On Windows you can use `backend/run.ps1` for the same command.

### 4. Seed mock traffic (optional)

```bash
curl -X POST "http://127.0.0.1:8000/admin/seed-mock-traffic?step_minutes=30&duration_hours=24"
```

Mock series use **Seattle local time** for rush/quiet shaping; bounds are **local midnight → next midnight** (see API response for `time_start`, `time_end_exclusive`, `time_last_frame`). Restart or reload the API after changing seed code.

### 5. Run the web app

From `web/`:

```bash
npm install
npm run dev
```

Create **`web/.env.local`**:

```env
NEXT_PUBLIC_MAPBOX_TOKEN=pk.your_token_here
```

Optional:

```env
NEXT_PUBLIC_API_URL=http://127.0.0.1:8000
TILE_BACKEND_URL=http://127.0.0.1:8000
```

Open [http://localhost:3000](http://localhost:3000). Map tile fetches go through Next **rewrites** to the API unless you point URLs directly at `:8000`.

## Environment variables

| Variable | Where | Purpose |
|----------|--------|--------|
| `DATABASE_URL` | Backend | Postgres DSN (defaults to local Docker URL above) |
| `NEXT_PUBLIC_MAPBOX_TOKEN` | Web | Mapbox GL access token |
| `NEXT_PUBLIC_API_URL` | Web | FastAPI base URL for `/meta/...` (default `http://127.0.0.1:8000`) |
| `TILE_BACKEND_URL` | Web (`next.config.ts`) | Origin for rewriting `/tiles/base|traffic/...` (default `http://127.0.0.1:8000`) |

## API highlights

| Method | Path | Description |
|--------|------|-------------|
| GET | `/health` | Liveness |
| GET | `/meta/traffic-frames` | `{ frame_count, times[] }` aligned with `c0`, `c1`, … |
| GET | `/meta/time-range` | Min/max `time` in `traffic_events` |
| GET | `/tiles/base/{z}/{x}/{y}.pbf` | Base road MVT |
| GET | `/tiles/traffic/{z}/{x}/{y}.pbf` | Traffic MVT with congestion series |
| POST | `/admin/seed-mock-traffic` | Query: `step_minutes`, `duration_hours` (rounded up to whole local days) |
| POST | `/admin/load-roads` | Load repo-root GeoJSON into `roads` |

Minimum zoom for MVT endpoints is enforced in code (`MIN_ZOOM`, typically 11).

## Project layout

```
├── docs/                 # e.g. demo.mp4 for README
├── db/init/              # SQL: extensions, schema (hypertable)
├── docker-compose.yml    # TimescaleDB HA image + init mount
├── backend/              # FastAPI, uvicorn, seed, MVT SQL
│   ├── app/main.py
│   ├── app/tiles.py
│   ├── app/seed.py
│   └── app/load_roads.py
├── web/                  # Next.js 15 + Mapbox GL
│   ├── app/page.tsx
│   └── next.config.ts    # tile rewrites → API
└── seattle-streets.geojson   # street source (not always in repo; add locally)
```

## Related

Earlier exploration of PostGIS MVT from Node lives in **[postgis-mapbox](https://github.com/srinivasrk/postgis-mapbox)**; this repo adds TimescaleDB time-series, FastAPI, and a Next.js client with embedded frame properties and blended animation.

## License

Use and modify as needed for your own projects.
