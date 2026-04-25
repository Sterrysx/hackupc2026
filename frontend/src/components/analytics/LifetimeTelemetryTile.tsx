import { useEffect, useMemo, useRef, useState } from "react";
import { motion } from "framer-motion";
import { useTwin } from "@/store/twin";
import {
  backendCityName, fetchTimeline,
  SIM_DAY_COUNT, TICKS_PER_DAY, tickToDay,
} from "@/lib/twinApi";

/**
 * LifetimeTelemetryTile — the page-12 schematic from the HP brief.
 *
 *   ┌──────────────────────────────────────────────────────────────────┐
 *   │  2015  2016  2017  …  2024 │  2025+ projected                   │
 *   ├──────────────────────────────────────────────────────────────────┤
 *   │  Temperature  ─╲╱╲╱╲╱╲╱─                                         │
 *   │  Humidity     ─╲ ╱ ╲╱╲ ─                                         │
 *   │  Print volume ─╱╲╱─╲╱╲ ─                                         │
 *   ├──────────────────────────────────────────────────────────────────┤
 *   │  C1  ▮▮▮▮▮▮▮▮▮▮▮▮▮▮▮▮ ▮▮▮▮▮ ▮▮▮▮▮ ▮▮▮▮▮▮▮ ▮▮▮▮▮▮▮▮▮▮▮▮▮         │
 *   │  C2  ▮▮▮▮▮▮▮▮▮▮▮▮▮▮▮▮ ▮▮▮▮▮ ▮▮▮▮▮ ▮▮▮▮▮▮▮ ▮▮▮▮▮▮▮▮▮▮▮▮▮         │
 *   │  …                                                                │
 *   └──────────────────┬─── time cursor (day current_day) ──────────────┘
 *
 * Top half: per-day driver traces (temp, humidity, jobs) as SVG paths.
 * Bottom half: a 6 × N status grid where each cell is colored by
 * `status_C{i}` (FUNCTIONAL / DEGRADED / CRITICAL / FAILED).
 *
 * The "projected future" zone (anything beyond the last historical day) is
 * rendered with a hatched overlay so the operator immediately sees which
 * part is observed vs which part is the model's extrapolation. Today the
 * parquet covers 2015-01-01 .. 2024-12-31; in the production version we'd
 * extend the grid into 2025+ with the SSL/RUL forecasts.
 *
 * The full-width vertical cursor reflects the current sim tick and the
 * operator can click anywhere on the strip to scrub.
 */

