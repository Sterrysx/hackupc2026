/**
 * Mock data service — simulates what the backend / ML / RAG teams will eventually send.
 *
 * Design notes:
 *  - Deterministic per `tick` so screenshots & demos are repeatable when needed.
 *  - **One tick = one simulated day** — same unit as the real backend. Wear
 *    curves below were calibrated for the legacy "1 tick = 1 minute" demo,
 *    so over 365 ticks they barely degrade; that's fine because the demo
 *    runs against the real backend and only falls through here when offline.
 *  - Each component models a different decay primitive (exponential, fatigue,
 *    Weibull-ish, drift) so the dashboard tells visibly different stories.
 *
 * When the real backend is up, replace every public function in this file with
 * a `fetch()` call to the FastAPI endpoint that returns the same shape.
 */

import type {
  ComponentForecast,
  ComponentId,
  ComponentMetric,
  ComponentState,
  DriverVector,
  OperationalStatus,
  Subsystem,
  SystemSnapshot,
} from "@/types/telemetry";

const FORECAST_HORIZON_DAYS = 1;

/* ─── Deterministic PRNG (mulberry32) ──────────────────────────────────── */

function rng(seed: number): () => number {
  let a = seed >>> 0;
  return () => {
    a = (a + 0x6d2b79f5) >>> 0;
    let t = a;
    t = Math.imul(t ^ (t >>> 15), t | 1);
    t ^= t + Math.imul(t ^ (t >>> 7), t | 61);
    return ((t ^ (t >>> 14)) >>> 0) / 4294967296;
  };
}

/* ─── Drivers — the environmental & operational vectors ────────────────── */

export function driversAtTick(tick: number): DriverVector {
  const r = rng(tick * 9301 + 49297);
  // Slow sinusoidal drift + bounded noise — feels alive, never wild.
  const ambient = 24 + 3 * Math.sin(tick / 180) + (r() - 0.5) * 1.2;
  const humidity = 38 + 6 * Math.sin(tick / 220 + 1) + (r() - 0.5) * 3;
  // Contamination accumulates slowly and dips after maintenance pulses.
  const contamination = clamp01(
    0.05 + tick / 4200 + 0.04 * Math.sin(tick / 95) + (r() - 0.5) * 0.03 -
      maintenancePulse(tick) * 0.4,
  );
  // Load: heavier during simulated "production hours".
  const hour = (tick / 60) % 24;
  const productionShift = hour > 6 && hour < 22 ? 0.78 : 0.22;
  const load = clamp01(productionShift + (r() - 0.5) * 0.08);
  // Maintenance coefficient stays high but slowly decays between pulses.
  const maintenance = clamp01(0.95 - (tick % 1440) / 4800 + maintenancePulse(tick));

  return {
    ambientTempC: round1(ambient),
    humidityPct: round1(humidity),
    contaminationPct: round1(contamination * 100),
    loadPct: round1(load * 100),
    maintenanceCoeff: round2(maintenance),
  };
}

function maintenancePulse(tick: number): number {
  // Brief recovery pulses every ~1440 ticks (24h).
  const inCycle = tick % 1440;
  return inCycle < 30 ? 0.3 * (1 - inCycle / 30) : 0;
}

/* ─── Component definitions & degradation models ───────────────────────── */

interface ComponentSpec {
  id: ComponentId;
  label: string;
  subsystem: Subsystem;
  primaryMetricKey: string;
  /** Returns a snapshot for this component at `tick`. */
  build: (tick: number, drivers: DriverVector) => ComponentState;
}

/**
 * Recoater Roller / Blade — abrasive wear accelerated by contamination.
 * Wear is monotonically increasing; thickness drops from 1.20mm to ~0.60mm.
 */
