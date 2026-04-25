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
  ChatMessage,
  ComponentId,
  SystemSnapshot,
} from "@/types/telemetry";
import { snapshotAtTick } from "@/lib/mockData";
import { deriveAlerts } from "@/lib/alerts";
import { answer, makeAssistantMessage, makeUserMessage } from "@/lib/rag";

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
  chatOpen: boolean;
  /** Top-level UI mode: dashboard panels visible, or immersive (panels hidden). */
  mode: "dashboard" | "immersive";
  /** Whether the floating Aether chat bubble is expanded into a panel. */
  bubbleOpen: boolean;

  messages: ChatMessage[];
  isThinking: boolean;

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
  setMode: (m: "dashboard" | "immersive") => void;
  setBubbleOpen: (o: boolean) => void;
  sendUserMessage: (text: string) => void;
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

const initial = (() => {
  const { snapshot, alerts } = buildState(INITIAL_TICK, new Set());
  const seedMessage: ChatMessage = {
    id: "seed-1",
    role: "assistant",
    text: "Aether co-pilot online. I'm watching every component live and projecting 45 minutes ahead. Ask me anything — try \"What's the highest-risk component?\" or hit ⌘K.",
    severity: "INFO",
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
  mode: "dashboard",
  bubbleOpen: false,

  messages: [initial.seedMessage],
  isThinking: false,

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
    });
  },

  setPaused: (p) => set({ paused: p }),
  setSpeed: (s) => set({ speed: s }),
  selectComponent: (id) => set({ selectedComponentId: id }),
  highlightComponent: (id) => set({ highlightComponentId: id }),
  setCommandPaletteOpen: (o) => set({ commandPaletteOpen: o }),
  setMode: (m) => set({ mode: m }),
  setBubbleOpen: (o) => set({ bubbleOpen: o }),
  setChatOpen: (o) => set({ chatOpen: o }),

  sendUserMessage: (text) => {
    const trimmed = text.trim();
    if (!trimmed) return;
    const userMsg = makeUserMessage(trimmed);
    set((s) => ({ messages: [...s.messages, userMsg], isThinking: true }));
    // Bumped to ~700ms so the typing indicator is actually visible.
    const snap = get().snapshot;
    setTimeout(() => {
      const reply = answer(trimmed, snap);
      set((s) => ({
        messages: [...s.messages, makeAssistantMessage(reply)],
        isThinking: false,
      }));
    }, 700);
  },
}));