const SIM_START_DATE_UTC = Date.UTC(2015, 0, 1);
const HISTORICAL_END_DAY = SIM_DAY_COUNT - 1;            // last parquet day
const PROJECTION_DAYS = 5 * 365;                          // 5 years forward
const TOTAL_DAYS = HISTORICAL_END_DAY + 1 + PROJECTION_DAYS;
const STATUS_COLORS: Record<string, string> = {
  OK: "rgba(76, 217, 100, 0.85)",
  FUNCTIONAL: "rgba(76, 217, 100, 0.85)",
  WARNING: "rgba(255, 204, 0, 0.85)",
  DEGRADED: "rgba(255, 204, 0, 0.85)",
  CRITICAL: "rgba(255, 149, 0, 0.85)",
  FAILED: "rgba(255, 69, 58, 0.85)",
};
const COMPONENT_ROWS: Array<{ sid: string; label: string }> = [
  { sid: "C1", label: "Recoater blade"   },
  { sid: "C2", label: "Recoater motor"   },
  { sid: "C3", label: "Nozzle plate"     },
  { sid: "C4", label: "Thermal resistor" },
  { sid: "C5", label: "Heating element"  },
  { sid: "C6", label: "Insulation panel" },
];

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
  const tick = useTwin((s) => s.tick);
  const setTick = useTwin((s) => s.setTick);
  const dataSource = useTwin((s) => s.dataSource);
  const selectedCity = useTwin((s) => s.selectedCity);
  const selectedPrinterId = useTwin((s) => s.selectedPrinterId);

  const [timeline, setTimeline] = useState<TimelineFrame | null>(null);
  const [loadError, setLoadError] = useState(false);

  // Fetch the full lifetime once when in live mode. Mock mode shows the
  // empty-state hint; the schematic is most valuable backed by real data.
  useEffect(() => {
    if (dataSource !== "live" || !selectedCity || selectedPrinterId === null) {
      setTimeline(null);
      return;
    }
    let cancelled = false;
    void (async () => {
      try {
        const raw = await fetchTimeline({
          city: backendCityName(selectedCity),
          printerId: selectedPrinterId,
          fields: [
            "ambient_temp_c", "humidity_pct", "daily_print_hours",
            "status_C1", "status_C2", "status_C3",
            "status_C4", "status_C5", "status_C6",
          ],
          dayFrom: 0,
          dayTo: HISTORICAL_END_DAY,
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
  }, [dataSource, selectedCity, selectedPrinterId]);

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
      <header className="flex items-baseline justify-between mb-3">
        <h2 className="text-[10px] uppercase tracking-[0.20em] text-[var(--color-fg-faint)]">
          Lifetime telemetry
        </h2>
        <span className="text-[10.5px] text-[var(--color-fg-faint)] tabular-nums">
          2015 — 2030 · observed + projected
        </span>
      </header>

      {loadError && (
        <p className="text-[12px] text-[var(--color-fg-muted)]">
          Unable to load timeline from /twin/timeline.
        </p>
      )}

      {!timeline && !loadError && (
        <p className="text-[12px] text-[var(--color-fg-muted)]">
          {dataSource !== "live"
            ? "Connect a live printer to render the lifetime telemetry strip."
            : "Loading 10 years of telemetry…"}
        </p>
      )}

      {timeline && (
        <TimelineCanvas
          frame={timeline}
          currentDay={tickToDay(tick)}
          onScrub={(day) => setTick(day * TICKS_PER_DAY)}
        />
      )}
    </motion.section>
  );
}

/* ───────────────────────────────────────────────────────────────────────── */
/*  Canvas — pure SVG, no chart lib, exact match to the schematic           */
/* ───────────────────────────────────────────────────────────────────────── */

const PAD_LEFT = 92;       // label gutter on the left
const PAD_RIGHT = 16;
const HEADER_H = 22;       // year ribbon
const DRIVERS_H = 110;     // 3 stacked driver lines
const ROW_H = 16;          // status grid row height
const ROW_GAP = 2;
const GRID_H = COMPONENT_ROWS.length * (ROW_H + ROW_GAP);
const TOTAL_H = HEADER_H + DRIVERS_H + 14 + GRID_H + 18;

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
  const projectionStartX = PAD_LEFT + (HISTORICAL_END_DAY + 1) * dayW;

  // ── Year ribbon labels ────────────────────────────────────────────────
  const yearTicks = useMemo(() => {
    const ticks: { x: number; label: string; isProjection: boolean }[] = [];
    for (let year = 2015; year <= 2030; year += 1) {
      const dayOfStart = Math.round(
        (Date.UTC(year, 0, 1) - SIM_START_DATE_UTC) / 86_400_000,
      );
      if (dayOfStart < 0 || dayOfStart > TOTAL_DAYS) continue;
      ticks.push({
        x: PAD_LEFT + dayOfStart * dayW,
        label: String(year),
        isProjection: dayOfStart > HISTORICAL_END_DAY,
      });
    }
    return ticks;
  }, [dayW]);

  // ── Driver paths ─────────────────────────────────────────────────────
  const driverPaths = useMemo(() => {
    return [
      driverLine(frame.ambient_temp_c,   frame.day, dayW, -10, 40, 0),
      driverLine(frame.humidity_pct,     frame.day, dayW, 0, 100, DRIVERS_H / 3),
      driverLine(frame.daily_print_hours, frame.day, dayW, 0, Math.max(12, ...frame.daily_print_hours), 2 * DRIVERS_H / 3),
    ];
  }, [frame, dayW]);

  // ── Status cells ─────────────────────────────────────────────────────
  // Downsample to ~one cell per (TOTAL_DAYS / max_cells) days, so we
  // don't paint 21,918 SVG rects on the page. 365 × 6 = 2,190 cells.
  const cellStep = Math.max(1, Math.ceil(HISTORICAL_END_DAY / 365));
  const statusCells = useMemo(() => {
    const out: { row: number; x: number; w: number; fill: string }[] = [];
    for (let r = 0; r < COMPONENT_ROWS.length; r += 1) {
      const sid = COMPONENT_ROWS[r].sid;
      const arr = (frame as unknown as Record<string, string[]>)[`status_${sid}`];
      for (let i = 0; i < arr.length; i += cellStep) {
        const status = arr[i];
        const fill = STATUS_COLORS[status] ?? "rgba(255,255,255,0.06)";
        const x = PAD_LEFT + i * dayW;
        const w = dayW * cellStep;
        out.push({ row: r, x, w, fill });
      }
    }
    return out;
  }, [frame, dayW, cellStep]);

  // ── Cursor ───────────────────────────────────────────────────────────
  const cursorX = PAD_LEFT + currentDay * dayW;

  function onClickStrip(e: React.MouseEvent<SVGRectElement>) {
    const rect = (e.currentTarget.ownerSVGElement as SVGSVGElement).getBoundingClientRect();
    const x = e.clientX - rect.left;
    const day = Math.max(0, Math.min(HISTORICAL_END_DAY, Math.round((x - PAD_LEFT) / dayW)));
    onScrub(day);
  }

  return (
    <svg ref={ref} width="100%" height={TOTAL_H} className="select-none">
      {/* Year ribbon */}
      <g>
        {yearTicks.map((t) => (
          <g key={t.label}>
            <line
              x1={t.x} x2={t.x}
              y1={HEADER_H - 4} y2={HEADER_H + DRIVERS_H + GRID_H + 14}
              stroke="rgba(255,255,255,0.04)"
              strokeWidth={1}
            />
            <text
              x={t.x + 3}
              y={HEADER_H - 6}
              fontSize={9.5}
              fill={t.isProjection ? "var(--color-warn)" : "var(--color-fg-faint)"}
              fontFamily="inherit"
            >
              {t.label}
            </text>
          </g>
        ))}
        <rect
          x={projectionStartX}
          y={HEADER_H - 4}
          width={Math.max(0, PAD_LEFT + innerW - projectionStartX)}
          height={DRIVERS_H + GRID_H + 18}
          fill="url(#projHatch)"
          opacity={0.9}
        />
      </g>

      <defs>
        <pattern id="projHatch" width="6" height="6" patternUnits="userSpaceOnUse" patternTransform="rotate(45)">
          <line x1="0" y1="0" x2="0" y2="6" stroke="rgba(255, 204, 0, 0.10)" strokeWidth="2" />
        </pattern>
        <linearGradient id="lineFadeTemp"  x1="0" x2="1" y1="0" y2="0">
          <stop offset="0%" stopColor="var(--color-accent)" stopOpacity="0.85" />
          <stop offset="100%" stopColor="var(--color-accent)" stopOpacity="0.85" />
        </linearGradient>
      </defs>

      {/* Driver block */}
      <g transform={`translate(0, ${HEADER_H})`}>
        <DriverRow label="Temperature" pathD={driverPaths[0]} y={0}             color="var(--color-fg)" />
        <DriverRow label="Humidity"    pathD={driverPaths[1]} y={DRIVERS_H/3}   color="var(--color-fg-muted)" />
        <DriverRow label="Print hours" pathD={driverPaths[2]} y={2*DRIVERS_H/3} color="var(--color-accent)" />
      </g>

      {/* Status grid */}
      <g transform={`translate(0, ${HEADER_H + DRIVERS_H + 14})`}>
        {COMPONENT_ROWS.map((c, i) => (
          <text
            key={c.sid}
            x={PAD_LEFT - 8}
            y={i * (ROW_H + ROW_GAP) + ROW_H * 0.7}
            fontSize={10}
            textAnchor="end"
            fill="var(--color-fg-muted)"
            fontFamily="inherit"
          >
            {c.label}
          </text>
        ))}
        {statusCells.map((cell, i) => (
          <rect
            key={i}
            x={cell.x}
            y={cell.row * (ROW_H + ROW_GAP)}
            width={Math.max(1, cell.w - 0.5)}
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
          y2={HEADER_H + DRIVERS_H + 14 + GRID_H}
          stroke="var(--color-fg)"
          strokeWidth={1}
          strokeOpacity={0.9}
        />
        <circle cx={cursorX} cy={HEADER_H + DRIVERS_H + 14 + GRID_H + 2} r={3} fill="var(--color-fg)" />
        <text
          x={cursorX + 5}
          y={HEADER_H + DRIVERS_H + 14 + GRID_H + 14}
          fontSize={9.5}
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
        x={PAD_LEFT - 8} y={DRIVERS_H / 6}
        fontSize={10} textAnchor="end" fill="var(--color-fg-muted)"
        fontFamily="inherit"
      >
        {label}
      </text>
      <path d={pathD} stroke={color} strokeWidth={1.25} fill="none" opacity={0.85} />
    </g>
  );
}

function driverLine(
  values: number[],
  days: number[],
  dayW: number,
  vMin: number,
  vMax: number,
  yOffset: number,
): string {
  const h = DRIVERS_H / 3 - 6;
  const span = vMax - vMin || 1;
  let d = "";
  for (let i = 0; i < values.length; i += 1) {
    const x = PAD_LEFT + days[i] * dayW;
    const norm = (values[i] - vMin) / span;
    const y = yOffset + 3 + (1 - Math.max(0, Math.min(1, norm))) * h;
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
