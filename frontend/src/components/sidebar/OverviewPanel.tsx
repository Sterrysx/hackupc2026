import { useMemo } from "react";
import { motion } from "framer-motion";
import { ChevronRight } from "lucide-react";
import { useTwin } from "@/store/twin";
import { Badge, statusLabel, statusToTone } from "@/components/ui/Badge";
import { HealthRing } from "@/components/HealthRing";
import { AnimatedNumber } from "@/components/AnimatedNumber";
import { formatEta } from "@/lib/alerts";
import type { ComponentState } from "@/types/telemetry";

/* ── Stagger config ───────────────────────────────────────────────────── */

const APPLE_EASE: [number, number, number, number] = [0.16, 1, 0.3, 1];

const containerVariants = {
  hidden: { opacity: 0 },
  visible: {
    opacity: 1,
    transition: { staggerChildren: 0.05, delayChildren: 0.04 },
  },
};

const itemVariants = {
  hidden: { opacity: 0, y: 10 },
  visible: { opacity: 1, y: 0, transition: { duration: 0.45, ease: APPLE_EASE } },
};

const SUBSYSTEM_ORDER: ComponentState["subsystem"][] = ["recoating", "printhead", "thermal"];

/**
 * Sidebar content shown when no component is selected.
 *  - Hero status (1-line headline + supporting line)
 *  - Components list (compact, single-column tiles)
 *  - Active alerts (compact rows)
 *  - Environment (collapsed by default — small footprint)
 */
export function OverviewPanel() {
  const { snapshot, alerts, backendPulseAlerts, selectComponent, highlightComponentId, highlightComponent } = useTwin();
  const combinedAlerts = useMemo(() => [...backendPulseAlerts, ...alerts], [backendPulseAlerts, alerts]);

  const failed   = snapshot.components.filter((c) => c.status === "FAILED").length;
  const critical = snapshot.components.filter((c) => c.status === "CRITICAL").length;
  const degraded = snapshot.components.filter((c) => c.status === "DEGRADED").length;
  const healthy  = snapshot.components.length - failed - critical - degraded;

  const headline =
    failed   ? `${failed} component${failed === 1 ? "" : "s"} offline` :
    critical ? "Attention needed" :
    degraded ? "All systems running" :
    combinedAlerts.length > 0 ? "All systems running" :
    "All systems healthy";

  const supporting =
    failed   ? "Immediate inspection recommended." :
    critical ? `${critical} critical · ${degraded} degraded · forecasting next ${snapshot.forecastHorizonMin} min.` :
    degraded ? `${degraded} component${degraded === 1 ? "" : "s"} degraded — schedule maintenance.` :
    combinedAlerts.length > 0 ? `${combinedAlerts.length} predictive watch${combinedAlerts.length === 1 ? "" : "es"} active.` :
    `${healthy} of ${snapshot.components.length} components nominal.`;

  const grouped = SUBSYSTEM_ORDER.map((sub) => ({
    sub,
    items: snapshot.components.filter((c) => c.subsystem === sub),
  }));

  const topAlerts = combinedAlerts.slice(0, 4);

  return (
    <motion.div
      key="overview"
      variants={containerVariants}
      initial="hidden"
      animate="visible"
      exit={{ opacity: 0, transition: { duration: 0.2 } }}
      className="flex flex-col gap-12 px-7 py-9"
    >
      {/* Hero */}
      <motion.section variants={itemVariants}>
        <p className="text-[10px] uppercase tracking-[0.20em] text-[var(--color-fg-faint)]">
          Overview
        </p>
        <h1 className="mt-2 text-[22px] font-medium tracking-[-0.01em] leading-[1.15]">
          {headline}
        </h1>
        <p className="mt-2 text-[13px] text-[var(--color-fg-muted)]">{supporting}</p>
      </motion.section>

      {/* Components */}
      <motion.section variants={itemVariants}>
        <header className="flex items-center justify-between mb-3">
          <h2 className="text-[10px] uppercase tracking-[0.20em] text-[var(--color-fg-faint)]">
            Components
          </h2>
          <span className="text-[10.5px] text-[var(--color-fg-faint)]">
            tap to focus
          </span>
        </header>
        <div className="flex flex-col gap-2">
          {grouped.map(({ sub, items }) => (
            <div key={sub} className="flex flex-col">
              <div className="text-[9.5px] uppercase tracking-[0.18em] text-[var(--color-fg-faint)] mt-5 mb-2 px-1">
                {prettySub(sub)}
              </div>
              {items.map((c) => (
                <CompactTile
                  key={c.id}
                  component={c}
                  highlighted={highlightComponentId === c.id}
                  onClick={() => {
                    selectComponent(c.id);
                    highlightComponent(c.id);
                    setTimeout(() => highlightComponent(null), 1200);
                  }}
                />
              ))}
            </div>
          ))}
        </div>
      </motion.section>

      {/* Alerts */}
      <motion.section variants={itemVariants}>
        <header className="flex items-baseline justify-between mb-3">
          <h2 className="text-[10px] uppercase tracking-[0.20em] text-[var(--color-fg-faint)]">
            Alerts
          </h2>
          <span className="text-[10.5px] text-[var(--color-fg-faint)] tabular-nums">
            {alerts.length === 0 ? "all clear" : `${alerts.length} active`}
          </span>
        </header>
        {topAlerts.length === 0 ? (
          <p className="text-[12.5px] text-[var(--color-fg-muted)]">
            No alerts. Twin is operating within all thresholds.
          </p>
        ) : (
          <ul className="flex flex-col">
            {topAlerts.map((a, i) => (
              <li key={a.id}>
                <button
                  type="button"
                  onClick={() => {
                    selectComponent(a.componentId);
                    highlightComponent(a.componentId);
                    setTimeout(() => highlightComponent(null), 1200);
                  }}
                  className={`w-full text-left flex items-center gap-3 py-2.5 -mx-2 px-2 rounded-2xl hover:bg-white/[0.03] transition-colors ${i !== 0 ? "border-t border-[var(--color-border)]" : ""}`}
                >
                  <span
                    className="h-1.5 w-1.5 rounded-full flex-shrink-0"
                    style={{ background: dotColour(a.severity) }}
                  />
                  <div className="flex-1 min-w-0">
                    <div className="text-[12.5px] text-[var(--color-fg)] truncate">
                      {a.componentLabel}
                    </div>
                    <div className="text-[11px] text-[var(--color-fg-muted)] truncate mt-0.5">
                      {a.kind === "predictive" ? "Predicted" : "Now"}
                      {a.etaMinutes !== undefined && ` · ${formatEta(a.etaMinutes)}`}
                    </div>
                  </div>
                </button>
              </li>
            ))}
          </ul>
        )}
      </motion.section>

      {/* Environment */}
      <motion.section variants={itemVariants}>
        <h2 className="text-[10px] uppercase tracking-[0.20em] text-[var(--color-fg-faint)] mb-3">
          Environment
        </h2>
        <dl className="grid grid-cols-2 gap-x-5 gap-y-3.5">
          <DriverRow label="Ambient" value={snapshot.drivers.ambientTempC} unit="°C" />
          <DriverRow label="Humidity" value={snapshot.drivers.humidityPct} unit="%" />
          <DriverRow label="Contamination" value={snapshot.drivers.contaminationPct} unit="%" />
          <DriverRow label="Load" value={snapshot.drivers.loadPct} unit="%" />
        </dl>
      </motion.section>
    </motion.div>
  );
}

