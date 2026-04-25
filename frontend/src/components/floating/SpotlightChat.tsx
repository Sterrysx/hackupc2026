import { useCallback, useEffect, useRef, useState } from "react";
import { motion, AnimatePresence } from "framer-motion";
import { MessageSquare, Send, Sparkles, X } from "lucide-react";
import { useTwin } from "@/store/twin";
import { Button } from "@/components/ui/Button";
import { Badge, severityToTone, severityLabel } from "@/components/ui/Badge";
import { ChatThinking } from "@/components/ui/Skeleton";
import { MicButton } from "@/components/floating/MicButton";
import type { ChatMessage, ComponentId, RagCitation } from "@/types/telemetry";

const APPLE_EASE: [number, number, number, number] = [0.16, 1, 0.3, 1];

// Native-feel spring; lands fast, settles softly. Apple-y.
const SPRING = { type: "spring" as const, stiffness: 380, damping: 30, mass: 0.7 };

const SUGGESTIONS_GLOBAL = [
  "What's the highest-risk component?",
  "When should I service the printer?",
  "Forecast next 45 minutes",
];

function chatApiStatusLabel(status: "unknown" | "live" | "offline"): { dot: string; text: string } {
  if (status === "live") return { dot: "bg-emerald-400/90", text: "Agent connected" };
  if (status === "offline") return { dot: "bg-amber-400/90", text: "Offline · local replies" };
  return { dot: "bg-white/25", text: "Checking API…" };
}

/**
 * SpotlightChat — summonable Aether overlay.
 *
 *   - FAB at bottom-right is the only persistent chat affordance.
 *   - ⌘K (Cmd/Ctrl + K) toggles the overlay; Esc closes it.
 *   - Click-out on the dimmed backdrop closes it.
 *   - When a component is focused, the header shows a "Focused on …" chip and
 *     the composer placeholder reads "Ask Aether about the {part}…".
 */
