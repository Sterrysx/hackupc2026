import { useEffect, useMemo, useState, type CSSProperties } from "react";
import { AnimatePresence, motion } from "framer-motion";
import { useTwin } from "@/store/twin";
import { type City } from "./cities";
import { WorldMap } from "./WorldMap";

/**
 * LocationSelectorPage — first-screen city picker for the HP S100 twin.
 *
 *   • Apple-product-page aesthetic (white / black) — local CSS vars on the
 *     page root so the rest of the dark Aether app keeps its global theme.
 *   • Hands the chosen city off to the rest of the app via Zustand:
 *       confirmCity(city)       — persists the selection
 *       launchSimulation()      — flips appPhase to "main", App.tsx then
 *                                  cross-fades into the existing twin shell.
 *     The optional `onCitySelected` / `onLaunchSimulation` props are escape
 *     hatches for tests or external routing.
 *   • Desktop-only (≥1280 px). Map data bundled offline (world-atlas).
 */

const SESSION_FLAG = "location_page_animated";
const TITLE_FADE_MS = 400;
const POPUP_FADE_MS = 150;
const BOTTOM_BAR_SLIDE_MS = 300;
const APPLE_EASE: [number, number, number, number] = [0.16, 1, 0.3, 1];

const LIGHT_PALETTE = {
  // Scoped white/black tokens. Children read these via var(--color-*) so
  // they don't fight the global dark Aether tokens.
  "--color-bg": "#ffffff",
  "--color-fg": "#000000",
  "--color-fg-muted": "#6b6b6b",
  "--color-border": "#000000",
  "--color-ocean": "#f0f0f0",
  "--color-land": "#ffffff",
  "--color-land-stroke": "#000000",
  fontFamily:
    '"Inter", "SF Pro Display", -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif',
  letterSpacing: "-0.005em",
  background: "var(--color-bg)",
  color: "var(--color-fg)",
} as CSSProperties;

interface LocationSelectorPageProps {
  /** Fires every time a city is confirmed via the popup. Defaults to Zustand `confirmCity`. */
  onCitySelected?: (city: City) => void;
  /** Fires when "Launch simulation" is clicked. Defaults to Zustand `launchSimulation`. */
  onLaunchSimulation?: (city: City) => void;
}

function readSessionFlag(): boolean {
  try {
    return typeof window !== "undefined" && window.sessionStorage.getItem(SESSION_FLAG) === "1";
  } catch {
    return false;
  }
}

function writeSessionFlag(): void {
  try {
    window.sessionStorage.setItem(SESSION_FLAG, "1");
  } catch {
    /* private mode etc. — non-fatal */
  }
}

