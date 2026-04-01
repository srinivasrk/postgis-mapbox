"use client";

import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import mapboxgl from "mapbox-gl";
import "mapbox-gl/dist/mapbox-gl.css";

const API_BASE = process.env.NEXT_PUBLIC_API_URL ?? "http://127.0.0.1:8000";
const SOURCE_BASE = "roads-base";
const SOURCE_TRAFFIC = "roads-traffic";
const LAYER_BASE = "roads-base-lines";
const LAYER_TRAFFIC = "roads-traffic-lines";
const SOURCE_LAYER_BASE = "roads_base";
const SOURCE_LAYER_TRAFFIC = "traffic_roads";

/** Seconds for one full sweep through all frames (lower = faster playback). */
const PLAY_LOOP_SECONDS = 24;

/** Mock traffic rush/quiet hours are defined in Seattle local time. */
const SEATTLE_TZ = "America/Los_Angeles";

function formatFrameTimePtUtc(iso: string | undefined): string {
  if (!iso) return "—";
  const d = new Date(iso);
  const pt = new Intl.DateTimeFormat("en-US", {
    timeZone: SEATTLE_TZ,
    month: "short",
    day: "numeric",
    hour: "numeric",
    minute: "2-digit",
    hour12: true,
  }).format(d);
  const utc = iso.replace("T", " ").slice(0, 19);
  return `${pt} PT · ${utc} UTC`;
}

function tileBaseUrlTemplate(): string {
  const origin = typeof window !== "undefined" ? window.location.origin : "";
  return `${origin}/tiles/base/{z}/{x}/{y}.pbf`;
}

/** Stable URL: full time series is inside each PBF as c0, c1, … */
function tileTrafficUrlTemplate(): string {
  const origin = typeof window !== "undefined" ? window.location.origin : "";
  return `${origin}/tiles/traffic/{z}/{x}/{y}.pbf`;
}

/** Blended congestion between frames i and i+1 (smooth animation). */
function congestionColorExprBlended(
  t: number,
  maxIdx: number,
): mapboxgl.Expression {
  if (maxIdx <= 0) {
    return lineColorFromCongestion([
      "coalesce",
      [
        "to-number",
        ["get", ["concat", "c", ["to-string", ["literal", 0]]]],
      ],
      0,
    ]);
  }
  const clamped = Math.min(maxIdx, Math.max(0, t));
  const i = Math.floor(clamped);
  const i1 = Math.min(i + 1, maxIdx);
  const f = clamped - i;

  const congestion: mapboxgl.Expression =
    i1 <= i
      ? [
          "coalesce",
          [
            "to-number",
            ["get", ["concat", "c", ["to-string", ["literal", i]]]],
          ],
          0,
        ]
      : [
          "interpolate",
          ["linear"],
          ["literal", f],
          0,
          [
            "coalesce",
            [
              "to-number",
              ["get", ["concat", "c", ["to-string", ["literal", i]]]],
            ],
            0,
          ],
          1,
          [
            "coalesce",
            [
              "to-number",
              ["get", ["concat", "c", ["to-string", ["literal", i1]]]],
            ],
            0,
          ],
        ];

  return lineColorFromCongestion(congestion);
}

function lineColorFromCongestion(
  congestionExpr: mapboxgl.Expression,
): mapboxgl.Expression {
  return [
    "interpolate",
    ["linear"],
    congestionExpr,
    0,
    "#166534",
    0.15,
    "#22c55e",
    0.35,
    "#84cc16",
    0.52,
    "#ca8a04",
    0.68,
    "#ea580c",
    0.82,
    "#dc2626",
    0.92,
    "#b91c1c",
    1,
    "#7f1d1d",
  ];
}

const lineWidth: mapboxgl.Expression = [
  "interpolate",
  ["linear"],
  ["zoom"],
  11,
  1.2,
  14,
  2.5,
  16,
  4,
];

type FramesMeta = { frame_count: number; times: string[] };