/* ── Subviews ──────────────────────────────────────────────────────────── */

function CompactTile({
  component,
  highlighted,
  onClick,
}: {
  component: ComponentState;
  highlighted?: boolean;
  onClick: () => void;
}) {
  const tone = statusToTone(component.status);
  return (
    <motion.button
      layout
      type="button"
      onClick={onClick}
      whileTap={{ scale: 0.99 }}
      className={`group relative w-full text-left rounded-2xl px-3.5 py-4 transition-colors duration-300
        hover:bg-white/[0.04]
        ${highlighted ? "bg-[oklch(0.32_0.005_240/0.55)]" : ""}`}
    >
      <div className="flex items-center gap-3">
        <HealthRing
          value={component.healthIndex}
          predicted={component.healthIndex}
          size={26}
          thickness={2.5}
        />
        <div className="flex-1 min-w-0">
          <div className="text-[13px] font-medium text-[var(--color-fg)] leading-tight truncate">
            {component.label}
          </div>
        </div>
        <Badge tone={tone} size="xs" withDot>
          {statusLabel(component.status)}
        </Badge>
        <ChevronRight
          size={14}
          className="text-[var(--color-fg-faint)] group-hover:text-[var(--color-fg-muted)] group-hover:translate-x-0.5 transition-all"
        />
      </div>
    </motion.button>
  );
}

function DriverRow({ label, value, unit }: { label: string; value: number; unit: string }) {
  const decimals = unit === "" ? 2 : 1;
  return (
    <div className="flex items-baseline justify-between">
      <dt className="text-[11.5px] text-[var(--color-fg-muted)]">{label}</dt>
      <dd className="text-[12.5px] font-medium tabular-nums text-[var(--color-fg)]">
        <AnimatedNumber value={value} format={(v) => v.toFixed(decimals)} duration={0.5} />
        {unit && <span className="text-[var(--color-fg-faint)]"> {unit}</span>}
      </dd>
    </div>
  );
}

function dotColour(s: "INFO" | "WARNING" | "CRITICAL"): string {
  if (s === "CRITICAL") return "var(--color-crit)";
  if (s === "WARNING")  return "var(--color-warn)";
  return "var(--color-info)";
}

function prettySub(s: ComponentState["subsystem"]): string {
  switch (s) {
    case "recoating": return "Recoater assembly";
    case "printhead": return "Printhead carriage";
    case "thermal":   return "Build unit";
  }
}
