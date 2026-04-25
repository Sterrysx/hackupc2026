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
import { snapshotAtTick } from "@/lib/mockData";
import { deriveAlerts } from "@/lib/alerts";
import { probeTwinApiHealth, queryAgent } from "@/lib/agentApi";
import { getOrCreateAgentThreadId } from "@/lib/agentThread";
import { resolveComponentForAgent, tryParseAgentReport } from "@/lib/componentMap";
import {
  answer,
  makeAssistantFromAgentReport,
  makeAssistantMessage,
  makeUserMessage,
  makeWatchdogAssistantMessage,
} from "@/lib/rag";

/** Latest `sendUserMessage` id — drop stale responses if the user sends again while in flight. */
let latestChatSendId = 0;

interface TwinState {
  tick: number;
  snapshot: SystemSnapshot;
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
   * Background visualization. The selected component, dashboard, AR card,
   * chat, etc. are all view-agnostic — they read the same store either way.
   */
  viewMode: "2d" | "3d";
  /** When true while focused in 3D, user can orbit/pan freely. */
  cameraOpen: boolean;

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
  advance: () => void;
  jumpForward: (ticks: number) => void;
  reset: () => void;
  setPaused: (p: boolean) => void;
  setSpeed: (s: number) => void;
  selectComponent: (id: ComponentId | null) => void;
  highlightComponent: (id: ComponentId | null) => void;
  setCommandPaletteOpen: (o: boolean) => void;
  setChatOpen: (o: boolean) => void;
  setDashboardOpen: (o: boolean) => void;
  toggleDashboard: () => void;
  setViewMode: (m: "2d" | "3d") => void;
  setCameraOpen: (open: boolean) => void;
  sendUserMessage: (text: string) => void;
  refreshChatApiStatus: () => Promise<void>;
  ingestProactiveNotification: (payload: Record<string, unknown>) => void;
}

const INITIAL_TICK = 1200; // start a few hours in so degradation is visible

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
  tick: INITIAL_TICK,
  snapshot: initial.snapshot,
  alerts: initial.alerts,
  alertHistory: [],
  newAlertIds: initial.newAlertIds,

  paused: false,
  speed: 8, // demo-friendly default — visible movement without being chaotic

  selectedComponentId: null,
  highlightComponentId: null,
  commandPaletteOpen: false,
  chatOpen: false,
  dashboardOpen: true,
  viewMode: "3d",
  cameraOpen: false,

  messages: [initial.seedMessage],
  isThinking: false,
  chatApiStatus: "unknown",
  backendPulseAlerts: [],

  refreshChatApiStatus: async () => {
    const ok = await probeTwinApiHealth();
    set({ chatApiStatus: ok ? "live" : "offline" });
  },

  advance: () => {
    const { tick, alerts, alertHistory, paused, speed } = get();
    if (paused) return;
    const nextTick = tick + speed;
    const prevKeys = new Set(alerts.map(stableAlertKey));
    const next = buildState(nextTick, prevKeys);
    // Append newly-raised alerts to history (capped).
    const trulyNew = next.alerts.filter((a) => !prevKeys.has(stableAlertKey(a)));
    const updatedHistory = [...trulyNew, ...alertHistory].slice(0, 80);
    set({
      tick: nextTick,
      snapshot: next.snapshot,
      alerts: next.alerts,
      newAlertIds: next.newAlertIds,
      alertHistory: updatedHistory,
    });
  },

  jumpForward: (ticks) => {
    const { tick, alerts, alertHistory } = get();
    const nextTick = tick + ticks;
    const prevKeys = new Set(alerts.map(stableAlertKey));
    const next = buildState(nextTick, prevKeys);
    const trulyNew = next.alerts.filter((a) => !prevKeys.has(stableAlertKey(a)));
    const updatedHistory = [...trulyNew, ...alertHistory].slice(0, 80);
    set({
      tick: nextTick,
      snapshot: next.snapshot,
      alerts: next.alerts,
      newAlertIds: next.newAlertIds,
      alertHistory: updatedHistory,
    });
  },

  reset: () => {
    const next = buildState(INITIAL_TICK, new Set());
    set({
      tick: INITIAL_TICK,
      snapshot: next.snapshot,
      alerts: next.alerts,
      newAlertIds: [],
      alertHistory: [],
      backendPulseAlerts: [],
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
