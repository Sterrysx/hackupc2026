import { useMemo } from "react";
import { motion } from "framer-motion";
import {
  Area, AreaChart, ResponsiveContainer, ReferenceLine, Tooltip,
  Line, LineChart,
} from "recharts";
import { useTwin } from "@/store/twin";
import { liveDaysRemaining, formatEta } from "@/lib/alerts";
import { TICKS_PER_DAY, tickToDay } from "@/lib/twinApi";
import { LifetimeTelemetryTile } from "@/components/analytics/LifetimeTelemetryTile";
import { PredictiveTrajectoryTile } from "@/components/analytics/PredictiveTrajectoryTile";
import type { ComponentForecast, ComponentState } from "@/types/telemetry";

/**
 * "God-mode" analytics surface. Bento-grid layout over a heavily blurred
 * copy of the underlying canvas — the blur lives in App.tsx, this component
 * only owns the foreground.
 *
 * Tiles are intentionally Apple-quiet:
 *  • no Cartesian gridlines, no axis ticks, no tooltip cruft
 *  • smooth `monotone` curves, gradient area fills
 *  • each tile is a single thought: hero forecast / risk ranking / drivers / alerts
 */

const APPLE_EASE: [number, number, number, number] = [0.16, 1, 0.3, 1];
// One year of forward projection — long enough that the worst-component
// curve actually reaches the critical threshold for most printers, short
// enough to keep the X axis legible at the bento tile width.
const HORIZON_DAYS = 365;
const HEALTH_CRITICAL = 0.4;        // mirror Ai_Agent/forecast.py::H_CRITICAL

export function AnalyticsView() {
  const snapshot = useTwin((s) => s.snapshot);
  const tick = useTwin((s) => s.tick);
  const snapshotMarkTick = useTwin((s) => s.snapshotMarkTick);
  const alerts = useTwin((s) => s.alerts);
  const backendPulseAlerts = useTwin((s) => s.backendPulseAlerts);
  const selectComponent = useTwin((s) => s.selectComponent);

  const combinedAlerts = useMemo(
    () => [...backendPulseAlerts, ...alerts],
    [backendPulseAlerts, alerts],
  );

  return (
    <motion.div
      key="analytics"
      initial={{ opacity: 0, y: 12 }}
      animate={{ opacity: 1, y: 0 }}
      exit={{ opacity: 0, y: 12 }}
      transition={{ duration: 0.45, ease: APPLE_EASE }}
      className="absolute inset-0 z-20 overflow-y-auto pointer-events-auto"
    >
      <div className="mx-auto w-full max-w-[1200px] px-8 py-12">
        <header className="mb-8">
          <p className="text-[10px] uppercase tracking-[0.22em] text-[var(--color-fg-faint)]">
            Analytics
          </p>
          <h1 className="mt-2 text-[24px] font-medium tracking-[-0.01em]">
            Predictive intelligence
          </h1>
          <p className="mt-2 text-[13px] text-[var(--color-fg-muted)]">
            Day {tickToDay(tick)} · ML projections, live drivers, and active maintenance signals.
          </p>
        </header>

        {/* Bento grid — 6 cols × auto rows. Each tile spans by intent. */}
        <div className="grid grid-cols-6 auto-rows-[160px] gap-4">
          {/* HERO: HP page-12 schematic — driver traces + status grid +
              year ribbon + scrubbable cursor. Full bento width and tall
              (5 rows) so every region — three driver traces, six
              component bands, year ribbon, cursor caption — has real
              whitespace and never reads as cramped. */}
          <LifetimeTelemetryTile className="col-span-6 row-span-5" />

          {/* Forward 10-year prediction trajectory from
              `data/validation/fleet_2026_2035.parquet`. Cursor walks with
              `tick` in playback mode, frozen on the current day in live
              mode — predictions are baked, never re-run client-side. */}
          <PredictiveTrajectoryTile className="col-span-6 row-span-4" />

          <DegradationForecastTile
            className="col-span-6 md:col-span-4 row-span-2"
            snapshotComponents={snapshot.components}
            forecasts={snapshot.forecasts}
            tick={tick}
            snapshotMarkTick={snapshotMarkTick}
          />
          <DriverRingTile
            className="col-span-3 md:col-span-2 row-span-1"
            label="Ambient temp"
            value={snapshot.drivers.ambientTempC}
            unit="°C"
            min={-10}
            max={40}
            warmAt={28}
          />
          <DriverRingTile
            className="col-span-3 md:col-span-2 row-span-1"
            label="Humidity"
            value={snapshot.drivers.humidityPct}
            unit="%"
            min={0}
            max={100}
            warmAt={75}
          />

          <RiskRankingTile
            className="col-span-6 md:col-span-3 row-span-2"
            forecasts={snapshot.forecasts}
            components={snapshot.components}
            tick={tick}
            snapshotMarkTick={snapshotMarkTick}
            onSelect={selectComponent}
          />
          <AlertsFeedTile
            className="col-span-6 md:col-span-3 row-span-2"
            alerts={combinedAlerts}
            onSelect={selectComponent}
          />
        </div>
      </div>
    </motion.div>
  );
}

