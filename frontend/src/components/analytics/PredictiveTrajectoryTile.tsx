import { useEffect, useMemo, useRef, useState } from "react";
import { motion } from "framer-motion";
import { useTwin } from "@/store/twin";
import { fetchPredictionsTimeline } from "@/lib/twinApi";

/**
 * PredictiveTrajectoryTile — operator-facing view of the 10-year forward
 * simulation stored in `data/validation/fleet_2026_2035.parquet`.
 *
 *   ┌────────────────────────────────────────────────────────────────────┐
 *   │  2026  2027  …  2035                                               │
 *   ├────────────────────────────────────────────────────────────────────┤
 *   │  C1 ─╲╲ ╲╲╲             ← solid past (≤ cursor)                    │
 *   │  C2 ──╲────                                                        │
 *   │  C3 ╲╲╲╲╲╲╲╲              ← lighter future (> cursor)              │
 *   │  C4, C5, C6 …                                                      │
 *   │                          │ cursor at currentDay                    │
 *   └────────────────────────────────────────────────────────────────────┘
 *
 * Every component's `H_C{i}` is plotted across the full validation horizon.
 * The cursor's position is driven by `forecastHorizonDays` — the value the
 * **predictive scrubber** owns. **Live mode = static**: when the operator
 * has not pressed play and has not dragged the scrubber, `forecastHorizonDays`
 * stays at 0 and the cursor stays pinned to the start of the predictive
 * window. Pressing play walks `forecastHorizonDays` forward via rAF in the
 * scrubber, and the cursor follows. Crucially this is decoupled from the
 * global simulation tick (which keeps advancing for the live snapshot) so
 * the analytics view never moves without the operator asking it to.
 *
 * Predictions are NEVER re-run client-side — the validation parquet is the
 * baked output of the simulator + RUL head, so this tile is just a renderer
 * over its pre-computed series.
 */

const APPLE_EASE: [number, number, number, number] = [0.16, 1, 0.3, 1];

const COMPONENT_TRACKS: Array<{ sid: string; label: string; color: string }> = [
  { sid: "C1", label: "Recoater blade",   color: "#7ec3ff" },
  { sid: "C2", label: "Recoater motor",   color: "#a4e3b5" },
  { sid: "C3", label: "Nozzle plate",     color: "#ffb663" },
  { sid: "C4", label: "Thermal resistor", color: "#ff8269" },
  { sid: "C5", label: "Heating element",  color: "#d3a3ff" },
  { sid: "C6", label: "Insulation panel", color: "#9ad7df" },
];

interface PredictionFrame {
  day: number[];
  H_C1: number[]; H_C2: number[]; H_C3: number[];
  H_C4: number[]; H_C5: number[]; H_C6: number[];
}

const SIM_START_DATE_UTC = Date.UTC(2026, 0, 1);

