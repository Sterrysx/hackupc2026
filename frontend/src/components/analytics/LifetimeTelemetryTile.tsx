import { useEffect, useMemo, useRef, useState } from "react";
import { motion } from "framer-motion";
import { useTwin } from "@/store/twin";
import { fetchPredictionsTimeline } from "@/lib/twinApi";

/**
 * LifetimeTelemetryTile — the page-12 schematic from the HP brief, wired
 * to the **predictive** dataset (`data/validation/fleet_2026_2035.parquet`).
 *
 *   ┌──────────────────────────────────────────────────────────────────┐
 *   │  2026  2027  2028  …  2035                                        │
 *   ├──────────────────────────────────────────────────────────────────┤
 *   │  Temperature  ─╲╱╲╱╲╱╲╱─                                         │
 *   │  Humidity     ─╲ ╱ ╲╱╲ ─                                         │
 *   │  Print hours  ─╱╲╱─╲╱╲ ─                                         │
 *   ├──────────────────────────────────────────────────────────────────┤
 *   │  C1  ▮▮▮▮▮▮▮▮▮▮▮▮▮▮▮▮▮▮▮▮▮▮▮▮▮▮▮▮▮▮▮▮                            │
 *   │  C2  ▮▮▮▮▮▮▮▮▮▮▮▮▮▮▮▮▮▮▮▮▮▮▮▮▮▮▮▮▮▮▮▮                            │
 *   │  …                                                                │
 *   └──────────────────┬─── cursor (forecastHorizonDays) ───────────────┘
 *
 * Every column in the strip is the model's forward simulation — the source
 * is the SAME baked-prediction parquet the PredictiveTrajectoryTile reads
 * from, just visualised differently (driver traces + per-component status
 * bands instead of the H envelope). The 2015-2024 historical data the old
 * version pulled from `/twin/timeline` is gone: this tile is purely about
 * what the predictor expects to happen next.
 *
 * The cursor is driven by `forecastHorizonDays` so it stays static in live
 * mode and only walks when the predictive scrubber's play is engaged.
 */

const SIM_START_DATE_UTC = Date.UTC(2026, 0, 1);
const TOTAL_DAYS = 3652;       // 10 years, matches validation parquet length
const STATUS_COLORS: Record<string, string> = {
  OK: "rgba(76, 217, 100, 0.85)",
  FUNCTIONAL: "rgba(76, 217, 100, 0.85)",
  WARNING: "rgba(255, 204, 0, 0.85)",
  DEGRADED: "rgba(255, 204, 0, 0.85)",
  CRITICAL: "rgba(255, 149, 0, 0.85)",
  FAILED: "rgba(255, 69, 58, 0.85)",
};
/**
 * Components grouped by physical subsystem so the grid reads bottom-up as
 * the operator inspecting one assembly at a time. C4 (firing-array thermal
 * resistor) is INSIDE the printhead — paired with C3 in the 3D model and
 * the 2D schematic — so we list it under "Printhead", not "Build unit".
 */
const COMPONENT_GROUPS: Array<{
  subsystem: string;
  rows: Array<{ sid: string; label: string }>;
}> = [
  { subsystem: "Recoating", rows: [
    { sid: "C1", label: "Recoater blade" },
    { sid: "C2", label: "Recoater motor" },
  ]},
  { subsystem: "Printhead", rows: [
    { sid: "C3", label: "Nozzle plate"     },
    { sid: "C4", label: "Thermal resistor" },
  ]},
  { subsystem: "Build unit", rows: [
    { sid: "C5", label: "Heating element"  },
    { sid: "C6", label: "Insulation panel" },
  ]},
];

// Flat row list (sid, label, row index) in the order they appear, plus the
// subsystem-header anchors used by the SVG layout.
interface FlatRow { sid: string; label: string; rowIndex: number; subsystem: string }
const FLAT_ROWS: FlatRow[] = COMPONENT_GROUPS.flatMap((g, gi) =>
  g.rows.map((r, ri) => ({
    sid: r.sid,
    label: r.label,
    rowIndex: gi * 0 + COMPONENT_GROUPS.slice(0, gi).reduce((acc, x) => acc + x.rows.length, 0) + ri,
    subsystem: g.subsystem,
  })),
);
const TOTAL_COMPONENT_ROWS = FLAT_ROWS.length;

