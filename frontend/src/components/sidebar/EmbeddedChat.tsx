import { useEffect, useRef, useState } from "react";
import { motion, AnimatePresence } from "framer-motion";
import { Send, Sparkles } from "lucide-react";
import { useTwin } from "@/store/twin";
import { Button } from "@/components/ui/Button";
import { Badge, severityToTone, severityLabel } from "@/components/ui/Badge";
import { ChatThinking } from "@/components/ui/Skeleton";
import type { ChatMessage, ComponentId, RagCitation } from "@/types/telemetry";

const APPLE_EASE: [number, number, number, number] = [0.16, 1, 0.3, 1];

const SUGGESTIONS = [
  "Highest-risk component?",
  "When should I service the printer?",
  "Forecast next 45 minutes",
];

/**
 * Aether chat — embedded at the bottom of the sidebar.
 *  - Messages list scrolls within its own region.
 *  - Composer pinned at the bottom.
 *  - "Thinking" indicator (3 pulsing dots) while the RAG simulates a reply.
 */
function chatApiStatusLabel(status: "unknown" | "live" | "offline"): { dot: string; text: string } {
  if (status === "live") return { dot: "bg-emerald-400/90", text: "Agente conectado" };
  if (status === "offline") return { dot: "bg-amber-400/90", text: "Sin API — respuestas locales" };
  return { dot: "bg-white/25", text: "Comprobando API…" };
}

export function EmbeddedChat() {
  const messages = useTwin((s) => s.messages);
  const isThinking = useTwin((s) => s.isThinking);
  const chatApiStatus = useTwin((s) => s.chatApiStatus);
  const sendUserMessage = useTwin((s) => s.sendUserMessage);
  const highlightComponent = useTwin((s) => s.highlightComponent);
  const statusUi = chatApiStatusLabel(chatApiStatus);

  const [draft, setDraft] = useState("");
  const scrollRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    scrollRef.current?.scrollTo({ top: scrollRef.current.scrollHeight, behavior: "smooth" });
  }, [messages.length, isThinking]);

  const submit = () => {
    if (!draft.trim()) return;
    sendUserMessage(draft);
    setDraft("");
  };

  return (
    <section className="flex flex-col min-h-0 border-t border-[var(--color-border)]">
      {/* Mini header */}
      <header className="flex items-center justify-between px-6 h-12 flex-shrink-0 gap-2">
        <div className="flex items-center gap-2 min-w-0">
          <div className="w-5 h-5 rounded-full flex items-center justify-center bg-[var(--color-accent-soft)] flex-shrink-0">
            <Sparkles size={11} className="text-[var(--color-accent)]" />
          </div>
          <div className="flex flex-col min-w-0 leading-tight">
            <span className="text-[12px] font-medium tracking-tight">Aether</span>
            <span className="text-[10px] uppercase tracking-[0.16em] text-[var(--color-fg-faint)] truncate">
              grounded co-pilot
            </span>
          </div>
        </div>
        <div
          className="flex items-center gap-1.5 flex-shrink-0 max-w-[52%]"
          title="El front llama a /api/… (Vite → :8000). Arranca uvicorn en el repo."
        >
          <span className={`h-1.5 w-1.5 rounded-full ${statusUi.dot}`} aria-hidden />
          <span className="text-[10px] text-[var(--color-fg-muted)] truncate">{statusUi.text}</span>
        </div>
      </header>

      {/* Messages */}
      <div ref={scrollRef} className="flex-1 overflow-y-auto px-5 pb-3 pt-1 flex flex-col gap-3 min-h-0">
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

      {/* Suggestion chips */}
      {messages.length <= 2 && !isThinking && (
        <div className="px-5 pb-2 flex flex-wrap gap-1.5 flex-shrink-0">
          {SUGGESTIONS.map((s) => (
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
        className="m-4 mt-1 flex items-center gap-2 bg-white/[0.06] rounded-full pl-4 pr-1.5 py-1.5 flex-shrink-0 focus-within:bg-white/[0.10] transition-colors"
        onSubmit={(e) => { e.preventDefault(); submit(); }}
      >
        <input
          value={draft}
          onChange={(e) => setDraft(e.target.value)}
          placeholder="Ask Aether…"
          className="flex-1 bg-transparent outline-none text-[13px] text-[var(--color-fg)] placeholder:text-[var(--color-fg-faint)]"
        />
        <Button type="submit" variant="primary" size="icon" disabled={!draft.trim() || isThinking}>
          <Send size={13} />
        </Button>
      </form>
    </section>
  );
}

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