export function PredictiveTrajectoryTile({ className }: { className?: string }) {
  // Cursor is driven by the predictive scrubber, NOT by the global tick.
  // forecastHorizonDays = 0 in live/idle mode → cursor pinned at day 0.
  // Dragging or playing the scrubber advances forecastHorizonDays → cursor
  // walks. This is the "live = static" contract the operator expects.
  const forecastHorizonDays = useTwin((s) => s.forecastHorizonDays);
  const selectedCity = useTwin((s) => s.selectedCity);
  const selectedPrinterId = useTwin((s) => s.selectedPrinterId);
  const dataSource = useTwin((s) => s.dataSource);

  const [frame, setFrame] = useState<PredictionFrame | null>(null);
  const [loadError, setLoadError] = useState<string | null>(null);

  // Fetch the full prediction trajectory once per (city, printer). The
  // parquet is pre-baked so a single fetch covers the whole 10-year horizon.
  useEffect(() => {
    if (!selectedCity || selectedPrinterId === null) {
      setFrame(null);
      setLoadError(null);
      return;
    }
    let cancelled = false;
    void (async () => {
      try {
        const raw = await fetchPredictionsTimeline({
          city: selectedCity.id,
          printerId: selectedPrinterId,
          fields: ["H_C1", "H_C2", "H_C3", "H_C4", "H_C5", "H_C6"],
        });
        if (cancelled) return;
        setFrame(raw as unknown as PredictionFrame);
        setLoadError(null);
      } catch (err) {
        if (cancelled) return;
        setLoadError(
          err instanceof Error
            ? err.message
            : "failed to load prediction trajectory",
        );
      }
    })();
    return () => { cancelled = true; };
  }, [selectedCity, selectedPrinterId]);

  const currentDay = Math.round(forecastHorizonDays);

  return (
    <motion.section
      initial={{ opacity: 0, y: 8 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{ duration: 0.4, ease: APPLE_EASE }}
      className={
        "glass-floating rounded-3xl p-5 flex flex-col overflow-hidden " +
        (className ?? "")
      }
    >
      <header className="flex items-baseline justify-between mb-3">
        <h2 className="text-[10px] uppercase tracking-[0.20em] text-[var(--color-fg-faint)]">
          Predictive trajectory
        </h2>
        <span className="text-[10.5px] text-[var(--color-fg-faint)] tabular-nums">
          2026 — 2035 · model forecast
        </span>
      </header>

      {loadError && (
        <p className="text-[12px] text-[var(--color-fg-muted)]">
          Unable to load forecast: {loadError}
        </p>
      )}

      {!frame && !loadError && (
        <p className="text-[12px] text-[var(--color-fg-muted)]">
          {dataSource !== "live"
            ? "Connect a printer to render the predictive trajectory."
            : "Loading 10-year prediction…"}
        </p>
      )}

      {frame && (
        <TrajectoryCanvas frame={frame} currentDay={currentDay} />
      )}
    </motion.section>
  );
}

/* ───────────────────────────────────────────────────────────────────────── */
/*  Canvas — pure SVG, six monotone curves split at the playback cursor      */
/* ───────────────────────────────────────────────────────────────────────── */

const PAD_LEFT = 92;
const PAD_RIGHT = 24;
const HEADER_H = 30;
const TRACK_H = 36;
const TRACK_GAP = 4;
const FOOTER_PAD = 28;
const TRACKS_H = COMPONENT_TRACKS.length * (TRACK_H + TRACK_GAP);
const TOTAL_H = HEADER_H + TRACKS_H + FOOTER_PAD;

function TrajectoryCanvas({
  frame,
  currentDay,
}: {
  frame: PredictionFrame;
  currentDay: number;
}) {
  const ref = useRef<SVGSVGElement>(null);
  const [width, setWidth] = useState(900);

  useEffect(() => {
    if (!ref.current) return;
    const el = ref.current;
    const ro = new ResizeObserver(([entry]) => {
      const w = entry.contentRect.width;
      if (w > 0) setWidth(w);
    });
    ro.observe(el);
    return () => ro.disconnect();
  }, []);

  const totalDays = frame.day.length;
  const innerW = Math.max(200, width - PAD_LEFT - PAD_RIGHT);
  const dayW = innerW / Math.max(1, totalDays);

  // Year ticks, anchored on Jan 1 2026 so the cursor's date label is
  // intelligible without an extra date column from the backend.
  const yearTicks = useMemo(() => {
    const ticks: { x: number; label: string }[] = [];
    const startYear = 2026;
    const endYear = 2035;
    for (let year = startYear; year <= endYear; year += 1) {
      const dayOfStart = Math.round(
        (Date.UTC(year, 0, 1) - SIM_START_DATE_UTC) / 86_400_000,
      );
      if (dayOfStart < 0 || dayOfStart > totalDays) continue;
      ticks.push({
        x: PAD_LEFT + dayOfStart * dayW,
        label: String(year),
      });
    }
    return ticks;
  }, [dayW, totalDays]);

  // Bucket the 10-year series into ~one sample per pixel — the simulator's
  // corrective-maintenance cycle restarts H every 1–3 days, so the raw
  // daily series goes 1.0 → 0.1 → 1.0 in well under a pixel and rasterises
  // as a flat band near H=1. Bucket-min/max gives the operator the wear
  // envelope (lows = pre-failure dips, highs = post-reset peaks).
  const trackPaths = useMemo(() => {
    const buckets = Math.max(120, Math.min(360, Math.floor(innerW / 3)));
    return COMPONENT_TRACKS.map((track) => {
      const series = (frame as unknown as Record<string, number[]>)[`H_${track.sid}`];
      return buildEnvelopePaths(series, dayW, currentDay, buckets);
    });
  }, [frame, dayW, currentDay, innerW]);

  const cursorX = PAD_LEFT + Math.min(totalDays, Math.max(0, currentDay)) * dayW;

  return (
    <svg ref={ref} width="100%" height={TOTAL_H} className="select-none">
      {/* Year ribbon */}
      <g>
        {yearTicks.map((t) => (
          <g key={t.label}>
            <line
              x1={t.x} x2={t.x}
              y1={HEADER_H - 4} y2={HEADER_H + TRACKS_H}
              stroke="rgba(255,255,255,0.04)"
              strokeWidth={1}
            />
            <text
              x={t.x + 3}
              y={HEADER_H - 8}
              fontSize={10.5}
              fill="var(--color-fg-faint)"
              fontFamily="inherit"
            >
              {t.label}
            </text>
          </g>
        ))}
      </g>

      {/* Tracks */}
      <g transform={`translate(0, ${HEADER_H})`}>
        {COMPONENT_TRACKS.map((track, i) => {
          const y = i * (TRACK_H + TRACK_GAP);
          const paths = trackPaths[i];
          return (
            <g key={track.sid} transform={`translate(0, ${y})`}>
              {/* Label */}
              <text
                x={PAD_LEFT - 10}
                y={TRACK_H * 0.62}
                fontSize={11}
                textAnchor="end"
                fill="var(--color-fg-muted)"
                fontFamily="inherit"
              >
                {track.label}
              </text>
              {/* Track baseline (H = 1.0 reference) */}
              <line
                x1={PAD_LEFT}
                x2={PAD_LEFT + innerW}
                y1={TRACK_H * 0.18}
                y2={TRACK_H * 0.18}
                stroke="rgba(255,255,255,0.04)"
                strokeDasharray="2 4"
              />
              {/* Past — filled wear envelope (min↔max band) + min-line. */}
              {paths.pastFill && (
                <path
                  d={paths.pastFill}
                  fill={track.color}
                  fillOpacity={0.45}
                  stroke="none"
                />
              )}
              {paths.pastMin && (
                <path
                  d={paths.pastMin}
                  fill="none"
                  stroke={track.color}
                  strokeWidth={1.8}
                  opacity={1.0}
                />
              )}
              {/* Future — same envelope, slightly faded + dashed min-line so
                  the eye reads "predicted" without losing the wear signal. */}
              {paths.futureFill && (
                <path
                  d={paths.futureFill}
                  fill={track.color}
                  fillOpacity={0.30}
                  stroke="none"
                />
              )}
              {paths.futureMin && (
                <path
                  d={paths.futureMin}
                  fill="none"
                  stroke={track.color}
                  strokeWidth={1.5}
                  strokeDasharray="4 3"
                  opacity={0.85}
                />
              )}
            </g>
          );
        })}
      </g>

      {/* Time cursor */}
      <g>
        <line
          x1={cursorX} x2={cursorX}
          y1={HEADER_H - 4}
          y2={HEADER_H + TRACKS_H}
          stroke="var(--color-fg)"
          strokeWidth={1}
          strokeOpacity={0.9}
        />
        <circle
          cx={cursorX}
          cy={HEADER_H + TRACKS_H + 4}
          r={3.5}
          fill="var(--color-fg)"
        />
        <text
          x={cursorX + 7}
          y={HEADER_H + TRACKS_H + 18}
          fontSize={10.5}
          fill="var(--color-fg)"
          fontFamily="inherit"
        >
          day {currentDay} · {dayToYearLabel(currentDay)}
        </text>
      </g>
    </svg>
  );
}

/**
 * Build the past + future envelope paths (filled min↔max band plus a
 * min-line stroke) for a single component's H series.
 *
 * Why bucketed envelope and not a raw line? The simulator runs corrective
 * maintenance every time H ≤ 0.1, snapping H back to 1.0. C3's mean
 * lifetime is ~50 days but maintenance + cycling has it dipping to 0.1
 * thousands of times across the 10-year horizon — a literal per-day line
 * over 3 652 samples in ~800 px renders as a flat band at H=1 because each
 * cycle is sub-pixel. Bucketing into 200ish columns and tracking
 * `(min, max)` per bucket gives the operator the actual wear envelope:
 * lows = pre-failure dips, highs = post-reset peaks.
 */
function buildEnvelopePaths(
  series: number[],
  dayW: number,
  cutoffDay: number,
  bucketCount: number,
): {
  pastFill: string | null;
  pastMin: string | null;
  futureFill: string | null;
  futureMin: string | null;
} {
  if (!series || series.length === 0) {
    return { pastFill: null, pastMin: null, futureFill: null, futureMin: null };
  }

  const trackTop = 4;
  const trackUsable = TRACK_H - 8;
  const totalDays = series.length;
  const bucketDays = Math.max(1, Math.ceil(totalDays / bucketCount));

  type Bucket = { day: number; min: number; max: number };
  const buckets: Bucket[] = [];
  for (let start = 0; start < totalDays; start += bucketDays) {
    const end = Math.min(totalDays, start + bucketDays);
    let bMin = Infinity;
    let bMax = -Infinity;
    for (let i = start; i < end; i += 1) {
      const v = Math.max(0, Math.min(1, series[i] ?? 0));
      if (v < bMin) bMin = v;
      if (v > bMax) bMax = v;
    }
    if (!isFinite(bMin)) { bMin = 0; bMax = 0; }
    // Anchor the bucket on its centre day so the cursor split lines up
    // with calendar position rather than bucket index.
    buckets.push({ day: start + Math.floor((end - start) / 2), min: bMin, max: bMax });
  }

  const yFor = (v: number) => trackTop + (1 - v) * trackUsable;
  const xFor = (day: number) => PAD_LEFT + day * dayW;

  // Split buckets into past (≤cutoff) / future (>cutoff). Walk both the
  // upper rail (max) forward and the lower rail (min) backward so the
  // resulting filled path is a single closed loop SVG can fill.
  const past: Bucket[] = [];
  const future: Bucket[] = [];
  for (const b of buckets) {
    if (b.day <= cutoffDay) past.push(b);
    else future.push(b);
  }
  // Bridge bucket — share the cutoff sample between the two halves so the
  // two envelopes visually touch.
  if (past.length > 0 && future.length > 0) {
    future.unshift(past[past.length - 1]);
  }

  return {
    pastFill: buildFillPath(past, xFor, yFor),
    pastMin: buildMinPath(past, xFor, yFor),
    futureFill: buildFillPath(future, xFor, yFor),
    futureMin: buildMinPath(future, xFor, yFor),
  };
}

function buildFillPath(
  buckets: { day: number; min: number; max: number }[],
  xFor: (d: number) => number,
  yFor: (v: number) => number,
): string | null {
  if (buckets.length < 2) return null;
  let d = "";
  // Upper rail (max) forward
  for (let i = 0; i < buckets.length; i += 1) {
    const b = buckets[i];
    d += (i === 0 ? "M" : "L") + xFor(b.day).toFixed(1) + "," + yFor(b.max).toFixed(1) + " ";
  }
  // Lower rail (min) backward — closes the loop
  for (let i = buckets.length - 1; i >= 0; i -= 1) {
    const b = buckets[i];
    d += "L" + xFor(b.day).toFixed(1) + "," + yFor(b.min).toFixed(1) + " ";
  }
  d += "Z";
  return d;
}

function buildMinPath(
  buckets: { day: number; min: number; max: number }[],
  xFor: (d: number) => number,
  yFor: (v: number) => number,
): string | null {
  if (buckets.length < 2) return null;
  let d = "";
  for (let i = 0; i < buckets.length; i += 1) {
    const b = buckets[i];
    d += (i === 0 ? "M" : "L") + xFor(b.day).toFixed(1) + "," + yFor(b.min).toFixed(1) + " ";
  }
  return d;
}

function dayToYearLabel(day: number): string {
  const ms = SIM_START_DATE_UTC + day * 86_400_000;
  const d = new Date(ms);
  return d.toISOString().slice(0, 10);
}
