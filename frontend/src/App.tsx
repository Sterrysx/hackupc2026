import { useEffect } from "react";
import { AnimatePresence } from "framer-motion";
import { useTwin } from "@/store/twin";
import { InteractiveSchematic } from "@/components/schematic/InteractiveSchematic";
import { CommandPalette } from "@/components/CommandPalette";
import { BrandMark } from "@/components/floating/BrandMark";
import { ModeToggle } from "@/components/floating/ModeToggle";
import { SimControls } from "@/components/floating/SimControls";
import { DashboardPanel } from "@/components/floating/DashboardPanel";
import { ARDataCard } from "@/components/floating/ARDataCard";
import { AetherBubble } from "@/components/floating/AetherBubble";

/**
 * "Ethereal Spatial" shell.
 *
 *   • Schematic is the entire 100vw × 100vh background — never constrained.
 *   • Floating glass overlays sit ABOVE it with margins from every edge.
 *   • Selecting a part:
 *       1. DashboardPanel (if visible) exits   (~0.32s)
 *       2. Schematic spring-zooms              (~0.8s)
 *       3. ARDataCard fades in spatially       (~0.42s, sequenced via mode="wait")
 *   • Reverse on Esc / back / re-click.
 *   • Mode toggle:
 *       - Dashboard → DashboardPanel visible (overview + embedded chat)
 *       - Immersive → DashboardPanel hidden, only schematic + chat bubble.
 *   • Aether chat bubble is a FAB at bottom-right whenever the dashboard
 *     widget isn't shown — so chat is always one click away.
 */
export default function App() {
  const advance = useTwin((s) => s.advance);
  const mode = useTwin((s) => s.mode);
  const selectedId = useTwin((s) => s.selectedComponentId);
  const setBubbleOpen = useTwin((s) => s.setBubbleOpen);

  // Tick the simulator once per second.
  useEffect(() => {
    const id = setInterval(() => advance(), 1000);
    return () => clearInterval(id);
  }, [advance]);

  const showDashboardPanel = mode === "dashboard" && !selectedId;
  const showBubble = !showDashboardPanel; // bubble fills in whenever the widget is gone

  // If the user opens the dashboard widget while the chat bubble is expanded,
  // close the bubble — its chat is now embedded in the widget.
  useEffect(() => {
    if (showDashboardPanel) setBubbleOpen(false);
  }, [showDashboardPanel, setBubbleOpen]);

  return (
    <div className="h-screen w-screen relative overflow-hidden bg-[var(--color-bg)]">
      {/* Full-bleed schematic background */}
      <div className="absolute inset-0">
        <InteractiveSchematic />
      </div>

      {/* Floating chrome (always visible) */}
      <BrandMark />
      <ModeToggle />
      <SimControls />

      {/* Right-side data surface — DashboardPanel and ARDataCard never both visible.
          mode="wait" sequences the cross-fade: one exits fully before the next enters. */}
      <AnimatePresence mode="wait">
        {showDashboardPanel && <DashboardPanel key="dashboard" />}
        {selectedId && <ARDataCard key={`ar-${selectedId}`} id={selectedId} />}
      </AnimatePresence>

      {/* Floating chat (FAB + expandable panel) — present whenever dashboard widget isn't. */}
      <AnimatePresence>
        {showBubble && <AetherBubble key="bubble" />}
      </AnimatePresence>

      <CommandPalette />
    </div>
  );
}
