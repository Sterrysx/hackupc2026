/**
 * Mock RAG agent — simulates the chatbot teammates are building.
 *
 * Critical principle (from Phase 3 brief):
 *   The AI must reason ONLY over the data we provide it.
 *   Every response carries explicit citations to specific telemetry points.
 *
 * This mock honours that principle: every reply pulls real values from the
 * current SystemSnapshot and tags them as citations the UI renders inline.
 */

import { formatEta } from "@/lib/alerts";
import type { AgentResponse } from "@/lib/agentApi";
import type {
  AgentReasoningStep,
  AlertSeverity,
  ChatMessage,
  ComponentId,
  ComponentState,
  RagCitation,
  SystemSnapshot,
} from "@/types/telemetry";
import { tickToHHMMSS } from "@/lib/mockData";

interface RagReply {
  text: string;
  citations: RagCitation[];
  severity: AlertSeverity;
}

export function answer(prompt: string, snap: SystemSnapshot): RagReply {
  const q = prompt.toLowerCase().trim();

  // Greetings / system identity.
  if (/^(hi|hello|hey|yo|sup)\b/.test(q)) {
    return {
      text: "Hi — I'm Aether, the digital co-pilot for this Metal Jet S100. Ask me about any component, the live alerts, or what the next 24 hours look like.",
      citations: [],
      severity: "INFO",
    };
  }

  // Per-component lookups.
  for (const c of snap.components) {
    if (matchesComponent(q, c)) {
      return describeComponent(c, snap);
    }
  }

  // Subsystem lookups.
  if (q.includes("recoat") || q.includes("blade")) {
    return describeSubsystem("recoating", snap);
  }
  if (q.includes("printhead") || q.includes("nozzle")) {
    return describeSubsystem("printhead", snap);
  }
  if (q.includes("therm") || q.includes("heat") || q.includes("temperature")) {
    return describeSubsystem("thermal", snap);
  }

  // Predictive intent.
  if (q.includes("predict") || q.includes("forecast") || q.includes("future") || q.includes("next")) {
    return describeForecast(snap);
  }

  // Failure / risk intent.
  if (q.includes("fail") || q.includes("risk") || q.includes("worst") || q.includes("urgent") || q.includes("critical")) {
    return describeWorst(snap);
  }

  // Maintenance recommendation.
  if (q.includes("maintenance") || q.includes("service") || q.includes("when") || q.includes("should")) {
    return describeMaintenance(snap);
  }

  // Driver inquiry.
  if (q.includes("driver") || q.includes("environment") || q.includes("humidity") || q.includes("contamination") || q.includes("load")) {
    return describeDrivers(snap);
  }

  // Default — overall status.
  return describeOverall(snap);
}

/* ─── Reply builders ───────────────────────────────────────────────────── */

function describeComponent(c: ComponentState, snap: SystemSnapshot): RagReply {
  const f = snap.forecasts.find((x) => x.id === c.id);
  const primary = c.metrics.find((m) => m.key === c.primaryMetricKey) ?? c.metrics[0];
  const citations: RagCitation[] = [
    {
      componentId: c.id,
      componentLabel: c.label,
      metricKey: primary.key,
      tick: snap.tick,
      timestamp: tickToHHMMSS(snap.tick),
    },
  ];

  let text =
    `${c.label} is ${c.status.toLowerCase()} — health index ${(c.healthIndex * 100).toFixed(0)}%. ` +
    `${primary.label} reads ${primary.value}${primary.unit}.`;

  let severity: AlertSeverity = sevFromStatus(c.status);

  // Trending-to-critical lookahead window: 5 sim-days. Mirrors the alert
  // engine's CRITICAL_ALERT_LEAD_DAYS so the chatbot and badges agree.
  if (f && f.daysUntilCritical !== null && f.daysUntilCritical < 5) {
    text += ` Forecast: trending toward CRITICAL in ~${formatEta(f.daysUntilCritical)} (${f.rationale})`;
    citations.push({
      componentId: c.id,
      componentLabel: c.label,
      tick: snap.tick + f.daysUntilCritical,
      timestamp: tickToHHMMSS(snap.tick + f.daysUntilCritical),
    });
    severity = "WARNING";
  }

  return { text, citations, severity };
}

function describeSubsystem(subsystem: ComponentState["subsystem"], snap: SystemSnapshot): RagReply {
  const components = snap.components.filter((c) => c.subsystem === subsystem);
  const worst = [...components].sort((a, b) => a.healthIndex - b.healthIndex)[0];
  const lines = components.map(
    (c) => `${c.label}: ${c.status.toLowerCase()} (${(c.healthIndex * 100).toFixed(0)}%)`,
  );
  const citations: RagCitation[] = components.map((c) => ({
    componentId: c.id,
    componentLabel: c.label,
    tick: snap.tick,
    timestamp: tickToHHMMSS(snap.tick),
  }));
  return {
    text: `${pretty(subsystem)} subsystem: ${lines.join(" · ")}. Lowest-health component is ${worst.label}.`,
    citations,
    severity: sevFromStatus(worst.status),
  };
}

