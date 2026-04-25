/**
 * Central Zustand store — single source of truth for the live digital twin.
 *
 * The store drives everything from a monotonic `tick` counter. A tiny
 * simulation loop (in <App />) advances tick, recomputes the snapshot,
 * derives alerts, and notifies the UI. When the real backend goes live we
 * replace `advance()` with a websocket / polling subscription; consumers
 * never change.
 */

import { create } from "zustand";
import type {
  Alert,
  AlertSeverity,
  ChatMessage,
  ComponentId,
  SystemSnapshot,
} from "@/types/telemetry";
import type { City } from "@/components/location/cities";
import { snapshotAtTick } from "@/lib/mockData";
import { deriveAlerts } from "@/lib/alerts";
import { probeTwinApiHealth, queryAgent } from "@/lib/agentApi";
import { getOrCreateAgentThreadId } from "@/lib/agentThread";
import { resolveComponentForAgent, tryParseAgentReport } from "@/lib/componentMap";
import {
  backendCityName,
  fetchTwinState,
  listPrinters,
  tickToDay,
} from "@/lib/twinApi";
import {
  answer,
  makeAssistantFromAgentReport,
  makeAssistantMessage,
  makeUserMessage,
  makeWatchdogAssistantMessage,
} from "@/lib/rag";

/**
 * Top-level app phase. The location-selector landing page renders while
 * `appPhase === "location-select"`; once the operator launches the
 * simulation we flip to `"main"` and the existing twin shell takes over.
 */
export type AppPhase = "location-select" | "main";

/** Latest `sendUserMessage` id — drop stale responses if the user sends again while in flight. */
let latestChatSendId = 0;

/** Live state fetcher token — bumped on city/printer change so stale fetches are dropped. */
let latestLiveFetchId = 0;

/** Source of the snapshot the UI is reading.
 *  - `mock`: the deterministic in-browser simulator (`snapshotAtTick`)
 *  - `live`: the FastAPI `/twin/state` (real Stage 1 parquet + Stage 2 forecast)
 */
export type TwinDataSource = "mock" | "live";

interface TwinState {
  /** Which top-level surface is rendered (landing vs. main twin shell). */
  appPhase: AppPhase;
  /** Physical location of the printer; null until the operator confirms. */
  selectedCity: City | null;
  /** Picked from the printers backing the chosen city (auto-set after confirmCity). */
  selectedPrinterId: number | null;
  /** Where today's snapshot is coming from. */
  dataSource: TwinDataSource;
  /** True while a `/twin/state` request is in flight — prevents request pileup. */
  fetchInflight: boolean;

  tick: number;
  snapshot: SystemSnapshot;
  /** Store-tick value at which the *current* snapshot landed. Used to
   *  smoothly interpolate ETAs (`daysUntilFailure`,
   *  `daysUntilCritical`) between snapshot fetches: the displayed ETA
   *  decrements by `(tick - snapshotMarkTick)` sim-days (1 tick = 1 day). */
  snapshotMarkTick: number;
  alerts: Alert[];
  alertHistory: Alert[];
  /** Last `seenAlertIds` — used to surface "new" alerts with toast/animation. */
  newAlertIds: string[];

  paused: boolean;
  speed: number; // 1 = real time (1 tick/sec), 4 = 4x faster, etc.

  selectedComponentId: ComponentId | null;
  highlightComponentId: ComponentId | null;
  commandPaletteOpen: boolean;
  /** SpotlightChat overlay (⌘K / FAB). */
  chatOpen: boolean;
  /**
   * Operator's preference for the right-hand telemetry panel.
   * The panel is shown iff `dashboardOpen && !selectedComponentId` — i.e. it
   * auto-hides during a component zoom and is restored on zoom-out, so the
   * user keeps full agency without us inventing a separate "mode" enum.
   */
  dashboardOpen: boolean;
  /**
   * Background visualization. "2d" = SVG schematic, "3d" = R3F spatial twin,
   * "analytics" = bento-grid ML/telemetry overview rendered over a heavily
   * blurred copy of the underlying scene. The selected component, dashboard,
   * AR card, chat, etc. are all view-agnostic — they read the same store.
   */
  viewMode: "2d" | "3d" | "analytics";
  /** When true while focused in 3D, user can orbit/pan freely. */
  cameraOpen: boolean;

