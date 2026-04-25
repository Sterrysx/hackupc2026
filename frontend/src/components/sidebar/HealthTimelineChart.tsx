/**
 * Sparkline of a component's health over the full Stage 1 timeline.
 *
 *  - Pulls H_C{i} for the focused part from `/twin/timeline` once per
 *    (city, printer, component); cached in-memory for the session.
 *  - Renders a tiny recharts area + reference line for the current day
 *    so the operator sees where they sit in the 10-year arc.
 *  - Hidden when the store is in mock mode (no live data to chart).
 */
import { useEffect, useState } from "react";
import {
  Area,
  AreaChart,
  ReferenceLine,
  ResponsiveContainer,
  YAxis,
} from "recharts";

import { useTwin } from "@/store/twin";
import {
  backendCityName,
  fetchTimeline,
  simIdFor,
  tickToDay,
} from "@/lib/twinApi";
import type { ComponentId } from "@/types/telemetry";

type Sample = { day: number; h: number };

/** In-memory cache so re-opening the same component doesn't re-fetch. */
const CACHE = new Map<string, Sample[]>();
const cacheKey = (city: string, printerId: number, simId: string) =>
  `${city}::${printerId}::${simId}`;

async function loadHealthSeries(
  city: string,
  printerId: number,
  componentId: ComponentId,
): Promise<Sample[]> {
  const simId = simIdFor(componentId);
  const key = cacheKey(city, printerId, simId);
  const cached = CACHE.get(key);
  if (cached) return cached;

  const field = `H_${simId}`;
  const raw = await fetchTimeline({ city, printerId, fields: [field] });
  const days = raw.day as number[];
  const values = raw[field] as number[];
  const samples: Sample[] = days.map((d, i) => ({ day: d, h: values[i] }));

  // Down-sample so recharts renders fast — 3,653 points → ~365 (every 10th day).
  // Health is smooth so visual fidelity is unaffected; current-day cursor is exact.
  const step = Math.max(1, Math.floor(samples.length / 400));
  const decimated = samples.filter((_, i) => i % step === 0);

  CACHE.set(key, decimated);
  return decimated;
}

export function HealthTimelineChart({ id }: { id: ComponentId }) {
  const dataSource = useTwin((s) => s.dataSource);
  const selectedCity = useTwin((s) => s.selectedCity);
  const selectedPrinterId = useTwin((s) => s.selectedPrinterId);
  const tick = useTwin((s) => s.tick);

  const [series, setSeries] = useState<Sample[] | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (dataSource !== "live" || !selectedCity || selectedPrinterId === null) {
      setSeries(null);
      return;
    }
    let cancelled = false;
    setError(null);
    loadHealthSeries(backendCityName(selectedCity), selectedPrinterId, id)
      .then((s) => { if (!cancelled) setSeries(s); })
      .catch((e: Error) => { if (!cancelled) setError(e.message); });
    return () => { cancelled = true; };
  }, [dataSource, selectedCity, selectedPrinterId, id]);

  if (dataSource !== "live") return null;

  const currentDay = tickToDay(tick);

  return (
    <section>
      <header className="flex items-baseline justify-between mb-2">
        <h3 className="text-[10px] uppercase tracking-[0.20em] text-[var(--color-fg-faint)]">
          Lifetime trace · 10y
        </h3>
        <span className="text-[10.5px] text-[var(--color-fg-faint)] tabular-nums">
          day {currentDay}
        </span>
      </header>
      <div className="h-20 w-full">
        {series === null && !error && (
          <div className="h-full w-full animate-pulse rounded-md bg-white/[0.03]" />
        )}
        {error && (
          <div className="text-[11px] text-[var(--color-fg-faint)]">
            timeline unavailable
          </div>
        )}
        {series && (
          <ResponsiveContainer width="100%" height="100%">
            <AreaChart data={series} margin={{ top: 4, right: 4, bottom: 0, left: 0 }}>
              <defs>
                <linearGradient id="healthGrad" x1="0" y1="0" x2="0" y2="1">
                  <stop offset="0%"   stopColor="var(--color-accent)" stopOpacity={0.45} />
                  <stop offset="100%" stopColor="var(--color-accent)" stopOpacity={0.0} />
                </linearGradient>
              </defs>
              <YAxis hide domain={[0, 1]} />
              <ReferenceLine
                x={currentDay}
                stroke="var(--color-fg)"
                strokeOpacity={0.55}
                strokeDasharray="2 3"
              />
              <Area
                type="monotone"
                dataKey="h"
                stroke="var(--color-accent)"
                strokeWidth={1.5}
                fill="url(#healthGrad)"
                isAnimationActive={false}
                dot={false}
              />
            </AreaChart>
          </ResponsiveContainer>
        )}
      </div>
    </section>
  );
}
