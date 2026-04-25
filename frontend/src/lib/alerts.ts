/**
 * Alert engine — fires on BOTH current-state thresholds and predictive thresholds.
 *
 * This is the dual-trigger system the brief calls out:
 *   1. CURRENT  -> a metric or healthIndex is breaching its operating band right now.
 *   2. PREDICTIVE -> the ML forecast says it will breach within the horizon.
 *
 * Predictive alerts are intentionally surfaced *before* current ones so the
 * operator gets time to act — that's the whole point of a Digital Co-Pilot.
 *
 * UNIT CONTRACT: every time field in this module is in DAYS. The backend hands
 * us `daysUntilCritical` / `daysUntilFailure`; the live ETA decrements by
 * `(tick - snapshotMarkTick)` since one tick equals one sim-day. No minute math.
 */

import type {
  Alert,
  AlertSeverity,
  ComponentForecast,
  ComponentState,
  SystemSnapshot,
} from "@/types/telemetry";
import { tickToHHMMSS } from "@/lib/mockData";

// Predictive thresholds in DAYS. Critical lead-time > failure lead-time
// because operators want a 5-day heads-up to schedule maintenance, but a
// 2-day "act now" siren when failure is imminent.
const FAILURE_ALERT_LEAD_DAYS = 2;
const CRITICAL_ALERT_LEAD_DAYS = 5;

export function deriveAlerts(snapshot: SystemSnapshot): Alert[] {
  const out: Alert[] = [];

  for (const c of snapshot.components) {
    out.push(...currentAlertsFor(c, snapshot));
  }

  for (const f of snapshot.forecasts) {
    const present = snapshot.components.find((c) => c.id === f.id);
    if (!present) continue;
    out.push(...predictiveAlertsFor(present, f, snapshot));
  }

  // Sort: CRITICAL > WARNING > INFO, then predictive > current within severity.
  return out.sort((a, b) => {
    const severityRank = sevRank(b.severity) - sevRank(a.severity);
    if (severityRank !== 0) return severityRank;
    if (a.kind !== b.kind) return a.kind === "predictive" ? -1 : 1;
    return (a.etaDays ?? 0) - (b.etaDays ?? 0);
  });
}

function currentAlertsFor(c: ComponentState, snap: SystemSnapshot): Alert[] {
  const out: Alert[] = [];

  // Health-based alert.
  if (c.status === "CRITICAL" || c.status === "FAILED") {
    out.push({
      id: `cur-health-${c.id}-${snap.tick}`,
      componentId: c.id,
      componentLabel: c.label,
      severity: c.status === "FAILED" ? "CRITICAL" : "CRITICAL",
      kind: "current",
      title: `${c.label} ${c.status.toLowerCase()}`,
      detail: `Health index at ${(c.healthIndex * 100).toFixed(0)}% — immediate inspection recommended.`,
      raisedAtTick: snap.tick,
      raisedAtIso: snap.timestamp,
    });
  } else if (c.status === "DEGRADED") {
    out.push({
      id: `cur-health-${c.id}-${snap.tick}`,
      componentId: c.id,
      componentLabel: c.label,
      severity: "WARNING",
      kind: "current",
      title: `${c.label} degraded`,
      detail: `Health index at ${(c.healthIndex * 100).toFixed(0)}% — schedule maintenance window.`,
      raisedAtTick: snap.tick,
      raisedAtIso: snap.timestamp,
    });
  }

  // Per-metric threshold alerts.
  for (const m of c.metrics) {
    const breach = breachKind(m.value, m);
    if (!breach) continue;
    out.push({
      id: `cur-metric-${c.id}-${m.key}-${snap.tick}`,
      componentId: c.id,
      componentLabel: c.label,
      severity: breach === "hard" ? "CRITICAL" : "WARNING",
      kind: "current",
      title: `${c.label} · ${m.label} out of band`,
      detail: `${m.label} at ${m.value}${m.unit} (${breach === "hard" ? "exceeds hard limit" : "exceeds soft limit"}).`,
      raisedAtTick: snap.tick,
      raisedAtIso: snap.timestamp,
      metricKey: m.key,
    });
  }

  return out;
}