export default function Home() {
  const containerRef = useRef<HTMLDivElement | null>(null);
  const mapRef = useRef<mapboxgl.Map | null>(null);
  const [tokenMissing, setTokenMissing] = useState(false);
  const [slider, setSlider] = useState(0);
  const [playing, setPlaying] = useState(false);
  const [frames, setFrames] = useState<FramesMeta | null>(null);
  const [status, setStatus] = useState("");

  const frameCount = frames?.frame_count ?? 0;
  const sliderMax = Math.max(0, frameCount - 1);

  const scrubIndex = useMemo(() => {
    if (frameCount <= 0) return 0;
    return Math.min(sliderMax, Math.max(0, Math.round(slider)));
  }, [slider, frameCount, sliderMax]);

  const applyFramePaint = useCallback(
    (map: mapboxgl.Map, t: number, maxIdx: number) => {
      if (!map.getLayer(LAYER_TRAFFIC)) return;
      map.setPaintProperty(
        LAYER_TRAFFIC,
        "line-color",
        congestionColorExprBlended(t, maxIdx),
      );
    },
    [],
  );

  useEffect(() => {
    const map = mapRef.current;
    if (!map?.isStyleLoaded() || frameCount <= 0) return;
    applyFramePaint(map, slider, sliderMax);
  }, [slider, frameCount, sliderMax, applyFramePaint]);

  useEffect(() => {
    const tok = process.env.NEXT_PUBLIC_MAPBOX_TOKEN;
    if (!tok) {
      setTokenMissing(true);
      return;
    }
    mapboxgl.accessToken = tok;
  }, []);

  useEffect(() => {
    fetch(`${API_BASE}/meta/traffic-frames`)
      .then((r) => r.json())
      .then((j: FramesMeta) => {
        setFrames(j);
        if (!j.frame_count) {
          setStatus("No traffic frames in DB — seed traffic first.");
        }
      })
      .catch(() => {
        setStatus("Could not load /meta/traffic-frames");
      });
  }, []);

  useEffect(() => {
    if (!playing || frameCount <= 0) return;

    let raf = 0;
    let last = performance.now();

    const step = (now: number) => {
      const dt = (now - last) / 1000;
      last = now;
      const maxT = Math.max(0, frameCount - 1);
      const span = maxT + 1;
      const delta = (dt / PLAY_LOOP_SECONDS) * span;
      setSlider((s) => {
        let n = s + delta;
        if (span <= 0) return 0;
        n = ((n % span) + span) % span;
        return n;
      });
      raf = requestAnimationFrame(step);
    };

    raf = requestAnimationFrame(step);
    return () => cancelAnimationFrame(raf);
  }, [playing, frameCount]);

  useEffect(() => {
    if (tokenMissing || !containerRef.current) return;

    const map = new mapboxgl.Map({
      container: containerRef.current,
      style: "mapbox://styles/mapbox/dark-v11",
      center: [-122.3321, 47.6062],
      zoom: 11.5,
      minZoom: 9,
      maxZoom: 16,
    });

    map.addControl(new mapboxgl.NavigationControl(), "top-right");

    map.on("load", () => {
      map.addSource(SOURCE_BASE, {
        type: "vector",
        tiles: [tileBaseUrlTemplate()],
        minzoom: 11,
        maxzoom: 16,
      });

      map.addSource(SOURCE_TRAFFIC, {
        type: "vector",
        tiles: [tileTrafficUrlTemplate()],
        minzoom: 11,
        maxzoom: 16,
      });

      map.addLayer({
        id: LAYER_BASE,
        type: "line",
        source: SOURCE_BASE,
        "source-layer": SOURCE_LAYER_BASE,
        paint: {
          "line-color": "#5c6570",
          "line-opacity": 0.92,
          "line-width": lineWidth,
        },
      });

      map.addLayer({
        id: LAYER_TRAFFIC,
        type: "line",
        source: SOURCE_TRAFFIC,
        "source-layer": SOURCE_LAYER_TRAFFIC,
        paint: {
          "line-color": congestionColorExprBlended(0, 0),
          "line-opacity": 0.95,
          "line-width": lineWidth,
        },
      });
    });

    mapRef.current = map;

    return () => {
      map.remove();
      mapRef.current = null;
    };
  }, [tokenMissing]);

  const currentTimeLabel = useMemo(() => {
    if (!frames?.times?.length) return "—";
    const t = frames.times[scrubIndex];
    return formatFrameTimePtUtc(t);
  }, [frames, scrubIndex]);

  if (tokenMissing) {
    return (
      <div
        style={{
          padding: 24,
          maxWidth: 560,
          lineHeight: 1.6,
        }}
      >
        <h1 style={{ fontSize: "1.25rem", fontWeight: 600 }}>
          Mapbox token required
        </h1>
        <p>
          Create <code style={{ color: "#7ee787" }}>web/.env.local</code> with:
        </p>
        <pre
          style={{
            background: "#161b22",
            padding: 12,
            borderRadius: 8,
            overflow: "auto",
          }}
        >
          {`NEXT_PUBLIC_MAPBOX_TOKEN=pk....`}
        </pre>
        <p style={{ opacity: 0.85, fontSize: 14 }}>
          Optional:{" "}
          <code style={{ color: "#7ee787" }}>NEXT_PUBLIC_API_URL</code> if the
          API is not at http://127.0.0.1:8000
        </p>
      </div>
    );
  }

  return (
    <div style={{ height: "100vh", display: "flex", flexDirection: "column" }}>
      <div
        ref={containerRef}
        style={{ flex: 1, minHeight: 0, position: "relative" }}
      />
      <div
        style={{
          padding: "12px 16px",
          borderTop: "1px solid #30363d",
          background: "#010409",
          display: "flex",
          flexDirection: "column",
          gap: 8,
        }}
      >
        <div
          style={{
            display: "flex",
            alignItems: "center",
            gap: 12,
            flexWrap: "wrap",
          }}
        >
          <button
            type="button"
            onClick={() => setPlaying((p) => !p)}
            disabled={frameCount <= 0}
            style={{
              padding: "6px 14px",
              borderRadius: 6,
              border: "1px solid #30363d",
              background: playing ? "#238636" : "#21262d",
              color: "#e6edf3",
              cursor: frameCount <= 0 ? "not-allowed" : "pointer",
              fontSize: 13,
              opacity: frameCount <= 0 ? 0.5 : 1,
            }}
          >
            {playing ? "Pause" : "Play"}
          </button>
          <span style={{ fontSize: 12, opacity: 0.65 }}>
            ~{PLAY_LOOP_SECONDS}s loop · blended{" "}
            <code style={{ color: "#7ee787" }}>c[i]→c[i+1]</code> · no tile
            refetch
          </span>
        </div>
        <label style={{ fontSize: 13, opacity: 0.9 }}>
          Frame / time — Seattle (PT) matches mock seed ({frameCount} steps)
        </label>
        <input
          type="range"
          min={0}
          max={sliderMax || 0}
          step={0.02}
          value={Math.min(sliderMax, Math.max(0, slider))}
          onChange={(e) => {
            setPlaying(false);
            setSlider(Number(e.target.value));
          }}
          disabled={frameCount <= 0}
          style={{ width: "100%" }}
        />
        <div
          style={{
            display: "flex",
            justifyContent: "space-between",
            fontSize: 12,
            fontFamily: "ui-monospace, monospace",
            opacity: 0.85,
          }}
        >
          <span>{formatFrameTimePtUtc(frames?.times?.[0])}</span>
          <span style={{ color: "#58a6ff" }}>{currentTimeLabel}</span>
          <span>{formatFrameTimePtUtc(frames?.times?.[sliderMax])}</span>
        </div>
        {status ? (
          <span style={{ fontSize: 12, opacity: 0.7 }}>{status}</span>
        ) : null}
      </div>
    </div>
  );
}
