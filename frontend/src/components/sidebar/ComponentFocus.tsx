import { motion } from "framer-motion";
import { ArrowLeft, MessageSquare } from "lucide-react";
import { useTwin } from "@/store/twin";
import { Badge, statusLabel, statusToTone } from "@/components/ui/Badge";
import { Button } from "@/components/ui/Button";
import { HealthRing } from "@/components/HealthRing";
import { AnimatedNumber } from "@/components/AnimatedNumber";
import { formatEta } from "@/lib/alerts";
import type { ComponentMetric } from "@/types/telemetry";

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
  const selectComponent = useTwin((s) => s.selectComponent);
  const sendUserMessage = useTwin((s) => s.sendUserMessage);

  const c = snapshot.components.find((x) => x.id === id);
  const f = snapshot.forecasts.find((x) => x.id === id);
  if (!c || !f) return null;

  const tone = statusToTone(c.status);
  const onBack = () => selectComponent(null);

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
        {(f.minutesUntilCritical !== null || f.minutesUntilFailure !== null) && (
          <div className="flex flex-wrap gap-1.5 mb-3">
            {f.minutesUntilFailure !== null && (
              <Badge tone="crit" size="sm">Failure ~{formatEta(f.minutesUntilFailure)}</Badge>
            )}
            {f.minutesUntilCritical !== null && (
              <Badge tone="warn" size="sm">Critical ~{formatEta(f.minutesUntilCritical)}</Badge>
            )}
          </div>
        )}
        <p className="text-[12.5px] text-[var(--color-fg-muted)] leading-relaxed">
          {f.rationale}
        </p>
      </motion.section>

      {/* CTA */}
      <motion.div variants={itemVariants}>
        <Button
          variant="primary"
          className="w-full h-10"
          onClick={() => {
            sendUserMessage(`Tell me about the ${c.label}`);
          }}
        >
          <MessageSquare size={13} />
          Ask Aether about this
        </Button>
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
    case "recoating": return "Recoating system";
    case "printhead": return "Printhead array";
    case "thermal":   return "Thermal control";
  }
}
