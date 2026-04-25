/**
 * Client for the FastAPI `/twin/*` endpoints (see repo root `app.py`).
 *
 * The backend serves a SystemSnapshot+forecast bundle off the Stage 1
 * simulator parquet (`data/fleet_baseline.parquet`). Shapes mirror
 * `frontend/src/types/telemetry.ts` so the response can be dropped into the
 * Zustand store with no transformation.
 */

import type { City } from "@/components/location/cities";
import type { ComponentId, SystemSnapshot, ComponentForecast } from "@/types/telemetry";
import { twinApiUrl } from "@/lib/agentApi";

/**
 * Frontend ComponentId → simulator C-id (matches `Ai_Agent/component_map.py`).
 * Use when requesting per-component parquet columns like `H_C1` from
 * `/twin/timeline`.
 */
export const FRONTEND_TO_SIM_ID: Record<ComponentId, string> = {
  recoater_blade:   "C1",
  recoater_motor:   "C2",
  nozzle_plate:     "C3",
  thermal_resistor: "C4",
  heating_element:  "C5",
  insulation_panel: "C6",
};

export function simIdFor(id: ComponentId): string {
  return FRONTEND_TO_SIM_ID[id];
}

/**
 * The parquet covers 15 European cities. The landing page lets the operator
 * choose from a worldwide list of 10 — only Barcelona and London overlap. For
 * the others, route to a climate-equivalent European city so the simulation
 * shown on screen still reflects the operator's intent.
 *
 * Update if the landing list or parquet city set changes.
 */
const CITY_TO_BACKEND: Record<string, string> = {
  singapore:   "Athens",       // hot + humid
  dubai:       "Madrid",       // hot + dry
  mumbai:      "Athens",       // hot + humid
  shanghai:    "Vienna",       // mild + humid
  barcelona:   "Barcelona",
  london:      "London",
  moscow:      "Helsinki",     // cold continental
  chicago:     "Warsaw",       // continental
  houston:     "Athens",       // hot
  mexico_city: "Madrid",       // mild altitude — closest fit
};

export function backendCityName(city: City): string {
  return CITY_TO_BACKEND[city.id] ?? city.name;
}

/**
 * Tick is the simulator's natural unit: **one tick = one day** (the parquet
 * has one row per day per printer and the RUL head reasons in days). At
 * `speed = 1` the wall clock advances 1 day/sec; the same tick that bumps
 * the timeline by a day also burns 1 sim-day off every visible ETA, so
 * the date readout and the failure countdown stay in lockstep. The
 * transport bar's speed picker scales both proportionally.
 *
 * NO MINUTE / HOUR UNITS BEYOND THIS LINE. Forecasts arrive from the backend
 * already expressed in days; ETAs decrement by `(tick - snapshotMarkTick)`
 * sim-days. If you find yourself reaching for `* 60` or `/ 60`, you've
 * misread the contract — go re-read this comment.
 */
export const TICKS_PER_DAY = 1;
export const SIM_DAY_COUNT = 3653;                     // 2015-01-01 .. 2024-12-31

export function tickToDay(tick: number): number {
  return ((tick % SIM_DAY_COUNT) + SIM_DAY_COUNT) % SIM_DAY_COUNT;
}


export interface TwinApiError extends Error {
  status: number;
}

function asTwinApiError(message: string, status: number): TwinApiError {
  const e = new Error(message) as TwinApiError;
  e.status = status;
  return e;
}

async function getJson<T>(path: string, params: Record<string, unknown>): Promise<T> {
  const qs = new URLSearchParams();
  for (const [k, v] of Object.entries(params)) {
    if (v === undefined || v === null) continue;
    qs.set(k, String(v));
  }
  const base = twinApiUrl(path);
  const finalUrl = qs.toString() ? `${base}?${qs.toString()}` : base;
  const res = await fetch(finalUrl, { method: "GET" });
  if (!res.ok) {
    let detail = res.statusText;
    try {
      const j = (await res.json()) as { detail?: unknown };
      if (typeof j.detail === "string") detail = j.detail;
    } catch {
      /* keep statusText */
    }
    throw asTwinApiError(detail || `HTTP ${res.status}`, res.status);
  }
  return (await res.json()) as T;
}


/* ------------------------------------------------------------ endpoints */

export async function listBackendCities(): Promise<string[]> {
  const j = await getJson<{ cities: string[] }>("/twin/cities", {});
  return j.cities;
}

export async function listPrinters(city: string): Promise<number[]> {
  const j = await getJson<{ city: string; printers: number[] }>(
    "/twin/printers", { city },
  );
  return j.printers;
}

export interface TwinStatePayload extends SystemSnapshot {
  forecasts: ComponentForecast[];
}

export async function fetchTwinState(args: {
  city: string;
  printerId: number;
  day: number;
  horizonDays?: number;
}): Promise<TwinStatePayload> {
  return getJson<TwinStatePayload>("/twin/state", {
    city: args.city,
    printer_id: args.printerId,
    day: args.day,
    horizon_d: args.horizonDays ?? 1,
  });
}

export async function fetchTimeline(args: {
  city: string;
  printerId: number;
  fields: string[];
  dayFrom?: number;
  dayTo?: number;
}): Promise<Record<string, number[] | string[] | boolean[]>> {
  return getJson<Record<string, number[] | string[] | boolean[]>>(
    "/twin/timeline",
    {
      city: args.city,
      printer_id: args.printerId,
      fields: args.fields.join(","),
      day_from: args.dayFrom,
      day_to: args.dayTo,
    },
  );
}

/**
 * Fetch the model-prediction timeline from `data/validation/fleet_2026_2035`.
 * Mirrors `fetchTimeline` shape but goes through the analytics-only
 * `/twin/predictions/timeline` endpoint and may include `rul_C{i}` columns.
 */
export async function fetchPredictionsTimeline(args: {
  city: string;
  printerId: number;
  fields: string[];
  dayFrom?: number;
  dayTo?: number;
}): Promise<Record<string, number[] | string[] | boolean[]>> {
  return getJson<Record<string, number[] | string[] | boolean[]>>(
    "/twin/predictions/timeline",
    {
      city: args.city,
      printer_id: args.printerId,
      fields: args.fields.join(","),
      day_from: args.dayFrom,
      day_to: args.dayTo,
    },
  );
}
