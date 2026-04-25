import { ArrowLeft } from "lucide-react";
import { InteractiveSchematic } from "@/components/schematic/InteractiveSchematic";

/**
 * Standalone schematic page. Reachable at `#schematic`.
 * Intentionally isolated from the dashboard so we can iterate without risk.
 */
export function SchematicView() {
  return (
    <div className="min-h-screen flex flex-col text-[var(--color-fg)]">
      <header className="sticky top-0 z-30 glass-strong">
        <div className="max-w-[1500px] mx-auto flex items-center justify-between gap-6 px-10 h-16">
          <button
            onClick={() => {
              window.location.hash = "";
            }}
            className="inline-flex items-center gap-2 h-9 pl-2 pr-3 rounded-full text-[var(--color-fg-muted)] hover:text-[var(--color-fg)] hover:bg-white/[0.06] transition-colors text-[13px]"
          >
            <ArrowLeft size={14} />
            Dashboard
          </button>

          <div className="text-[10.5px] uppercase tracking-[0.18em] text-[var(--color-fg-faint)]">
            Phase 2 · Interactive Schematic
          </div>
        </div>
      </header>

      <main className="flex-1 flex items-center justify-center p-6">
        <div className="w-full max-w-[1400px] aspect-[5/3] relative">
          <InteractiveSchematic />
        </div>
      </main>
    </div>
  );
}
