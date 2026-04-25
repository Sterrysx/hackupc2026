import { AnimatePresence, motion } from "framer-motion";
import { useState } from "react";
import { useTwin } from "@/store/twin";

/**
 * Drivers — collapsed by default. A single line of summary, expand to read.
 * No pills, no icons, no card background; just a quiet list.
 */
export function DriversCard() {
  const { snapshot } = useTwin();
  const [expanded, setExpanded] = useState(false);
  const d = snapshot.drivers;

  const items = [
    { label: "Ambient",       value: `${d.ambientTempC}°C` },
    { label: "Humidity",      value: `${d.humidityPct}%` },
    { label: "Contamination", value: `${d.contaminationPct}%` },
    { label: "Load",          value: `${d.loadPct}%` },
    { label: "Maintenance",   value: d.maintenanceCoeff.toFixed(2) },
  ];

  return (
    <section className="flex flex-col gap-5">
      <header
        className="flex items-center justify-between gap-4 cursor-pointer select-none"
        onClick={() => setExpanded(!expanded)}
      >
        <div>
          <h2 className="text-[16px] font-medium tracking-tight text-[var(--color-fg)]">
            Environment
          </h2>
          <p className="text-[12.5px] text-[var(--color-fg-muted)] mt-1">
            Live inputs feeding the degradation engine.
          </p>
        </div>
        <button
          type="button"
          className="text-[12px] text-[var(--color-fg-muted)] hover:text-[var(--color-fg)] transition-colors"
        >
          {expanded ? "Hide" : "Show"}
        </button>
      </header>

      <AnimatePresence initial={false}>
        {expanded && (
          <motion.dl
            initial={{ opacity: 0, height: 0 }}
            animate={{ opacity: 1, height: "auto" }}
            exit={{ opacity: 0, height: 0 }}
            transition={{ duration: 0.28, ease: "easeOut" }}
            className="overflow-hidden flex flex-col"
          >
            {items.map((it, i) => (
              <div
                key={it.label}
                className={`flex items-baseline justify-between py-3 ${i !== 0 ? "border-t border-[var(--color-border)]" : ""}`}
              >
                <dt className="text-[13px] text-[var(--color-fg-muted)]">{it.label}</dt>
                <dd className="text-[14px] font-medium tabular-nums text-[var(--color-fg)]">
                  {it.value}
                </dd>
              </div>
            ))}
          </motion.dl>
        )}
      </AnimatePresence>
    </section>
  );
}
