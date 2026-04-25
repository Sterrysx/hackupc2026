import { useEffect } from "react";
import { AnimatePresence } from "framer-motion";
import { useTwin } from "@/store/twin";
import { InteractiveSchematic } from "@/components/schematic/InteractiveSchematic";
import { CommandPalette } from "@/components/CommandPalette";
import { BrandMark } from "@/components/floating/BrandMark";
import { SidebarToggle } from "@/components/floating/SidebarToggle";
import { SimControls } from "@/components/floating/SimControls";
import { DashboardPanel } from "@/components/floating/DashboardPanel";
import { ARDataCard } from "@/components/floating/ARDataCard";
import { SpotlightChat } from "@/components/floating/SpotlightChat";

/**
 * "Ethereal Spatial" shell.
 *
 *   • Schematic = full-bleed background. Tapping the empty canvas:
 *       - while zoomed in  → zooms out (clears selection)
 *       - while in overview → toggles the right-hand telemetry panel
 *         (Apple-style "tap to clear UI")
 *
 *   • Right-hand surface — exactly one of these can be visible at a time:
 *       - DashboardPanel  →  `dashboardOpen && !selectedComponentId`
 *       - ARDataCard      →  `selectedComponentId !== null`
 *     `AnimatePresence mode="wait"` sequences the cross-fade so one fully
 *     exits before the next enters.
 *
 *   • Auto-hide on zoom is enforced purely by deriving visibility from
 *     `selectedComponentId`. Zooming out restores the user's previous
 *     dashboard preference automatically.
 *
 *   • SidebarToggle (top-right) is the explicit, glassmorphic control. It
 *     stays low-opacity until hovered.
 *
 *   • SpotlightChat (FAB + ⌘K overlay) is the only persistent chat surface.
 *
 *   • CommandPalette is on ⌘⇧K (⌘K is owned by SpotlightChat).
 */
export default function App() {
  const advance = useTwin((s) => s.advance);
  const dashboardOpen = useTwin((s) => s.dashboardOpen);
  const selectedId = useTwin((s) => s.selectedComponentId);

  useEffect(() => {
    void useTwin.getState().refreshChatApiStatus();
  }, []);

  useEffect(() => {
    const id = setInterval(() => advance(), 1000);
    return () => clearInterval(id);
  }, [advance]);

  const showDashboardPanel = dashboardOpen && !selectedId;

  return (
    <div className="h-screen w-screen relative overflow-hidden bg-[var(--color-bg)]">
      {/* Full-bleed schematic background (also handles tap-to-clear gestures). */}
      <div className="absolute inset-0">
        <InteractiveSchematic />
      </div>

      {/* Floating chrome */}
      <BrandMark />
      <SidebarToggle />
      <SimControls />

      {/* Right-side data surface — exactly one at a time. */}
      <AnimatePresence mode="wait">
        {showDashboardPanel && <DashboardPanel key="dashboard" />}
        {selectedId && <ARDataCard key={`ar-${selectedId}`} id={selectedId} />}
      </AnimatePresence>

      {/* Persistent chat surface — FAB + summonable overlay. */}
      <SpotlightChat />

      <CommandPalette />
    </div>
  );
}