/* ───────────────────────────────────────────────────────────────────────── */
/*  Bento tile shell                                                          */
/* ───────────────────────────────────────────────────────────────────────── */

function Tile({
  className,
  title,
  caption,
  children,
}: {
  className?: string;
  title?: string;
  caption?: string;
  children: React.ReactNode;
}) {
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
      {(title || caption) && (
        <header className="flex items-baseline justify-between mb-3">
          {title && (
            <h2 className="text-[10px] uppercase tracking-[0.20em] text-[var(--color-fg-faint)]">
              {title}
            </h2>
          )}
          {caption && (
            <span className="text-[10.5px] text-[var(--color-fg-faint)] tabular-nums">
              {caption}
            </span>
          )}
        </header>
      )}
      <div className="flex-1 min-h-0">{children}</div>
    </motion.section>
  );
}

/* ───────────────────────────────────────────────────────────────────────── */
/*  Tile 1 — System Degradation Forecast (hero, 4×2)                          */
/* ───────────────────────────────────────────────────────────────────────── */

function DegradationForecastTile({
  className,
  snapshotComponents,
  forecasts,
  tick,
  snapshotMarkTick,
}: {
  className?: string;
  snapshotComponents: ComponentState[];
  forecasts: ComponentForecast[];
  tick: number;
  snapshotMarkTick: number;
}) {
  // Project the *worst-component* health across the operational horizon.
  // Linear projection from current health using the implied per-day rate
  // back-derived from each component's `daysUntilFailure` (the same signal
  // the backend already exposes). We pick the worst component each day so
  // the hero curve always reflects "the machine's bottleneck".
  const data = useMemo(() => {
    return Array.from({ length: HORIZON_DAYS + 1 }, (_, dayOffset) => {
      let worstHealth = 1;
      for (const c of snapshotComponents) {
        const f = forecasts.find((x) => x.id === c.id);
        const failureDays = liveDaysRemaining(
          f?.daysUntilFailure ?? null,
          tick, snapshotMarkTick,
        );
        // Project: if failure is N days away, health drops linearly from
        // current value to ~0 over N days. After that, it's failed (~0).
        let projected = c.healthIndex;
        if (failureDays !== null && failureDays > 0) {
          const progress = Math.min(1, dayOffset / failureDays);
          projected = c.healthIndex * (1 - progress);
        } else if (failureDays === 0) {
          projected = 0;
        }
        if (projected < worstHealth) worstHealth = projected;
      }
      return {
        day: dayOffset,
        health: Number((worstHealth * 100).toFixed(2)),
      };
    });
  }, [snapshotComponents, forecasts, tick, snapshotMarkTick]);

  // Find first crossing of the critical threshold for the marker.
  const criticalCrossing = useMemo(() => {
    const t = HEALTH_CRITICAL * 100;
    return data.find((d) => d.health <= t)?.day;
  }, [data]);

  const currentHealth = data[0]?.health ?? 100;

  return (
    <Tile
      className={className}
      title="System degradation forecast"
      caption={HORIZON_DAYS >= 365
        ? `next ${(HORIZON_DAYS / 365).toFixed(1)} y`
        : `next ${HORIZON_DAYS} d`}
    >
      <div className="flex items-baseline gap-3 mb-2">
        <span className="text-[28px] font-semibold tracking-tight tabular-nums">
          {currentHealth.toFixed(0)}%
        </span>
        <span className="text-[11px] text-[var(--color-fg-muted)]">
          worst-component health · {criticalCrossing !== undefined
            ? `crosses critical in ~${formatHorizonOffset(criticalCrossing)}`
            : "stays above critical"}
        </span>
      </div>
      <ResponsiveContainer width="100%" height="80%">
        <AreaChart data={data} margin={{ top: 8, right: 4, left: 4, bottom: 0 }}>
          <defs>
            <linearGradient id="degGradient" x1="0" y1="0" x2="0" y2="1">
              <stop offset="0%"   stopColor="var(--color-accent)" stopOpacity={0.55} />
              <stop offset="100%" stopColor="var(--color-accent)" stopOpacity={0}  />
            </linearGradient>
          </defs>
          <Tooltip
            contentStyle={{
              background: "rgba(20,20,24,0.85)",
              border: "1px solid rgba(255,255,255,0.08)",
              borderRadius: 12,
              fontSize: 11,
              color: "var(--color-fg)",
            }}
            formatter={(v) => [`${Number(v).toFixed(1)}%`, "Health"]}
            labelFormatter={(d) => `day +${d}`}
          />
          {criticalCrossing !== undefined && (
            <ReferenceLine
              y={HEALTH_CRITICAL * 100}
              stroke="var(--color-warn)"
              strokeDasharray="3 3"
              strokeOpacity={0.6}
            />
          )}
          <Area
            type="monotone"
            dataKey="health"
            stroke="var(--color-accent)"
            strokeWidth={2}
            fill="url(#degGradient)"
            isAnimationActive={false}
          />
        </AreaChart>
      </ResponsiveContainer>
    </Tile>
  );
}

