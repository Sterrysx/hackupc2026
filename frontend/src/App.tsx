import { useEffect } from "react";
import { AnimatePresence } from "framer-motion";
import { useTwin } from "@/store/twin";
import { startProactiveWebSocket } from "@/lib/twinNotifications";
import { SpatialScene } from "@/components/scene/SpatialScene";
import { InteractiveSchematic } from "@/components/schematic/InteractiveSchematic";
import { CommandPalette } from "@/components/CommandPalette";
import { BrandMark } from "@/components/floating/BrandMark";
import { SidebarToggle } from "@/components/floating/SidebarToggle";
import { SimControls } from "@/components/floating/SimControls";
import { DashboardPanel } from "@/components/floating/DashboardPanel";
import { ARDataCard } from "@/components/floating/ARDataCard";
import { SpotlightChat } from "@/components/floating/SpotlightChat";
import { ViewToggle } from "@/components/floating/ViewToggle";
import { OpenViewButton } from "@/components/floating/OpenViewButton";

/**
 * "Ethereal Spatial" shell — Phase 3.6.
 *
 *   • Background is a SINGLE source of focus that can switch between two
 *     visualisations via the ViewToggle:
 *       - "3d": photorealistic HP S100 (SpatialScene + R3F).
 *       - "2d": SVG schematic (Phase 2 InteractiveSchematic).
 *     The AR card, dashboard, chat, alerts, etc. live entirely in the HTML
 *     overlay layer and read the SAME store, so they persist across both
 *     views and never lose context.
 *
 *   • Cross-fade between views uses AnimatePresence (mode="wait") so the
 *     outgoing scene fully fades before the incoming scene mounts —
 *     prevents two heavy renderers being alive at once.
 *
 *   • All click semantics, dashboard auto-hide on zoom, spotlight chat,
 *     sidebar toggle, and ⌘K command palette are unchanged from earlier
 *     phases and work identically in both views.
 */
export default function App() {
  const advance = useTwin((s) => s.advance);
  const dashboardOpen = useTwin((s) => s.dashboardOpen);
  const selectedId = useTwin((s) => s.selectedComponentId);
  const viewMode = useTwin((s) => s.viewMode);

  useEffect(() => {
    void useTwin.getState().refreshChatApiStatus();
  }, []);

  useEffect(() => {
    const close = startProactiveWebSocket();
    return () => close();
  }, []);

  useEffect(() => {
    const id = setInterval(() => advance(), 1000);
    return () => clearInterval(id);
  }, [advance]);

  const showDashboardPanel = dashboardOpen && !selectedId;

  return (
    <div className="relative h-screen w-screen min-h-0 overflow-hidden bg-[var(--color-bg)]">
      {/*
        3D is NOT wrapped in framer initial={{ opacity: 0 }} — on some
        browsers / framer+AnimatePresence+React 19 combos the WebGL layer
        never left opacity 0 (reads as a void while the 2D UI over z-index
        still looked fine). Use a plain div + fixed viewport fill instead.
        2D keeps the cross-fade.
      */}
      <div className="absolute inset-0 min-h-0">
        <div
          className={
            "fixed left-0 top-0 z-0 h-[100dvh] w-full min-w-0 transition-opacity duration-500 " +
            (viewMode === "3d" ? "opacity-100" : "opacity-0 pointer-events-none")
          }
        >
          <SpatialScene />
        </div>

        <div
          className={
            "absolute inset-0 transition-opacity duration-500 " +
            (viewMode === "2d" ? "opacity-100" : "opacity-0 pointer-events-none")
          }
        >
          <InteractiveSchematic />
        </div>
      </div>

      {/* Floating chrome — view-agnostic. */}
      <BrandMark />
      <ViewToggle />
      <OpenViewButton />
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
