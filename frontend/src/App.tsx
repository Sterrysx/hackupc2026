import { useEffect } from "react";
import { AnimatePresence, motion } from "framer-motion";
import { useTwin } from "@/store/twin";
import { startProactiveWebSocket } from "@/lib/twinNotifications";
import { SpatialScene } from "@/components/scene/SpatialScene";
import { InteractiveSchematic } from "@/components/schematic/InteractiveSchematic";
import { CommandPalette } from "@/components/CommandPalette";
import { BrandMark } from "@/components/floating/BrandMark";
import { SidebarToggle } from "@/components/floating/SidebarToggle";
import { PredictiveScrubber } from "@/components/floating/PredictiveScrubber";
import { TemporalStateBadge, PredictiveTint } from "@/components/floating/TemporalStateBadge";
import { ExecutePrintButton } from "@/components/floating/ExecutePrintButton";
import { DashboardPanel } from "@/components/floating/DashboardPanel";
import { ARDataCard } from "@/components/floating/ARDataCard";
import { SpotlightChat } from "@/components/floating/SpotlightChat";
import { ViewToggle } from "@/components/floating/ViewToggle";
import { OpenViewButton } from "@/components/floating/OpenViewButton";
import LocationSelectorPage from "@/components/location/LocationSelectorPage";
import { AnalyticsView } from "@/components/analytics/AnalyticsView";

/**
 * "Ethereal Spatial" shell — Phase 3.6 + Location Selector.
 *
 *   • Top-level surface is gated by `appPhase`:
 *       - "location-select": LocationSelectorPage (white/black Apple-style
 *         landing). Once the operator confirms a city and clicks Launch,
 *         appPhase flips to "main".
 *       - "main": the existing twin shell (SpatialScene + schematic + chrome).
 *     The transition is a 400ms opacity cross-fade via AnimatePresence
 *     (mode="wait") so the two surfaces never overlap.
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
  const appPhase = useTwin((s) => s.appPhase);

  useEffect(() => {
    void useTwin.getState().refreshChatApiStatus();
  }, []);

  useEffect(() => {
    const close = startProactiveWebSocket();
    return () => close();
  }, []);

  // The simulation tick only runs while the main shell is live. While the
  // operator is still on the landing page there's no benefit to advancing
  // the snapshot — it just burns CPU on a screen that doesn't read it.
  useEffect(() => {
    if (appPhase !== "main") return;
    const id = setInterval(() => advance(), 1000);
    return () => clearInterval(id);
  }, [advance, appPhase]);

  const showDashboardPanel = dashboardOpen && !selectedId && viewMode !== "analytics";
  const inAnalytics = viewMode === "analytics";

  return (
    <AnimatePresence mode="wait">
      {appPhase === "location-select" ? (
        <motion.div
          key="location"
          exit={{ opacity: 0 }}
          transition={{ duration: 0.4, ease: [0.16, 1, 0.3, 1] }}
        >
          <LocationSelectorPage />
        </motion.div>
      ) : (
        <motion.div
          key="twin"
          initial={{ opacity: 0 }}
          animate={{ opacity: 1 }}
          transition={{ duration: 0.4, ease: [0.16, 1, 0.3, 1] }}
          className="relative h-screen w-screen min-h-0 overflow-hidden bg-[var(--color-bg)]"
        >
          {/*
            3D is NOT wrapped in framer initial={{ opacity: 0 }} — on some
            browsers / framer+AnimatePresence+React 19 combos the WebGL layer
            never left opacity 0 (reads as a void while the 2D UI over z-index
            still looked fine). Use a plain div + fixed viewport fill instead.
            2D keeps the cross-fade.
          */}
          {/*
            Background canvas. In analytics mode it stays mounted but is
            heavily blurred + darkened, so the bento grid floats over a
            recognisable but recessed copy of the scene the operator just
            left. The blur is GPU-cheap because it's the only thing in the
            backdrop layer at that moment.
          */}
          <div
            className={
              "absolute inset-0 min-h-0 transition-[filter,opacity] duration-500 " +
              (inAnalytics
                ? "blur-[28px] brightness-[0.35] pointer-events-none"
                : "")
            }
          >
            <div
              className={
                "fixed left-0 top-0 z-0 h-[100dvh] w-full min-w-0 transition-opacity duration-500 " +
                (viewMode === "3d" || inAnalytics ? "opacity-100" : "opacity-0 pointer-events-none")
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

          {/* Analytics overlay — fades in over the blurred backdrop. */}
          <AnimatePresence>
            {inAnalytics && <AnalyticsView key="analytics" />}
          </AnimatePresence>

          {/* Predictive-mode tint — sits BELOW the floating chrome (z-5) so it
              washes the scene without hazing the controls. Pointer-events off. */}
          <PredictiveTint />

          {/* Floating chrome — view-agnostic. */}
          <BrandMark />
          <ViewToggle />
          <OpenViewButton />
          <SidebarToggle />
          <TemporalStateBadge />
          <ExecutePrintButton />
          <PredictiveScrubber />

          {/* Right-side data surface — hidden in analytics mode. */}
          <AnimatePresence mode="wait">
            {showDashboardPanel && <DashboardPanel key="dashboard" />}
            {selectedId && !inAnalytics && <ARDataCard key={`ar-${selectedId}`} id={selectedId} />}
          </AnimatePresence>

          {/* Persistent chat surface — FAB + summonable overlay. */}
          <SpotlightChat />

          <CommandPalette />
        </motion.div>
      )}
    </AnimatePresence>
  );
}