function buildBlade(tick: number, drivers: DriverVector): ComponentState {
  const wearRate =
    0.00018 *
    (1 + drivers.contaminationPct / 60) *
    (1 + drivers.loadPct / 240) *
    (2 - drivers.maintenanceCoeff);
  const wear = clamp01(1 - Math.exp(-wearRate * tick));
  const thickness = round2(1.2 - wear * 0.6);
  const surfaceRoughness = round2(0.4 + wear * 2.8);
  const passCount = Math.floor(tick * 1.6);

  const health = clamp01(1 - wear);
  const metrics: ComponentMetric[] = [
    {
      key: "thickness",
      label: "Roller blade thickness",
      value: thickness,
      unit: "mm",
      softMin: 0.85,
      hardMin: 0.7,
    },
    {
      key: "roughness",
      label: "Powder layer roughness",
      value: surfaceRoughness,
      unit: "µm Ra",
      softMax: 2.2,
      hardMax: 2.8,
    },
    {
      key: "passes",
      label: "Recoat passes",
      value: passCount,
      unit: "",
    },
  ];

  return {
    id: "recoater_blade",
    label: "Recoater Roller / Blade",
    subsystem: "recoating",
    healthIndex: round2(health),
    status: statusFromHealth(health),
    metrics,
    primaryMetricKey: "thickness",
  };
}

/**
 * Recoater Drive Motor — mechanical fatigue (Weibull-flavoured).
 */
function buildMotor(tick: number, drivers: DriverVector): ComponentState {
  const beta = 1.4;
  const eta = 18000 * (2 - drivers.loadPct / 100);
  const cdf = 1 - Math.exp(-Math.pow(tick / eta, beta));
  const fatigue = clamp01(cdf);
  const tempC = round1(38 + drivers.loadPct * 0.18 + fatigue * 14);
  const vibration = round2(0.6 + fatigue * 2.4 + (drivers.loadPct / 100) * 0.4);
  const current = round2(2.1 + fatigue * 1.8);

  const health = clamp01(1 - fatigue);
  const metrics: ComponentMetric[] = [
    {
      key: "temperature",
      label: "Bearing temp",
      value: tempC,
      unit: "°C",
      softMax: 62,
      hardMax: 75,
    },
    {
      key: "vibration",
      label: "Vibration RMS",
      value: vibration,
      unit: "mm/s",
      softMax: 2.2,
      hardMax: 3.0,
    },
    {
      key: "current",
      label: "Drive current",
      value: current,
      unit: "A",
      softMax: 3.6,
      hardMax: 4.2,
    },
  ];

  return {
    id: "recoater_motor",
    label: "Recoater Drive Motor",
    subsystem: "recoating",
    healthIndex: round2(health),
    status: statusFromHealth(health),
    metrics,
    primaryMetricKey: "vibration",
  };
}

/**
 * Printhead Carriage / Firing Array — clogging accelerated when temperature
 * wanders out of band. The "nozzle plate" id is preserved for store/API
 * stability but the operator-facing label uses the canonical HP terminology.
 */
function buildNozzle(tick: number, drivers: DriverVector): ComponentState {
  const idealTemp = 235;
  const tempC =
    idealTemp +
    (drivers.ambientTempC - 24) * 0.6 +
    Math.sin(tick / 110) * 4 +
    (drivers.loadPct / 100) * 8;
  const tempStress = Math.abs(tempC - idealTemp) / 25;
  const clogRate = 0.00012 * (1 + tempStress * 2.4) * (1 + drivers.contaminationPct / 50);
  const clogging = clamp01(1 - Math.exp(-clogRate * tick));
  const activeNozzles = Math.max(180, Math.round(256 * (1 - clogging * 0.32)));
  const dropletVariance = round2(1.4 + clogging * 4.8);

  const health = clamp01(1 - clogging);
  const metrics: ComponentMetric[] = [
    {
      key: "temperature",
      label: "Carriage temperature",
      value: round1(tempC),
      unit: "°C",
      softMin: 220,
      softMax: 250,
      hardMin: 205,
      hardMax: 260,
    },
    {
      key: "active_nozzles",
      label: "Active nozzles",
      value: activeNozzles,
      unit: "/256",
      softMin: 230,
      hardMin: 200,
    },
    {
      key: "droplet_variance",
      label: "Binder droplet variance",
      value: dropletVariance,
      unit: "%",
      softMax: 4.0,
      hardMax: 5.5,
    },
  ];

  return {
    id: "nozzle_plate",
    label: "Printhead Carriage",
    subsystem: "printhead",
    healthIndex: round2(health),
    status: statusFromHealth(health),
    metrics,
    primaryMetricKey: "temperature",
  };
}