  /**
   * Predictive forecast scrubber state.
   *
   * `forecastHorizonDays === 0` means the UI is in **Live Mode** — the
   * snapshot reflects right-now telemetry. Any value > 0 puts the UI in
   * **Predictive Mode**: the dashboard reads simulated future state at
   * `now + forecastHorizonDays` (clamped to `forecastHorizonMax`).
   *
   * `forecastPlaying` drives an auto-advance loop in the scrubber
   * component (it owns the rAF, not the store) — when true the scrubber
   * walks `forecastHorizonDays` forward at `forecastSpeed` × default-rate
   * until it hits the right edge.
   */
  forecastHorizonDays: number;
  forecastHorizonMax: number;
  forecastPlaying: boolean;
  forecastSpeed: number;

  /**
   * Mock "Execute Print" — purely cosmetic right now. While true, the 3D
   * recoater translates back and forth and a warm point light pulses
   * inside the build chamber. The store flips back to false on its own
   * after `PRINT_ANIMATION_MS`.
   */
  executingPrint: boolean;

  messages: ChatMessage[];
  isThinking: boolean;
  /** Si el backend FastAPI responde en `/health` (proxy `/api` o URL absoluta). */
  chatApiStatus: "unknown" | "live" | "offline";
  /**
   * Watchdog / historian alerts pushed over `WebSocket` (`/ws/notifications`) —
   * merged (first) in the overview alert strip.
   */
  backendPulseAlerts: Alert[];

  /* Actions */
  /** Persist the operator's chosen city; does NOT change phase.
   *  Side effect: triggers a printer auto-pick + first live state fetch when
   *  the API is reachable. */
  confirmCity: (city: City) => void;
  /** Manually override the auto-picked printer. */
  setSelectedPrinter: (id: number | null) => void;
  /** Flip from landing to the main twin shell. */
  launchSimulation: () => void;
  advance: () => void;
  jumpForward: (ticks: number) => void;
  /** Absolute tick scrub — used by the expanded transport timeline. Negative
   *  values are clamped to 0; live-mode triggers a re-fetch on day boundary. */
  setTick: (tick: number) => void;
  reset: () => void;
  setPaused: (p: boolean) => void;
  setSpeed: (s: number) => void;
  selectComponent: (id: ComponentId | null) => void;
  highlightComponent: (id: ComponentId | null) => void;
  setCommandPaletteOpen: (o: boolean) => void;
  setChatOpen: (o: boolean) => void;
  setDashboardOpen: (o: boolean) => void;
  toggleDashboard: () => void;
  setViewMode: (m: "2d" | "3d" | "analytics") => void;
  setCameraOpen: (open: boolean) => void;
  setForecastHorizon: (days: number) => void;
  setForecastPlaying: (playing: boolean) => void;
  setForecastSpeed: (speed: number) => void;
  resetToLive: () => void;
  executePrint: () => void;
  sendUserMessage: (text: string) => void;
  refreshChatApiStatus: () => Promise<void>;
  ingestProactiveNotification: (payload: Record<string, unknown>) => void;
}

// 1 tick = 1 sim day. Starting on day 150 gives the printer 5 months of
// runtime so the simulator has had a chance to build up real degradation
// before the operator looks at it.
const INITIAL_TICK = 150;

/** Width of the predictive horizon, in days. Caps how far the scrubber goes. */
const FORECAST_HORIZON_MAX_DAYS = 30;
/** Total ms the mock "Execute Print" animation runs end-to-end. */
const PRINT_ANIMATION_MS = 5000;

function buildState(tick: number, prevAlertIds: Set<string>) {
  const snapshot = snapshotAtTick(tick);
  const alerts = deriveAlerts(snapshot);
  const newAlertIds = alerts.filter((a) => !prevAlertIds.has(stableAlertKey(a))).map((a) => a.id);
  return { snapshot, alerts, newAlertIds };
}

/** A stable identity for an alert across ticks (so it doesn't re-fire every second). */
function stableAlertKey(a: Alert): string {
  // Strip the trailing -<tick> from the id.
  return a.id.replace(/-(\d+)$/, "");
}

function sevFromAgentString(raw: string): AlertSeverity {
  const u = raw.toUpperCase();
  if (u === "CRITICAL" || u === "WARNING" || u === "INFO") return u;
  if (u.includes("CRIT")) return "CRITICAL";
  if (u.includes("WARN")) return "WARNING";
  return "CRITICAL";
}

const initial = (() => {
  const { snapshot, alerts } = buildState(INITIAL_TICK, new Set());
  const seedMessage: ChatMessage = {
    id: "seed-1",
    role: "assistant",
    text: "Aether co-pilot online. I'm watching every component live and projecting 45 minutes ahead. Ask me anything — try \"What's the highest-risk component?\" or hit ⌘K.",
    createdAt: new Date().toISOString(),
  };
  return { snapshot, alerts, newAlertIds: [] as string[], seedMessage };
})();

