import type { ComponentId, SystemSnapshot } from "@/types/telemetry";

/** Map historian / backend `component` strings to UI `ComponentId` when unambiguous. */
const BACKEND_TO_ID: Record<string, ComponentId> = {
  recoater_blade: "recoater_blade",
  recoater_motor: "recoater_motor",
  nozzle_plate: "nozzle_plate",
  heating_element: "heating_element",
  thermal_resistor: "thermal_resistor",
  insulation_panel: "insulation_panel",
};

/**
 * 3D model groups two physical parts under one clickable assembly. The 2D
 * schematic exposes all six individually. The detail popup shows BOTH parts
 * of the assembly side-by-side regardless of which one was clicked, so the
 * mental model stays consistent across views (clicking either half of the
 * recoater opens "blade + motor", etc.).
 */
const GROUP_PAIRS: Array<readonly [ComponentId, ComponentId]> = [
  ["recoater_blade", "recoater_motor"],
  ["nozzle_plate", "thermal_resistor"],
  ["heating_element", "insulation_panel"],
];

/**
 * Returns the two ComponentIds that share a physical 3D assembly with the
 * given id, ordered with the *anchor* (the id that names the 3D group) first.
 * Result is always length 2.
 */
export function groupPairFor(id: ComponentId): readonly [ComponentId, ComponentId] {
  for (const pair of GROUP_PAIRS) {
    if (pair[0] === id || pair[1] === id) return pair;
  }
  // Defensive — every ComponentId belongs to exactly one pair, but if a
  // future addition skips this map we fall back to a self-pair so the popup
  // still renders something sensible.
  return [id, id];
}

/**
 * Resolves a backend component string to a live snapshot component for labels & citations.
 */
export function resolveComponentForAgent(
  raw: string,
  snap: SystemSnapshot,
  focusId: ComponentId | null,
): { id: ComponentId; label: string } {
  if (focusId) {
    const c = snap.components.find((x) => x.id === focusId);
    if (c) return { id: c.id, label: c.label };
  }
  const k = raw.trim().toLowerCase();
  const mapped = BACKEND_TO_ID[k];
  if (mapped) {
    const c = snap.components.find((x) => x.id === mapped);
    if (c) return { id: c.id, label: c.label };
  }
  const byPartial = snap.components.find(
    (c) => k.includes(c.id) || c.id.includes(k) || c.label.toLowerCase().includes(k),
  );
  if (byPartial) return { id: byPartial.id, label: byPartial.label };
  const fallback = snap.components[0];
  return { id: fallback.id, label: fallback.label };
}

export function tryParseAgentReport(
  data: unknown,
):
  | { ok: true; report: import("@/lib/agentApi").AgentResponse }
  | { ok: false } {
  if (!data || typeof data !== "object") return { ok: false };
  const o = data as Record<string, unknown>;
  if (typeof o.grounded_text !== "string") return { ok: false };
  const traceRaw = o.reasoning_trace;
  const reasoning_trace: import("@/lib/agentApi").ReasoningStep[] = Array.isArray(traceRaw)
    ? traceRaw
        .filter(
          (s): s is { kind: string; label: string; content: string } =>
            !!s && typeof s === "object" &&
            typeof (s as { kind?: unknown }).kind === "string" &&
            typeof (s as { label?: unknown }).label === "string" &&
            typeof (s as { content?: unknown }).content === "string",
        )
        .map((s) => ({ kind: s.kind, label: s.label, content: s.content }))
    : [];
  return {
    ok: true,
    report: {
      grounded_text: o.grounded_text,
      evidence_citation: typeof o.evidence_citation === "string" ? o.evidence_citation : "",
      severity_indicator: typeof o.severity_indicator === "string" ? o.severity_indicator : "INFO",
      recommended_actions: Array.isArray(o.recommended_actions)
        ? (o.recommended_actions as string[]).filter((x) => typeof x === "string")
        : [],
      priority_level: typeof o.priority_level === "string" ? o.priority_level : "LOW",
      reasoning_trace,
    },
  };
}