export function SpotlightChat() {
  const open = useTwin((s) => s.chatOpen);
  const setOpen = useTwin((s) => s.setChatOpen);
  const messages = useTwin((s) => s.messages);
  const isThinking = useTwin((s) => s.isThinking);
  const chatApiStatus = useTwin((s) => s.chatApiStatus);
  const sendUserMessage = useTwin((s) => s.sendUserMessage);
  const highlightComponent = useTwin((s) => s.highlightComponent);
  const selectedId = useTwin((s) => s.selectedComponentId);
  const snapshot = useTwin((s) => s.snapshot);
  const alerts = useTwin((s) => s.alerts);

  const focused = selectedId ? snapshot.components.find((c) => c.id === selectedId) ?? null : null;

  const [draft, setDraft] = useState("");
  const scrollRef = useRef<HTMLDivElement>(null);
  const inputRef = useRef<HTMLInputElement>(null);
  const statusUi = chatApiStatusLabel(chatApiStatus);
  const critCount = alerts.filter((a) => a.severity === "CRITICAL").length;

  // ⌘K toggles, Esc closes — global.
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      // Don't fight ⌘⇧K (CommandPalette).
      if ((e.metaKey || e.ctrlKey) && !e.shiftKey && e.key.toLowerCase() === "k") {
        e.preventDefault();
        setOpen(!open);
      }
      if (e.key === "Escape" && open) setOpen(false);
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [open, setOpen]);

  useEffect(() => {
    if (open) {
      // Focus the composer on open (after the spring settles a tick).
      const t = setTimeout(() => inputRef.current?.focus(), 80);
      return () => clearTimeout(t);
    }
  }, [open]);

  useEffect(() => {
    scrollRef.current?.scrollTo({ top: scrollRef.current.scrollHeight, behavior: "smooth" });
  }, [messages.length, isThinking, open]);

  const submit = () => {
    const trimmed = draft.trim();
    if (!trimmed) return;
    sendUserMessage(trimmed);
    setDraft("");
  };

  // Voice → drop the transcript into the draft so the user can review/edit
  // before sending. Append (with a single space) if there's already text.
  const handleTranscript = useCallback((text: string) => {
    setDraft((d) => {
      const t = text.trim();
      if (!t) return d;
      return d.trim() ? `${d.trim()} ${t}` : t;
    });
    inputRef.current?.focus();
  }, []);

  const placeholder = focused ? `Ask Aether about the ${focused.label}…` : "Ask Aether…";
  const showSuggestions = !focused && messages.length <= 2 && !isThinking;

  return (
    <>
      {/* Subtle dim/blur backdrop — click anywhere to dismiss. */}
      <AnimatePresence>
        {open && (
          <motion.div
            key="spotlight-backdrop"
            initial={{ opacity: 0 }}
            animate={{ opacity: 1 }}
            exit={{ opacity: 0 }}
            transition={{ duration: 0.18, ease: APPLE_EASE }}
            onClick={() => setOpen(false)}
            className="fixed inset-0 z-30 bg-[oklch(0.10_0.005_260/0.32)] backdrop-blur-[2px]"
          />
        )}
      </AnimatePresence>

      {/* The panel — origin pinned to the FAB so it scales out from the button. */}
      <AnimatePresence>
        {open && (
          <motion.section
            key="spotlight-panel"
            initial={{ opacity: 0, scale: 0.94, y: 12 }}
            animate={{ opacity: 1, scale: 1, y: 0 }}
            exit={{ opacity: 0, scale: 0.96, y: 8 }}
            transition={SPRING}
            style={{ transformOrigin: "bottom right" }}
            className="
              fixed bottom-24 right-6 z-40
              w-[420px] max-w-[calc(100vw-3rem)]
              h-[min(580px,72vh)]
              flex flex-col overflow-hidden
              rounded-[28px] glass-floating
            "
            role="dialog"
            aria-label="Aether chat"
          >
            {/* Header */}
            <header className="flex items-center justify-between gap-3 px-5 pt-4 pb-3 flex-shrink-0">
              <div className="flex items-center gap-2 min-w-0">
                <div className="w-6 h-6 rounded-full flex items-center justify-center bg-[var(--color-accent-soft)] flex-shrink-0">
                  <Sparkles size={12} className="text-[var(--color-accent)]" />
                </div>
                <div className="flex flex-col min-w-0 leading-tight">
                  <span className="text-[12.5px] font-medium tracking-tight">Aether</span>
                  <span className="text-[10px] uppercase tracking-[0.16em] text-[var(--color-fg-faint)]">
                    grounded co-pilot
                  </span>
                </div>
              </div>
              <div className="flex items-center gap-2 flex-shrink-0">
                <div
                  className="flex items-center gap-1.5"
                  title="The frontend talks to /api/… (Vite proxy → :8000)."
                >
                  <span className={`h-1.5 w-1.5 rounded-full ${statusUi.dot}`} aria-hidden />
                  <span className="text-[10px] text-[var(--color-fg-muted)]">{statusUi.text}</span>
                </div>
                <button
                  type="button"
                  onClick={() => setOpen(false)}
                  className="h-7 w-7 rounded-full flex items-center justify-center text-[var(--color-fg-muted)] hover:text-[var(--color-fg)] hover:bg-white/[0.06] transition-colors"
                  title="Close (Esc)"
                  aria-label="Close chat"
                >
                  <X size={13} />
                </button>
              </div>
            </header>

            {/* Focus chip — appears whenever a part is selected so the user knows context is locked in. */}
            <AnimatePresence initial={false}>
              {focused && (
                <motion.div
                  key="focus-chip"
                  initial={{ opacity: 0, y: -4, height: 0 }}
                  animate={{ opacity: 1, y: 0, height: "auto" }}
                  exit={{ opacity: 0, y: -4, height: 0 }}
                  transition={{ duration: 0.22, ease: APPLE_EASE }}
                  className="px-5 pb-2 flex-shrink-0"
                >
                  <div className="inline-flex items-center gap-1.5 px-2.5 py-1 rounded-full bg-[var(--color-accent-soft)] text-[10.5px] text-[var(--color-fg)]">
                    <Sparkles size={10} className="text-[var(--color-accent)]" />
                    Focused on {focused.label}
                  </div>
                </motion.div>
              )}
            </AnimatePresence>

            <div className="h-px mx-2 bg-[var(--color-border)]" />

            {/* Messages */}
            <div
              ref={scrollRef}
              className="flex-1 overflow-y-auto px-5 pt-3 pb-3 flex flex-col gap-3 min-h-0"
            >
              <AnimatePresence initial={false}>
                {messages.map((m) => (
                  <Message key={m.id} message={m} onCiteHover={highlightComponent} />
                ))}
              </AnimatePresence>
              {isThinking && (
                <motion.div
                  key="thinking"
                  initial={{ opacity: 0, y: 4 }}
                  animate={{ opacity: 1, y: 0 }}
                  exit={{ opacity: 0 }}
                  transition={{ duration: 0.25, ease: APPLE_EASE }}
                  className="flex justify-start"
                >
                  <ChatThinking />
                </motion.div>
              )}
            </div>

            {/* Suggestions — only when nothing's focused (focused state has its own composer hint). */}
            {showSuggestions && (
              <div className="px-5 pb-2 flex flex-wrap gap-1.5 flex-shrink-0">
                {SUGGESTIONS_GLOBAL.map((s) => (
                  <button
                    key={s}
                    onClick={() => sendUserMessage(s)}
                    className="text-[11px] px-2.5 py-1.5 rounded-full bg-white/[0.06] text-[var(--color-fg-muted)] hover:text-[var(--color-fg)] hover:bg-white/[0.10] transition-all"
                  >
                    {s}
                  </button>
                ))}
              </div>
            )}

            {/* Composer */}
            <form
              className="m-4 mt-1 flex items-center gap-1.5 bg-white/[0.06] rounded-full pl-4 pr-1.5 py-1.5 flex-shrink-0 focus-within:bg-white/[0.10] transition-colors"
              onSubmit={(e) => {
                e.preventDefault();
                submit();
              }}
            >
              <input
                ref={inputRef}
                value={draft}
                onChange={(e) => setDraft(e.target.value)}
                placeholder={placeholder}
                className="flex-1 bg-transparent outline-none text-[13px] text-[var(--color-fg)] placeholder:text-[var(--color-fg-faint)]"
              />
              <MicButton
                onTranscript={handleTranscript}
                hint={focused ? `Speak about the ${focused.label}…` : "Talk to Aether"}
              />
              <Button type="submit" variant="primary" size="icon" disabled={!draft.trim() || isThinking}>
                <Send size={13} />
              </Button>
            </form>
          </motion.section>
        )}
      </AnimatePresence>

      {/* FAB — the only persistent chat affordance. Always visible. */}
      <motion.button
        type="button"
        initial={{ opacity: 0, scale: 0.85 }}
        animate={{ opacity: 1, scale: 1 }}
        transition={{ duration: 0.32, ease: APPLE_EASE, delay: 0.05 }}
        onClick={() => setOpen(!open)}
        title={open ? "Close Aether (Esc)" : "Ask Aether (⌘K)"}
        aria-label={open ? "Close Aether chat" : "Open Aether chat"}
        className="fixed bottom-6 right-6 z-50 h-14 w-14 rounded-full glass-floating flex items-center justify-center hover:scale-105 active:scale-95 transition-transform"
      >
        <AnimatePresence mode="wait" initial={false}>
          {open ? (
            <motion.span
              key="x"
              initial={{ rotate: -45, opacity: 0 }}
              animate={{ rotate: 0, opacity: 1 }}
              exit={{ rotate: 45, opacity: 0 }}
              transition={{ duration: 0.18 }}
              className="text-[var(--color-fg)]"
            >
              <X size={18} />
            </motion.span>
          ) : (
            <motion.span
              key="chat"
              initial={{ scale: 0.85, opacity: 0 }}
              animate={{ scale: 1, opacity: 1 }}
              exit={{ scale: 0.85, opacity: 0 }}
              transition={{ duration: 0.18 }}
              className="text-[var(--color-accent)]"
            >
              <MessageSquare size={18} />
            </motion.span>
          )}
        </AnimatePresence>

        {/* Coral dot when something critical is on fire. */}
        {!open && critCount > 0 && (
          <span
            className="absolute -top-0.5 -right-0.5 h-3 w-3 rounded-full"
            style={{
              background: "var(--color-crit)",
              border: "2px solid oklch(0.18 0.003 260)",
            }}
          />
        )}
      </motion.button>
    </>
  );
}