export const useTwin = create<TwinState>((set, get) => ({
  appPhase: "location-select",
  selectedCity: null,
  selectedPrinterId: null,
  dataSource: "mock",
  fetchInflight: false,

  tick: INITIAL_TICK,
  snapshot: initial.snapshot,
  snapshotMarkTick: INITIAL_TICK,
  alerts: initial.alerts,
  alertHistory: [],
  newAlertIds: initial.newAlertIds,

  paused: false,
  speed: 1, // 1× = real-time. The expanded transport bar lets the operator
            // boost to 32× when they want to skim across days quickly.

  selectedComponentId: null,
  highlightComponentId: null,
  commandPaletteOpen: false,
  chatOpen: false,
  dashboardOpen: true,
  viewMode: "3d",
  cameraOpen: false,

  forecastHorizonDays: 0,
  forecastHorizonMax: FORECAST_HORIZON_MAX_DAYS,
  forecastPlaying: false,
  forecastSpeed: 1,
  executingPrint: false,

  messages: [initial.seedMessage],
  isThinking: false,
  chatApiStatus: "unknown",
  backendPulseAlerts: [],

  refreshChatApiStatus: async () => {
    const ok = await probeTwinApiHealth();
    set({ chatApiStatus: ok ? "live" : "offline" });
  },

  confirmCity: (city) => {
    set({ selectedCity: city, selectedPrinterId: null });
    // Fire-and-forget: try to fetch the printer roster from the backend, pick
    // the first one, and switch the snapshot source to live. If anything
    // fails (API down, city not in parquet, etc.) we silently stay on mock.
    const ticket = ++latestLiveFetchId;
    void (async () => {
      const backendCity = backendCityName(city);
      try {
        const printers = await listPrinters(backendCity);
        if (ticket !== latestLiveFetchId) return;
        if (printers.length === 0) return;
        const pid = printers[0];
        const day = tickToDay(get().tick);
        const live = await fetchTwinState({ city: backendCity, printerId: pid, day });
        if (ticket !== latestLiveFetchId) return;
        const alerts = deriveAlerts(live);
        set({
          selectedPrinterId: pid,
          dataSource: "live",
          snapshot: live,
          snapshotMarkTick: get().tick,
          alerts,
        });
      } catch {
        if (ticket !== latestLiveFetchId) return;
        set({ dataSource: "mock" });
      }
    })();
  },
  setSelectedPrinter: (id) => set({ selectedPrinterId: id }),
  launchSimulation: () => set({ appPhase: "main" }),

  advance: () => {
    const {
      tick, alerts, alertHistory, paused, speed,
      dataSource, selectedCity, selectedPrinterId, fetchInflight,
    } = get();
    if (paused) return;
    const nextTick = tick + speed;

    if (dataSource === "live" && selectedCity && selectedPrinterId !== null) {
      // Always advance the tick — the visual clock keeps moving even while
      // a fetch is in flight; we only debounce the network call.
      set({ tick: nextTick });
      if (fetchInflight) return;

      const prevDay = tickToDay(tick);
      const nextDay = tickToDay(nextTick);
      // Only refetch on day boundaries — within a day the parquet has nothing
      // new to say, so polling 8×/sec would be wasted load.
      if (nextDay === prevDay) return;

      const ticket = ++latestLiveFetchId;
      const backendCity = backendCityName(selectedCity);
      set({ fetchInflight: true });
      void (async () => {
        try {
          const live = await fetchTwinState({
            city: backendCity, printerId: selectedPrinterId, day: nextDay,
          });
          if (ticket !== latestLiveFetchId) return;
          const prevKeys = new Set(get().alerts.map(stableAlertKey));
          const nextAlerts = deriveAlerts(live);
          const newAlertIds = nextAlerts
            .filter((a) => !prevKeys.has(stableAlertKey(a)))
            .map((a) => a.id);
          const trulyNew = nextAlerts.filter((a) => !prevKeys.has(stableAlertKey(a)));
          const updatedHistory = [...trulyNew, ...get().alertHistory].slice(0, 80);
          set({
            snapshot: live,
            snapshotMarkTick: get().tick,
            alerts: nextAlerts,
            newAlertIds,
            alertHistory: updatedHistory,
            fetchInflight: false,
          });
        } catch {
          if (ticket !== latestLiveFetchId) return;
          // Backend hiccup — keep ticking against the mock until it recovers.
          set({ fetchInflight: false, dataSource: "mock" });
        }
      })();
      return;
    }

    // Mock path — unchanged behaviour for offline / pre-fetch demos.
    const prevKeys = new Set(alerts.map(stableAlertKey));
    const next = buildState(nextTick, prevKeys);
    const trulyNew = next.alerts.filter((a) => !prevKeys.has(stableAlertKey(a)));
    const updatedHistory = [...trulyNew, ...alertHistory].slice(0, 80);
    set({
      tick: nextTick,
      snapshot: next.snapshot,
      snapshotMarkTick: nextTick,
      alerts: next.alerts,
      newAlertIds: next.newAlertIds,
      alertHistory: updatedHistory,
    });
  },

  jumpForward: (ticks) => {
    get().setTick(get().tick + ticks);
  },

  setTick: (target) => {
    const {
      tick, alerts, alertHistory,
      dataSource, selectedCity, selectedPrinterId,
    } = get();
    const next = Math.max(0, Math.floor(target));
    if (next === tick) return;

    if (dataSource === "live" && selectedCity && selectedPrinterId !== null) {
      // Live mode: jump tick visually right away, then debounce a fetch on
      // the day boundary so the scrubber feels responsive even mid-drag.
      set({ tick: next });
      const prevDay = tickToDay(tick);
      const nextDay = tickToDay(next);
      if (nextDay === prevDay) return;
      const ticket = ++latestLiveFetchId;
      const backendCity = backendCityName(selectedCity);
      set({ fetchInflight: true });
      void (async () => {
        try {
          const live = await fetchTwinState({
            city: backendCity, printerId: selectedPrinterId, day: nextDay,
          });
          if (ticket !== latestLiveFetchId) return;
          const prevKeys = new Set(get().alerts.map(stableAlertKey));
          const nextAlerts = deriveAlerts(live);
          const newAlertIds = nextAlerts
            .filter((a) => !prevKeys.has(stableAlertKey(a)))
            .map((a) => a.id);
          const trulyNew = nextAlerts.filter((a) => !prevKeys.has(stableAlertKey(a)));
          const updatedHistory = [...trulyNew, ...get().alertHistory].slice(0, 80);
          set({
            snapshot: live, snapshotMarkTick: get().tick,
            alerts: nextAlerts, newAlertIds,
            alertHistory: updatedHistory, fetchInflight: false,
          });
        } catch {
          if (ticket !== latestLiveFetchId) return;
          set({ fetchInflight: false, dataSource: "mock" });
        }
      })();
      return;
    }

    // Mock path
    const prevKeys = new Set(alerts.map(stableAlertKey));
    const built = buildState(next, prevKeys);
    const trulyNew = built.alerts.filter((a) => !prevKeys.has(stableAlertKey(a)));
    const updatedHistory = [...trulyNew, ...alertHistory].slice(0, 80);
    set({
      tick: next,
      snapshot: built.snapshot,
      snapshotMarkTick: next,
      alerts: built.alerts,
      newAlertIds: built.newAlertIds,
      alertHistory: updatedHistory,
    });
  },

  reset: () => {
    const next = buildState(INITIAL_TICK, new Set());
    set({
      tick: INITIAL_TICK,
      snapshot: next.snapshot,
      snapshotMarkTick: INITIAL_TICK,
      alerts: next.alerts,
      newAlertIds: [],
      alertHistory: [],
      backendPulseAlerts: [],
      dataSource: "mock",
      selectedPrinterId: null,
      fetchInflight: false,
    });
  },

  setPaused: (p) => set({ paused: p }),
  setSpeed: (s) => set({ speed: s }),
  selectComponent: (id) => set({ selectedComponentId: id, cameraOpen: id ? get().cameraOpen : false }),
  highlightComponent: (id) => set({ highlightComponentId: id }),
  setCommandPaletteOpen: (o) => set({ commandPaletteOpen: o }),
  setChatOpen: (o) => set({ chatOpen: o }),
  setDashboardOpen: (o) => set({ dashboardOpen: o }),
  toggleDashboard: () => set((s) => ({ dashboardOpen: !s.dashboardOpen })),
  setViewMode: (m) => set({ viewMode: m, cameraOpen: m === "3d" ? get().cameraOpen : false }),
  setCameraOpen: (open) => set({ cameraOpen: open }),

  setForecastHorizon: (days) => {
    const clamped = Math.max(0, Math.min(get().forecastHorizonMax, days));
    // Stop auto-play the moment the operator drags the thumb back to 0.
    const stillPlaying = clamped > 0 ? get().forecastPlaying : false;
    set({ forecastHorizonDays: clamped, forecastPlaying: stillPlaying });
  },
  setForecastPlaying: (playing) => {
    // Pressing play from Live mode should kick the scrubber off zero so
    // the auto-advance loop has somewhere to walk to. The actual ramp is
    // owned by the scrubber's rAF (decoupled from the store's tick loop).
    if (playing && get().forecastHorizonDays === 0) {
      set({ forecastPlaying: true, forecastHorizonDays: 0.001 });
      return;
    }
    set({ forecastPlaying: playing });
  },
  setForecastSpeed: (speed) => set({ forecastSpeed: speed }),
  resetToLive: () => set({ forecastHorizonDays: 0, forecastPlaying: false }),

  executePrint: () => {
    if (get().executingPrint) return; // re-entry guard
    set({ executingPrint: true });
    setTimeout(() => set({ executingPrint: false }), PRINT_ANIMATION_MS);
  },

  ingestProactiveNotification: (payload) => {
    if (payload.type !== "PROACTIVE_ALERT") return;
    const component = typeof payload.component === "string" ? payload.component : "unknown";
    const status = typeof payload.status === "string" ? payload.status : "ALERT";
    const parsed = tryParseAgentReport(payload.report);
    if (!parsed.ok) return;

    const snap = get().snapshot;
    const { id, label } = resolveComponentForAgent(component, snap, null);
    const msg = makeWatchdogAssistantMessage(
      parsed.report,
      label,
      snap.tick,
      id,
      `Watchdog · ${label} (${status})`,
    );
    const pulse: Alert = {
      id: `proactive-ws-${Date.now()}-${id}`,
      componentId: id,
      componentLabel: label,
      severity: sevFromAgentString(parsed.report.severity_indicator),
      kind: "current",
      title: `Watchdog: ${label} ${status}`,
      detail: parsed.report.grounded_text.slice(0, 220),
      raisedAtTick: snap.tick,
      raisedAtIso: new Date().toISOString(),
    };
    set((s) => ({
      messages: [...s.messages, msg],
      backendPulseAlerts: [pulse, ...s.backendPulseAlerts].slice(0, 20),
    }));
  },

  sendUserMessage: (text) => {
    const trimmed = text.trim();
    if (!trimmed) return;

    const sendId = ++latestChatSendId;
    const prior = get().messages;
    const userMsg = makeUserMessage(trimmed);

    set({ messages: [...prior, userMsg], isThinking: true });

    const snap = get().snapshot;
    const selectedId = get().selectedComponentId;
    const focused = selectedId ? snap.components.find((c) => c.id === selectedId) : null;
    const focusedForecast = focused ? snap.forecasts.find((f) => f.id === focused.id) : null;

    // Tag the query with spatial focus so the agent answers about *this* part by default.
    // We send the augmented query to the API but keep the user's chat bubble untouched.
    const contextLine = focused
      ? `[Operator focus → component "${focused.label}" (id=${focused.id}, status=${focused.status}, health=${(focused.healthIndex * 100).toFixed(0)}%${
          focusedForecast ? `, predicted_health=${(focusedForecast.predictedHealthIndex * 100).toFixed(0)}%` : ""
        }). Prefer answers about this part unless the user asks otherwise.]\n\n`
      : "";
    const apiQuery = `${contextLine}${trimmed}`;
    const run_identifier = `twin-${snap.tick}-${snap.timestamp}${focused ? `-focus-${focused.id}` : ""}`;
    const thread_id = getOrCreateAgentThreadId();
    const { id: evId, label: evLabel } = resolveComponentForAgent(
      focused ? focused.id : "recoater_blade",
      snap,
      focused ? selectedId : null,
    );

    void (async () => {
      try {
        const res = await queryAgent({
          query: apiQuery,
          thread_id,
          run_identifier,
        });
        if (sendId !== latestChatSendId) return;
        set((s) => ({
          messages: [
            ...s.messages,
            makeAssistantFromAgentReport(res, {
              tick: snap.tick,
              evidenceComponent: evId,
              componentLabel: evLabel,
            }),
          ],
          isThinking: false,
          chatApiStatus: "live",
        }));
      } catch {
        if (sendId !== latestChatSendId) return;
        const reply = answer(trimmed, snap);
        set((s) => ({
          messages: [...s.messages, makeAssistantMessage(reply)],
          isThinking: false,
          chatApiStatus: "offline",
        }));
      }
    })();
  },
}));