function predictiveAlertsFor(
  present: ComponentState,
  f: ComponentForecast,
  snap: SystemSnapshot,
): Alert[] {
  const out: Alert[] = [];

  if (f.daysUntilFailure !== null && f.daysUntilFailure <= FAILURE_ALERT_LEAD_DAYS) {
    out.push({
      id: `pred-fail-${f.id}-${snap.tick}`,
      componentId: f.id,
      componentLabel: present.label,
      severity: "CRITICAL",
      kind: "predictive",
      title: `${present.label} forecast: failure in ~${formatEta(f.daysUntilFailure)}`,
      detail: f.rationale,
      raisedAtTick: snap.tick,
      raisedAtIso: snap.timestamp,
      etaDays: f.daysUntilFailure,
    });
  } else if (f.daysUntilCritical !== null && f.daysUntilCritical <= CRITICAL_ALERT_LEAD_DAYS) {
    out.push({
      id: `pred-crit-${f.id}-${snap.tick}`,
      componentId: f.id,
      componentLabel: present.label,
      severity: "WARNING",
      kind: "predictive",
      title: `${present.label} forecast: critical in ~${formatEta(f.daysUntilCritical)}`,
      detail: f.rationale,
      raisedAtTick: snap.tick,
      raisedAtIso: snap.timestamp,
      etaDays: f.daysUntilCritical,
    });
  }

  // Predicted metric breaches that aren't breaching yet — high signal value.
  for (const pm of f.predictedMetrics) {
    const presentMetric = present.metrics.find((m) => m.key === pm.key);
    if (!presentMetric) continue;
    const presentBreach = breachKind(presentMetric.value, presentMetric);
    const futureBreach = breachKind(pm.value, presentMetric);
    if (!presentBreach && futureBreach) {
      out.push({
        id: `pred-metric-${f.id}-${pm.key}-${snap.tick}`,
        componentId: f.id,
        componentLabel: present.label,
        severity: futureBreach === "hard" ? "CRITICAL" : "WARNING",
        kind: "predictive",
        title: `${present.label} · ${presentMetric.label} forecast breach`,
        detail: `Predicted to reach ${pm.value}${presentMetric.unit} within ${snap.forecastHorizonDays} day(s).`,
        raisedAtTick: snap.tick,
        raisedAtIso: snap.timestamp,
        etaDays: snap.forecastHorizonDays,
        metricKey: pm.key,
      });
    }
  }

  return out;
}

function breachKind(
  value: number,
  bands: { softMin?: number; softMax?: number; hardMin?: number; hardMax?: number },
): "soft" | "hard" | null {
  if (bands.hardMax !== undefined && value > bands.hardMax) return "hard";
  if (bands.hardMin !== undefined && value < bands.hardMin) return "hard";
  if (bands.softMax !== undefined && value > bands.softMax) return "soft";
  if (bands.softMin !== undefined && value < bands.softMin) return "soft";
  return null;
}

function sevRank(s: AlertSeverity): number {
  return s === "CRITICAL" ? 3 : s === "WARNING" ? 2 : 1;
}

/**
 * Smoothly interpolate a forecast ETA between snapshot fetches.
 *
 * The backend only refreshes a snapshot at sim-day boundaries (every
 * `TICKS_PER_DAY` store ticks), so the raw `daysUntilFailure` field stays
 * frozen for up to a sim day at a time. To keep the badge alive while the
 * day clock advances, we subtract simulated days elapsed since the
 * snapshot landed (one tick = one sim day, so it's just a subtraction).
 *
 * Returns:
 *   - `null` if the source ETA was already null (stable / past horizon)
 *   - `0` once the elapsed sim time has caught up with the original ETA
 *   - the remaining sim days otherwise
 */
export function liveDaysRemaining(
  rawDays: number | null,
  currentTick: number,
  snapshotMarkTick: number,
): number | null {
  if (rawDays === null) return null;
  const elapsedSimDays = Math.max(0, currentTick - snapshotMarkTick);
  return Math.max(0, rawDays - elapsedSimDays);
}

/**
 * Format a day-valued ETA for the operator UI. Picks an appropriately coarse
 * unit so a 730-day horizon doesn't render as "730d".
 */
export function formatEta(days: number): string {
  if (days < 1) {
    // sub-day ETAs land here when the printer is *very* close to failure;
    // show the fractional day directly so the operator sees the urgency
    // without inventing finer time units that aren't in our contract.
    return `${days.toFixed(2)}d`;
  }
  if (days < 14) {
    return `${days.toFixed(1)}d`;
  }
  if (days < 60) {
    return `${Math.round(days / 7)}w`;
  }
  if (days < 730) {
    return `${Math.round(days / 30)}mo`;
  }
  const years = days / 365;
  return `${years.toFixed(1)}y`;
}

/** Pick the single most urgent alert, used by the failure-ribbon. */
export function topAlert(alerts: Alert[]): Alert | null {
  return alerts[0] ?? null;
}

/** Cite an alert as a chat citation (timestamp + component). */
export function citationFromAlert(a: Alert) {
  return {
    componentId: a.componentId,
    componentLabel: a.componentLabel,
    metricKey: a.metricKey,
    tick: a.raisedAtTick,
    timestamp: tickToHHMMSS(a.raisedAtTick),
  };
}
