import { AnimatePresence, motion } from "framer-motion";
import { ChevronRight } from "lucide-react";
import { useTwin } from "@/store/twin";
import { topAlert, formatEta } from "@/lib/alerts";

/**
 * FailureRibbon — Apple-style banner notification.
 *  - No pulse, no border accent, no urgent colour.
 *  - Soft tinted background (coral-or-sand at low alpha) + a single-line message.
 *  - Slides in/out smoothly only when there's something worth surfacing.
 */
export function FailureRibbon() {
  const { alerts, selectComponent, highlightComponent } = useTwin();
  const top = topAlert(alerts);

  if (!top || top.severity === "INFO") return null;

  const isCrit = top.severity === "CRITICAL";

  const onClick = () => {
    selectComponent(top.componentId);
    highlightComponent(top.componentId);
    setTimeout(() => highlightComponent(null), 1400);
  };

  return (
    <AnimatePresence mode="popLayout">
      <motion.button
        key={top.id}
        type="button"
        initial={{ opacity: 0, y: -4 }}
        animate={{ opacity: 1, y: 0 }}
        exit={{ opacity: 0, y: -4 }}
        transition={{ duration: 0.4, ease: "easeOut" }}
        onClick={onClick}
        className="group w-full flex items-center justify-between gap-5 rounded-3xl px-6 py-4 text-left transition-colors"
        style={{
          background: isCrit
            ? "oklch(0.72 0.13 25 / 0.10)"
            : "oklch(0.83 0.12 75 / 0.10)",
          border: "1px solid oklch(1 0 0 / 0.06)",
        }}
      >
        <div className="flex items-center gap-4 min-w-0">
          <span
            className="h-2 w-2 rounded-full flex-shrink-0"
            style={{
              background: isCrit ? "var(--color-crit)" : "var(--color-warn)",
              animation: "softPulse 2.4s ease-in-out infinite",
            }}
          />
          <div className="min-w-0">
            <div className="text-[14px] font-medium text-[var(--color-fg)] truncate">
              {top.title}
            </div>
            <div className="text-[12.5px] text-[var(--color-fg-muted)] mt-0.5 truncate">
              {top.kind === "predictive" && top.etaMinutes !== undefined
                ? `Estimated ${formatEta(top.etaMinutes)} from now`
                : "Active now"}
            </div>
          </div>
        </div>
        <ChevronRight
          size={18}
          className="text-[var(--color-fg-faint)] group-hover:text-[var(--color-fg-muted)] group-hover:translate-x-0.5 transition-all flex-shrink-0"
        />
      </motion.button>
    </AnimatePresence>
  );
}