/**
 * Firing Array (thermal firing resistors) — electrical fatigue from cycling.
 */
function buildResistor(tick: number, drivers: DriverVector): ComponentState {
  const cycles = tick * 28;
  const fatigue = clamp01(1 - Math.exp(-cycles / 720000));
  const resistance = round2(48.5 + fatigue * 4.2 + (drivers.ambientTempC - 24) * 0.06);
  const efficiency = clamp01(1 - fatigue * 0.18);
  const drawWatts = round1(420 / efficiency + (drivers.loadPct / 100) * 60);

  const health = clamp01(1 - fatigue);
  const metrics: ComponentMetric[] = [
    {
      key: "resistance",
      label: "Resistance",
      value: resistance,
      unit: "Ω",
      softMax: 51.5,
      hardMax: 53,
    },
    {
      key: "efficiency",
      label: "Efficiency",
      value: round2(efficiency * 100),
      unit: "%",
      softMin: 88,
      hardMin: 82,
    },
    {
      key: "power",
      label: "Power draw",
      value: drawWatts,
      unit: "W",
      softMax: 520,
      hardMax: 580,
    },
  ];

  return {
    id: "thermal_resistor",
    label: "Firing Array",
    subsystem: "printhead",
    healthIndex: round2(health),
    status: statusFromHealth(health),
    metrics,
    primaryMetricKey: "resistance",
  };
}

/**
 * Build Unit / Powder Bed — heater element of the platform that lowers as
 * each layer is fused. Electrical degradation accelerated by insulation loss.
 */
function buildHeater(tick: number, drivers: DriverVector): ComponentState {
  // Insulation degrades a touch with humidity → feedback loop on heater wear.
  const insulationDegradation = clamp01(0.05 + tick / 18000 + drivers.humidityPct / 1500);
  const wearRate = 0.00009 * (1 + insulationDegradation * 1.6) * (1 + drivers.loadPct / 200);
  const wear = clamp01(1 - Math.exp(-wearRate * tick));
  const setpointC = 1180;
  const actualC = round1(setpointC - wear * 24 + Math.sin(tick / 70) * 2);
  const drawAmps = round2(11.5 + wear * 4.1);

  const health = clamp01(1 - wear);
  const metrics: ComponentMetric[] = [
    {
      key: "build_temp",
      label: "Powder bed temp",
      value: actualC,
      unit: "°C",
      softMin: 1160,
      hardMin: 1140,
    },
    {
      key: "current",
      label: "Heater current",
      value: drawAmps,
      unit: "A",
      softMax: 14.5,
      hardMax: 16,
    },
    {
      key: "setpoint_delta",
      label: "Setpoint Δ",
      value: round1(actualC - setpointC),
      unit: "°C",
      softMin: -18,
      hardMin: -32,
    },
  ];

  return {
    id: "heating_element",
    label: "Build Unit Heater",
    subsystem: "thermal",
    healthIndex: round2(health),
    status: statusFromHealth(health),
    metrics,
    primaryMetricKey: "build_temp",
  };
}

/**
 * Build Unit Insulation — slow degradation amplified by humidity (cascading
 * effect on the bed heater).
 */
