import { useEffect, useRef, useState } from "react";
import { motion, AnimatePresence } from "framer-motion";
import { Send, Sparkles, X } from "lucide-react";
import { useTwin } from "@/store/twin";
import { Button } from "@/components/ui/Button";
import { Badge, severityToTone, severityLabel } from "@/components/ui/Badge";
import type { ChatMessage, ComponentId, RagCitation } from "@/types/telemetry";

const SUGGESTIONS = [
  "Highest-risk component?",
  "When should I service the printer?",
  "Forecast the next 45 minutes",
  "Why is the nozzle plate degrading?",
];

/**
 * ChatPanel — floating Spotlight-style overlay anchored bottom-right.
 *  - Not a sidebar; never compresses the dashboard.
 *  - Glass material, large squircle, low elevation shadow.
 *  - Esc closes; clicking the FAB toggles.
 */
export function ChatPanel() {
  const { messages, sendUserMessage, chatOpen, setChatOpen, highlightComponent } = useTwin();
  const [draft, setDraft] = useState("");
  const scrollRef = useRef<HTMLDivElement>(null);
  const inputRef = useRef<HTMLInputElement>(null);

  useEffect(() => {
    if (chatOpen) {
      requestAnimationFrame(() => inputRef.current?.focus());
    }
  }, [chatOpen]);

  useEffect(() => {
    scrollRef.current?.scrollTo({ top: scrollRef.current.scrollHeight, behavior: "smooth" });
  }, [messages.length, chatOpen]);

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape" && chatOpen) setChatOpen(false);
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [chatOpen, setChatOpen]);

  const submit = () => {
    if (!draft.trim()) return;
    sendUserMessage(draft);
    setDraft("");
  };

  return (
    <AnimatePresence>
      {chatOpen && (
        <motion.aside
          key="chat"
          initial={{ opacity: 0, y: 16, scale: 0.98 }}
          animate={{ opacity: 1, y: 0, scale: 1 }}
          exit={{ opacity: 0, y: 12, scale: 0.98 }}
          transition={{ type: "spring", damping: 28, stiffness: 280 }}
          className="
            fixed z-40
            bottom-24 right-6
            w-[min(420px,calc(100vw-3rem))]
            h-[min(640px,calc(100vh-10rem))]
            flex flex-col overflow-hidden
            rounded-3xl glass-floating
          "
        >
          <header className="flex items-center justify-between px-6 h-14 flex-shrink-0">
            <div className="flex items-center gap-2.5">
              <div className="w-7 h-7 rounded-full flex items-center justify-center bg-[var(--color-accent-soft)]">
                <Sparkles size={14} className="text-[var(--color-accent)]" />
              </div>
              <div className="leading-tight">
                <div className="text-[13.5px] font-medium tracking-tight">Aether</div>
                <div className="text-[10px] uppercase tracking-[0.16em] text-[var(--color-fg-faint)]">
                  grounded co-pilot
                </div>
              </div>
            </div>
            <Button variant="ghost" size="icon" onClick={() => setChatOpen(false)}>
              <X size={15} />
            </Button>
          </header>

          <div ref={scrollRef} className="flex-1 overflow-y-auto px-6 py-4 flex flex-col gap-4 min-h-0">
            <AnimatePresence initial={false}>
              {messages.map((m) => (
                <Message key={m.id} message={m} onCiteHover={highlightComponent} />
              ))}
            </AnimatePresence>
          </div>

          {messages.length <= 2 && (
            <div className="px-6 pb-3 flex flex-wrap gap-1.5 flex-shrink-0">
              {SUGGESTIONS.map((s) => (
                <button
                  key={s}
                  onClick={() => sendUserMessage(s)}
                  className="text-[11.5px] px-3 py-1.5 rounded-full bg-white/[0.06] text-[var(--color-fg-muted)] hover:text-[var(--color-fg)] hover:bg-white/[0.10] transition-all"
                >
                  {s}
                </button>
              ))}
            </div>
          )}

          <form
            className="m-4 mt-2 flex items-center gap-2 bg-white/[0.06] rounded-full pl-5 pr-1.5 py-1.5 flex-shrink-0 focus-within:bg-white/[0.10] transition-colors"
            onSubmit={(e) => { e.preventDefault(); submit(); }}
          >
            <input
              ref={inputRef}
              value={draft}
              onChange={(e) => setDraft(e.target.value)}
              placeholder="Ask Aether…"
              className="flex-1 bg-transparent outline-none text-[13.5px] text-[var(--color-fg)] placeholder:text-[var(--color-fg-faint)]"
            />
            <Button type="submit" variant="primary" size="icon" disabled={!draft.trim()}>
              <Send size={13} />
            </Button>
          </form>
        </motion.aside>
      )}
    </AnimatePresence>
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
      initial={{ opacity: 0, y: 4 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{ duration: 0.22, ease: "easeOut" }}
      className={`flex ${isUser ? "justify-end" : "justify-start"}`}
    >
      <div className={`max-w-[88%] flex flex-col gap-1.5 ${isUser ? "items-end" : "items-start"}`}>
        <div
          className={`px-4 py-2.5 text-[13.5px] leading-relaxed ${
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