/* ───────────────────────────────────────────────────────────────────────── */
/*  Tile 2 — Component Risk Ranking (3×2)                                     */
/* ───────────────────────────────────────────────────────────────────────── */

function RiskRankingTile({
  className,
  forecasts,
  components,
  tick,
  snapshotMarkTick,
  onSelect,
}: {
  className?: string;
  forecasts: ComponentForecast[];
  components: ComponentState[];
  tick: number;
  snapshotMarkTick: number;
  onSelect: (id: ComponentState["id"]) => void;
}) {
  const ranked = useMemo(() => {
    const fById = new Map(forecasts.map((f) => [f.id, f]));
    return components
      .map((c) => {
        const f = fById.get(c.id);
        const liveDays = liveDaysRemaining(
          f?.daysUntilFailure ?? null,
          tick, snapshotMarkTick,
        );
        // Simple risk score: combine current health (lower -> riskier) with
        // ETA (sooner -> riskier). Components with no ETA are pushed down.
        const etaDays = liveDays === null ? Infinity : liveDays;
        const risk = (1 - c.healthIndex) * 0.6 + (1 / (1 + etaDays)) * 0.4;
        return { component: c, forecast: f, liveDays, risk };
      })
      .sort((a, b) => b.risk - a.risk)
      .slice(0, 3);
  }, [components, forecasts, tick, snapshotMarkTick]);

  return (
    <Tile className={className} title="Component risk ranking" caption="top 3">
      <ul className="flex flex-col gap-3 h-full">
        {ranked.map(({ component, liveDays, risk }, idx) => {
          // Build a tiny sparkline from a synthetic decay tail anchored on
          // the actual current health and projected ETA (no random noise).
          const tail = sparklineSeries(component.healthIndex, liveDays);
          const probPct = Math.min(99, Math.round(risk * 100));
          return (
            <li key={component.id}>
              <button
                type="button"
                onClick={() => onSelect(component.id)}
                className="group w-full grid grid-cols-[auto_1fr_auto_auto] items-center gap-3 -mx-1 px-1 py-1.5 rounded-xl hover:bg-white/[0.04] transition-colors"
              >
                <span className="text-[10px] tabular-nums text-[var(--color-fg-faint)] w-4">
                  {idx + 1}
                </span>
                <div className="text-left min-w-0">
                  <div className="text-[12.5px] text-[var(--color-fg)] truncate">
                    {component.label}
                  </div>
                  <div className="text-[10.5px] text-[var(--color-fg-muted)] tabular-nums">
                    H {(component.healthIndex * 100).toFixed(0)}%
                    {liveDays !== null && ` · fail ~${formatEta(liveDays)}`}
                  </div>
                </div>
                <div className="w-[70px] h-7">
                  <ResponsiveContainer width="100%" height="100%">
                    <LineChart data={tail} margin={{ top: 2, right: 0, left: 0, bottom: 2 }}>
                      <Line
                        type="monotone"
                        dataKey="h"
                        stroke="var(--color-warn)"
                        strokeWidth={1.5}
                        dot={false}
                        isAnimationActive={false}
                      />
                    </LineChart>
                  </ResponsiveContainer>
                </div>
                <span className="text-[12px] tabular-nums font-medium text-[var(--color-warn)] w-10 text-right">
                  {probPct}%
                </span>
              </button>
            </li>
          );
        })}
      </ul>
    </Tile>
  );
}

function formatHorizonOffset(days: number): string {
  if (days < 14) return `${days}d`;
  if (days < 60) return `${Math.round(days / 7)}w`;
  if (days < 730) return `${Math.round(days / 30)}mo`;
  return `${(days / 365).toFixed(1)}y`;
}

