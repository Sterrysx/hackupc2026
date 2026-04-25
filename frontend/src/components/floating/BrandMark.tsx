import { useTwin } from "@/store/twin";

/**
 * Floating brand mark — top-left corner. Tiny glass pill with a soft-pulsing
 * heartbeat dot and the product name. Always visible.
 */
export function BrandMark() {
  const paused = useTwin((s) => s.paused);

  return (
    <div className="fixed top-6 left-6 z-30 inline-flex items-center gap-2.5 h-10 pl-3 pr-4 rounded-full glass-floating select-none">
      <span
        className="h-1.5 w-1.5 rounded-full flex-shrink-0"
        style={{
          background: paused ? "var(--color-fg-faint)" : "var(--color-ok)",
          animation: paused ? undefined : "softPulse 2.4s ease-in-out infinite",
        }}
      />
      <div className="leading-tight">
        <span className="text-[12.5px] font-medium tracking-tight">Aether</span>
        <span className="ml-2 text-[9.5px] uppercase tracking-[0.18em] text-[var(--color-fg-faint)]">
          S100
        </span>
      </div>
    </div>
  );
}
