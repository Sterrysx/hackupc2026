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
 * Tick → simulator day. With `TICKS_PER_DAY = 8` each store tick is 3 sim
 * hours (= 180 sim minutes); the operator picks the wall-clock pace via the
 * speed multiplier in the transport bar (default 1× = real time).
 */
export const TICKS_PER_DAY = 8;
export const SIM_DAY_COUNT = 3653; // 2015-01-01 .. 2024-12-31
export const SIM_MINUTES_PER_TICK = 1440 / TICKS_PER_DAY; // 180 sim min / tick

export function tickToDay(tick: number): number {
  const day = Math.floor(tick / TICKS_PER_DAY);
  return ((day % SIM_DAY_COUNT) + SIM_DAY_COUNT) % SIM_DAY_COUNT;
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
  horizonMin?: number;
}): Promise<TwinStatePayload> {
  return getJson<TwinStatePayload>("/twin/state", {
    city: args.city,
    printer_id: args.printerId,
    day: args.day,
    horizon_min: args.horizonMin ?? 45,
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
