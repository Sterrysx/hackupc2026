import { motion } from "framer-motion";
import { ChevronRight } from "lucide-react";
import type { ComponentForecast, ComponentState } from "@/types/telemetry";
import { Badge, statusLabel, statusToTone } from "@/components/ui/Badge";
import { HealthRing } from "@/components/HealthRing";
import { cn } from "@/lib/cn";

interface MetricTileProps {
  component: ComponentState;
  forecast: ComponentForecast;
  highlighted?: boolean;
  onClick?: () => void;
}

/**
 * Default-view tile: minimum viable signal only.
 *  - Component name (large)
 *  - Tiny subsystem caption above
 *  - Status pill ("Healthy" / "Warning" / "Critical" / "Failed")
 *  - Small visual health ring on the right (no number, no glow)
 *  - A muted chevron that nudges right on hover, hinting "click to reveal"
 *
 * Everything else (raw metrics, sparkline, predictive rationale, history)
 * lives in the side drawer. That is the Apple Rule.
 */
export function MetricTile({ component, forecast, highlighted, onClick }: MetricTileProps) {
  const tone = statusToTone(component.status);

  return (
    <motion.button
      layout
      type="button"
      onClick={onClick}
      initial={{ opacity: 0, y: 6 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{ duration: 0.4, ease: "easeOut" }}
      whileTap={{ scale: 0.995 }}
      className={cn(
        "group relative w-full text-left",
        "rounded-3xl px-7 py-6",
        "glass transition-colors duration-300 ease-out",
        "hover:bg-[oklch(0.30_0.003_260/0.62)]",
        "focus-visible:outline-2 focus-visible:outline-[var(--color-accent)]",
        highlighted && "bg-[oklch(0.32_0.005_240/0.6)] ring-1 ring-[var(--color-accent)]/40",
      )}
    >
      <div className="flex items-center gap-5">
        <HealthRing value={component.healthIndex} predicted={forecast.predictedHealthIndex} size={32} thickness={3} />

        <div className="flex-1 min-w-0">
          <div className="text-[10.5px] uppercase tracking-[0.16em] text-[var(--color-fg-faint)] mb-1">
            {prettySubsystem(component.subsystem)}
          </div>
          <div className="text-[16px] font-medium tracking-tight text-[var(--color-fg)] leading-tight truncate">
            {component.label}
          </div>
        </div>

        <div className="flex items-center gap-2">
          <Badge tone={tone} size="sm" withDot>{statusLabel(component.status)}</Badge>
          <ChevronRight
            size={16}
            className="text-[var(--color-fg-faint)] group-hover:text-[var(--color-fg-muted)] group-hover:translate-x-0.5 transition-all"
          />
        </div>
      </div>
    </motion.button>
  );
}

function prettySubsystem(s: ComponentState["subsystem"]): string {
  switch (s) {
    case "recoating": return "Recoating";
    case "printhead": return "Printhead";
    case "thermal":   return "Thermal";
  }
}