function buildInsulation(tick: number, drivers: DriverVector): ComponentState {
  const wear = clamp01(tick / 22000 + (drivers.humidityPct / 100) * 0.1);
  const conductivity = round2(0.045 + wear * 0.04);
  const heatLossPct = round1(2.5 + wear * 6);

  const health = clamp01(1 - wear);
  const metrics: ComponentMetric[] = [
    {
      key: "conductivity",
      label: "Thermal conductivity",
      value: conductivity,
      unit: "W/m·K",
      softMax: 0.07,
      hardMax: 0.085,
    },
    {
      key: "heat_loss",
      label: "Heat loss",
      value: heatLossPct,
      unit: "%",
      softMax: 6.5,
      hardMax: 8.5,
    },
  ];

  return {
    id: "insulation_panel",
    label: "Build Unit Insulation",
    subsystem: "thermal",
    healthIndex: round2(health),
    status: statusFromHealth(health),
    metrics,
    primaryMetricKey: "heat_loss",
  };
}

const COMPONENT_SPECS: ComponentSpec[] = [
  { id: "recoater_blade",   label: "Recoater Roller / Blade", subsystem: "recoating", primaryMetricKey: "thickness", build: buildBlade },
  { id: "recoater_motor",   label: "Recoater Drive Motor",    subsystem: "recoating", primaryMetricKey: "vibration", build: buildMotor },
  { id: "nozzle_plate",     label: "Printhead Carriage",      subsystem: "printhead", primaryMetricKey: "temperature", build: buildNozzle },
  { id: "thermal_resistor", label: "Firing Array",            subsystem: "printhead", primaryMetricKey: "resistance", build: buildResistor },
  { id: "heating_element",  label: "Build Unit Heater",       subsystem: "thermal",   primaryMetricKey: "build_temp", build: buildHeater },
  { id: "insulation_panel", label: "Build Unit Insulation",   subsystem: "thermal",   primaryMetricKey: "heat_loss", build: buildInsulation },
];

/* ─── Forecasting ──────────────────────────────────────────────────────── */

function forecastFor(spec: ComponentSpec, tick: number): ComponentForecast {
  const futureTick = tick + FORECAST_HORIZON_DAYS;
  const futureDrivers = driversAtTick(futureTick);
  const future = spec.build(futureTick, futureDrivers);
  const present = spec.build(tick, driversAtTick(tick));

  const daysUntilCritical = projectDaysUntil(spec, tick, 0.35);
  const daysUntilFailure = projectDaysUntil(spec, tick, 0.12);

  return {
    id: spec.id,
    predictedHealthIndex: future.healthIndex,
    predictedStatus: future.status,
    predictedMetrics: future.metrics.map((m) => ({ key: m.key, value: m.value })),
    daysUntilCritical,
    daysUntilFailure,
    rationale: rationaleFor(spec, present, future, futureDrivers),
    confidence: round2(0.78 + Math.min(0.18, (1 - future.healthIndex) * 0.25)),
  };
}

function projectDaysUntil(
  spec: ComponentSpec,
  tick: number,
  threshold: number,
): number | null {
  // Sparse search across the operational window (tick = day), then binary
  // refinement to 1-day resolution. The wide horizon (~6 months) covers the
  // slow mock curves; live backend forecasts come straight from the API.
  const horizons = [1, 2, 3, 5, 7, 14, 30, 60, 120, 180];
  let lo = 0;
  let hi: number | null = null;
  for (const dt of horizons) {
    const future = spec.build(tick + dt, driversAtTick(tick + dt));
    if (future.healthIndex <= threshold) {
      hi = dt;
      break;
    }
    lo = dt;
  }
  if (hi === null) return null;
  while (hi - lo > 1) {
    const mid = Math.floor((lo + hi) / 2);
    const future = spec.build(tick + mid, driversAtTick(tick + mid));
    if (future.healthIndex <= threshold) hi = mid;
    else lo = mid;
  }
  return hi;
}