export default function LocationSelectorPage({
  onCitySelected,
  onLaunchSimulation,
}: LocationSelectorPageProps = {}) {
  const confirmCity = useTwin((s) => s.confirmCity);
  const launchSimulation = useTwin((s) => s.launchSimulation);
  const confirmedCity = useTwin((s) => s.selectedCity);

  const skipIntro = useMemo(() => readSessionFlag(), []);

  const [popupCity, setPopupCity] = useState<City | null>(null);
  const [titleVisible, setTitleVisible] = useState(skipIntro);

  // Escape closes the popup; reattaches when popupCity changes.
  useEffect(() => {
    if (!popupCity) return;
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") setPopupCity(null);
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [popupCity]);

  const handleIntroComplete = () => {
    setTitleVisible(true);
    if (!skipIntro) writeSessionFlag();
  };

  const handleConfirm = () => {
    if (!popupCity) return;
    const city = popupCity;
    confirmCity(city);
    setPopupCity(null);
    onCitySelected?.(city);
  };

  const handleLaunch = () => {
    if (!confirmedCity) return;
    onLaunchSimulation?.(confirmedCity);
    launchSimulation();
  };

  return (
    <div
      className="relative flex h-screen w-screen flex-col overflow-hidden"
      style={LIGHT_PALETTE}
    >
      {/* ── Map ──────────────────────────────────────────────────── */}
      <WorldMap
        highlightedCityId={popupCity?.id ?? null}
        confirmedCityId={confirmedCity?.id ?? null}
        skipIntroAnimation={skipIntro}
        onIntroComplete={handleIntroComplete}
        onMarkerClick={(c) => setPopupCity(c)}
      />

      {/* ── Top-left brand identifier ───────────────────────────── */}
      <div className="pointer-events-none fixed left-8 top-8 z-20 flex items-center gap-3">
        <span
          aria-hidden
          className="block w-px"
          style={{ height: 12, background: "var(--color-fg)" }}
        />
        <span
          className="text-[11px] font-medium"
          style={{
            color: "var(--color-fg-muted)",
            fontVariant: "small-caps",
            letterSpacing: "0.12em",
          }}
        >
          HP Metal Jet S100 · Digital Twin
        </span>
      </div>

      {/* ── Top-right instruction (fades after first confirm) ──── */}
      <motion.div
        className="pointer-events-none fixed right-8 top-8 z-20"
        animate={{ opacity: confirmedCity ? 0 : 1 }}
        transition={{ duration: 0.35, ease: APPLE_EASE }}
      >
        <span className="text-[12px]" style={{ color: "var(--color-fg-muted)" }}>
          Select a location to begin
        </span>
      </motion.div>

      {/* ── Title + subtitle ─────────────────────────────────────── */}
      <div
        className="pointer-events-none fixed left-1/2 top-[14%] z-10 -translate-x-1/2 text-center"
        style={{
          opacity: titleVisible ? 1 : 0,
          transform: titleVisible ? "translate(-50%, 0)" : "translate(-50%, 12px)",
          transition: skipIntro
            ? "none"
            : `opacity ${TITLE_FADE_MS}ms cubic-bezier(0.16, 1, 0.3, 1),` +
              ` transform ${TITLE_FADE_MS}ms cubic-bezier(0.16, 1, 0.3, 1)`,
        }}
      >
        <h1
          className="text-[34px] font-semibold leading-tight"
          style={{ letterSpacing: "-0.02em", color: "var(--color-fg)" }}
        >
          Choose a deployment site
        </h1>
        <p className="mt-2 text-[14px]" style={{ color: "var(--color-fg-muted)" }}>
          The selected city's climate drives five years of simulated component degradation.
        </p>
      </div>

      {/* ── City popup ───────────────────────────────────────────── */}
      <AnimatePresence>
        {popupCity && (
          <CityPopup
            city={popupCity}
            onCancel={() => setPopupCity(null)}
            onConfirm={handleConfirm}
          />
        )}
      </AnimatePresence>

      {/* ── Bottom bar ───────────────────────────────────────────── */}
      <BottomBar selectedCity={confirmedCity} onLaunch={handleLaunch} />
    </div>
  );
}

// ── CityPopup ─────────────────────────────────────────────────────────────── //

interface CityPopupProps {
  city: City;
  onCancel: () => void;
  onConfirm: () => void;
}

function CityPopup({ city, onCancel, onConfirm }: CityPopupProps) {
  // Backdrop + centered card. Spec: open is instant, close fades 150ms.
  return (
    <>
      <motion.div
        onClick={onCancel}
        initial={false}
        exit={{ opacity: 0 }}
        transition={{ duration: POPUP_FADE_MS / 1000 }}
        className="fixed inset-0 z-40"
        style={{ background: "rgba(0, 0, 0, 0.06)" }}
      />
      <motion.div
        role="dialog"
        aria-modal="true"
        aria-label={`${city.name} info`}
        initial={false}
        exit={{ opacity: 0 }}
        transition={{ duration: POPUP_FADE_MS / 1000 }}
        className="fixed left-1/2 top-1/2 z-50 w-[360px] -translate-x-1/2 -translate-y-1/2 overflow-hidden"
        style={{
          background: "var(--color-bg)",
          color: "var(--color-fg)",
          border: "1px solid var(--color-border)",
          borderRadius: 24,
          boxShadow:
            "0 16px 40px rgba(0, 0, 0, 0.10), 0 2px 8px rgba(0, 0, 0, 0.04)",
        }}
      >
        {/* Header */}
        <div
          className="px-8 pt-8 pb-6"
          style={{ borderBottom: "1px solid var(--color-border)" }}
        >
          <h2
            className="text-[24px] font-bold uppercase"
            style={{ letterSpacing: "-0.01em" }}
          >
            {city.name}
          </h2>
          <p className="mt-1 text-[13px]" style={{ color: "var(--color-fg-muted)" }}>
            {city.country}
          </p>
        </div>

        {/* Metrics */}
        <div
          className="grid grid-cols-2 gap-x-6 gap-y-5 px-8 py-6"
          style={{ borderBottom: "1px solid var(--color-border)" }}
        >
          <Metric label="Avg Temperature" value={`${city.avgTemp.toFixed(1)} °C`} />
          <Metric label="Humidity" value={`${city.avgHumidity} %`} />
          <Metric label="Altitude" value={`${city.altitude} m`} />
          <Metric label="Pressure" value={`${city.pressure} hPa`} />
        </div>

        {/* Footer */}
        <div className="flex gap-3 px-8 py-6">
          <button
            type="button"
            onClick={onCancel}
            className="flex-1 px-4 py-2.5 text-[13px] font-medium transition-colors"
            style={{
              background: "var(--color-bg)",
              color: "var(--color-fg)",
              border: "1px solid var(--color-border)",
              borderRadius: 14,
              cursor: "pointer",
            }}
          >
            Cancel
          </button>
          <button
            type="button"
            onClick={onConfirm}
            className="flex-1 px-4 py-2.5 text-[13px] font-semibold transition-opacity hover:opacity-90"
            style={{
              background: "var(--color-fg)",
              color: "var(--color-bg)",
              border: "1px solid var(--color-fg)",
              borderRadius: 14,
              cursor: "pointer",
            }}
          >
            Confirm location →
          </button>
        </div>
      </motion.div>
    </>
  );
}

function Metric({ label, value }: { label: string; value: string }) {
  return (
    <div>
      <div
        className="text-[11px] font-medium"
        style={{
          color: "var(--color-fg-muted)",
          fontVariant: "small-caps",
          letterSpacing: "0.08em",
        }}
      >
        {label}
      </div>
      <div className="mt-1 text-[22px] font-bold" style={{ color: "var(--color-fg)" }}>
        {value}
      </div>
    </div>
  );
}

// ── BottomBar ─────────────────────────────────────────────────────────────── //

function BottomBar({
  selectedCity,
  onLaunch,
}: {
  selectedCity: City | null;
  onLaunch: () => void;
}) {
  return (
    <motion.div
      initial={{ y: "100%" }}
      animate={{ y: selectedCity ? 0 : "100%" }}
      transition={{ duration: BOTTOM_BAR_SLIDE_MS / 1000, ease: APPLE_EASE }}
      className="fixed bottom-0 left-0 right-0 z-30 flex items-center justify-between px-12 py-5"
      style={{
        background: "var(--color-bg)",
        color: "var(--color-fg)",
        borderTop: "1px solid var(--color-border)",
      }}
    >
      <div>
        <div
          className="text-[10px] font-medium"
          style={{
            color: "var(--color-fg-muted)",
            fontVariant: "small-caps",
            letterSpacing: "0.12em",
          }}
        >
          Selected Location
        </div>
        <div
          className="mt-1 text-[16px] font-bold"
          style={{ color: "var(--color-fg)" }}
        >
          {selectedCity ? `${selectedCity.name}, ${selectedCity.country}` : "—"}
        </div>
      </div>

      <button
        type="button"
        onClick={onLaunch}
        disabled={!selectedCity}
        className="px-5 py-2.5 text-[13px] font-semibold transition-opacity hover:opacity-90 disabled:opacity-40"
        style={{
          background: "var(--color-fg)",
          color: "var(--color-bg)",
          border: "1px solid var(--color-fg)",
          borderRadius: 14,
          cursor: selectedCity ? "pointer" : "default",
        }}
      >
        Launch simulation →
      </button>
    </motion.div>
  );
}