function sparklineSeries(currentHealth: number, failureDays: number | null) {
  // 16 points across "now -> projected failure or ~7 days, whichever is sooner".
  const horizonDays = failureDays && failureDays > 0
    ? Math.min(failureDays, 7)
    : 7;
  return Array.from({ length: 16 }, (_, i) => {
    const t = i / 15;
    const drop = failureDays !== null
      ? Math.min(1, (t * horizonDays) / failureDays)
      : t * 0.15; // gentle drift if stable
    return { t, h: Math.max(0, currentHealth * (1 - drop)) };
  });
}

/* ───────────────────────────────────────────────────────────────────────── */
/*  Tile 3 — Live external variables (2×1 each, with circular progress)       */
/* ───────────────────────────────────────────────────────────────────────── */

function DriverRingTile({
  className,
  label,
  value,
  unit,
  min,
  max,
  warmAt,
}: {
  className?: string;
  label: string;
  value: number;
  unit: string;
  min: number;
  max: number;
  warmAt: number;
}) {
  const fraction = Math.max(0, Math.min(1, (value - min) / (max - min)));
  const ringStroke = value >= warmAt ? "var(--color-warn)" : "var(--color-accent)";
  return (
    <Tile className={className} title={label}>
      <div className="flex items-center gap-4 h-full">
        <Ring fraction={fraction} stroke={ringStroke} />
        <div className="flex flex-col leading-tight">
          <span className="text-[26px] font-semibold tabular-nums tracking-tight">
            {value.toFixed(value < 10 ? 1 : 0)}
            <span className="text-[13px] font-normal text-[var(--color-fg-muted)] ml-1">
              {unit}
            </span>
          </span>
          <span className="text-[10.5px] text-[var(--color-fg-faint)] tabular-nums mt-0.5">
            range {min}{unit} – {max}{unit}
          </span>
        </div>
      </div>
    </Tile>
  );
}

function Ring({ fraction, stroke }: { fraction: number; stroke: string }) {
  const r = 26;
  const c = 2 * Math.PI * r;
  return (
    <svg width="64" height="64" viewBox="0 0 64 64" className="-rotate-90">
      <circle
        cx="32" cy="32" r={r}
        fill="none"
        stroke="rgba(255,255,255,0.10)"
        strokeWidth="4"
      />
      <circle
        cx="32" cy="32" r={r}
        fill="none"
        stroke={stroke}
        strokeWidth="4"
        strokeLinecap="round"
        strokeDasharray={`${c * fraction} ${c}`}
        style={{ transition: "stroke-dasharray 600ms ease" }}
      />
    </svg>
  );
}

/* ───────────────────────────────────────────────────────────────────────── */
/*  Tile 4 — Active Maintenance Alerts (3×2)                                  */
/* ───────────────────────────────────────────────────────────────────────── */

function AlertsFeedTile({
  className,
  alerts,
  onSelect,
}: {
  className?: string;
  alerts: import("@/types/telemetry").Alert[];
  onSelect: (id: ComponentState["id"]) => void;
}) {
  const top = alerts.slice(0, 6);
  return (
    <Tile
      className={className}
      title="Active maintenance alerts"
      caption={alerts.length === 0 ? "all clear" : `${alerts.length} active`}
    >
      {top.length === 0 ? (
        <p className="text-[12.5px] text-[var(--color-fg-muted)]">
          No alerts. Twin is operating within all thresholds.
        </p>
      ) : (
        <ul className="flex flex-col">
          {top.map((a, i) => (
            <li key={a.id}>
              <button
                type="button"
                onClick={() => onSelect(a.componentId)}
                className={
                  "w-full text-left flex items-start gap-3 py-2 -mx-2 px-2 rounded-xl hover:bg-white/[0.04] transition-colors " +
                  (i !== 0 ? "border-t border-[var(--color-border)]" : "")
                }
              >
                <span
                  className="mt-1.5 h-1.5 w-1.5 rounded-full flex-shrink-0"
                  style={{ background: dotColour(a.severity) }}
                />
                <div className="flex-1 min-w-0">
                  <div className="text-[12.5px] text-[var(--color-fg)] truncate">
                    {a.title}
                  </div>
                  <div className="text-[11px] text-[var(--color-fg-muted)] truncate mt-0.5">
                    {a.componentLabel} · {a.kind === "predictive" ? "predicted" : "now"}
                    {a.etaDays !== undefined && ` · ${formatEta(a.etaDays)}`}
                  </div>
                </div>
              </button>
            </li>
          ))}
        </ul>
      )}
    </Tile>
  );
}

function dotColour(s: "INFO" | "WARNING" | "CRITICAL"): string {
  if (s === "CRITICAL") return "var(--color-crit)";
  if (s === "WARNING")  return "var(--color-warn)";
  return "var(--color-info)";
}

// Suppress unused-import warning during refactor: TICKS_PER_DAY may be
// useful for future per-tick projections, but we currently project in days.
void TICKS_PER_DAY;