function describeForecast(snap: SystemSnapshot): RagReply {
  const ranked = [...snap.forecasts].sort((a, b) => {
    const am = a.daysUntilFailure ?? a.daysUntilCritical ?? 1e9;
    const bm = b.daysUntilFailure ?? b.daysUntilCritical ?? 1e9;
    return am - bm;
  });
  const top = ranked.slice(0, 3);
  const lines = top.map((f) => {
    const c = snap.components.find((x) => x.id === f.id)!;
    if (f.daysUntilFailure !== null) return `${c.label}: failure in ~${formatEta(f.daysUntilFailure)}`;
    if (f.daysUntilCritical !== null) return `${c.label}: critical in ~${formatEta(f.daysUntilCritical)}`;
    return `${c.label}: stable`;
  });
  const citations: RagCitation[] = top.map((f) => {
    const c = snap.components.find((x) => x.id === f.id)!;
    const horizon = f.daysUntilFailure ?? f.daysUntilCritical ?? snap.forecastHorizonDays;
    return {
      componentId: f.id,
      componentLabel: c.label,
      tick: snap.tick + horizon,
      timestamp: tickToHHMMSS(snap.tick + horizon),
    };
  });
  return {
    text: `Looking ${snap.forecastHorizonDays} day(s) ahead, three components warrant attention. ${lines.join(". ")}.`,
    citations,
    severity: top[0]?.daysUntilFailure !== null ? "CRITICAL" : "WARNING",
  };
}

function describeWorst(snap: SystemSnapshot): RagReply {
  const worst = [...snap.components].sort((a, b) => a.healthIndex - b.healthIndex)[0];
  return describeComponent(worst, snap);
}

function describeMaintenance(snap: SystemSnapshot): RagReply {
  // Look two weeks ahead for "schedule maintenance" candidates — long enough
  // that the operator has time to plan, short enough that we're not nagging
  // about month-out forecasts that the daily refresh will revise.
  const MAINT_LOOKAHEAD_DAYS = 14;
  const candidates = snap.components
    .map((c) => ({ c, f: snap.forecasts.find((f) => f.id === c.id)! }))
    .filter((x) => x.f.daysUntilCritical !== null && x.f.daysUntilCritical < MAINT_LOOKAHEAD_DAYS)
    .sort((a, b) => (a.f.daysUntilCritical ?? 1e9) - (b.f.daysUntilCritical ?? 1e9));

  if (candidates.length === 0) {
    return {
      text: `No maintenance is required right now — every component is FUNCTIONAL with no forecast breach in the next ${MAINT_LOOKAHEAD_DAYS} days.`,
      citations: snap.components.slice(0, 3).map((c) => ({
        componentId: c.id,
        componentLabel: c.label,
        tick: snap.tick,
        timestamp: tickToHHMMSS(snap.tick),
      })),
      severity: "INFO",
    };
  }

  const next = candidates[0];
  // Schedule the window a couple days *before* the forecast crossing so the
  // operator isn't doing surgery on a part that's already critical.
  const window = Math.max(0.5, (next.f.daysUntilCritical ?? 1) - 2);
  return {
    text: `Recommend scheduling a maintenance window in the next ${formatEta(window)} to address ${next.c.label}. ${next.f.rationale}`,
    citations: [
      {
        componentId: next.c.id,
        componentLabel: next.c.label,
        tick: snap.tick + (next.f.daysUntilCritical ?? 0),
        timestamp: tickToHHMMSS(snap.tick + (next.f.daysUntilCritical ?? 0)),
      },
    ],
    severity: "WARNING",
  };
}

function describeDrivers(snap: SystemSnapshot): RagReply {
  const d = snap.drivers;
  return {
    text: `Current drivers — ambient ${d.ambientTempC}°C · humidity ${d.humidityPct}% · contamination ${d.contaminationPct}% · load ${d.loadPct}% · maintenance ${d.maintenanceCoeff}.`,
    citations: [
      {
        componentId: snap.components[0].id,
        componentLabel: "Environment",
        tick: snap.tick,
        timestamp: tickToHHMMSS(snap.tick),
      },
    ],
    severity: "INFO",
  };
}