function rationaleFor(
  spec: ComponentSpec,
  _present: ComponentState,
  future: ComponentState,
  futureDrivers: DriverVector,
): string {
  switch (spec.id) {
    case "recoater_blade":
      return `Abrasive wear projected to drop blade thickness by ${(0.6 - (future.metrics[0].value - 0.6)).toFixed(2)}mm under current contamination (${futureDrivers.contaminationPct.toFixed(1)}%).`;
    case "recoater_motor":
      return `Bearing temperature climbing with ${futureDrivers.loadPct.toFixed(0)}% load — Weibull failure curve crossing threshold.`;
    case "nozzle_plate":
      return `Thermal stress + powder contamination accelerating clog probability. Active nozzles forecast: ${future.metrics[1].value}/256.`;
    case "thermal_resistor":
      return `Cumulative firing cycles increasing resistance by ${(future.metrics[0].value - 48.5).toFixed(2)}Ω; efficiency falling.`;
    case "heating_element":
      return `Insulation loss creating a feedback loop — element working harder to hit setpoint, driving accelerated wear.`;
    case "insulation_panel":
      return `Humidity (${futureDrivers.humidityPct.toFixed(0)}%) raising thermal conductivity; expect cascade into heating element wear.`;
  }
}

/* ─── Public API — what the UI consumes ────────────────────────────────── */

export function snapshotAtTick(tick: number): SystemSnapshot {
  const drivers = driversAtTick(tick);
  const components = COMPONENT_SPECS.map((spec) => spec.build(tick, drivers));
  const forecasts = COMPONENT_SPECS.map((spec) => forecastFor(spec, tick));
  return {
    timestamp: tickToIso(tick),
    tick,
    drivers,
    components,
    forecasts,
    forecastHorizonDays: FORECAST_HORIZON_DAYS,
  };
}

/** Build a series of (tick, healthIndex) for a given component — used for sparklines. */
export function healthHistory(
  componentId: ComponentId,
  endTick: number,
  windowSize = 60,
  stride = 1,
): { tick: number; healthIndex: number; predictedHealthIndex: number }[] {
  const spec = COMPONENT_SPECS.find((s) => s.id === componentId);
  if (!spec) return [];
  const start = Math.max(0, endTick - windowSize * stride);
  const out: { tick: number; healthIndex: number; predictedHealthIndex: number }[] = [];
  for (let t = start; t <= endTick; t += stride) {
    const present = spec.build(t, driversAtTick(t));
    const future = spec.build(t + FORECAST_HORIZON_DAYS, driversAtTick(t + FORECAST_HORIZON_DAYS));
    out.push({
      tick: t,
      healthIndex: present.healthIndex,
      predictedHealthIndex: future.healthIndex,
    });
  }
  return out;
}

/* ─── Helpers ──────────────────────────────────────────────────────────── */

function statusFromHealth(h: number): OperationalStatus {
  if (h <= 0.0) return "FAILED";
  if (h <= 0.20) return "CRITICAL";
  if (h <= 0.50) return "DEGRADED";
  return "FUNCTIONAL";
}

function clamp01(v: number): number {
  return Math.max(0, Math.min(1, v));
}

function round1(v: number): number {
  return Math.round(v * 10) / 10;
}

function round2(v: number): number {
  return Math.round(v * 100) / 100;
}

/**
 * Map a tick (1 sim-day) to an ISO wall-clock timestamp anchored at session
 * start. The wall-clock spacing is arbitrary — we use 1 minute per tick so the
 * timeline ticker on screen looks alive — but the *semantic* unit of a tick
 * remains one simulated day.
 */
const SESSION_START = Date.now();
const WALL_CLOCK_MS_PER_TICK = 60_000;
export function tickToIso(tick: number): string {
  return new Date(SESSION_START + tick * WALL_CLOCK_MS_PER_TICK).toISOString();
}

export function tickToHHMMSS(tick: number): string {
  const d = new Date(SESSION_START + tick * WALL_CLOCK_MS_PER_TICK);
  return d.toTimeString().slice(0, 8);
}

export const ALL_COMPONENT_IDS = COMPONENT_SPECS.map((s) => s.id);
export const FORECAST_HORIZON = FORECAST_HORIZON_DAYS;
