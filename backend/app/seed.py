"""Generate mock traffic series: traveling-wave pattern for visible flow on the map."""

from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from .db import connection_ctx

# Mock traffic uses Seattle wall time for rush/quiet; series bounds are local midnights.
LA = ZoneInfo("America/Los_Angeles")

DEFAULT_SEED_DAY_START_LA = datetime(2025, 1, 15, 0, 0, 0, tzinfo=LA)


def _local_midnight_la(d: datetime) -> datetime:
    """Normalize to America/Los_Angeles midnight for the calendar date of d."""
    if d.tzinfo is None:
        d = d.replace(tzinfo=LA)
    d = d.astimezone(LA)
    return datetime(d.year, d.month, d.day, 0, 0, 0, tzinfo=LA)


def _add_local_days(midnight_la: datetime, days: int) -> datetime:
    """midnight_la must be 00:00 in LA; return midnight LA `days` later."""
    dd = midnight_la.date() + timedelta(days=days)
    return datetime(dd.year, dd.month, dd.day, 0, 0, 0, tzinfo=LA)

TRUNCATE_SQL = "TRUNCATE traffic_events;"

# Congestion from two moving sinusoidal waves over (lon, lat) + time (scaled by Seattle time of day).
# Rush peaks: 07:30-10:00 and 16:00-19:00 Seattle. Overnight the wave pattern is heavily damped so
# the map stays low and smooth (real freeways at 3 AM), instead of full-strength faux gridlock.
INSERT_SEED_SQL = """
INSERT INTO traffic_events ("time", road_id, speed_kph, congestion)
SELECT
    s.ts,
    b.road_id,
    GREATEST(
        5.0::double precision,
        b.free_flow_kph * (1.0 - 0.9::double precision * cc.congestion)
    ) AS speed_kph,
    cc.congestion
FROM (
    SELECT
        r.road_id,
        (
            COALESCE(NULLIF(r.speed_limit, 0), 25)::double precision * 0.44704
        ) AS free_flow_kph,
        ST_X(ST_PointOnSurface(r.geom::geometry)) AS cx,
        ST_Y(ST_PointOnSurface(r.geom::geometry)) AS cy
    FROM roads r
) b
CROSS JOIN LATERAL (
    SELECT generate_series(
        %(start)s::timestamptz,
        %(end)s::timestamptz,
        %(step)s::interval
    ) AS ts
) s(ts)
CROSS JOIN LATERAL (
    SELECT
        (
            extract(
                hour FROM s.ts AT TIME ZONE 'America/Los_Angeles'
            )::double precision * 60.0::double precision
            + extract(
                minute FROM s.ts AT TIME ZONE 'America/Los_Angeles'
            )::double precision
        ) AS mins_la
) la
CROSS JOIN LATERAL (
    SELECT
        CASE
            WHEN la.mins_la < 330::double precision THEN
                0.04::double precision
                + 0.10::double precision * (la.mins_la / 330.0::double precision)
            WHEN la.mins_la < 420::double precision THEN
                0.14::double precision
                + 0.78::double precision * ((la.mins_la - 330.0::double precision) / 90.0::double precision)
            WHEN la.mins_la <= 1140::double precision THEN
                1.0::double precision
            WHEN la.mins_la < 1320::double precision THEN
                1.0::double precision
                - 0.68::double precision * ((la.mins_la - 1140.0::double precision) / 180.0::double precision)
            ELSE
                GREATEST(
                    0.06::double precision,
                    0.32::double precision
                    - 0.26::double precision * ((la.mins_la - 1320.0::double precision) / 120.0::double precision)
                )
        END AS wave_scale
) ws
CROSS JOIN LATERAL (
    SELECT
        LEAST(
            1.0::double precision,
            GREATEST(
                0.0::double precision,
                0.02::double precision
                + ws.wave_scale * (
                    0.58::double precision * (
                        0.5::double precision
                        + 0.5::double precision * sin(
                            radians(
                                b.cx * 385.0::double precision
                                + b.cy * 165.0::double precision
                                - (
                                    extract(epoch FROM (s.ts - %(start)s::timestamptz))
                                    / 200.0::double precision
                                ) * 18.0::double precision
                            )
                        )
                    )
                    + 0.28::double precision * (
                        0.5::double precision
                        + 0.5::double precision * sin(
                            radians(
                                (b.cx - b.cy) * 210.0::double precision
                                - (
                                    extract(epoch FROM (s.ts - %(start)s::timestamptz))
                                    / 420.0::double precision
                                ) * 24.0::double precision
                            )
                        )
                    )
                    + 0.10::double precision * sin(
                        radians(
                            mod(b.road_id, 61)::double precision * 5.9::double precision
                            + extract(epoch FROM s.ts) / 1200.0::double precision
                        )
                    )
                )
            )
        ) AS base_cong
) bc
CROSS JOIN LATERAL (
    SELECT
        LEAST(
            1.0::double precision,
            GREATEST(
                0.0::double precision,
                bc.base_cong
                + 0.34::double precision * GREATEST(
                    GREATEST(
                        0.0::double precision,
                        1.0::double precision
                        - abs(
                            2.0::double precision
                            * (la.mins_la - 525.0::double precision)
                            / 150.0::double precision
                        )
                    ),
                    GREATEST(
                        0.0::double precision,
                        1.0::double precision
                        - abs(
                            2.0::double precision
                            * (la.mins_la - 1050.0::double precision)
                            / 180.0::double precision
                        )
                    )
                )
            )
        ) AS congestion
) cc;
"""


def seed_mock_traffic(
    start: datetime | None = None,
    *,
    duration_hours: int = 24,
    step_minutes: int = 30,
) -> dict:
    """
    Fill traffic_events on a Seattle calendar-day grid: first frame 00:00 PT, last frame
    just before the next midnight (no duplicate 00:00). duration_hours is rounded up
    to whole local days (default 24 h → one day).
    """
    if start is None:
        start = DEFAULT_SEED_DAY_START_LA
    start = _local_midnight_la(start)

    num_days = max(1, (duration_hours + 23) // 24)
    end_exclusive = _add_local_days(start, num_days)
    step = timedelta(minutes=step_minutes)
    series_end = end_exclusive - step
    if series_end < start:
        raise ValueError("step_minutes is larger than the seeded day span")

    params = {
        "start": start,
        "end": series_end,
        "step": step,
    }

    with connection_ctx() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT COUNT(*) FROM roads")
            (n_roads,) = cur.fetchone()
            if n_roads == 0:
                raise RuntimeError("roads table is empty; load GeoJSON first")

            cur.execute(TRUNCATE_SQL)
            cur.execute(INSERT_SEED_SQL, params)
            cur.execute("SELECT COUNT(*) FROM traffic_events")
            (n_events,) = cur.fetchone()

    return {
        "roads": n_roads,
        "traffic_rows": n_events,
        "time_start": start.isoformat(),
        "time_end_exclusive": end_exclusive.isoformat(),
        "time_last_frame": series_end.isoformat(),
        "step_minutes": step_minutes,
        "num_days": num_days,
    }
