import { AnimatePresence, motion } from "framer-motion";
import { X, MessageSquare } from "lucide-react";
import { useTwin } from "@/store/twin";
import { Button } from "@/components/ui/Button";
import { Badge, statusLabel, statusToTone } from "@/components/ui/Badge";
import { HealthRing } from "@/components/HealthRing";
import { Sparkline } from "@/components/Sparkline";
import { healthHistory } from "@/lib/mockData";
import { formatEta } from "@/lib/alerts";

/**
 * Side drawer with the *full* per-component story. This is the only place
 * where raw metric values appear — by design.
 */
export function ComponentDrawer() {
  const { selectedComponentId, snapshot, selectComponent, sendUserMessage, setChatOpen } = useTwin();
  const c = snapshot.components.find((x) => x.id === selectedComponentId);
  const f = snapshot.forecasts.find((x) => x.id === selectedComponentId);

  const history = c ? healthHistory(c.id, snapshot.tick, 60) : [];

  return (
    <AnimatePresence>
      {c && f && (
        <>
          <motion.div
            initial={{ opacity: 0 }}
            animate={{ opacity: 1 }}
            exit={{ opacity: 0 }}
            transition={{ duration: 0.2 }}
            className="fixed inset-0 z-40 bg-[oklch(0.10_0.005_260/0.45)] backdrop-blur-sm"
            onClick={() => selectComponent(null)}
          />
          <motion.aside
            initial={{ x: "100%" }}
            animate={{ x: 0 }}
            exit={{ x: "100%" }}
            transition={{ type: "spring", damping: 30, stiffness: 260 }}
            className="
              fixed top-0 right-0 z-50
              h-full w-full max-w-[460px]
              flex flex-col overflow-hidden
              glass-floating
              rounded-l-3xl
            "
          >
            <header className="flex items-center justify-between px-8 h-16 flex-shrink-0">
              <div className="text-[10.5px] uppercase tracking-[0.18em] text-[var(--color-fg-faint)]">
                {prettySubsystem(c.subsystem)}
              </div>
              <Button variant="ghost" size="icon" onClick={() => selectComponent(null)}>
                <X size={15} />
              </Button>
            </header>

            <div className="flex-1 overflow-y-auto px-8 pb-8 flex flex-col gap-10">
              {/* Hero */}
              <div className="flex items-start justify-between gap-6">
                <div className="min-w-0 flex-1">
                  <h2 className="text-[26px] font-medium tracking-tight text-[var(--color-fg)]">
                    {c.label}
                  </h2>
                  <div className="flex items-center gap-2 mt-3">
                    <Badge tone={statusToTone(c.status)} size="sm" withDot>
                      {statusLabel(c.status)}
                    </Badge>
                    <span className="text-[12.5px] text-[var(--color-fg-muted)] tabular-nums">
                      {(c.healthIndex * 100).toFixed(0)}% health
                    </span>
                  </div>
                </div>
                <HealthRing
                  value={c.healthIndex}
                  predicted={f.predictedHealthIndex}
                  size={88}
                  thickness={5}
                  showValue
                />
              </div>

              {/* Forecast */}
              <Section title="Forecast" caption={`${snapshot.forecastHorizonMin}-minute horizon · ${(f.confidence * 100).toFixed(0)}% confidence`}>
                <p className="text-[14px] leading-relaxed text-[var(--color-fg)]">
                  {f.rationale}
                </p>
                {(f.minutesUntilCritical !== null || f.minutesUntilFailure !== null) && (
                  <div className="flex items-center gap-2 mt-4">
                    {f.minutesUntilCritical !== null && (
                      <Badge tone="warn" size="sm">
                        Critical in ~{formatEta(f.minutesUntilCritical)}
                      </Badge>
                    )}
                    {f.minutesUntilFailure !== null && (
                      <Badge tone="crit" size="sm">
                        Failure in ~{formatEta(f.minutesUntilFailure)}
                      </Badge>
                    )}
                  </div>
                )}
              </Section>

              {/* History chart */}
              <Section title="Health history" caption="Last 60 minutes · dashed line is the projected curve">
                <div className="-mx-1">
                  <Sparkline
                    values={history.map((h) => h.healthIndex)}
                    predictedValues={history.map((h) => h.predictedHealthIndex)}
                    width={400}
                    height={64}
                  />
                </div>
              </Section>

              {/* Live metrics — the raw numbers, finally */}
              <Section title="Live metrics" caption="Telemetry feeding the degradation engine">
                <ul className="flex flex-col">
                  {c.metrics.map((m, i) => {
                    const pred = f.predictedMetrics.find((pm) => pm.key === m.key);
                    const drift = pred ? pred.value - m.value : 0;
                    return (
                      <li
                        key={m.key}
                        className={`flex items-baseline justify-between gap-4 py-3.5 ${i !== 0 ? "border-t border-[var(--color-border)]" : ""}`}
                      >
                        <span className="text-[13.5px] text-[var(--color-fg-muted)]">{m.label}</span>
                        <div className="flex items-baseline gap-3 tabular-nums">
                          <span className="text-[15px] font-medium text-[var(--color-fg)]">
                            {formatValue(m.value)}{m.unit && <span className="text-[var(--color-fg-faint)]"> {m.unit}</span>}
                          </span>
                          {pred && Math.abs(drift) > 0.01 && (
                            <span className="text-[11.5px] text-[var(--color-fg-faint)]">
                              → {formatValue(pred.value)}{m.unit ? ` ${m.unit}` : ""}
                            </span>
                          )}
                        </div>
                      </li>
                    );
                  })}
                </ul>
              </Section>
            </div>

            <div className="px-8 pb-6 pt-2 flex-shrink-0">
              <Button
                variant="primary"
                className="w-full h-11"
                onClick={() => {
                  setChatOpen(true);
                  sendUserMessage(`Tell me about the ${c.label}`);
                  selectComponent(null);
                }}
              >
                <MessageSquare size={14} />
                Ask Aether about this component
              </Button>
            </div>
          </motion.aside>
        </>
      )}
    </AnimatePresence>
  );
}

function Section({
  title,
  caption,
  children,
}: {
  title: string;
  caption?: string;
  children: React.ReactNode;
}) {
  return (
    <section>
      <header className="mb-3">
        <h3 className="text-[10.5px] uppercase tracking-[0.18em] text-[var(--color-fg-faint)]">
          {title}
        </h3>
        {caption && (
          <p className="text-[12px] text-[var(--color-fg-muted)] mt-1">{caption}</p>
        )}
      </header>
      {children}
    </section>
  );
}

function prettySubsystem(s: "recoating" | "printhead" | "thermal"): string {
  switch (s) {
    case "recoating": return "Recoating system";
    case "printhead": return "Printhead array";
    case "thermal":   return "Thermal control";
  }
}

function formatValue(v: number): string {
  if (Number.isInteger(v)) return v.toString();
  if (Math.abs(v) >= 100) return v.toFixed(1);
  return v.toFixed(2);
}
