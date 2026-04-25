import { useCallback, useState } from "react";
import { motion } from "framer-motion";
import { ArrowLeft, Send, Sparkles } from "lucide-react";
import { useTwin } from "@/store/twin";
import { Badge, statusLabel, statusToTone } from "@/components/ui/Badge";
import { Button } from "@/components/ui/Button";
import { HealthRing } from "@/components/HealthRing";
import { AnimatedNumber } from "@/components/AnimatedNumber";
import { MicButton } from "@/components/floating/MicButton";
import { HealthTimelineChart } from "@/components/sidebar/HealthTimelineChart";
import { formatEta, liveMinutesRemaining } from "@/lib/alerts";
import { SIM_MINUTES_PER_TICK } from "@/lib/twinApi";
import type { ComponentId, ComponentMetric } from "@/types/telemetry";

const APPLE_EASE: [number, number, number, number] = [0.16, 1, 0.3, 1];

const containerVariants = {
  hidden: { opacity: 0 },
  visible: {
    opacity: 1,
    transition: { staggerChildren: 0.05, delayChildren: 0.05 },
  },
};

const itemVariants = {
  hidden: { opacity: 0, y: 10 },
  visible: { opacity: 1, y: 0, transition: { duration: 0.45, ease: APPLE_EASE } },
};

/**
 * Sidebar content shown while a component is selected from the schematic.
 *  - Back affordance at the top
 *  - Hero (name + status + ring with animated %)
 *  - Live metrics with number tickers
 *  - ML forecast with rationale + ETA badges
 *  - "Ask Aether about this" button
 */
export function ComponentFocus({ id }: { id: string }) {
  const snapshot = useTwin((s) => s.snapshot);
  const tick = useTwin((s) => s.tick);
  const snapshotMarkTick = useTwin((s) => s.snapshotMarkTick);
  const selectComponent = useTwin((s) => s.selectComponent);
  const sendUserMessage = useTwin((s) => s.sendUserMessage);
  const setChatOpen = useTwin((s) => s.setChatOpen);
  const isThinking = useTwin((s) => s.isThinking);

  const [draft, setDraft] = useState("");

  const c = snapshot.components.find((x) => x.id === id);
  const f = snapshot.forecasts.find((x) => x.id === id);
  if (!c || !f) return null;

  const tone = statusToTone(c.status);
  const onBack = () => selectComponent(null);

  const askContextual = (text: string) => {
    const trimmed = text.trim();
    if (!trimmed) return;
    setDraft("");
    setChatOpen(true);
    // sendUserMessage reads selectedComponentId from the store and tags the
    // payload with the focused component, so the agent answers about THIS part.
    sendUserMessage(trimmed);
  };

  // Voice input: append transcript to the contextual draft so the user can
  // review the question before submitting it to the agent.
  const handleTranscript = useCallback((text: string) => {
    setDraft((d) => {
      const t = text.trim();
      if (!t) return d;
      return d.trim() ? `${d.trim()} ${t}` : t;
    });
  }, []);

  return (
    <motion.div
      key={`focus-${id}`}
      variants={containerVariants}
      initial="hidden"
      animate="visible"
      exit={{ opacity: 0, transition: { duration: 0.18 } }}
      className="flex flex-col gap-8 px-6 py-7"
    >
      {/* Back */}
      <motion.div variants={itemVariants}>
        <button
          type="button"
          onClick={onBack}
          className="inline-flex items-center gap-1.5 -ml-1.5 px-2 py-1.5 rounded-full text-[12px] text-[var(--color-fg-muted)] hover:text-[var(--color-fg)] hover:bg-white/[0.06] transition-colors"
        >
          <ArrowLeft size={13} />
          Back to overview
        </button>
      </motion.div>

      {/* Hero */}
      <motion.section variants={itemVariants} className="flex items-start justify-between gap-4">
        <div className="min-w-0 flex-1">
          <p className="text-[10px] uppercase tracking-[0.20em] text-[var(--color-fg-faint)]">
            {prettySub(c.subsystem)}
          </p>
          <h2 className="mt-2 text-[22px] font-medium tracking-tight text-[var(--color-fg)] leading-tight">
            {c.label}
          </h2>
          <div className="mt-3">
            <Badge tone={tone} size="sm" withDot>
              {statusLabel(c.status)}
            </Badge>
          </div>
        </div>
        <HealthRing
          value={c.healthIndex}
          predicted={f.predictedHealthIndex}
          size={76}
          thickness={5}
          showValue
        />
      </motion.section>

      {/* Lifetime trace — only renders when live data is available. */}
      <motion.div variants={itemVariants}>
        <HealthTimelineChart id={c.id as ComponentId} />
      </motion.div>

      {/* Live metrics */}
      <motion.section variants={itemVariants}>
        <header className="flex items-baseline justify-between mb-3">
          <h3 className="text-[10px] uppercase tracking-[0.20em] text-[var(--color-fg-faint)]">
            Live metrics
          </h3>
          <span className="text-[10.5px] text-[var(--color-fg-faint)]">live</span>
        </header>
        <ul className="flex flex-col">
          {c.metrics.map((m, i) => (
            <MetricRow key={m.key} metric={m} predictedValue={f.predictedMetrics.find((p) => p.key === m.key)?.value} dividerAbove={i !== 0} />
          ))}
        </ul>
      </motion.section>

      {/* Forecast */}
      <motion.section variants={itemVariants}>
        <header className="flex items-baseline justify-between mb-3">
          <h3 className="text-[10px] uppercase tracking-[0.20em] text-[var(--color-fg-faint)]">
            Forecast · {snapshot.forecastHorizonMin} min
          </h3>
          <span className="text-[10.5px] text-[var(--color-fg-faint)] tabular-nums">
            <AnimatedNumber value={f.confidence * 100} format={(v) => `${Math.round(v)}% confidence`} />
          </span>
        </header>
        {(() => {
          // Tone the badge by *urgency*, not by mere presence of a forecast.
          // The backend already drops ETAs beyond the 30-day operational
          // horizon (see `Ai_Agent/forecast.py::_OPERATIONAL_HORIZON_MIN`),
          // so anything we get here is at least within planning range — but
          // we still need to distinguish "act in the next hour" from
          // "schedule maintenance next week".
          const FAILURE_HOT_MIN = 2 * 60;        // < 2h → CRITICAL red
          const FAILURE_SOON_MIN = 24 * 60;      // < 24h → WARN amber
          const CRITICAL_HOT_MIN = 8 * 60;       // < 8h → WARN amber
          // Smoothly interpolate ETA between snapshot fetches so the badge
          // counts down with simulated time instead of staying frozen for
          // a full sim-day (see `liveMinutesRemaining` in lib/alerts).
          const mF = liveMinutesRemaining(f.minutesUntilFailure, tick, snapshotMarkTick, SIM_MINUTES_PER_TICK);
          const mC = liveMinutesRemaining(f.minutesUntilCritical, tick, snapshotMarkTick, SIM_MINUTES_PER_TICK);
          const failureBadge = mF === null
            ? null
            : mF < FAILURE_HOT_MIN
              ? <Badge key="f" tone="crit" size="sm">Failure ~{formatEta(mF)}</Badge>
              : mF < FAILURE_SOON_MIN
                ? <Badge key="f" tone="warn" size="sm">Failure ~{formatEta(mF)}</Badge>
                : <Badge key="f" tone="neutral" size="sm">Failure ~{formatEta(mF)}</Badge>;
          const criticalBadge = mC === null
            ? null
            : mC < CRITICAL_HOT_MIN
              ? <Badge key="c" tone="warn" size="sm">Critical ~{formatEta(mC)}</Badge>
              : <Badge key="c" tone="neutral" size="sm">Critical ~{formatEta(mC)}</Badge>;
          if (failureBadge === null && criticalBadge === null) {
            return (
              <div className="flex flex-wrap gap-1.5 mb-3">
                <Badge tone="ok" size="sm">Stable · no failure in 30 d</Badge>
              </div>
            );
          }
          return (
            <div className="flex flex-wrap gap-1.5 mb-3">
              {failureBadge}
              {criticalBadge}
            </div>
          );
        })()}
        <p className="text-[12.5px] text-[var(--color-fg-muted)] leading-relaxed">
          {f.rationale}
        </p>
      </motion.section>

      {/* Contextual chat composer — opens Spotlight overlay with this part already in context. */}
      <motion.div variants={itemVariants} className="flex flex-col gap-2">
        <form
          className="flex items-center gap-1.5 bg-white/[0.05] hover:bg-white/[0.07] focus-within:bg-white/[0.10] rounded-full pl-3.5 pr-1.5 py-1.5 transition-colors"
          onSubmit={(e) => {
            e.preventDefault();
            askContextual(draft);
          }}
        >
          <Sparkles size={12} className="text-[var(--color-accent)] flex-shrink-0" />
          <input
            value={draft}
            onChange={(e) => setDraft(e.target.value)}
            placeholder={`Ask Aether about the ${c.label}…`}
            className="flex-1 bg-transparent outline-none text-[12.5px] text-[var(--color-fg)] placeholder:text-[var(--color-fg-faint)]"
          />
          <MicButton size="sm" onTranscript={handleTranscript} hint={`Speak about the ${c.label}…`} />
          <Button
            type="submit"
            variant="primary"
            size="icon"
            className="h-7 w-7"
            disabled={!draft.trim() || isThinking}
            title="Send (opens Aether)"
          >
            <Send size={11} />
          </Button>
        </form>
      </motion.div>
    </motion.div>
  );
}