/* ── Subviews (mirror EmbeddedChat's bubbles so the look stays consistent) ── */

function Message({
  message,
  onCiteHover,
}: {
  message: ChatMessage;
  onCiteHover: (id: ComponentId | null) => void;
}) {
  const isUser = message.role === "user";
  return (
    <motion.div
      layout
      initial={{ opacity: 0, y: 6 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{ duration: 0.28, ease: APPLE_EASE }}
      className={`flex ${isUser ? "justify-end" : "justify-start"}`}
    >
      <div className={`max-w-[88%] flex flex-col gap-1.5 ${isUser ? "items-end" : "items-start"}`}>
        <div
          className={`px-3.5 py-2.5 text-[13px] leading-relaxed ${
            isUser
              ? "bg-[var(--color-fg)] text-[var(--color-bg)] rounded-[20px] rounded-br-md"
              : "bg-white/[0.06] text-[var(--color-fg)] rounded-[20px] rounded-bl-md"
          }`}
        >
          {message.text}
        </div>
        {message.citations && message.citations.length > 0 && (
          <div className="flex flex-wrap gap-1">
            {message.severity && (
              <Badge tone={severityToTone(message.severity)} size="xs">
                {severityLabel(message.severity)}
              </Badge>
            )}
            {message.citations.map((c, i) => (
              <CitationChip key={`${c.componentId}-${c.tick}-${i}`} citation={c} onHover={onCiteHover} />
            ))}
          </div>
        )}
      </div>
    </motion.div>
  );
}

function CitationChip({
  citation,
  onHover,
}: {
  citation: RagCitation;
  onHover: (id: ComponentId | null) => void;
}) {
  return (
    <button
      type="button"
      onMouseEnter={() => onHover(citation.componentId)}
      onMouseLeave={() => onHover(null)}
      className="inline-flex items-center gap-1.5 px-2 py-0.5 rounded-full bg-white/[0.05] text-[10.5px] tabular-nums text-[var(--color-fg-muted)] hover:bg-white/[0.10] hover:text-[var(--color-fg)] transition-all"
      title={`Cited from telemetry at ${citation.timestamp}`}
    >
      <span className="opacity-70">{citation.timestamp}</span>
      <span className="opacity-30">·</span>
      <span>{citation.componentLabel}</span>
    </button>
  );
}