function describeOverall(snap: SystemSnapshot): RagReply {
  const failed = snap.components.filter((c) => c.status === "FAILED").length;
  const critical = snap.components.filter((c) => c.status === "CRITICAL").length;
  const degraded = snap.components.filter((c) => c.status === "DEGRADED").length;
  const ok = snap.components.length - failed - critical - degraded;

  const sev: AlertSeverity = failed || critical ? "CRITICAL" : degraded ? "WARNING" : "INFO";
  const text =
    `Printer overview: ${ok} functional · ${degraded} degraded · ${critical} critical · ${failed} failed. ` +
    `Average health ${(snap.components.reduce((a, c) => a + c.healthIndex, 0) / snap.components.length * 100).toFixed(0)}%.`;
  return {
    text,
    citations: snap.components.map((c) => ({
      componentId: c.id,
      componentLabel: c.label,
      tick: snap.tick,
      timestamp: tickToHHMMSS(snap.tick),
    })),
    severity: sev,
  };
}

/* ─── Helpers ──────────────────────────────────────────────────────────── */

function matchesComponent(q: string, c: ComponentState): boolean {
  const tokens = c.label.toLowerCase().split(/\W+/).filter(Boolean);
  return tokens.some((t) => t.length > 3 && q.includes(t));
}

function sevFromStatus(s: ComponentState["status"]): AlertSeverity {
  if (s === "FAILED" || s === "CRITICAL") return "CRITICAL";
  if (s === "DEGRADED") return "WARNING";
  return "INFO";
}

function pretty(subsystem: ComponentState["subsystem"]): string {
  switch (subsystem) {
    case "recoating": return "Recoater assembly";
    case "printhead": return "Printhead carriage";
    case "thermal":   return "Build unit";
  }
}

/** Build a fresh ChatMessage for an assistant reply. */
export function makeAssistantMessage(reply: RagReply): ChatMessage {
  return {
    id: `m-${Math.random().toString(36).slice(2, 10)}`,
    role: "assistant",
    text: reply.text,
    citations: reply.citations,
    severity: reply.severity,
    createdAt: new Date().toISOString(),
  };
}

function severityFromAgentIndicator(raw: string): AlertSeverity {
  const u = raw.toUpperCase();
  if (u === "CRITICAL" || u === "WARNING" || u === "INFO") return u;
  if (u.includes("CRIT")) return "CRITICAL";
  if (u.includes("WARN")) return "WARNING";
  return "INFO";
}

export interface AgentReportUiContext {
  /** Current tick for telemetry citation chip. */
  tick: number;
  /** Component to anchor the evidence row (operator focus or best match). */
  evidenceComponent: ComponentId;
  componentLabel: string;
}

function formatAgentResponseBody(r: AgentResponse): string {
  const lines = [r.grounded_text?.trim() || ""];
  if (r.evidence_citation?.trim()) {
    lines.push("", `Evidence: ${r.evidence_citation.trim()}`);
  }
  if (r.recommended_actions?.length) {
    lines.push("", "Recommended actions:", ...r.recommended_actions.map((a) => `• ${a}`));
  }
  if (r.priority_level?.trim()) {
    lines.push("", `Priority: ${r.priority_level.trim()}`);
  }
  const text = lines.join("\n").trim();
  return text || "No report generated.";
}

/** Assistant message from the real agent (`/agent/query` → `AgentResponse`). */
export function makeAssistantFromAgentReport(
  report: AgentResponse,
  ctx: AgentReportUiContext,
): ChatMessage {
  const sev = severityFromAgentIndicator(report.severity_indicator);
  const text = formatAgentResponseBody(report);
  const citations: RagCitation[] = [
    {
      componentId: ctx.evidenceComponent,
      componentLabel: ctx.componentLabel,
      tick: ctx.tick,
      timestamp: tickToHHMMSS(ctx.tick),
    },
  ];
  const steps: AgentReasoningStep[] = (report.reasoning_trace ?? []).map((s) => ({
    kind: s.kind,
    label: s.label,
    content: s.content,
  }));
  return {
    id: `m-${Math.random().toString(36).slice(2, 10)}`,
    role: "assistant",
    text,
    citations,
    severity: sev,
    reasoningTrace: steps.length > 0 ? steps : undefined,
    createdAt: new Date().toISOString(),
  };
}

/** Proactive watchdog or non-interactive push using the same shape as the graph output. */
export function makeWatchdogAssistantMessage(
  report: AgentResponse,
  componentLabel: string,
  tick: number,
  evidenceComponent: ComponentId,
  headline?: string,
): ChatMessage {
  const prefix = headline ? `${headline}\n\n` : "";
  const body = makeAssistantFromAgentReport(report, {
    tick,
    evidenceComponent,
    componentLabel,
  });
  return { ...body, text: `${prefix}${body.text}` };
}

export function makeUserMessage(text: string): ChatMessage {
  return {
    id: `m-${Math.random().toString(36).slice(2, 10)}`,
    role: "user",
    text,
    createdAt: new Date().toISOString(),
  };
}