function MetricRow({
  metric,
  predictedValue,
  dividerAbove,
}: {
  metric: ComponentMetric;
  predictedValue?: number;
  dividerAbove?: boolean;
}) {
  const decimals = Number.isInteger(metric.value) ? 0 : Math.abs(metric.value) >= 100 ? 1 : 2;
  const fmt = (v: number) => v.toFixed(decimals);
  const drift = predictedValue !== undefined ? predictedValue - metric.value : 0;
  return (
    <li
      className={`flex items-baseline justify-between gap-3 py-3 ${dividerAbove ? "border-t border-[var(--color-border)]" : ""}`}
    >
      <span className="text-[12.5px] text-[var(--color-fg-muted)]">{metric.label}</span>
      <div className="flex items-baseline gap-2.5 tabular-nums">
        <span className="text-[14px] font-medium text-[var(--color-fg)]">
          <AnimatedNumber value={metric.value} format={fmt} duration={0.5} />
          {metric.unit && <span className="text-[var(--color-fg-faint)]"> {metric.unit}</span>}
        </span>
        {predictedValue !== undefined && Math.abs(drift) > 0.01 && (
          <span className="text-[11px] text-[var(--color-fg-faint)]">
            → <AnimatedNumber value={predictedValue} format={fmt} duration={0.5} />
            {metric.unit && ` ${metric.unit}`}
          </span>
        )}
      </div>
    </li>
  );
}

function prettySub(s: "recoating" | "printhead" | "thermal"): string {
  switch (s) {
    case "recoating": return "Recoater assembly";
    case "printhead": return "Printhead carriage";
    case "thermal":   return "Build unit";
  }
}
