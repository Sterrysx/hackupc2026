import { motion } from "framer-motion";
import { Box, LayoutGrid, Activity } from "lucide-react";
import { useTwin } from "@/store/twin";
import { cn } from "@/lib/cn";

const OPTIONS: Array<{
  value: "2d" | "3d" | "analytics";
  label: string;
  icon: typeof Box;
}> = [
  { value: "2d",        label: "Schematic",    icon: LayoutGrid },
  { value: "3d",        label: "Digital Twin", icon: Box },
  { value: "analytics", label: "Analytics",    icon: Activity },
];

/**
 * Global mode switcher — three views over the same store: SVG schematic,
 * 3D spatial twin, and the analytics bento. The active option uses a
 * shared `layoutId` so the highlight thumb glides between options as one
 * continuous motion. Hidden during a component zoom (focused work area).
 */
export function ViewToggle() {
  const viewMode = useTwin((s) => s.viewMode);
  const setViewMode = useTwin((s) => s.setViewMode);
  const selectedId = useTwin((s) => s.selectedComponentId);

  if (selectedId) return null;

  return (
    <div className="fixed top-6 right-20 z-40">
      <div className="relative inline-flex items-center p-1 rounded-full glass-floating">
        {OPTIONS.map((opt) => {
          const Icon = opt.icon;
          const active = viewMode === opt.value;
          return (
            <button
              key={opt.value}
              type="button"
              onClick={() => setViewMode(opt.value)}
              title={opt.label}
              aria-pressed={active}
              className={cn(
                "relative h-7 px-3 rounded-full text-[11.5px] font-medium tracking-tight transition-colors flex items-center gap-1.5",
                active
                  ? "text-[var(--color-fg)]"
                  : "text-[var(--color-fg-muted)] hover:text-[var(--color-fg)]",
              )}
            >
              {active && (
                <motion.span
                  layoutId="viewToggleThumb"
                  className="absolute inset-0 rounded-full bg-white/[0.12]"
                  transition={{ type: "spring", stiffness: 360, damping: 32, mass: 0.7 }}
                />
              )}
              <Icon size={11} className="relative z-10" />
              <span className="relative z-10">{opt.label}</span>
            </button>
          );
        })}
      </div>
    </div>
  );
}
