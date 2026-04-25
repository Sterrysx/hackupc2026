import { useEffect } from "react";
import { Command } from "cmdk";
import { motion, AnimatePresence } from "framer-motion";
import { Activity, MessageSquare, RotateCcw, FastForward, Pause, Play } from "lucide-react";
import { useTwin } from "@/store/twin";

/**
 * Command palette — Spotlight-style.
 *  - Quiet glass surface, no harsh borders.
 *  - Grouped by Components / Ask Aether / Simulation.
 */
export function CommandPalette() {
  const {
    commandPaletteOpen,
    setCommandPaletteOpen,
    snapshot,
    selectComponent,
    highlightComponent,
    paused,
    setPaused,
    jumpForward,
    reset,
    setChatOpen,
    sendUserMessage,
  } = useTwin();

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if ((e.metaKey || e.ctrlKey) && e.key.toLowerCase() === "k") {
        e.preventDefault();
        setCommandPaletteOpen(!commandPaletteOpen);
      }
      if (e.key === "Escape" && commandPaletteOpen) setCommandPaletteOpen(false);
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [commandPaletteOpen, setCommandPaletteOpen]);

  const close = () => setCommandPaletteOpen(false);

  const focusComponent = (id: typeof snapshot.components[number]["id"]) => {
    selectComponent(id);
    highlightComponent(id);
    setTimeout(() => highlightComponent(null), 1600);
    close();
  };

  return (
    <AnimatePresence>
      {commandPaletteOpen && (
        <motion.div
          initial={{ opacity: 0 }}
          animate={{ opacity: 1 }}
          exit={{ opacity: 0 }}
          className="fixed inset-0 z-50 flex items-start justify-center pt-[16vh] px-4 bg-[oklch(0.10_0.005_260/0.45)] backdrop-blur-sm"
          onClick={close}
        >
          <motion.div
            initial={{ scale: 0.97, y: -6, opacity: 0 }}
            animate={{ scale: 1, y: 0, opacity: 1 }}
            exit={{ scale: 0.98, y: -4, opacity: 0 }}
            transition={{ duration: 0.2, ease: "easeOut" }}
            onClick={(e) => e.stopPropagation()}
            className="w-full max-w-xl glass-floating rounded-3xl overflow-hidden"
          >
            <Command label="Command palette" className="bg-transparent">
              <Command.Input
                placeholder="Search components, run actions, or ask Aether…"
                className="w-full bg-transparent border-0 outline-none px-6 py-5 text-[15px] text-[var(--color-fg)] placeholder:text-[var(--color-fg-faint)]"
                autoFocus
              />
              <div className="h-px mx-2 bg-[var(--color-border)]" />
              <Command.List className="max-h-[60vh] overflow-y-auto p-2">
                <Command.Empty className="px-4 py-8 text-center text-[12.5px] text-[var(--color-fg-muted)]">
                  No matches.
                </Command.Empty>

                <Group title="Components">
                  {snapshot.components.map((c) => (
                    <Item
                      key={c.id}
                      value={`${c.label} ${c.subsystem} ${c.status}`}
                      onSelect={() => focusComponent(c.id)}
                    >
                      <Activity size={14} className="text-[var(--color-fg-muted)]" />
                      <span className="flex-1">{c.label}</span>
                      <span className="text-[11.5px] text-[var(--color-fg-faint)] tabular-nums">
                        {(c.healthIndex * 100).toFixed(0)}%
                      </span>
                    </Item>
                  ))}
                </Group>

                <Group title="Ask Aether">
                  {[
                    "What's the highest-risk component?",
                    "When should I schedule maintenance?",
                    "Show me the forecast for the next hour",
                  ].map((q) => (
                    <Item
                      key={q}
                      value={`ask ${q}`}
                      onSelect={() => {
                        setChatOpen(true);
                        sendUserMessage(q);
                        close();
                      }}
                    >
                      <MessageSquare size={14} className="text-[var(--color-fg-muted)]" />
                      <span className="flex-1">{q}</span>
                    </Item>
                  ))}
                </Group>

                <Group title="Simulation">
                  <Item value={paused ? "resume" : "pause"} onSelect={() => { setPaused(!paused); close(); }}>
                    {paused ? <Play size={14} className="text-[var(--color-fg-muted)]" /> : <Pause size={14} className="text-[var(--color-fg-muted)]" />}
                    <span className="flex-1">{paused ? "Resume simulation" : "Pause simulation"}</span>
                  </Item>
                  <Item value="jump 2 hours" onSelect={() => { jumpForward(120); close(); }}>
                    <FastForward size={14} className="text-[var(--color-fg-muted)]" />
                    <span className="flex-1">Jump 2 hours forward</span>
                  </Item>
                  <Item value="jump 8 hours shift" onSelect={() => { jumpForward(480); close(); }}>
                    <FastForward size={14} className="text-[var(--color-fg-muted)]" />
                    <span className="flex-1">Jump 8 hours (full shift)</span>
                  </Item>
                  <Item value="reset" onSelect={() => { reset(); close(); }}>
                    <RotateCcw size={14} className="text-[var(--color-fg-muted)]" />
                    <span className="flex-1">Reset simulation</span>
                  </Item>
                </Group>
              </Command.List>
              <div className="h-px mx-2 bg-[var(--color-border)]" />
              <div className="px-5 py-2.5 flex items-center justify-between text-[10.5px] text-[var(--color-fg-faint)] font-mono">
                <span>↑↓ navigate</span>
                <span>↵ run</span>
                <span>esc close</span>
              </div>
            </Command>
          </motion.div>
        </motion.div>
      )}
    </AnimatePresence>
  );
}

function Group({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <Command.Group
      heading={title}
      className="text-[10px] uppercase tracking-[0.16em] text-[var(--color-fg-faint)] px-3 pt-3 pb-1"
    >
      {children}
    </Command.Group>
  );
}

function Item({
  value,
  onSelect,
  children,
}: {
  value: string;
  onSelect: () => void;
  children: React.ReactNode;
}) {
  return (
    <Command.Item
      value={value}
      onSelect={onSelect}
      className="flex items-center gap-3 px-3 py-2.5 rounded-2xl cursor-pointer text-[13.5px] text-[var(--color-fg)] data-[selected=true]:bg-white/[0.07]"
    >
      {children}
    </Command.Item>
  );
}
