import { AnimatePresence, motion } from "framer-motion";
import { useState } from "react";
import { useTwin } from "@/store/twin";
import { Badge, severityToTone } from "@/components/ui/Badge";
import { formatEta } from "@/lib/alerts";

/**
 * AlertsPanel — quiet by default.
 *  - Default: a single-line summary "All clear" / "2 warnings · 1 critical".
 *  - Expand to see the rolled-up list, one row per alert with a dot + label.
 *  - No raw threshold text; click an alert to open the component drawer.
 */
export function AlertsPanel() {
  const { alerts, selectComponent, highlightComponent } = useTwin();
  const [expanded, setExpanded] = useState(false);
  const visible = alerts.slice(0, 6);

  const critCount = alerts.filter((a) => a.severity === "CRITICAL").length;
  const warnCount = alerts.filter((a) => a.severity === "WARNING").length;

  const summary =
    alerts.length === 0
      ? "All clear"
      : [
          warnCount && `${warnCount} warning${warnCount === 1 ? "" : "s"}`,
          critCount && `${critCount} critical`,
        ]
          .filter(Boolean)
          .join(" · ");

  const summaryTone = critCount ? "crit" : warnCount ? "warn" : "ok";

  return (
    <section className="flex flex-col gap-5">
      <header
        className="flex items-center justify-between gap-4 cursor-pointer select-none"
        onClick={() => setExpanded(!expanded)}
      >
        <div>
          <h2 className="text-[16px] font-medium tracking-tight text-[var(--color-fg)]">
            Alerts
          </h2>
          <p className="text-[12.5px] text-[var(--color-fg-muted)] mt-1 flex items-center gap-2">
            <Badge tone={summaryTone} size="xs" withDot>{summary}</Badge>
            <span className="text-[var(--color-fg-faint)]">·</span>
            <span>predictive listed before current</span>
          </p>
        </div>
        <button
          type="button"
          className="text-[12px] text-[var(--color-fg-muted)] hover:text-[var(--color-fg)] transition-colors"
        >
          {expanded ? "Hide" : "Show all"}
        </button>
      </header>

      <AnimatePresence initial={false}>
        {expanded && (
          <motion.div
            key="list"
            initial={{ opacity: 0, height: 0 }}
            animate={{ opacity: 1, height: "auto" }}
            exit={{ opacity: 0, height: 0 }}
            transition={{ duration: 0.28, ease: "easeOut" }}
            className="overflow-hidden"
          >
            {visible.length === 0 ? (
              <p className="text-[13px] text-[var(--color-fg-muted)] py-3">
                Nothing to attend to. Twin operating within all thresholds.
              </p>
            ) : (
              <ul className="flex flex-col">
                {visible.map((a, i) => (
                  <li key={a.id}>
                    <button
                      type="button"
                      onClick={() => {
                        selectComponent(a.componentId);
                        highlightComponent(a.componentId);
                        setTimeout(() => highlightComponent(null), 1400);
                      }}
                      className={`w-full text-left flex items-center gap-4 py-3.5 transition-colors hover:bg-white/[0.03] -mx-2 px-2 rounded-2xl ${i !== 0 ? "border-t border-[var(--color-border)]" : ""}`}
                    >
                      <span
                        className="h-2 w-2 rounded-full flex-shrink-0"
                        style={{ background: dotColour(a.severity) }}
                      />
                      <div className="flex-1 min-w-0">
                        <div className="text-[13.5px] text-[var(--color-fg)] truncate">
                          {a.componentLabel}
                        </div>
                        <div className="text-[11.5px] text-[var(--color-fg-muted)] truncate mt-0.5">
                          {a.kind === "predictive" ? "Predicted" : "Now"}
                          {a.etaMinutes !== undefined && ` · ${formatEta(a.etaMinutes)}`}
                        </div>
                      </div>
                      <Badge tone={severityToTone(a.severity)} size="xs">
                        {a.kind === "predictive" ? "Forecast" : "Active"}
                      </Badge>
                    </button>
                  </li>
                ))}
              </ul>
            )}
          </motion.div>
        )}
      </AnimatePresence>
    </section>
  );
}

function dotColour(s: "INFO" | "WARNING" | "CRITICAL"): string {
  if (s === "CRITICAL") return "var(--color-crit)";
  if (s === "WARNING")  return "var(--color-warn)";
  return "var(--color-info)";
}