interface TimelineFrame {
  day: number[];
  ambient_temp_c: number[];
  humidity_pct: number[];
  daily_print_hours: number[];
  status_C1: string[];
  status_C2: string[];
  status_C3: string[];
  status_C4: string[];
  status_C5: string[];
  status_C6: string[];
}

export function LifetimeTelemetryTile({ className }: { className?: string }) {
  const setForecastHorizon = useTwin((s) => s.setForecastHorizon);
  const forecastHorizonDays = useTwin((s) => s.forecastHorizonDays);
  const selectedCity = useTwin((s) => s.selectedCity);
  const selectedPrinterId = useTwin((s) => s.selectedPrinterId);

  const [timeline, setTimeline] = useState<TimelineFrame | null>(null);
  const [loadError, setLoadError] = useState(false);

  // Fetch the full predicted lifetime once per (city, printer). The
  // validation parquet is pre-baked, so a single request returns the whole
  // 10-year strip — no day-by-day client compute.
  useEffect(() => {
    if (!selectedCity || selectedPrinterId === null) {
      setTimeline(null);
      return;
    }
    let cancelled = false;
    void (async () => {
      try {
        const raw = await fetchPredictionsTimeline({
          city: selectedCity.id,
          printerId: selectedPrinterId,
          fields: [
            "ambient_temp_c", "humidity_pct", "daily_print_hours",
            "status_C1", "status_C2", "status_C3",
            "status_C4", "status_C5", "status_C6",
          ],
        });
        if (!cancelled) {
          setTimeline(raw as unknown as TimelineFrame);
          setLoadError(false);
        }
      } catch {
        if (!cancelled) setLoadError(true);
      }
    })();
    return () => { cancelled = true; };
  }, [selectedCity, selectedPrinterId]);

  return (
    <motion.section
      initial={{ opacity: 0, y: 8 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{ duration: 0.4, ease: [0.16, 1, 0.3, 1] }}
      className={
        "glass-floating rounded-3xl p-5 flex flex-col overflow-hidden " +
        (className ?? "")
      }
    >
      <header className="flex items-baseline justify-between mb-2">
        <h2 className="text-[10px] uppercase tracking-[0.20em] text-[var(--color-fg-faint)]">
          Lifetime telemetry
        </h2>
        <span className="text-[10.5px] text-[var(--color-fg-faint)] tabular-nums">
          2026 — 2035 · model forecast
        </span>
      </header>

      {/* Legends — driver line colours + component status palette. Sit
          right under the title so the eye picks up the colour key before
          looking at the chart, matching the `ui-ux-pro-max` `chart-type`
          + `legend-visible` rules. */}
      <div className="flex flex-wrap items-center gap-x-4 gap-y-1.5 mb-3">
        {DRIVER_TRACES.map((d) => (
          <span key={d.label} className="inline-flex items-center gap-1.5 text-[10px] text-[var(--color-fg-muted)]">
            <span
              aria-hidden
              className="block h-[2px] w-3.5 rounded-full"
              style={{ background: d.color }}
            />
            {d.label}
          </span>
        ))}
        <span className="block h-3 w-px bg-[var(--color-border)] mx-1" aria-hidden />
        {STATUS_LEGEND.map((s) => (
          <span key={s.label} className="inline-flex items-center gap-1.5 text-[10px] text-[var(--color-fg-muted)]">
            <span
              aria-hidden
              className="block h-2 w-2 rounded-sm"
              style={{ background: s.color }}
            />
            {s.label}
          </span>
        ))}
      </div>

      {loadError && (
        <p className="text-[12px] text-[var(--color-fg-muted)]">
          Unable to load forecast from /twin/predictions/timeline.
        </p>
      )}

      {!timeline && !loadError && (
        <p className="text-[12px] text-[var(--color-fg-muted)]">
          Loading 10-year prediction…
        </p>
      )}

      {timeline && (
        <TimelineCanvas
          frame={timeline}
          currentDay={Math.round(forecastHorizonDays)}
          onScrub={(day) => setForecastHorizon(day)}
        />
      )}
    </motion.section>
  );
}

/* ───────────────────────────────────────────────────────────────────────── */
/*  Canvas — pure SVG, no chart lib, exact match to the schematic           */
/* ───────────────────────────────────────────────────────────────────────── */

// Layout constants — sized to fill a `row-span-5` bento tile (~800 px
// tall) end-to-end with no wasted whitespace below the status grid.
const PAD_LEFT = 108;      // label gutter on the left
const PAD_RIGHT = 24;
const HEADER_H = 36;       // year ribbon
const DRIVERS_H = 260;     // 3 stacked driver lines
const DRIVERS_GAP = 34;    // breathing room between drivers band and status grid
const SUBSYS_LABEL_H = 18; // vertical room for each "RECOATING / PRINTHEAD / BUILD UNIT" header
const SUBSYS_GAP = 6;      // extra space below the last row of a group
const ROW_H = 36;          // status grid row height
const ROW_GAP = 2;         // hairline separator within a group
// Status grid height = N subsystem headers + N rows + a SUBSYS_GAP after
// every group except the last. Pre-computing avoids drift if we add
// another subsystem later.
const GRID_H =
  COMPONENT_GROUPS.length * SUBSYS_LABEL_H +
  TOTAL_COMPONENT_ROWS * (ROW_H + ROW_GAP) +
  Math.max(0, COMPONENT_GROUPS.length - 1) * SUBSYS_GAP;
const FOOTER_PAD = 38;     // bottom buffer below the status grid
const TOTAL_H = HEADER_H + DRIVERS_H + DRIVERS_GAP + GRID_H + FOOTER_PAD;

/** Y offset of a component row inside the status grid (relative to the
 *  grid's own translation). Honours subsystem-header rows + inter-group
 *  gaps so the rows don't slide under their headers. */
function rowYOffset(rowIndex: number): number {
  // Walk groups, accumulate header + rows + gap up to the row.
  let y = 0;
  let consumed = 0;
  for (let gi = 0; gi < COMPONENT_GROUPS.length; gi += 1) {
    y += SUBSYS_LABEL_H;
    const group = COMPONENT_GROUPS[gi];
    for (let ri = 0; ri < group.rows.length; ri += 1) {
      if (consumed === rowIndex) return y;
      y += ROW_H + ROW_GAP;
      consumed += 1;
    }
    if (gi < COMPONENT_GROUPS.length - 1) y += SUBSYS_GAP;
  }
  return y;
}

/** Y of the start of a subsystem header row inside the grid. */
function subsystemHeaderY(groupIndex: number): number {
  let y = 0;
  for (let gi = 0; gi < groupIndex; gi += 1) {
    y += SUBSYS_LABEL_H;
    y += COMPONENT_GROUPS[gi].rows.length * (ROW_H + ROW_GAP);
    y += SUBSYS_GAP;
  }
  return y;
}

const DRIVER_TRACES: Array<{ label: string; color: string }> = [
  { label: "Temperature", color: "var(--color-fg)"        },
  { label: "Humidity",    color: "var(--color-fg-muted)"  },
  { label: "Print hours", color: "var(--color-accent)"    },
];

const STATUS_LEGEND: Array<{ label: string; color: string }> = [
  { label: "OK",       color: "rgba(76, 217, 100, 0.85)" },
  { label: "Degraded", color: "rgba(255, 204, 0, 0.85)"  },
  { label: "Critical", color: "rgba(255, 149, 0, 0.85)"  },
  { label: "Failed",   color: "rgba(255, 69, 58, 0.85)"  },
];

function TimelineCanvas({
  frame,
  currentDay,
  onScrub,
}: {
  frame: TimelineFrame;
  currentDay: number;
  onScrub: (day: number) => void;
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

  const innerW = Math.max(200, width - PAD_LEFT - PAD_RIGHT);
  const dayW = innerW / TOTAL_DAYS;

  // ── Year ribbon labels ────────────────────────────────────────────────
  // Every label is the model's forecast — no observed/projected split, so
  // every tick uses the same neutral fill colour.
  const yearTicks = useMemo(() => {
    const ticks: { x: number; label: string }[] = [];
    for (let year = 2026; year <= 2035; year += 1) {
      const dayOfStart = Math.round(
        (Date.UTC(year, 0, 1) - SIM_START_DATE_UTC) / 86_400_000,
      );
      if (dayOfStart < 0 || dayOfStart > TOTAL_DAYS) continue;
      ticks.push({
        x: PAD_LEFT + dayOfStart * dayW,
        label: String(year),
      });
    }
    return ticks;
  }, [dayW]);

  // ── Driver paths ─────────────────────────────────────────────────────
  // Each path is built with yOffset = 0 (i.e. coordinates LOCAL to its row);
  // DriverRow translates the row group to its band slot.
  // Vertical range is auto-fitted from the data with a 10 % padding so the
  // line's amplitude actually stretches across its band — fixed -10..40 °C
  // / 0..100 % buckets squashed real-world fluctuations down to ~25 % of
  // the band height.
  const driverPaths = useMemo(() => {
    return [
      driverLine(frame.ambient_temp_c,    frame.day, dayW, ...autoRange(frame.ambient_temp_c, 0.1)),
      driverLine(frame.humidity_pct,      frame.day, dayW, ...autoRange(frame.humidity_pct,    0.1)),
      driverLine(frame.daily_print_hours, frame.day, dayW, ...autoRange(frame.daily_print_hours, 0.1)),
    ];
  }, [frame, dayW]);

  // ── Status cells ─────────────────────────────────────────────────────
  // Run-length-encode each row so contiguous days of the same status
  // render as ONE rect rather than ~one rect per day.
  const statusCells = useMemo(() => {
    const out: { row: number; x: number; w: number; fill: string }[] = [];
    for (const flat of FLAT_ROWS) {
      const arr = (frame as unknown as Record<string, string[]>)[`status_${flat.sid}`];
      if (!arr || arr.length === 0) continue;
      let runStart = 0;
      let runStatus = arr[0];
      for (let i = 1; i <= arr.length; i += 1) {
        const next = i < arr.length ? arr[i] : "__END__";
        if (next !== runStatus) {
          const fill = STATUS_COLORS[runStatus] ?? "rgba(255,255,255,0.06)";
          out.push({
            row: flat.rowIndex,
            x: PAD_LEFT + runStart * dayW,
            w: (i - runStart) * dayW,
            fill,
          });
          runStart = i;
          runStatus = next;
        }
      }
    }
    return out;
  }, [frame, dayW]);

  // ── Cursor ───────────────────────────────────────────────────────────
  const cursorX = PAD_LEFT + currentDay * dayW;

  function onClickStrip(e: React.MouseEvent<SVGRectElement>) {
    const rect = (e.currentTarget.ownerSVGElement as SVGSVGElement).getBoundingClientRect();
    const x = e.clientX - rect.left;
    const day = Math.max(0, Math.min(TOTAL_DAYS - 1, Math.round((x - PAD_LEFT) / dayW)));
    onScrub(day);
  }

  return (
    <svg ref={ref} width="100%" height={TOTAL_H} className="select-none">
      {/* Year ribbon — uniform style, every tick is forecast.
          The vertical guideline only spans the DRIVER area; we stop it
          before the status grid so it doesn't show as a slim dark cut
          through the green/orange status bands. */}
      <g>
        {yearTicks.map((t) => (
          <g key={t.label}>
            <line
              x1={t.x} x2={t.x}
              y1={HEADER_H - 4} y2={HEADER_H + DRIVERS_H + 4}
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

      {/* Driver block */}
      <g transform={`translate(0, ${HEADER_H})`}>
        <DriverRow label="Temperature" pathD={driverPaths[0]} y={0}             color="var(--color-fg)" />
        <DriverRow label="Humidity"    pathD={driverPaths[1]} y={DRIVERS_H/3}   color="var(--color-fg-muted)" />
        <DriverRow label="Print hours" pathD={driverPaths[2]} y={2*DRIVERS_H/3} color="var(--color-accent)" />
      </g>

      {/* Status grid */}
      <g transform={`translate(0, ${HEADER_H + DRIVERS_H + DRIVERS_GAP})`}>
        {/* Subsystem headers — small caps over each group, with a faint
            full-width hairline so the bands group visually under them. */}
        {COMPONENT_GROUPS.map((g, gi) => {
          const y = subsystemHeaderY(gi);
          return (
            <g key={g.subsystem}>
              <text
                x={PAD_LEFT - 10}
                y={y + SUBSYS_LABEL_H * 0.78}
                fontSize={9.5}
                textAnchor="end"
                fill="var(--color-fg-faint)"
                fontFamily="inherit"
                style={{ letterSpacing: "0.18em", textTransform: "uppercase" }}
              >
                {g.subsystem}
              </text>
              <line
                x1={PAD_LEFT}
                x2={PAD_LEFT + innerW}
                y1={y + SUBSYS_LABEL_H - 3}
                y2={y + SUBSYS_LABEL_H - 3}
                stroke="rgba(255,255,255,0.06)"
                strokeWidth={1}
              />
            </g>
          );
        })}
        {/* Component labels — placed at the row's actual Y so they don't
            slide under their subsystem header. */}
        {FLAT_ROWS.map((flat) => (
          <text
            key={flat.sid}
            x={PAD_LEFT - 10}
            y={rowYOffset(flat.rowIndex) + ROW_H * 0.68}
            fontSize={11}
            textAnchor="end"
            fill="var(--color-fg-muted)"
            fontFamily="inherit"
          >
            {flat.label}
          </text>
        ))}
        {/* Status bands — same RLE'd rects as before, just positioned via
            the new rowYOffset helper which honours the subsystem headers. */}
        {statusCells.map((cell, i) => (
          <rect
            key={i}
            x={cell.x}
            y={rowYOffset(cell.row)}
            width={cell.w}
            height={ROW_H}
            fill={cell.fill}
            shapeRendering="crispEdges"
          />
        ))}
        {/* click target spans the whole strip */}
        <rect
          x={PAD_LEFT}
          y={0}
          width={innerW}
          height={GRID_H}
          fill="transparent"
          style={{ cursor: "pointer" }}
          onClick={onClickStrip}
        />
      </g>

      {/* Time cursor */}
      <g>
        <line
          x1={cursorX} x2={cursorX}
          y1={HEADER_H - 4}
          y2={HEADER_H + DRIVERS_H + DRIVERS_GAP + GRID_H}
          stroke="var(--color-fg)"
          strokeWidth={1}
          strokeOpacity={0.9}
        />
        <circle cx={cursorX} cy={HEADER_H + DRIVERS_H + DRIVERS_GAP + GRID_H + 4} r={3.5} fill="var(--color-fg)" />
        <text
          x={cursorX + 7}
          y={HEADER_H + DRIVERS_H + DRIVERS_GAP + GRID_H + 18}
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

/* ───────────────────────────────────────────────────────────────────────── */
/*  Helpers                                                                  */
/* ───────────────────────────────────────────────────────────────────────── */

function DriverRow({
  label, pathD, y, color,
}: { label: string; pathD: string; y: number; color: string }) {
  return (
    <g transform={`translate(0, ${y})`}>
      <text
        x={PAD_LEFT - 10} y={DRIVERS_H / 6}
        fontSize={11} textAnchor="end" fill="var(--color-fg-muted)"
        fontFamily="inherit"
      >
        {label}
      </text>
      <path d={pathD} stroke={color} strokeWidth={1.5} fill="none" opacity={0.9} />
    </g>
  );
}

/**
 * Auto-fit a driver series's vertical range with `padPct` headroom on each
 * end. Returns a tuple compatible with the trailing `vMin, vMax, yOffset`
 * args of `driverLine` (yOffset is always 0 — local-to-row coords).
 */
function autoRange(values: number[], padPct: number): [number, number, number] {
  if (!values || values.length === 0) return [0, 1, 0];
  let lo = Infinity;
  let hi = -Infinity;
  for (const v of values) {
    if (v < lo) lo = v;
    if (v > hi) hi = v;
  }
  if (!isFinite(lo) || !isFinite(hi) || lo === hi) {
    return [lo - 1, hi + 1, 0];
  }
  const pad = (hi - lo) * padPct;
  return [lo - pad, hi + pad, 0];
}

function driverLine(
  values: number[],
  days: number[],
  dayW: number,
  vMin: number,
  vMax: number,
  yOffset: number,
): string {
  const h = DRIVERS_H / 3 - 10;
  const span = vMax - vMin || 1;
  let d = "";
  for (let i = 0; i < values.length; i += 1) {
    const x = PAD_LEFT + days[i] * dayW;
    const norm = (values[i] - vMin) / span;
    const y = yOffset + 5 + (1 - Math.max(0, Math.min(1, norm))) * h;
    d += (i === 0 ? "M" : "L") + x.toFixed(1) + "," + y.toFixed(1) + " ";
  }
  return d;
}

function dayToYearLabel(day: number): string {
  const ms = SIM_START_DATE_UTC + day * 86_400_000;
  const d = new Date(ms);
  return d.toLocaleDateString(undefined, {
    year: "numeric", month: "short", day: "numeric",
  });
}
