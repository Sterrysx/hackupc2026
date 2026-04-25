/**
 * Telemetry data contract.
 *
 * These types mirror the pydantic schemas the backend team will publish.
 * When their FastAPI is up, regenerate from the OpenAPI schema and replace
 * the contents of this file — every UI consumer imports from here, so the
 * swap is mechanical.
 */

export type Subsystem = "recoating" | "printhead" | "thermal";

export type ComponentId =
  | "recoater_blade"
  | "recoater_motor"
  | "nozzle_plate"
  | "thermal_resistor"
  | "heating_element"
  | "insulation_panel";

export type OperationalStatus =
  | "FUNCTIONAL"
  | "DEGRADED"
  | "CRITICAL"
  | "FAILED";

export type AlertSeverity = "INFO" | "WARNING" | "CRITICAL";

/** A single physical metric tracked on a component (e.g. temperature, wear). */
export interface ComponentMetric {
  key: string;
  label: string;
  value: number;
  unit: string;
  /** Operating range — anything outside the soft band is "DEGRADED". */
  softMin?: number;
  softMax?: number;
  /** Hard band — outside this the component is at risk of failure. */
  hardMin?: number;
  hardMax?: number;
}

/** Snapshot of a single component at a single instant. */
export interface ComponentState {
  id: ComponentId;
  label: string;
  subsystem: Subsystem;
  /** Normalized 0..1 — fraction of remaining life. */
  healthIndex: number;
  status: OperationalStatus;
  metrics: ComponentMetric[];
  /** Convenience: the most-stressed metric, used as the tile's headline. */
  primaryMetricKey: string;
}

/** Environmental & operational drivers that feed the Phase 1 engine. */
export interface DriverVector {
  ambientTempC: number;
  humidityPct: number;
  contaminationPct: number;
  loadPct: number;
  maintenanceCoeff: number;
}

/** A predictive forecast for a single component. */
export interface ComponentForecast {
  id: ComponentId;
  /** Predicted health index N minutes from now (matches `forecastHorizonMin`). */
  predictedHealthIndex: number;
  predictedStatus: OperationalStatus;
  /** Predicted values for the same metrics (same `key`s). */
  predictedMetrics: { key: string; value: number }[];
  /** Estimated minutes until status crosses into CRITICAL. null = stable. */
  minutesUntilCritical: number | null;
  /** Estimated minutes until status reaches FAILED. null = not predicted to fail. */
  minutesUntilFailure: number | null;
  /** Plain-language root cause from the ML model. */
  rationale: string;
  /** 0..1 — how confident the predictor is. */
  confidence: number;
}

export interface SystemSnapshot {
  /** ISO timestamp of when this snapshot was generated. */
  timestamp: string;
  /** Monotonic tick count from the simulator (useful for citations). */
  tick: number;
  /** Drivers at this instant. */
  drivers: DriverVector;
  /** Per-component current state. */
  components: ComponentState[];
  /** Per-component predictive forecast. */
  forecasts: ComponentForecast[];
  /** Minutes the prediction looks ahead (e.g. 45). */
  forecastHorizonMin: number;
}

/** A surfaced alert (current OR predictive). */
export interface Alert {
  id: string;
  componentId: ComponentId;
  componentLabel: string;
  severity: AlertSeverity;
  /** "current" = threshold breached now; "predictive" = forecast says it will. */
  kind: "current" | "predictive";
  title: string;
  detail: string;
  /** Tick at which the alert was raised — used for chat citations. */
  raisedAtTick: number;
  raisedAtIso: string;
  /** Only set for predictive alerts: minutes until the breach happens. */
  etaMinutes?: number;
  /** Optional: which metric caused the breach. */
  metricKey?: string;
}

/**
 * RAG response from the chat agent. Every assistant message must cite at least
 * one telemetry point so the response is verifiable per the challenge brief.
 */
export interface RagCitation {
  componentId: ComponentId;
  componentLabel: string;
  metricKey?: string;
  /** Tick the cited datapoint comes from. */
  tick: number;
  /** Human-readable timestamp like "14:05:02". */
  timestamp: string;
}

/** One step in the backend LangGraph / tool trace (`POST /agent/query` → `reasoning_trace`). */
export interface AgentReasoningStep {
  kind: string;
  label: string;
  content: string;
}

export interface ChatMessage {
  id: string;
  role: "user" | "assistant" | "system";
  text: string;
  citations?: RagCitation[];
  severity?: AlertSeverity;
  /** LangGraph + tool activity when the reply comes from the real agent API. */
  reasoningTrace?: AgentReasoningStep[];
  /** Wall-clock time the message was created (for UI display). */
  createdAt: string;
}
